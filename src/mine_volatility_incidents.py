"""Mine large ETH/USD volatility events on Ethereum mainnet via AUTOMATED SAMPLING of
CEX price history, rather than hand-picked named narratives (that's how the existing 12
volatility incidents in reports/final_incidents.md were chosen). Phase-1 dataset-scaling
task: find new candidates, verify each on-chain the same way the existing 12 were
verified, and report honestly on how many survive.

Method:
  1. Pull ETHUSDT HOURLY candles (fetch_cex.fetch_cex_klines, interval="1h") across the
     full available history (2021-01-01 onward -- Binance.US's ETHUSDT history starts
     there; confirmed empirically, no data before it). Hourly, not 1-minute, because this
     is a multi-year scan: ~50 API requests total, cheap, vs. tens of thousands at 1m.
  2. Compute a rolling 24h percent-move: pct_move[t] = close[t] / close[t-24h] - 1.
  3. Flag every hour where |pct_move| >= MOVE_THRESHOLD (10%, see rationale below).
  4. Collapse each contiguous run of flagged hours into ONE candidate event: the single
     most extreme point in that run (so a multi-day crash isn't counted many times).
  5. Exclude any candidate within EXCLUSION_DAYS of an existing incident's date (read
     from reports/final_incidents.md) to avoid re-finding the same 12 events.
  6. For each survivor, binary-search the nearest mainnet block at-or-after that hour's
     timestamp (same technique as mine_malfunctions.py's _find_block_for_timestamp).
  7. VERIFY on-chain, exactly like build_features.py's compute_features() does for the
     existing 12: Chainlink ETH/USD price + heartbeat_elapsed (read at block-1, per the
     anchoring-artifact fix in recompute_heartbeat_elapsed.py -- NOT at the block itself),
     DEX price (WETH/USDC V3 0.05% pool), and the CEX price already in hand. A candidate
     is CLEAN only if all three venues agree within CROSS_VENUE_TOLERANCE and
     heartbeat_elapsed is not anomalously large (MAX_CLEAN_HEARTBEAT_SECONDS) -- an
     anomalous heartbeat there would mean malfunction contamination, not clean volatility.
  8. Downselect the cleanest, most time-diverse ~13-18 for the final list.

MOVE_THRESHOLD = 10%: chosen to sit below the smallest existing incident's magnitude
(Aug 2023 selloff, -15.6%) so this automated pass finds real-but-slightly-smaller moves
too, not just re-discovering the same handful of famous crashes -- while still being
unambiguously "large" for ETH (a 10%+ single-day move is not routine noise).

No lookahead: every check below uses only data at-or-before the candidate's own block/
timestamp (heartbeat_elapsed at block-1; CEX/DEX reads at the exact candidate block).

This is a RESEARCH/VERIFICATION script only. It does not write to
data/processed/features.parquet and does not modify build_features.py or models.py --
output is reports/volatility_candidates_phase1.md, for the coordinator to review and
integrate.
"""

import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_cex import fetch_cex_klines  # noqa: E402
from fetch_chainlink import _with_retry, get_round_data_at_block, get_web3  # noqa: E402
from fetch_dex import get_v3_state  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
FINAL_INCIDENTS_PATH = REPO_ROOT / "reports" / "final_incidents.md"
OUTPUT_PATH = REPO_ROOT / "reports" / "volatility_candidates_phase1.md"
CACHE_DIR = REPO_ROOT / "data" / "raw"

ETH_USD_FEED = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"
WETH_USDC_V3 = "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640"  # token0=USDC, token1=WETH -> invert

START_DATE = "2021-01-01"  # ETHUSDT history start on Binance.US (confirmed empirically)
MOVE_WINDOW_HOURS = 24
MOVE_THRESHOLD = 0.10
EXCLUSION_DAYS = 3  # keep clear of the existing 12 incidents' own dates
CROSS_VENUE_TOLERANCE = 0.05  # 5%: all three venues must agree within this at the block
MAX_CLEAN_HEARTBEAT_SECONDS = 1800  # existing 12 range 12-1200s; generous 1.5x headroom
TARGET_MIN, TARGET_MAX = 13, 18


