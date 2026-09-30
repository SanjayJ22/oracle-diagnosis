"""Compute the crash-vs-attack discriminating feature pair for all 165 incidents
(reports/crash_vs_attack_feature.md).

Motivation: reports/confusion_analysis.md found that all 11 of the current
production BN's LOOCV errors are explained by a single mechanism -- `reserve_skew`
(a same-venue DEX price % change over a trailing ~1h window) crossing the fixed
0.05 discretization threshold, in BOTH directions: large-magnitude manipulation
incidents are caught, small-magnitude ones are missed; violent real-market crashes
push `reserve_skew` past 0.05 and get misread as manipulation. `reserve_skew` alone
cannot tell a market-wide move from a localized, single-venue attack.

Hypothesis: a market-wide crash moves many independent DEX pools' prices together
(correlated, market-wide) and correlates with elevated CEX-measured realized
volatility; a localized attack distorts one venue's price while the broader market
(other pools, CEX realized vol) stays calm. Two features operationalize this:

  market_basket_skew        - median |% price change| (same before/after ratio
                               convention as reserve_skew, same BASELINE_LAG_BLOCKS
                               window) across a FIXED reference basket of 2-3
                               unrelated, highly-liquid pools (WETH/USDC V3 0.05%,
                               WETH/USDC V2, wstETH/WETH V3), excluding whichever
                               basket pool happens to BE the incident's own
                               manipulated/observed venue (see _excluded_basket
                               below -- prevents circularity for the 138 volatility
                               incidents + MEVBOTa47b, whose own dex_pool IS
                               WETH_USDC_V3, and for stETH/ETH heartbeat lag, whose
                               own dex_pool IS WSTETH_WETH_V3).
  reserve_skew_localization - |reserve_skew| - market_basket_skew. High positive:
                               this venue moved much more than the general market
                               (localized/attack signature). Near zero or negative:
                               this venue moved about as much as the general market
                               (market-wide/crash signature).
  skew_vol_ratio             - |reserve_skew| / (ref_realized_vol + SKEW_VOL_EPS).
                               A real crash has both numerator and denominator high
                               (ratio stays moderate); a localized attack has a high
                               numerator but a calm market (low denominator), so the
                               ratio blows up. Uses ref_realized_vol, ALREADY computed
                               for every incident -- no new RPC calls for this one.

FEASIBILITY (reports/crash_vs_attack_feature.md Sec 1 has the full writeup): reading
several reference pools per incident on the current free Alchemy tier is feasible
and cheap IN NORMAL OPERATION (~1-7s per incident for a full 3-pool/2-block read),
but a naive implementation that calls fetch_dex.py's get_v2_reserves/get_v3_state
directly on a pool that doesn't exist yet at an old block height (e.g. Uniswap V3
did not exist before ~May 2021, so Harvest Finance's Oct 2020 block predates it)
triggers that pool's contract-call revert on EVERY sub-call (token0, token1,
slot0/reserves, liquidity, decimals), each retried MAX_RETRIES=6 times with
exponential-ish backoff (5,10,15,20,25s) -- tens of minutes of pure sleep for one
incident, confirmed directly during this feasibility check (a naive first attempt
was killed after 2+ minutes of silence). Fixed by prechecking pool deployment via
a single, near-instant `w3.eth.get_code(pool_address, block_identifier=block)` call
BEFORE attempting the expensive multi-call read -- if the bytecode is empty, the
pool doesn't exist yet at this block, skip it with zero retries burned. This
precheck is the reason multi-pool reading is feasible here at all; without it, the
retry-storm cost would make it impractical at 165-incident scale.

All windows strictly trailing (baseline block = incident_block - BASELINE_LAG_BLOCKS,
same convention build_features.py already uses for reserve_skew) -- no lookahead.
"""

import sys
import time
import warnings
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
from web3 import Web3

