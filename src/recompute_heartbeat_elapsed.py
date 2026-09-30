"""Fix the heartbeat_elapsed anchoring artifact flagged after the first model pass.

Old (buggy) definition: heartbeat_elapsed = anchor_block_timestamp - updated_at of the
oracle round AT the anchor block. For malfunction/volatility incidents, the anchor block
WAS itself chosen to be an oracle-update transaction (the trough price update, the final
freeze update), so this trivially returned 0 for all 15 of them. Manipulation incidents
were anchored to the exploit transaction (not an oracle update), so this correctly
returned a nonzero "how stale was the oracle at that moment" gap. The result: heartbeat_
elapsed was 0 for every non-manipulation incident and nonzero for every manipulation
incident -- a giveaway the models were exploiting, not a real freshness signal.

Fix: always read the oracle round at (anchor_block - 1), i.e. the round in effect
STRICTLY BEFORE the anchor block, excluding any update that happens to land exactly on
it. heartbeat_elapsed = anchor_block_timestamp - that_round's updated_at.
  - Malfunction/volatility (anchor = an update tx itself): this now returns the gap
    that PRECEDED the anchor update -- e.g. stETH's ~24h heartbeat lag, exactly matching
    reports/malfunction_candidates.md's own gap_seconds finding.
  - Manipulation (anchor = an unrelated exploit tx, essentially never landing exactly on
    an oracle update): querying block-1 vs block returns the same prior round almost
    always, so these values should be essentially unchanged.

Same measurement, same class of block (each incident's own defining event/transaction),
now applied uniformly. Updates ONLY the heartbeat_elapsed column; nothing else in
features.parquet changes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from build_features import INCIDENTS
from fetch_chainlink import _with_retry, get_round_data_at_block, get_web3

FEATURES_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "features.parquet"


def main():
    w3 = get_web3()
    df = pd.read_parquet(FEATURES_PATH)

    print(f"{'incident':35s} {'old':>10s} {'new':>10s}  change")
    for incident in INCIDENTS:
        name, block_number, feed = incident["name"], incident["block"], incident["oracle_feed"]
        block = _with_retry(lambda: w3.eth.get_block(block_number))
        prev_round = get_round_data_at_block(w3, feed, block_number - 1)
        new_elapsed = block["timestamp"] - int(prev_round["updated_at"])

        idx = df.index[df["incident"] == name][0]
        old_elapsed = df.loc[idx, "heartbeat_elapsed"]
        df.loc[idx, "heartbeat_elapsed"] = new_elapsed

        flag = "  <-- was the artifact (0)" if old_elapsed == 0 and new_elapsed != 0 else (
            "  <-- changed" if old_elapsed != new_elapsed else "  (unchanged)"
        )
        print(f"{name:35s} {old_elapsed:>10} {new_elapsed:>10}{flag}")

    df.to_parquet(FEATURES_PATH, index=False)
    print(f"\nWrote corrected heartbeat_elapsed for {len(INCIDENTS)} incidents to {FEATURES_PATH}")


if __name__ == "__main__":
    main()
