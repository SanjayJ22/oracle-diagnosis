"""Recompute reserve_skew for phase 3's 7 new manipulation incidents (reports/
scaling_plan.md), using each incident's actually-exploited venue instead of the
ETH/USD fallback baked into build_features.py's standard path -- same pattern as
src/recompute_manipulation_curve_features.py (original 5), src/recompute_phase1_
manipulation_curve_features.py (phase 1's 6), and src/recompute_phase2_manipulation_
curve_features.py (phase 2's 5 surviving incidents).

Unlike phase 2, all 7 of these were pre-screened for the atomic-round-trip/diffuse-
venue failure mode BEFORE integration (see reports/manipulation_candidates_phase3.md),
not after -- 2 of the 7 (EFLeverVault, ThetanutsIndexVault) already needed a venue
correction during that pre-screening pass, applied here directly rather than
discovered as a NaN later.

Venue per incident (full before/after evidence and sourcing in
reports/manipulation_candidates_phase3.md):
  AjnaFinance              - cbETH/WETH ERC20Pool, 0xad24FC773e125Edb223C38a39657cB64bc7C178e
                             -> max abs skew across [cbETH, WETH]
  BalancerBoostedPool2023  - Balancer V2 bb-a-USDC Linear Pool, 0x9210F1204b5a24742Eba12f710636D76240dF3d0
                             -> USDC balance only via the Vault method (aUSDC buffer is dust at
                                both blocks -- a degenerate value explicitly excluded, not picked
                                by a naive max-abs-skew that would otherwise select it)
  DRLVaultV3               - leveraged vault, 0x6A06707ab339BEE00C6663db17DdB422301ff5e8
                             -> USDC balance (clean full drain)
  EFLeverVault             - Aave V1 aSTETH position, 0x1982b2F5814301d4e9a8b0201555376e62F82428,
                             at vault 0xe39fd820B58f83205Db1D9225f28105971c3D309
                             -> aSTETH balance (CORRECTED from the PoC's WETH/EF_LEVER_TOKEN guess,
                                which came back all-zero)
  SecuredFi                - TokenVault, 0xb74749b2213916b1da3b869e41c7c57f1db69393
                             -> WBTC balance
  ThetanutsIndexVault      - BTC_USD_VAULT, 0x3BA337F3167eA35910E6979D5BC3b0AeE60E7d59 (primary;
                             ETH_USD_VAULT 0xE1c93dE547cc85CBD568295f6CC322B1dbBCf8Ae also drained
                             same tx, sums to the exact reported loss -- CORRECTED from the PoC's
                             INDEX_VAULT guess, which came back all-zero)
                             -> USDC balance at BTC_USD_VAULT
  USM                      - native ETH, 0x2a7FFf44C19f39468064ab5e5c304De01D591675
                             -> native ETH balance via eth_getBalance, NOT balanceOf (this drains
                                ETH directly, not WETH)

price_dev is left None for all 7, same reasoning as every prior phase's additions:
none has a single clean "implied price vs a peg/reference" number. reserve_skew
(before/after at the SAME venue) is the signal. Same BASELINE_LAG_BLOCKS (~1h before
the incident block) as every other recompute script in this project.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from web3 import Web3
from fetch_chainlink import get_web3  # noqa: E402
from fetch_curve import get_coin_balances  # noqa: E402

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
    pool_contract = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=VAULT_ABI)
    pool_id = pool_contract.functions.getPoolId().call(block_identifier=block)
    vault = w3.eth.contract(address=BALANCER_VAULT, abi=VAULT_ABI)
    tokens, balances, _ = vault.functions.getPoolTokens(pool_id).call(block_identifier=block)
    wanted = {c.lower() for c in coins}
    # decimals: USDC is 6, everything else here is 18 -- read live rather than hardcode
    out = {}
    for t, bal in zip(tokens, balances):
        if t.lower() not in wanted:
            continue
        dec = 6 if t.lower() == "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48" else 18
        out[t] = bal / (10 ** dec)
    return out


def get_native_eth_balance(w3, address: str, block: int) -> dict:
    """USM drains native ETH, not an ERC20 -- eth_getBalance, not balanceOf()."""
    bal = w3.eth.get_balance(Web3.to_checksum_address(address), block_identifier=block)
    return {"NATIVE_ETH": bal / 1e18}


FEATURES_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "features.parquet"
BASELINE_LAG_BLOCKS = 300

WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
CBETH = "0xBe9895146f7AF43049ca1c1AE358B0541Ea49704"
WBTC = "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599"
ASTETH = "0x1982b2F5814301d4e9a8b0201555376e62F82428"

VENUES = {
    "AjnaFinance": ("0xad24FC773e125Edb223C38a39657cB64bc7C178e", [CBETH, WETH], "erc20"),
    "BalancerBoostedPool2023": ("0x9210F1204b5a24742Eba12f710636D76240dF3d0", [USDC], "balancer_v2"),
    "DRLVaultV3": ("0x6A06707ab339BEE00C6663db17DdB422301ff5e8", [USDC], "erc20"),
    "EFLeverVault": ("0xe39fd820B58f83205Db1D9225f28105971c3D309", [ASTETH], "erc20"),
    "SecuredFi": ("0xb74749b2213916b1da3b869e41c7c57f1db69393", [WBTC], "erc20"),
    "ThetanutsIndexVault": ("0x3BA337F3167eA35910E6979D5BC3b0AeE60E7d59", [USDC], "erc20"),
    "USM": ("0x2a7FFf44C19f39468064ab5e5c304De01D591675", ["NATIVE_ETH"], "native"),
}


def _pct_change(new, old):
    if old is None or new is None:
        return None
    if old == 0:
        return float("inf") if new != 0 else 0.0
    return (new - old) / old


def recompute(w3, name: str, block: int):
    pool, coins, method = VENUES[name]
    baseline_block = block - BASELINE_LAG_BLOCKS

    if method == "balancer_v2":
        reader = lambda w3, p, c, b: get_balancer_v2_pool_balances(w3, p, c, b)
    elif method == "native":
        reader = lambda w3, p, c, b: get_native_eth_balance(w3, p, b)
    else:
        reader = lambda w3, p, c, b: get_coin_balances(w3, p, c, b)["balances"]

    now = reader(w3, pool, coins, block)
    base = reader(w3, pool, coins, baseline_block)
    skews = {c: _pct_change(now.get(c), base.get(c)) for c in coins}

    print(f"--- {name} ---")
    print(f"  venue: {pool} (method={method})")
    for c in coins:
        print(f"    {c}: now={now.get(c)} baseline={base.get(c)} skew={skews.get(c)}")

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
        f" [PHASE3 reserve_skew: UNRESOLVED -- venue/token guess ({coins} at {pool}) showed "
        f"zero balance at both blocks, not force-set to a misleading 0.0]" if all_zero else
        f" [PHASE3 reserve_skew: max abs balance skew across {coins} at venue "
        f"{pool} (method={method}), incident block vs block-{BASELINE_LAG_BLOCKS}: {reserve_skew}]"
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
    print(f"\nDone. Updated features.parquet for {len(VENUES)} phase-3 manipulation rows.")


if __name__ == "__main__":
    main()
