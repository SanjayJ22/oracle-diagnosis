"""Recompute reserve_skew for 6 of phase 1's 7 new manipulation incidents (reports/
scaling_plan.md), using each incident's actually-exploited venue instead of the ETH/USD
fallback baked into build_features.py's standard path -- same pattern as
src/recompute_manipulation_curve_features.py did for the original 5.

MEVBOTa47b is excluded here: its exploited venue genuinely IS the WETH/USDC V3 pool
already used elsewhere in this project, so build_features.py's standard dex_pool path
already gives it a correct reserve_skew (and cross_venue_spread/dex_oracle_spread) --
no bespoke recompute needed.

price_dev is left None for all 7, same reasoning as Indexed/Inverse Finance in the
original 5: none of these incidents has a single clean "implied price vs a peg/reference"
number (a multi-token balance skew, a vault share price, or a raw balance spike --
not a peg ratio), so there's nothing for price_dev to correctly represent. reserve_skew
(before/after at the SAME venue) is the signal, not price_dev.

Venue per incident (identified from each incident's own DeFiHackLabs PoC source,
addresses cross-checked against the PoC's own contract declarations, not guessed):
  Conic Finance 02  - Curve crvUSD/USDC pool, 0x4DEcE678ceceb27446b35C672dC7d61F30bAD69E
                      -> max abs balance skew across [crvUSD, USDC]
  ZunamiProtocol    - Curve UZD/crvFRAX pool, 0x68934F60758243eafAf4D2cFeD27BF8010bede3a
                      -> max abs balance skew across [UZD, crvFRAX]
  CompoundUni       - Uniswap V3 UNI/WETH pool, 0x1d42064Fc4Beb5F8aAF85F4617AE8b3b5B8Bd801
                      (the exact pool Compound's UniswapAnchoredView reads)
                      -> max abs balance skew across [UNI, WETH]
  CurveLlamaLend    - CORRECTED after post-mortem review (was: a Curve DOLA/sDOLA pool
                      that turned out to hold zero raw DOLA -- wrong venue). The real
                      target, confirmed via darknavy.org's writeup and Curve's own
                      governance post-mortem (gov.curve.finance/t/llamalend-sdola-long2-
                      post-mortem/11020): DolaSavings (sDOLA's own ERC4626-style vault),
                      0xE5f24791E273Cb96A1f8E5B67Bc2397F0AD9B8B4, whose convertToAssets()
                      was atomically manipulated via a large stake()/unstake() round-trip
                      within the attack transaction (13.79% price inflation, 1.189 ->
                      1.353) -> tracks [DOLA] balance only.
  ResupplyFi        - CORRECTED after post-mortem review (was: the Curve reUSD pool,
                      which turned out to hold zero raw crvUSD -- wrong venue). The real
                      target, confirmed via rekt.news's writeup AND by decoding the
                      attack tx's own crvUSD Transfer logs directly on-chain: a classic
                      donation attack against a newly-deployed, nearly-empty cvcrvUSD
                      vault controller, 0x89707721927d7aaeeee513797A8d6cBbD0e08f41 --
                      2,002 crvUSD transferred directly to it (confirmed via the attack
                      tx's logs: balance 0 -> 2002.0 crvUSD) to corrupt its
                      exchange-rate math -> tracks [crvUSD] balance only.
  MonoX Finance     - Monoswap's own MonoXPool (custom AMM, not Uniswap/Curve),
                      0x59653E37F8c491C3Be36e5DD4D503Ca32B5ab2f4
                      -> max abs balance skew across [MONO, USDC] (the pool's own vCash
                      pricing model isn't a standard invariant, so a raw balanceOf()
                      skew is used as the best-available proxy, same spirit as Indexed
                      Finance's own multi-token max-skew treatment in the original 5)

MorphoBlue is DELETED from this file and from build_features.py's
PHASE1_MANIPULATION_INCIDENTS entirely (not just re-pointed to a new venue): its root
cause, confirmed via two independent post-mortems, is a static oracle SCALE_FACTOR
misconfiguration (a PAXG/USDC decimals mismatch inflating PAXG's price by 10^12,
wrong from the market's deployment) -- no market was ever manipulated, no venue exists
to read from, and this incident has no market-observable signature of any kind. It does
not belong in this project's manipulation class (a market-observable price distortion),
so it was dropped rather than patched with a misleading reserve_skew. See
reports/manipulation_candidates_phase1.md for the full writeup.

Same BASELINE_LAG_BLOCKS (~1h before the incident block) as build_features.py /
recompute_manipulation_curve_features.py for consistency.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from fetch_chainlink import get_web3  # noqa: E402
from fetch_curve import get_coin_balances  # noqa: E402

FEATURES_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "features.parquet"
BASELINE_LAG_BLOCKS = 300

CONIC02_POOL = "0x4DEcE678ceceb27446b35C672dC7d61F30bAD69E"
CONIC02_COINS = [
    "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E",  # crvUSD
    "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # USDC
]
ZUNAMI_POOL = "0x68934F60758243eafAf4D2cFeD27BF8010bede3a"
ZUNAMI_COINS = [
    "0xb40b6608B2743E691C9B54DdBDEe7bf03cd79f1c",  # UZD
    "0x3175Df0976dFA876431C2E9eE6Bc45b65d3473CC",  # crvFRAX
]
COMPOUNDUNI_POOL = "0x1d42064Fc4Beb5F8aAF85F4617AE8b3b5B8Bd801"
COMPOUNDUNI_COINS = [
    "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",  # UNI
    "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
]
CURVELLAMALEND_POOL = "0xE5f24791E273Cb96A1f8E5B67Bc2397F0AD9B8B4"  # DolaSavings (sDOLA vault)
CURVELLAMALEND_COINS = [
    "0x865377367054516e17014CcdED1e7d814EDC9ce4",  # DOLA
]
RESUPPLYFI_POOL = "0x89707721927d7aaeeee513797A8d6cBbD0e08f41"  # cvcrvUSD vault controller (donation target)
RESUPPLYFI_COINS = [
    "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E",  # crvUSD
]
MONOX_POOL = "0x59653E37F8c491C3Be36e5DD4D503Ca32B5ab2f4"
MONOX_COINS = [
    "0x2920f7d6134f4669343e70122cA9b8f19Ef8fa5D",  # MONO
    "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # USDC
]

VENUES = {
    "Conic Finance 02": (CONIC02_POOL, CONIC02_COINS),
    "ZunamiProtocol": (ZUNAMI_POOL, ZUNAMI_COINS),
    "CompoundUni": (COMPOUNDUNI_POOL, COMPOUNDUNI_COINS),
    "CurveLlamaLend": (CURVELLAMALEND_POOL, CURVELLAMALEND_COINS),
    "ResupplyFi": (RESUPPLYFI_POOL, RESUPPLYFI_COINS),
    "MonoX Finance": (MONOX_POOL, MONOX_COINS),
}
# MorphoBlue intentionally excluded -- see module docstring: dropped from the dataset
# entirely (not a venue-identification fix), a static oracle misconfiguration with no
# manipulated venue at all.


def _pct_change(new, old):
    if old is None or new is None:
        return None
    if old == 0:
        return float("inf") if new != 0 else 0.0
    return (new - old) / old


def recompute(w3, name: str, block: int):
    pool, coins = VENUES[name]
    baseline_block = block - BASELINE_LAG_BLOCKS
    now = get_coin_balances(w3, pool, coins, block)["balances"]
    base = get_coin_balances(w3, pool, coins, baseline_block)["balances"]
    skews = {c: _pct_change(now[c], base[c]) for c in coins}
    max_coin = max(skews, key=lambda c: abs(skews[c]) if skews[c] not in (None, float("inf")) else -1)
    reserve_skew = skews[max_coin]

    print(f"--- {name} ---")
    print(f"  venue: {pool}")
    for c in coins:
        print(f"    {c}: now={now[c]:.6f} baseline={base[c]:.6f} skew={skews[c]}")
    print(f"  reserve_skew (max abs skew): {reserve_skew}")

    df = pd.read_parquet(FEATURES_PATH)
    idx = df.index[df["incident"] == name][0]
    df.loc[idx, "price_dev"] = None
    df.loc[idx, "reserve_skew"] = reserve_skew
    note = (
        f" [PHASE1 reserve_skew: max abs balance skew across {[c for c in coins]} at venue "
        f"{pool}, incident block vs block-{BASELINE_LAG_BLOCKS}: {reserve_skew}]"
    )
    df.loc[idx, "reference_note"] = str(df.loc[idx, "reference_note"] or "") + note
    df.to_parquet(FEATURES_PATH, index=False)


def main():
    w3 = get_web3()
    df = pd.read_parquet(FEATURES_PATH)
    for name in VENUES:
        row = df[df["incident"] == name]
        if row.empty:
            print(f"SKIP {name}: not found in features.parquet (run build_features.py first)")
            continue
        recompute(w3, name, int(row.iloc[0]["block"]))
        time.sleep(0.2)
    print("\nDone. Updated features.parquet for 6 of phase 1's 7 new manipulation rows "
          "(MEVBOTa47b excluded -- uses the standard WETH/USDC V3 dex_pool path instead).")


if __name__ == "__main__":
    main()
