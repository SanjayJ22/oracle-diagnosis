"""Phase 3 extension of src/mine_volatility_incidents_phase2.py (kept, not
overwritten, so phase 2's exact run remains reproducible): same automated-sampling
method, lower threshold (to reach a larger target on top of the 85 already locked),
and an exclusion set read directly from data/processed/features.parquet's own
`label == "large volatility event"` rows -- simpler and less fragile than phase 2's
approach of regex-parsing 2 separate markdown report files, now that a single
consolidated features table exists covering all 85 currently-locked volatility
incidents (12 original + 18 phase 1 + 55 phase 2).

Everything else (no-lookahead heartbeat_elapsed at block-1, WETH/USDC V3 cross-venue
check, chain-merge collapsing, time-stratified pre-selection before spending RPC
budget) is identical logic to phase 2's script -- only the threshold, exclusion
source, and target count differ.
"""

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_cex import fetch_cex_klines  # noqa: E402
from fetch_chainlink import _with_retry, get_round_data_at_block, get_web3  # noqa: E402
from fetch_dex import get_v3_state  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
FEATURES_PATH = REPO_ROOT / "data" / "processed" / "features.parquet"
OUTPUT_PATH = REPO_ROOT / "reports" / "volatility_candidates_phase3.md"
CACHE_DIR = REPO_ROOT / "data" / "raw"

ETH_USD_FEED = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"
WETH_USDC_V3 = "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640"

START_DATE = "2021-01-01"
MOVE_WINDOW_HOURS = 24
MOVE_THRESHOLD = 0.03  # lowered from phase 2's 5% to reach a larger target on top of the 85 already locked
EXCLUSION_DAYS = 3
CROSS_VENUE_TOLERANCE = 0.05
MAX_CLEAN_HEARTBEAT_SECONDS = 1800
TARGET_MIN, TARGET_MAX = 80, 110
MERGE_GAP_HOURS = 48
STRATIFY_BUCKET_DAYS = 15  # finer than phase 2's 30, since a larger target is needed from an already-sampled range


def _existing_incident_dates() -> list[pd.Timestamp]:
    """All 85 currently-locked volatility incidents, read directly from
    features.parquet -- supersedes phase 2's markdown-regex approach now that a
    single consolidated table exists."""
    df = pd.read_parquet(FEATURES_PATH)
    vol = df[df["label"] == "large volatility event"]
    return [pd.Timestamp(d, tz="UTC") for d in pd.to_datetime(vol["date"])]


def fetch_full_history() -> pd.DataFrame:
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


def find_candidate_windows(history: pd.DataFrame) -> pd.DataFrame:
    df = history.copy()
    shift = MOVE_WINDOW_HOURS
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


