"""Recompute reserve_skew for phase 2's manipulation incidents (reports/
scaling_plan.md), using each incident's actually-exploited venue instead of the
ETH/USD fallback baked into build_features.py's standard path -- same pattern as
src/recompute_manipulation_curve_features.py (original 5) and
src/recompute_phase1_manipulation_curve_features.py (phase 1's 6).

Phase 2 originally added 12 manipulation incidents. 8 came back with reserve_skew
unresolved (zero balance at both the incident and baseline blocks). A dedicated
resolution pass (reading each attack tx's own Transfer logs directly, not trusting
the PoC's declared address) found:
  - TOPBPool: the configured venue was simply wrong (didn't appear in the attack
    tx's logs at all). The real venue was identified and FIXED below -- a genuine,
    persisting balance drain, not an atomic round-trip.
  - The other 7 (SummerFi, Raft_fi, bZxProtocol, edel-xstock, CompounderFinance,
    MetaPool, MahaLend) were DROPPED from build_features.py's
    PHASE2_MANIPULATION_INCIDENTS entirely, not kept as a misleading NaN or 0.0.
    Each falls into one of two categories, confirmed via direct log decoding (see
    the removal comments in build_features.py for the specific evidence per
    incident):
      (a) diffuse multi-venue exploits with no single venue balance representing
          the incident (SummerFi, edel-xstock), or
      (b) exchange-rate/accounting manipulations (iYFI, yDAI, mUSDC, mpETH share
          pricing) where the underlying token balance returns to ~baseline within
          the same transaction regardless of which venue address is used -- an
          architectural blind spot of a before/after balance-ratio metric, not a
          wrong-venue-guess problem (Raft_fi, bZxProtocol, CompounderFinance,
          MetaPool, MahaLend).
  This VENUES dict now reflects only the 5 phase-2 manipulation incidents that
  resolve cleanly: BalancerV2, Makina, TOPBPool (corrected), WiseLending,
  BalancerV1BPool.

  BalancerV2         - osETH/wETH ComposableStablePool, 0xDACf5Fa19b1f720111609043ac67A9818262850c
                       -> max abs skew across [osETH, WETH]
  Makina             - DUSD/USDC Curve pool, 0x32e616f4f17d43f9a5cd9be0e294727187064cb3
                       -> USDC balance only (DUSD address not independently confirmed)
  TOPBPool           - CORRECTED: bonding-curve-style AMM, 0x0fa3e014fa2e751f78e53dca766fac2223327329
                       (originally configured venue did not appear in the attack tx at all)
                       -> max abs skew across [TOP, WETH]
  WiseLending        - pool contract, 0x84524baa1951247b3a2617a843e6ece915bb9674
                       -> max abs skew across [WETH, USDC]
  BalancerV1BPool    - DPI/USDC/WETH/WBTC BPool, 0x2257aaac34bcb27900291f7b84ee2565a6cbac57
                       -> max abs skew across [WETH, USDC]

price_dev is left None for all of these, same reasoning as the original 5's Indexed/
Inverse Finance and all of phase 1's additions: none has a single clean "implied
price vs a peg/reference" number. reserve_skew (before/after at the SAME venue) is
the signal. Same BASELINE_LAG_BLOCKS (~1h before the incident block) as the other
recompute scripts.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from web3 import Web3
from fetch_chainlink import get_web3  # noqa: E402
from fetch_curve import get_coin_balances  # noqa: E402

# Balancer V2 architecture note, found the hard way: unlike Curve/V1-style pools,
# a Balancer V2 pool contract does NOT hold its own tokens -- ALL V2 pools' tokens
# are held by one shared Vault contract, indexed internally by pool ID. Querying
# balanceOf(pool_address) via get_coin_balances() (correct for every other venue in
# this project) returns 0 for a V2 pool by design, not because nothing happened --
# confirmed by checking BalancerV1BPool (an actual V1 pool, which DOES hold tokens
# directly) worked fine with the generic method, isolating this to V2 specifically.
BALANCER_VAULT = Web3.to_checksum_address("0xBA12222222228d8Ba445958a75a0704d566BF2C8")
VAULT_ABI = [
    {"inputs": [{"name": "poolId", "type": "bytes32"}], "name": "getPoolTokens",
     "outputs": [{"name": "tokens", "type": "address[]"}, {"name": "balances", "type": "uint256[]"},
                 {"name": "lastChangeBlock", "type": "uint256"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "getPoolId", "outputs": [{"name": "", "type": "bytes32"}],
     "stateMutability": "view", "type": "function"},
]


def get_balancer_v2_pool_balances(w3, pool_address: str, coins: list, block: int) -> dict:
    """Balancer-V2-specific equivalent of get_coin_balances(): reads token balances
    from the shared Vault via getPoolTokens(poolId), not balanceOf(pool_address)."""
    pool_contract = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=VAULT_ABI)
    pool_id = pool_contract.functions.getPoolId().call(block_identifier=block)
    vault = w3.eth.contract(address=BALANCER_VAULT, abi=VAULT_ABI)
    tokens, balances, _ = vault.functions.getPoolTokens(pool_id).call(block_identifier=block)
    wanted = {c.lower() for c in coins}
    return {t: bal / 1e18 for t, bal in zip(tokens, balances) if t.lower() in wanted}

FEATURES_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "features.parquet"
BASELINE_LAG_BLOCKS = 300

WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
OSETH = "0xf1C9acDc66974dFB6dEcB12aA385b9cD01190E38"
TOP = "0x0EBD5eC91680d3B0CEDbb1d5BB61851154D3eDb6"

VENUES = {
    "BalancerV2": ("0xDACf5Fa19b1f720111609043ac67A9818262850c", [OSETH, WETH]),
    "Makina": ("0x32e616f4f17d43f9a5cd9be0e294727187064cb3", [USDC]),
    "TOPBPool": ("0x0fa3e014fa2e751f78e53dca766fac2223327329", [TOP, WETH]),
    "WiseLending": ("0x84524baa1951247b3a2617a843e6ece915bb9674", [WETH, USDC]),
    "BalancerV1BPool": ("0x2257aaac34bcb27900291f7b84ee2565a6cbac57", [WETH, USDC]),
}


def _pct_change(new, old):
    if old is None or new is None:
        return None
    if old == 0:
        return float("inf") if new != 0 else 0.0
    return (new - old) / old


def recompute(w3, name: str, block: int):
    pool, coins = VENUES[name]
    baseline_block = block - BASELINE_LAG_BLOCKS
    reader = get_balancer_v2_pool_balances if name == "BalancerV2" else \
        (lambda w3, p, c, b: get_coin_balances(w3, p, c, b)["balances"])
    now = reader(w3, pool, coins, block)
    base = reader(w3, pool, coins, baseline_block)
    skews = {c: _pct_change(now.get(c), base.get(c)) for c in coins}

    print(f"--- {name} ---")
    print(f"  venue: {pool}")
    for c in coins:
        print(f"    {c}: now={now.get(c)} baseline={base.get(c)} skew={skews.get(c)}")

    # If EVERY tracked coin shows baseline==0 AND now==0, this is not a genuine "no
    # change" -- it means the address never held this token at this block at all
    # (found the hard way: 8 of these 12 venues came back this way on the first
    # attempt, meaning the guessed venue address or token was wrong, not that
    # nothing happened -- a real drain-to-zero, like WiseLending's, has a NONZERO
    # baseline). Reported honestly as unresolved (NaN), not silently kept as a
    # misleading 0.0 that would look identical to "checked and clean" in the data.
    all_zero = all((base.get(c) or 0) == 0 and (now.get(c) or 0) == 0 for c in coins)
    if all_zero:
        reserve_skew = None
        print("  ALL TRACKED COINS SHOW ZERO BALANCE AT BOTH BLOCKS -- venue/token guess "
              "did not resolve to a real holding. reserve_skew left as NaN (unresolved), "
              "not force-set to 0.0.")
    else:
        max_coin = max(skews, key=lambda c: abs(skews[c]) if skews[c] not in (None, float("inf")) else -1)
        reserve_skew = skews[max_coin]
        print(f"  reserve_skew (max abs skew): {reserve_skew}")

    df = pd.read_parquet(FEATURES_PATH)
    idx = df.index[df["incident"] == name][0]
    df.loc[idx, "price_dev"] = None
    df.loc[idx, "reserve_skew"] = reserve_skew
    note = (
        f" [PHASE2 reserve_skew: UNRESOLVED -- venue/token guess ({coins} at {pool}) showed "
        f"zero balance at both blocks, not force-set to a misleading 0.0]" if all_zero else
        f" [PHASE2 reserve_skew: max abs balance skew across {coins} at venue "
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
    print(f"\nDone. Updated features.parquet for {len(VENUES)} phase-2 manipulation rows.")


if __name__ == "__main__":
    main()
