"""Mine real Chainlink staleness events (malfunction candidates) on Ethereum mainnet.

For each feed, walk its full reachable round history (fetch_chainlink.get_feed_update_history),
compute the gap between consecutive updates, and flag gaps that are far larger than the feed's
own empirical update cadence (median gap) -- optionally corroborated by elevated network
congestion (base fee) around the gap's end. These are candidates only: real on-chain staleness,
but not yet checked against news/post-mortems to rule out an unrelated cause. Output is
reports/malfunction_candidates.md for hand verification.
"""

import re
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_chainlink import INTER_BATCH_SLEEP_SECONDS, _with_retry, get_feed_update_history, get_web3  # noqa: E402


def _get_block(w3, block_number: int):
    """w3.eth.get_block wrapped with the same retry/backoff as the round-walking
    calls -- plain get_block calls aren't covered by fetch_chainlink's retry wrapper
    and would otherwise crash on a 429 near the end of a long mining run."""
    block = _with_retry(lambda: w3.eth.get_block(block_number))
    time.sleep(INTER_BATCH_SLEEP_SECONDS)
    return block

FEEDS = {
    "ETH/USD": "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419",
    "BTC/USD": "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c",
    "USDC/USD": "0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6",
    "USDT/USD": "0x3E7d1eAB13ad0104d2750B8863b489D65364e32D",
}

# Alchemy's free tier sustains ~10 eth_call/sec (confirmed empirically: batches of 10
# succeed reliably, batches of 20+ instantly 429). Full multi-year history for the two
# hourly feeds (ETH/USD, BTC/USD have ~130K+ rounds each across all phases) would take
# hours at that rate, so each feed is capped at max_rounds -- generous for the two
# stablecoin feeds (their entire history is under ~1,100 rounds on a single phase) and
# a bounded recent window for ETH/USD and BTC/USD. Round-count caps (not calendar dates)
# because they directly control API call volume, which is what's actually rate-limited.
MIN_TIMESTAMP = int(pd.Timestamp("2020-01-01", tz="UTC").timestamp())
FEED_MAX_ROUNDS = {
    "ETH/USD": 4000,
    "BTC/USD": 4000,
    "USDC/USD": 1500,
    "USDT/USD": 1000,
}
BATCH_SIZE = 10

# Flag a gap if it's at least this many times the feed's own median update interval...
HEARTBEAT_MULTIPLE = 6
# ...or at least this many seconds, whichever is larger (keeps fast stablecoin feeds sane).
MIN_ABSOLUTE_GAP_SECONDS = 4 * 3600

TOP_N = 12
EXCLUSION_BLOCK_WINDOW = 2000  # ~7.5 hours either side of a locked manipulation incident block

FINAL_INCIDENTS_PATH = Path(__file__).resolve().parent.parent / "reports" / "final_incidents.md"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "reports" / "malfunction_candidates.md"


def _find_block_for_timestamp(w3, target_ts: int) -> int:
    """Binary search mainnet blocks for the one closest to (at or after) target_ts."""
    lo, hi = 0, w3.eth.block_number
    while lo < hi:
        mid = (lo + hi) // 2
        if _get_block(w3, mid)["timestamp"] < target_ts:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _load_manipulation_blocks() -> list[int]:
    """Pull the locked manipulation incidents' block numbers so we don't double-count."""
    if not FINAL_INCIDENTS_PATH.exists():
        return []
    text = FINAL_INCIDENTS_PATH.read_text()
    return [int(b.replace(",", "")) for b in re.findall(r"\|\s*([\d,]{6,})\s*\|", text)]


def _congestion_note(w3, block_number: int, baseline_fees: list[float]) -> str:
    """Compare a block's base fee against a sampled baseline; note if pre-EIP-1559."""
    block = _get_block(w3, block_number)
    base_fee = block.get("baseFeePerGas")
    if base_fee is None:
        gas_ratio = block["gasUsed"] / block["gasLimit"]
        return f"pre-EIP-1559 (no base fee); gasUsed/gasLimit={gas_ratio:.0%}"

    base_fee_gwei = base_fee / 1e9
    if baseline_fees:
        pct_below = sum(f <= base_fee_gwei for f in baseline_fees) / len(baseline_fees)
        level = "elevated" if pct_below >= 0.90 else ("normal" if pct_below >= 0.25 else "low")
        return f"{base_fee_gwei:.1f} gwei base fee ({level}, ~p{int(pct_below*100)} vs. sampled baseline)"
    return f"{base_fee_gwei:.1f} gwei base fee (no baseline available)"


def mine_feed(w3, name: str, address: str) -> pd.DataFrame:
    max_rounds = FEED_MAX_ROUNDS[name]
    print(f"Mining {name} ({address}), max_rounds={max_rounds}...", flush=True)
    history = get_feed_update_history(
        w3, address, min_timestamp=MIN_TIMESTAMP, max_rounds=max_rounds, batch_size=BATCH_SIZE
    )
    print(
        f"  {len(history)} rounds, {history['timestamp'].min()} -> {history['timestamp'].max()}",
        flush=True,
    )

    baseline_heartbeat = history["gap_seconds"].median()
    threshold = max(HEARTBEAT_MULTIPLE * baseline_heartbeat, MIN_ABSOLUTE_GAP_SECONDS)
    print(f"  median gap: {baseline_heartbeat:.0f}s, flagging gaps >= {threshold:.0f}s", flush=True)

    flagged = history[history["gap_seconds"] >= threshold].copy()
    flagged["feed_name"] = name
    flagged["feed_address"] = address
    flagged["baseline_heartbeat_seconds"] = baseline_heartbeat
    flagged["price_before"] = history["answer"].shift(1).loc[flagged.index]
    return flagged