from build_features import BASELINE_LAG_BLOCKS, INCIDENTS, WETH_USDC_V2, WETH_USDC_V3, WSTETH_WETH_V3
from fetch_chainlink import get_web3
from fetch_dex import get_v2_reserves, get_v3_state

FEATURES_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "features.parquet"
REFERENCE_BASKET = [WETH_USDC_V3, WETH_USDC_V2, WSTETH_WETH_V3]  # (kind, addr, invert) tuples
SKEW_VOL_EPS = 0.001  # ~ the smallest observed ref_realized_vol magnitude; prevents divide-by-near-zero blowup


def _deployed(w3, addr: str, block_number: int) -> bool:
    """Cheap existence precheck -- avoids the retry-storm cost documented above."""
    code = w3.eth.get_code(Web3.to_checksum_address(addr), block_identifier=block_number)
    return len(code) > 0


def _pool_pct_change(w3, kind: str, addr: str, block_number: int, baseline_block: int):
    """Same before/after ratio convention as build_features.py's reserve_skew."""
    if not _deployed(w3, addr, baseline_block):
        return None  # not yet deployed at the EARLIER of the two blocks -> skip, no retries spent
    reader = get_v3_state if kind == "v3" else get_v2_reserves
    st_now = reader(w3, addr, block_number)
    st_base = reader(w3, addr, baseline_block)
    p_now = float(st_now["price_1_per_0"])
    p_base = float(st_base["price_1_per_0"])
    if p_base == 0:
        return None
    return (p_now - p_base) / p_base


def compute_for_incident(w3, incident: dict):
    block = incident["block"]
    baseline_block = block - BASELINE_LAG_BLOCKS
    own_addr = incident["dex_pool"][1].lower() if incident.get("dex_pool") else None

    changes = []
    for kind, addr, _invert in REFERENCE_BASKET:
        if own_addr is not None and addr.lower() == own_addr:
            continue  # exclude the incident's own venue from its own "market" reference
        try:
            chg = _pool_pct_change(w3, kind, addr, block, baseline_block)
        except Exception:
            chg = None
        if chg is not None:
            changes.append(abs(chg))
        time.sleep(0.1)

    if not changes:
        return None, 0, "no reference-basket pool both deployed and readable at this incident's blocks"
    return median(changes), len(changes), ""


def main():
    warnings.filterwarnings("ignore")
    w3 = get_web3()
    df = pd.read_parquet(FEATURES_PATH)

    rows = []
    for i, incident in enumerate(INCIDENTS, 1):
        name = incident["name"]
        print(f"[{i}/{len(INCIDENTS)}] {name}...", flush=True)
        basket_skew, n_basket, reason = compute_for_incident(w3, incident)
        if basket_skew is None:
            print(f"  market_basket_skew=NaN: {reason}", flush=True)
        else:
            print(f"  market_basket_skew={basket_skew:.6f} (n_basket_pools={n_basket})", flush=True)
        rows.append({"incident": name, "market_basket_skew": basket_skew, "n_basket_pools": n_basket})

    basket_df = pd.DataFrame(rows)
    out = df.merge(basket_df, on="incident", how="left")

    abs_skew = out["reserve_skew"].abs()
    out["reserve_skew_localization"] = abs_skew - out["market_basket_skew"]
    out["skew_vol_ratio"] = abs_skew / (out["ref_realized_vol"] + SKEW_VOL_EPS)

    out.to_parquet(FEATURES_PATH, index=False)
    print(f"\nDone. Wrote market_basket_skew, reserve_skew_localization, skew_vol_ratio "
          f"for {len(basket_df)} incidents to {FEATURES_PATH}")

    print("\n=== Coverage report, per class ===")
    for col in ["market_basket_skew", "reserve_skew_localization", "skew_vol_ratio"]:
        print(f"-- {col} --")
        print(out.groupby("label")[col].apply(lambda s: f"{s.notna().sum()}/{len(s)} non-NaN"))


if __name__ == "__main__":
    main()
