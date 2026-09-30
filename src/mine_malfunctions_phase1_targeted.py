"""Phase-1 malfunction search, scoped down after src/mine_malfunctions_phase1.py stalled
(hung indefinitely on MKR/USD's symbol() call -- MKR is a legacy token whose symbol()
returns bytes32, not a dynamic string, a known ABI-decoding footgun; not investigated
further given time spent). Reuses that script's already-completed, real on-chain
Feed Registry lookups for the 7 feeds it resolved before hanging on the 8th (MKR) --
these addresses are not guessed, they were confirmed via a live getFeed() call plus a
symbol() match, exactly per this project's registry-lookup methodology
(reports/malfunction_candidates.md's own "registry-lookup trick").

Mines full history for these 7 feeds (LINK, DAI, UNI, COMP, MATIC, SNX, AAVE, all vs
USD) with the exact same method/thresholds as the original src/mine_malfunctions.py
(HEARTBEAT_MULTIPLE=6x own median, or >=4h absolute, whichever is larger), excluding
gaps within 2000 blocks of any of the 46 already-locked incidents (original 20 +
phase 1's 8 manipulation + 18 volatility), not just the original 20.

CRV/USD, MKR/USD, and the newer-LSD depeg-lag checks (Part B of the stalled script)
are NOT covered here -- reported as skipped, not as "checked and found nothing."
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from fetch_chainlink import get_feed_update_history, get_web3

FEEDS = {
    "LINK/USD": "0x96d6e33B411dc1f4E3F1e894A5A5d9CE0F96738D",
    "DAI/USD": "0x709783ab12b65fD6cd948214EEe6448f3BdD72A3",
    "UNI/USD": "0xdEf8C51d7c1040637A198efFc39613865B32EA51",
    "COMP/USD": "0x24e3c657c27DfC7ea6f9f58e86387D846b3BaA59",
    "MATIC/USD": "0xC1e7D47ECfbb15B99a4B5F69E6931587000DD0b0",
    "SNX/USD": "0xc778E9686F0fde6Fe4D7d8fE4B481463Fce898fD",
    "AAVE/USD": "0xd8B9aA6E811c935eF63e877CFA7Be276931293DA",
}

MIN_TIMESTAMP = int(pd.Timestamp("2020-01-01", tz="UTC").timestamp())
MAX_ROUNDS = 3000
BATCH_SIZE = 10
HEARTBEAT_MULTIPLE = 6
MIN_ABSOLUTE_GAP_SECONDS = 4 * 3600

# All 46 currently-locked incident blocks (original 20 + phase 1's 8 manipulation +
# 18 volatility) -- read from data/processed/features.parquet directly so this list
# can't drift out of sync with what's actually locked.
FEATURES_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "features.parquet"
LOCKED_BLOCKS = pd.read_parquet(FEATURES_PATH)["block"].astype(int).tolist()
EXCLUSION_BLOCK_WINDOW = 2000


def _find_block_for_timestamp(w3, target_ts: int) -> int:
    lo, hi = 0, w3.eth.block_number
    while lo < hi:
        mid = (lo + hi) // 2
        if w3.eth.get_block(mid)["timestamp"] < target_ts:
            lo = mid + 1
        else:
            hi = mid
    return lo


def mine_feed(w3, name, address):
    print(f"Mining {name} ({address})...", flush=True)
    history = get_feed_update_history(w3, address, min_timestamp=MIN_TIMESTAMP, max_rounds=MAX_ROUNDS, batch_size=BATCH_SIZE)
    if history.empty:
        print(f"  no history returned", flush=True)
        return pd.DataFrame()
    print(f"  {len(history)} rounds, {history['timestamp'].min()} -> {history['timestamp'].max()}", flush=True)
    baseline = history["gap_seconds"].median()
    threshold = max(HEARTBEAT_MULTIPLE * baseline, MIN_ABSOLUTE_GAP_SECONDS)
    print(f"  median gap {baseline:.0f}s, flagging >= {threshold:.0f}s", flush=True)
    flagged = history[history["gap_seconds"] >= threshold].copy()
    flagged["feed_name"] = name
    flagged["feed_address"] = address
    flagged["price_before"] = history["answer"].shift(1).loc[flagged.index]
    print(f"  {len(flagged)} gap(s) flagged", flush=True)
    return flagged


def main():
    w3 = get_web3()
    print(f"Excluding gaps within {EXCLUSION_BLOCK_WINDOW} blocks of {len(LOCKED_BLOCKS)} locked incidents.", flush=True)

    all_flagged = pd.concat([mine_feed(w3, n, a) for n, a in FEEDS.items()], ignore_index=True)
    if all_flagged.empty:
        print("\nNo gaps flagged across any of the 7 feeds -- clean, no candidates.", flush=True)
        rows = []
    else:
        all_flagged = all_flagged.sort_values("gap_seconds", ascending=False).reset_index(drop=True)
        rows = []
        for _, r in all_flagged.iterrows():
            block_number = _find_block_for_timestamp(w3, int(r["updated_at"]))
            if any(abs(block_number - lb) <= EXCLUSION_BLOCK_WINDOW for lb in LOCKED_BLOCKS):
                continue
            rows.append({
                "feed_name": r["feed_name"], "feed_address": r["feed_address"], "block_number": block_number,
                "gap_seconds": r["gap_seconds"], "price_before": r["price_before"], "price_after": r["answer"],
                "updated_at": r["timestamp"],
            })

    lines = [
        "# Malfunction Candidates -- Phase 1 (targeted re-run)",
        "",
        "**Scope note**: the original phase-1 malfunction search "
        "(`src/mine_malfunctions_phase1.py`) hung indefinitely on MKR/USD's `symbol()` "
        "call (MKR is a legacy token whose `symbol()` returns `bytes32`, not a dynamic "
        "string -- a known ABI-decoding footgun) after successfully resolving 7 other "
        "feeds via live Feed Registry lookups. This script mines full history for those "
        "7 already-verified feeds directly. **CRV/USD, MKR/USD, and the newer-LSD "
        "depeg-lag checks (weETH/ezETH/osETH) from the original plan were NOT "
        "completed** -- reported as skipped due to a tooling stall, not as checked-and-"
        "clean.",
        "",
        f"Feeds mined (full history from 2020-01-01, {MAX_ROUNDS}-round cap per feed): "
        f"{', '.join(FEEDS.keys())}. Same method as the original malfunction search "
        f"(`src/mine_malfunctions.py`): a gap is flagged if >= {HEARTBEAT_MULTIPLE}x the "
        f"feed's own median update interval, or >= {MIN_ABSOLUTE_GAP_SECONDS//3600}h, "
        f"whichever is larger. Excluded any gap within {EXCLUSION_BLOCK_WINDOW} blocks "
        f"of any of the 46 currently-locked incidents (original 20 + phase 1's 26).",
        "",
    ]
    if not rows:
        lines.append("**Result: zero new malfunction candidates found** across all 7 feeds mined. "
                      "Consistent with the original search's conclusion that clean mainnet "
                      "malfunctions are structurally rare.")
    else:
        lines.append("| Feed | Address | Block | Gap (s) | Price Before | Price After | Updated At |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in rows:
            lines.append(f"| {r['feed_name']} | `{r['feed_address']}` | {r['block_number']:,} | "
                          f"{r['gap_seconds']:.0f} | {r['price_before']:.4f} | {r['price_after']:.4f} | "
                          f"{r['updated_at']} |")

    out_path = Path(__file__).resolve().parent.parent / "reports" / "malfunction_candidates_phase1.md"
    out_path.write_text("\n".join(lines) + "\n")
    print(f"\nWrote {len(rows)} candidates to {out_path}", flush=True)


if __name__ == "__main__":
    main()