def main():
    w3 = get_web3()
    manipulation_blocks = _load_manipulation_blocks()
    print(f"Excluding gaps within {EXCLUSION_BLOCK_WINDOW} blocks of {len(manipulation_blocks)} locked manipulation incidents.", flush=True)

    all_flagged = pd.concat([mine_feed(w3, name, addr) for name, addr in FEEDS.items()], ignore_index=True)
    all_flagged = all_flagged.sort_values("gap_seconds", ascending=False).reset_index(drop=True)

    print("Resolving block numbers for flagged gaps (this hits the RPC per candidate)...", flush=True)
    rows = []
    for _, r in all_flagged.iterrows():
        block_number = _find_block_for_timestamp(w3, int(r["updated_at"]))
        if any(abs(block_number - mb) <= EXCLUSION_BLOCK_WINDOW for mb in manipulation_blocks):
            continue
        rows.append(
            {
                "feed_name": r["feed_name"],
                "feed_address": r["feed_address"],
                "block_number": block_number,
                "gap_seconds": r["gap_seconds"],
                "price_before": r["price_before"],
                "price_after": r["answer"],
                "updated_at": r["timestamp"],
                "baseline_heartbeat_seconds": r["baseline_heartbeat_seconds"],
            }
        )
        if len(rows) >= TOP_N:
            break

    print(f"Sampling baseline base fees for congestion comparison...", flush=True)
    latest_block = w3.eth.block_number
    sample_blocks = range(latest_block - 2_000_000, latest_block, 50_000)
    baseline_fees = []
    for b in sample_blocks:
        blk = _get_block(w3, b)
        if blk.get("baseFeePerGas") is not None:
            baseline_fees.append(blk["baseFeePerGas"] / 1e9)

    for row in rows:
        row["congestion_note"] = _congestion_note(w3, row["block_number"], baseline_fees)
        row["gap_human"] = _format_gap(row["gap_seconds"])
        row["heartbeat_multiple"] = row["gap_seconds"] / row["baseline_heartbeat_seconds"]

    write_report(rows, manipulation_blocks)
    return rows


def _format_gap(seconds: float) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes and not days:
        parts.append(f"{minutes}m")
    return " ".join(parts) if parts else f"{seconds}s"


def write_report(rows: list[dict], manipulation_blocks: list[int]) -> None:
    lines = [
        "# Malfunction (Staleness) Candidates — Ethereum Mainnet",
        "",
        "Mined directly from on-chain Chainlink round history (`getRoundData`, walked round-by-round "
        "via `src/mine_malfunctions.py` since Alchemy's free tier caps `eth_getLogs` at a 10-block range). "
        "A gap is flagged if it's at least "
        f"{HEARTBEAT_MULTIPLE}x the feed's own empirical median update interval, or at least "
        f"{MIN_ABSOLUTE_GAP_SECONDS // 3600}h, whichever is larger. "
        f"Candidates within {EXCLUSION_BLOCK_WINDOW} blocks of a locked manipulation incident "
        "(reports/final_incidents.md) were excluded to keep the classes clean.",
        "",
        "**These are candidates only — not verified against news/post-mortems. Please hand-verify "
        "and pick 7 before they're used as labels.**",
        "",
        "| # | Feed | Feed Address | Block Number | Gap | Price Before | Price After | Updated At (UTC) | Source Note |",
        "|---|------|---------------|---------------|-----|--------------|-------------|-------------------|--------------|",
    ]
    for i, r in enumerate(rows, 1):
        lines.append(
            f"| {i} | {r['feed_name']} | `{r['feed_address']}` | {r['block_number']:,} | "
            f"{r['gap_human']} ({r['heartbeat_multiple']:.0f}x median) | "
            f"{r['price_before']:.4f} | {r['price_after']:.4f} | {r['updated_at']} | "
            f"Mined from on-chain round history; {r['congestion_note']} |"
        )

    lines += [
        "",
        "## Methodology notes",
        "",
        f"- History pulled back to {pd.Timestamp(MIN_TIMESTAMP, unit='s', tz='UTC').date()} where reachable "
        "(older Chainlink phases before the current proxy's phase 3 use a pre-v3 interface and aren't "
        "reachable via `getRoundData` — this truncates ETH/USD and BTC/USD's earliest coverage; see console "
        "output from the mining run for each feed's actual covered range).",
        "- 'Baseline' heartbeat is each feed's own median inter-update gap over its mined history, not the "
        "feed's configured heartbeat parameter (that's an on-chain-observable-only design choice, consistent "
        "with treating the oracle as a black box).",
        "- Congestion baseline is sampled base fee (gwei) across ~40 blocks spread over the last ~2,000,000 "
        "blocks; 'elevated' means the candidate's base fee is at or above the 90th percentile of that sample.",
        f"- {len(manipulation_blocks)} manipulation incident blocks were used for exclusion: {manipulation_blocks}",
    ]

    OUTPUT_PATH.write_text("\n".join(lines) + "\n")
    print(f"Wrote {len(rows)} candidates to {OUTPUT_PATH}", flush=True)


if __name__ == "__main__":
    main()