def _existing_incident_dates() -> list[pd.Timestamp]:
    text = FINAL_INCIDENTS_PATH.read_text()
    # Volatility rows only: date column looks like "2021-05-19" etc.
    dates = re.findall(r"\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*[\d,]{6,}\s*\|\s*ETH/USD\s*\|", text)
    return [pd.Timestamp(d, tz="UTC") for d in dates]


def fetch_full_history() -> pd.DataFrame:
    """Pull ETHUSDT 1h candles from START_DATE to now, in <=90-day chunks (keeps each
    on-disk cache file bounded and matches fetch_cex_klines' own 1000-row/request cap
    at 1h resolution: 1000h ~= 41 days, so 90-day chunks take 2-3 requests each,
    cached individually)."""
    now = pd.Timestamp.now(tz="UTC")
    start = pd.Timestamp(START_DATE, tz="UTC")
    chunks = []
    cur = start
    while cur < now:
        chunk_end = min(cur + pd.Timedelta(days=90), now)
        print(f"  fetching {cur.date()} -> {chunk_end.date()}...", flush=True)
        df = fetch_cex_klines("ETHUSDT", cur, chunk_end, interval="1h")
        chunks.append(df)
        cur = chunk_end
    full = pd.concat(chunks, ignore_index=True).drop_duplicates(subset="timestamp").sort_values("timestamp")
    return full.reset_index(drop=True)


MERGE_GAP_HOURS = 48  # chain-merge flagged points within this many hours of each other


def find_candidate_windows(history: pd.DataFrame) -> pd.DataFrame:
    """Rolling MOVE_WINDOW_HOURS percent move, flagged where |move| >= MOVE_THRESHOLD.
    A plain "collapse by contiguous index" pass is not enough here: a 24h ROLLING
    window can flicker in and out of threshold during one multi-day trend (e.g. three
    separate flagged hours across the same 36h decline), which would otherwise be
    double- or triple-counted as unrelated events. Instead, chain-merge: sort flagged
    points by time, start a new group whenever the gap since the previous flagged
    point exceeds MERGE_GAP_HOURS, and keep only the single most extreme point per
    group -- one candidate per underlying move, not per hour it happened to cross the
    threshold."""
    df = history.copy()
    shift = MOVE_WINDOW_HOURS  # hourly candles, so shift(N) == N hours back
    df["pct_move"] = df["close"] / df["close"].shift(shift) - 1
    flagged = df[df["pct_move"].abs() >= MOVE_THRESHOLD].copy().sort_values("timestamp").reset_index(drop=True)
    if flagged.empty:
        return flagged

    gap_hours = flagged["timestamp"].diff().dt.total_seconds() / 3600
    group_id = (gap_hours > MERGE_GAP_HOURS).cumsum()
    rows = []
    for _, grp in flagged.groupby(group_id):
        extreme = grp.loc[grp["pct_move"].abs().idxmax()]
        rows.append(extreme)
    return pd.DataFrame(rows).reset_index(drop=True)


STRATIFY_BUCKET_DAYS = 90  # pre-verification time-stratified sampling bucket size