def stratify_by_time(candidates: list) -> list:
    if not candidates:
        return candidates
    start = min(r["timestamp"] for r in candidates)
    buckets: dict[int, dict] = {}
    for r in candidates:
        bucket = int((r["timestamp"] - start).days // STRATIFY_BUCKET_DAYS)
        if bucket not in buckets or abs(r["pct_move"]) > abs(buckets[bucket]["pct_move"]):
            buckets[bucket] = r
    return sorted(buckets.values(), key=lambda r: r["timestamp"])


_LATEST_BLOCK_CACHE = {}


def _get_latest_block_cached(w3):
    if not _LATEST_BLOCK_CACHE:
        blk = _with_retry(lambda: w3.eth.get_block("latest"))
        _LATEST_BLOCK_CACHE["number"] = blk["number"]
        _LATEST_BLOCK_CACHE["timestamp"] = blk["timestamp"]
    return _LATEST_BLOCK_CACHE["number"], _LATEST_BLOCK_CACHE["timestamp"]


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


def _find_block_for_timestamp(w3, target_ts: int) -> int:
    latest_num, latest_ts = _get_latest_block_cached(w3)
    if target_ts >= latest_ts:
        return latest_num
    avg_block_time = 12.0
    guess = max(0, latest_num - int((latest_ts - target_ts) / avg_block_time))
    for _ in range(4):
        blk = _get_block_cached(w3, guess)
        error_seconds = target_ts - blk["timestamp"]
        if abs(error_seconds) < 60:
            break
        guess = max(0, min(latest_num, guess + int(error_seconds / avg_block_time)))
    lo, hi = max(0, guess - 1500), min(latest_num, guess + 1500)
    while lo < hi:
        mid = (lo + hi) // 2
        if _get_block_cached(w3, mid)["timestamp"] < target_ts:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _dex_price(w3, pool_address: str, block_number: int) -> float:
    state = get_v3_state(w3, pool_address, block_number)
    return 1.0 / float(state["price_1_per_0"])


def verify_candidate(w3, ts: pd.Timestamp, cex_price: float, pct_move: float) -> dict:
    block_number = _find_block_for_timestamp(w3, int(ts.timestamp()))
    block = _get_block_cached(w3, block_number)
    block_ts = block["timestamp"]

    oracle_round = get_round_data_at_block(w3, ETH_USD_FEED, block_number)
    oracle_price = float(oracle_round["answer"])
    prev_round = get_round_data_at_block(w3, ETH_USD_FEED, block_number - 1)
    heartbeat_elapsed = block_ts - int(prev_round["updated_at"])

    from web3 import Web3 as _Web3
    if w3.eth.get_code(_Web3.to_checksum_address(WETH_USDC_V3), block_identifier=block_number) in (b"", b"0x"):
        return {
            "timestamp": ts, "block": block_number, "pct_move_24h": pct_move,
            "cex_price": cex_price, "oracle_price": oracle_price, "dex_price": float("nan"),
            "price_dev": (oracle_price - cex_price) / cex_price,
            "cross_venue_spread": float("nan"), "dex_oracle_spread": float("nan"),
            "heartbeat_elapsed": heartbeat_elapsed, "clean": False,
            "reject_reason": "DEX pool not yet deployed at this block (predates Uniswap V3's 2021-05-04 mainnet launch)",
        }

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
        "timestamp": ts, "block": block_number, "pct_move_24h": pct_move,
        "cex_price": cex_price, "oracle_price": oracle_price, "dex_price": dex_price,
        "price_dev": price_dev, "cross_venue_spread": cross_venue_spread,
        "dex_oracle_spread": dex_oracle_spread, "heartbeat_elapsed": heartbeat_elapsed,
        "clean": clean, "reject_reason": "" if clean else "failed cross-venue/heartbeat cleanliness gate",
    }


def main():
    w3 = get_web3()
    existing_dates = _existing_incident_dates()
    print(f"Excluding candidates within {EXCLUSION_DAYS} days of {len(existing_dates)} "
          f"existing volatility incident dates (all 85 currently locked, read from features.parquet).", flush=True)

    print("Fetching ETHUSDT hourly history...", flush=True)
    history = fetch_full_history()
    print(f"  {len(history)} hourly candles, {history['timestamp'].min()} -> {history['timestamp'].max()}", flush=True)

    print(f"\nScanning for |{MOVE_WINDOW_HOURS}h move| >= {MOVE_THRESHOLD:.0%}...", flush=True)
    candidates = find_candidate_windows(history)
    print(f"  {len(candidates)} contiguous flagged events before exclusion", flush=True)

    kept = []
    for _, r in candidates.iterrows():
        ts = r["timestamp"]
        if any(abs((ts - ed).days) <= EXCLUSION_DAYS for ed in existing_dates):
            continue
        kept.append(r)
    print(f"  {len(kept)} events survive exclusion of existing incident dates", flush=True)

    kept = stratify_by_time(kept)
    print(f"  {len(kept)} events after time-stratified pre-selection ({STRATIFY_BUCKET_DAYS}-day buckets)", flush=True)

    print(f"\nVerifying {len(kept)} candidates on-chain...", flush=True)
    verified = []
    for i, r in enumerate(kept, 1):
        print(f"  [{i}/{len(kept)}] {r['timestamp']} ({r['pct_move']:+.1%})...", flush=True)
        result = verify_candidate(w3, r["timestamp"], float(r["close"]), float(r["pct_move"]))
        verified.append(result)
        time.sleep(0.1)

    clean = [v for v in verified if v["clean"]]
    dirty = [v for v in verified if not v["clean"]]
    print(f"\n{len(clean)}/{len(verified)} candidates pass cleanliness checks.", flush=True)

    clean_sorted = sorted(clean, key=lambda v: abs(v["pct_move_24h"]), reverse=True)
    final = clean_sorted[:TARGET_MAX] if len(clean_sorted) > TARGET_MAX else clean_sorted
    final = sorted(final, key=lambda v: v["timestamp"])

    write_report(final, dirty, len(candidates), len(kept))
    print(f"\nFinal: {len(final)} verified new volatility candidates "
          f"({'within' if TARGET_MIN <= len(final) <= TARGET_MAX else 'OUTSIDE'} the {TARGET_MIN}-{TARGET_MAX} target range).", flush=True)
    return final, dirty


