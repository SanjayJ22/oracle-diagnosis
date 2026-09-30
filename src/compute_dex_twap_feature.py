"""Compute the DEX-TWAP disagreement feature (reports/richer_features.md Sec 2,
"chainlink_twap_spread") for all 165 incidents -- the one multi-oracle-disagreement
signal in that design doc that works retroactively (unlike Pyth, whose Ethereum
mainnet feeds only went live in 2023, per that doc's own coverage-gap note).

dex_twap_spread = (chainlink_price - dex_twap_price) / dex_twap_price

Where dex_twap_price is the DEX pool's TIME-WEIGHTED AVERAGE price over a
trailing 1800s (30 min) window ending at the incident's own anchor block --
via Uniswap V3's built-in observe() oracle (src/fetch_dex.py's get_v3_twap),
not a manually-averaged sample of several blocks. 1800s reuses this project's
existing MAX_CLEAN_HEARTBEAT_SECONDS convention (the volatility-mining
cleanliness gate's own staleness bar) rather than inventing a new window size.

Coverage, by design, mirrors dex_oracle_spread/cross_venue_spread: only
incidents with a `dex_pool` configured (build_features.py's INCIDENTS list) can
get a real value -- reports/richer_features.md's own Sec 2 already flagged this
gap explicitly ("does not reach the 4 manipulation incidents with no identified
DEX pool at all ... or FTT/USD"). Reused, not newly discovered here.

No lookahead: get_v3_twap reads observe() AT block_identifier=<incident_block>,
which only ever has access to that block's own past observation history --
architecturally incapable of seeing a future block, the same guarantee as every
prior point-in-time read in this project.
"""

import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from build_features import INCIDENTS, WSTETH_WETH_V3, _get_wsteth_rate_cached
from fetch_chainlink import get_round_data_at_block, get_web3
from fetch_dex import get_v3_twap

FEATURES_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "features.parquet"
TWAP_WINDOW_SECONDS = 1800  # 30 min -- reuses MAX_CLEAN_HEARTBEAT_SECONDS's existing convention


def compute_for_incident(w3, incident: dict):
    dex_pool = incident.get("dex_pool")
    if dex_pool is None:
        return None, "no dex_pool configured for this incident"

    kind, addr, invert = dex_pool
    if kind != "v3":
        return None, f"dex_pool kind={kind!r} not supported (only v3 observe()-based TWAP implemented)"

    block = incident["block"]
    twap = get_v3_twap(w3, addr, block, window_seconds=TWAP_WINDOW_SECONDS)
    if twap is None:
        return None, "observe() failed (likely insufficient observation cardinality at this block)"

    dex_twap_price = float(twap["price_1_per_0"])
    dex_twap_price = (1.0 / dex_twap_price) if invert else dex_twap_price
    if addr.lower() == WSTETH_WETH_V3[1].lower():
        dex_twap_price = dex_twap_price / _get_wsteth_rate_cached(w3, block)

    oracle_round = get_round_data_at_block(w3, incident["oracle_feed"], block)
    chainlink_price = float(oracle_round["answer"])

    if dex_twap_price == 0:
        return None, "dex_twap_price is exactly zero, cannot compute a spread"

    spread = (chainlink_price - dex_twap_price) / dex_twap_price
    return {"dex_twap_spread": spread, "dex_twap_price": dex_twap_price,
            "chainlink_price_at_twap": chainlink_price}, ""


def main():
    warnings.filterwarnings("ignore")
    w3 = get_web3()
    df = pd.read_parquet(FEATURES_PATH)

    rows = []
    for i, incident in enumerate(INCIDENTS, 1):
        name = incident["name"]
        print(f"[{i}/{len(INCIDENTS)}] {name}...", flush=True)
        result, reason = compute_for_incident(w3, incident)
        if result is None:
            print(f"  NaN: {reason}", flush=True)
            rows.append({"incident": name, "dex_twap_spread": np.nan})
        else:
            print(f"  dex_twap_spread={result['dex_twap_spread']:.6f} "
                  f"(chainlink={result['chainlink_price_at_twap']:.4f}, "
                  f"dex_twap={result['dex_twap_price']:.4f})", flush=True)
            rows.append({"incident": name, "dex_twap_spread": result["dex_twap_spread"]})
        time.sleep(0.1)

    twap_df = pd.DataFrame(rows)
    out = df.merge(twap_df, on="incident", how="left")
    out.to_parquet(FEATURES_PATH, index=False)
    print(f"\nDone. Wrote dex_twap_spread for {len(twap_df)} incidents to {FEATURES_PATH}")

    print("\n=== Coverage report, per class ===")
    print(out.groupby("label")["dex_twap_spread"].apply(lambda s: f"{s.notna().sum()}/{len(s)} non-NaN"))


if __name__ == "__main__":
    main()