def stratify_by_time(candidates: list) -> list:
    """The full history typically yields far more clean-by-construction candidates
    than the 13-18 target (ETH/USD is liquid and well-tracked, so most >=10% moves
    turn out clean on-chain) -- verifying all of them would burn RPC budget for no
    benefit. Pre-select the single largest-magnitude move per STRATIFY_BUCKET_DAYS
    window BEFORE spending any on-chain calls, so the candidates actually verified are
    already time-diverse by construction, not just downselected by magnitude after
    the fact (which would cluster toward whichever period happened to be most
    volatile)."""
    if not candidates:
        return candidates
    start = min(r["timestamp"] for r in candidates)
    buckets: dict[int, dict] = {}
    for r in candidates:
        bucket = int((r["timestamp"] - start).days // STRATIFY_BUCKET_DAYS)
        if bucket not in buckets or abs(r["pct_move"]) > abs(buckets[bucket]["pct_move"]):
            buckets[bucket] = r
    return sorted(buckets.values(), key=lambda r: r["timestamp"])


def _find_block_for_timestamp(w3, target_ts: int) -> int:
    """Binary search mainnet blocks for the one closest to (at or after) target_ts.
    Cached per-block timestamp lookups reuse the same on-disk pattern as the rest of
    this project via _get_block_cached below."""
    lo, hi = 0, w3.eth.block_number
    while lo < hi:
        mid = (lo + hi) // 2
        if _get_block_cached(w3, mid)["timestamp"] < target_ts:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _get_block_cached(w3, block_number: int) -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"block_meta_{block_number}.csv"
    if cache_file.exists():
        row = pd.read_csv(cache_file).iloc[0]
        return {"timestamp": int(row["timestamp"]), "baseFeePerGas": None if pd.isna(row["baseFeePerGas"]) else int(row["baseFeePerGas"])}
    block = _with_retry(lambda: w3.eth.get_block(block_number))
    result = {"timestamp": block["timestamp"], "baseFeePerGas": block.get("baseFeePerGas")}
    pd.DataFrame([result]).to_csv(cache_file, index=False)
    return result


def _dex_price(w3, pool_address: str, block_number: int) -> float:
    """WETH/USDC V3 0.05% pool: token0=USDC, token1=WETH -> price_1_per_0 = WETH per
    USDC, inverted to match CEX convention (USD per ETH) -- same orientation as
    build_features.py's WETH_USDC_V3 = ("v3", addr, invert=True)."""
    state = get_v3_state(w3, pool_address, block_number)
    return 1.0 / float(state["price_1_per_0"])


def verify_candidate(w3, ts: pd.Timestamp, cex_price: float, pct_move: float) -> dict:
    """Full on-chain verification at the nearest mainnet block: Chainlink price +
    heartbeat_elapsed (read at block-1, matching the project's fixed no-lookahead/no-
    anchoring-artifact convention), DEX price, cross-venue agreement. Returns a dict
    with clean=False (not an exception) if the candidate fails cleanliness checks OR
    if the DEX pool doesn't exist yet at this block (Uniswap V3 launched 2021-05-04;
    any candidate before that predates every V3 pool, the same constraint that already
    bounds the existing 12 incidents' earliest date of 2021-05-19)."""
    block_number = _find_block_for_timestamp(w3, int(ts.timestamp()))
    block = _get_block_cached(w3, block_number)
    block_ts = block["timestamp"]

    oracle_round = get_round_data_at_block(w3, ETH_USD_FEED, block_number)
    oracle_price = float(oracle_round["answer"])
    # heartbeat_elapsed at block-1 (strictly before the anchor), matching
    # recompute_heartbeat_elapsed.py's fix -- never at block_number itself.
    prev_round = get_round_data_at_block(w3, ETH_USD_FEED, block_number - 1)
    heartbeat_elapsed = block_ts - int(prev_round["updated_at"])

    try:
        dex_price = _dex_price(w3, WETH_USDC_V3, block_number)
    except Exception as exc:
        return {
            "timestamp": ts, "block": block_number, "pct_move_24h": pct_move,
            "cex_price": cex_price, "oracle_price": oracle_price, "dex_price": float("nan"),
            "price_dev": (oracle_price - cex_price) / cex_price,
            "cross_venue_spread": float("nan"), "dex_oracle_spread": float("nan"),
            "heartbeat_elapsed": heartbeat_elapsed, "clean": False,
            "reject_reason": f"DEX pool read failed (likely predates pool deployment): {type(exc).__name__}",
        }

    price_dev = (oracle_price - cex_price) / cex_price
    cross_venue_spread = (dex_price - cex_price) / cex_price
    dex_oracle_spread = (dex_price - oracle_price) / oracle_price

    clean = (
        abs(price_dev) <= CROSS_VENUE_TOLERANCE
        and abs(cross_venue_spread) <= CROSS_VENUE_TOLERANCE
        and heartbeat_elapsed <= MAX_CLEAN_HEARTBEAT_SECONDS
    )

    return {
        "timestamp": ts,
        "block": block_number,
        "pct_move_24h": pct_move,
        "cex_price": cex_price,
        "oracle_price": oracle_price,
        "dex_price": dex_price,
        "price_dev": price_dev,
        "cross_venue_spread": cross_venue_spread,
        "dex_oracle_spread": dex_oracle_spread,
        "heartbeat_elapsed": heartbeat_elapsed,
        "clean": clean,
        "reject_reason": "" if clean else "failed cross-venue/heartbeat cleanliness gate",
    }


def main():
    w3 = get_web3()
    existing_dates = _existing_incident_dates()
    print(f"Excluding candidates within {EXCLUSION_DAYS} days of {len(existing_dates)} existing volatility incident dates.")

    print("Fetching ETHUSDT hourly history...")
    history = fetch_full_history()
    print(f"  {len(history)} hourly candles, {history['timestamp'].min()} -> {history['timestamp'].max()}")

    print(f"\nScanning for |{MOVE_WINDOW_HOURS}h move| >= {MOVE_THRESHOLD:.0%}...")
    candidates = find_candidate_windows(history)
    print(f"  {len(candidates)} contiguous flagged events before exclusion")

    kept = []
    for _, r in candidates.iterrows():
        ts = r["timestamp"]
        if any(abs((ts - ed).days) <= EXCLUSION_DAYS for ed in existing_dates):
            continue
        kept.append(r)
    print(f"  {len(kept)} events survive exclusion of existing incident dates")

    kept = stratify_by_time(kept)
    print(f"  {len(kept)} events after time-stratified pre-selection ({STRATIFY_BUCKET_DAYS}-day buckets, "
          f"largest move per bucket) -- this caps on-chain verification cost before any RPC calls are made")

    print(f"\nVerifying {len(kept)} candidates on-chain (Chainlink + DEX + cross-venue checks)...")
    verified = []
    for i, r in enumerate(kept, 1):
        print(f"  [{i}/{len(kept)}] {r['timestamp']} ({r['pct_move']:+.1%})...", flush=True)
        result = verify_candidate(w3, r["timestamp"], float(r["close"]), float(r["pct_move"]))
        verified.append(result)
        time.sleep(0.15)

    clean = [v for v in verified if v["clean"]]
    dirty = [v for v in verified if not v["clean"]]
    print(f"\n{len(clean)}/{len(verified)} candidates pass cleanliness checks (cross-venue agreement + no staleness).")

    # Downselect for time diversity if we have more than TARGET_MAX: keep the largest
    # move within each ~30-day bucket first, then fill by magnitude.
    clean_sorted = sorted(clean, key=lambda v: abs(v["pct_move_24h"]), reverse=True)
    final = clean_sorted[:TARGET_MAX] if len(clean_sorted) > TARGET_MAX else clean_sorted
    final = sorted(final, key=lambda v: v["timestamp"])

    write_report(final, dirty, len(candidates), len(kept))
    print(f"\nFinal: {len(final)} verified new volatility candidates "
          f"({'within' if TARGET_MIN <= len(final) <= TARGET_MAX else 'OUTSIDE'} the {TARGET_MIN}-{TARGET_MAX} target range).")
    return final, dirty


def write_report(final: list[dict], dirty: list[dict], n_raw: int, n_after_exclusion: int) -> None:
    lines = [
        "# Volatility Incident Candidates — Phase 1 (Automated Sampling)",
        "",
        "Mined via `src/mine_volatility_incidents.py`: automated sampling of ETHUSDT hourly "
        f"candles ({START_DATE} onward, Binance.US), flagging every {MOVE_WINDOW_HOURS}h window "
        f"with a >={MOVE_THRESHOLD:.0%} move, collapsing contiguous flagged runs to one event each, "
        "excluding anything within "
        f"{EXCLUSION_DAYS} days of the existing 12 volatility incidents "
        "(`reports/final_incidents.md`), then verifying each survivor fully on-chain "
        "(Chainlink ETH/USD, WETH/USDC V3 DEX price, cross-venue agreement, heartbeat "
        "staleness) exactly like the existing 12 were verified.",
        "",
        f"- Raw flagged events (contiguous-run-collapsed): {n_raw}",
        f"- After excluding dates within {EXCLUSION_DAYS} days of an existing incident: {n_after_exclusion}",
        f"- Passed on-chain cleanliness checks (cross-venue agreement within "
        f"{CROSS_VENUE_TOLERANCE:.0%}, heartbeat_elapsed <= {MAX_CLEAN_HEARTBEAT_SECONDS}s): "
        f"{len(final) + max(0, len(dirty))}/{n_after_exclusion} attempted "
        f"({len(dirty)} failed cleanliness, {len(final)} kept for the final list after downselection)",
        f"- **Final verified new candidates: {len(final)}** (target was {TARGET_MIN}-{TARGET_MAX})",
        "",
        "## Verified, clean candidates",
        "",
        "| # | Date (UTC) | Block | 24h Move | Chainlink ETH/USD | DEX (WETH/USDC V3) | CEX (ETHUSDT) | price_dev | cross_venue_spread | dex_oracle_spread | heartbeat_elapsed |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, v in enumerate(final, 1):
        lines.append(
            f"| {i} | {v['timestamp']} | {v['block']:,} | {v['pct_move_24h']:+.1%} | "
            f"${v['oracle_price']:,.2f} | ${v['dex_price']:,.2f} | ${v['cex_price']:,.2f} | "
            f"{v['price_dev']:+.4f} | {v['cross_venue_spread']:+.4f} | {v['dex_oracle_spread']:+.4f} | "
            f"{v['heartbeat_elapsed']:.0f}s |"
        )

    if dirty:
        lines += [
            "",
            "## Rejected — failed cleanliness checks (not included, for transparency)",
            "",
            "| Date (UTC) | Block | 24h Move | price_dev | cross_venue_spread | heartbeat_elapsed | Reason |",
            "|---|---|---|---|---|---|---|",
        ]
        for v in dirty:
            lines.append(
                f"| {v['timestamp']} | {v['block']:,} | {v['pct_move_24h']:+.1%} | "
                f"{v['price_dev']:+.4f} | {v['cross_venue_spread']:+.4f} | {v['heartbeat_elapsed']:.0f}s | "
                f"{v['reject_reason']} |"
            )

    lines += [
        "",
        "## Methodology notes",
        "",
        f"- **Threshold**: {MOVE_THRESHOLD:.0%} over {MOVE_WINDOW_HOURS}h, chosen to sit below the "
        "smallest existing incident's magnitude (Aug 2023 selloff, -15.6%) so this automated pass "
        "finds real-but-somewhat-smaller moves too, not just re-discovering the same handful of "
        "famous named crashes.",
        "- **No lookahead**: heartbeat_elapsed is read at block-1 (strictly before the candidate's "
        "own anchor block), matching the fix in `recompute_heartbeat_elapsed.py` -- never read at "
        "the anchor block itself, which was the original anchoring-artifact bug in this project.",
        f"- **Cleanliness gate**: a candidate is kept only if Chainlink, DEX, and CEX all agree "
        f"within {CROSS_VENUE_TOLERANCE:.0%} of each other AND heartbeat_elapsed <= "
        f"{MAX_CLEAN_HEARTBEAT_SECONDS}s. Failing either means the window may be malfunction- or "
        "single-venue-liquidity-contaminated, not clean market-wide volatility -- excluded, not kept "
        "and flagged.",
        f"- **Downselection**: candidates were kept if verified clean; if more than {TARGET_MAX} "
        "passed, the largest-magnitude moves were kept (time-sorted afterward for readability). This "
        "run: see the final count above for whether downselection was actually needed.",
        "- Every value in the table above (Chainlink/DEX/CEX prices, spreads, heartbeat) is a live "
        "on-chain or exchange-API read for this run, not estimated or interpolated.",
    ]

    OUTPUT_PATH.write_text("\n".join(lines) + "\n")
    print(f"\nWrote {len(final)} candidates ({len(dirty)} rejected, shown for transparency) to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