def write_report(final: list[dict], dirty: list[dict], n_raw: int, n_after_exclusion: int) -> None:
    lines = [
        "# Volatility Incident Candidates — Phase 3 (Automated Sampling)",
        "",
        "Extends `src/mine_volatility_incidents_phase2.py`'s method (same code, threshold "
        f"lowered further to reach a larger target on top of the 85 already locked): automated "
        f"sampling of ETHUSDT hourly candles ({START_DATE} onward), flagging every "
        f"{MOVE_WINDOW_HOURS}h window with a >={MOVE_THRESHOLD:.0%} move, collapsing contiguous "
        "flagged runs to one event each, excluding anything within "
        f"{EXCLUSION_DAYS} days of any of the 85 currently-locked volatility incidents (read "
        "directly from `data/processed/features.parquet`, not re-parsed from markdown reports), "
        "then verifying each survivor fully on-chain (Chainlink ETH/USD, WETH/USDC V3 DEX price, "
        "cross-venue agreement, heartbeat staleness) exactly like the existing 85 were verified.",
        "",
        f"- Raw flagged events (contiguous-run-collapsed): {n_raw}",
        f"- After excluding dates within {EXCLUSION_DAYS} days of any of the 85 existing incidents: {n_after_exclusion}",
        f"- Passed on-chain cleanliness checks (cross-venue agreement within "
        f"{CROSS_VENUE_TOLERANCE:.0%}, heartbeat_elapsed <= {MAX_CLEAN_HEARTBEAT_SECONDS}s): "
        f"{len(final) + len(dirty)}/{n_after_exclusion} attempted "
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
        f"- **Threshold**: {MOVE_THRESHOLD:.0%} over {MOVE_WINDOW_HOURS}h -- lowered from phase 2's "
        "5% specifically to reach a larger target on top of the 85 already locked, for phase 3's "
        "45->105->~200 total scaling goal. This means phase 3's volatility incidents are, on "
        "average, smaller and calmer moves than the original 12, phase 1's 18 (10%+), and phase "
        "2's 55 (5%+). Flagged explicitly since this affects the deterministic baseline's "
        "reserve_skew-threshold behavior in a known, already-documented way.",
        "- **No lookahead**: heartbeat_elapsed is read at block-1, matching this project's fixed "
        "anchoring-artifact convention.",
        f"- **Cleanliness gate**: unchanged from phases 1-2 -- {CROSS_VENUE_TOLERANCE:.0%} cross-venue "
        f"agreement, heartbeat_elapsed <= {MAX_CLEAN_HEARTBEAT_SECONDS}s.",
        "- **Block resolution**: timestamp-linear estimate + short local binary search, same as "
        "phases 1-2.",
        "- Every value in the table above is a live on-chain or exchange-API read for this run, "
        "not estimated or interpolated.",
    ]

    OUTPUT_PATH.write_text("\n".join(lines) + "\n")
    print(f"\nWrote {len(final)} candidates ({len(dirty)} rejected, shown for transparency) to {OUTPUT_PATH}", flush=True)


if __name__ == "__main__":
    main()
