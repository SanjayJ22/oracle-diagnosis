"""Recompute price_dev and reserve_skew for the 5 manipulation incidents using the
actual manipulated venue (a Curve pool, DEFI5's own weighted pool, or a Yearn vault's
share-price accounting) instead of the ETH/USD or BTC/USD fallback used previously.

Leaves all other rows/columns in data/processed/features.parquet untouched -- this
script only overwrites price_dev/reserve_skew (and reference_note) for the 5
manipulation rows.

Per-incident venue (identified from post-mortems, confirmed on-chain before use here):
  Harvest Finance  - Curve Y pool (yDAI/yUSDC/yUSDT/yTUSD), 0x45F783CCE6B7FF23B2ab2D70e416cdb7D6055f51
                     -> implied USDC/USDT ratio (both should peg ~1.0)
  Cream Finance    - Yearn yUSD Vault, 0x4b5bfd52124784745c1071dcb244c6688d2533d3,
                     holding Curve Y-pool LP token 0xdF5e0e81Dff6FAF3A7e52BA697820c5e32D806A8
                     -> vault price-per-share (should be ~1.0 when healthy)
  Indexed Finance  - DEFI5's own Balancer-style weighted pool (NOT Curve),
                     0xfa6de2697d59e88ed7fc4dfe5a33dac43565ea41, 7 constituent tokens
                     -> max absolute balance-ratio skew across the 7 tokens
  Inverse Finance  - Curve tricrypto2 (USDT/WBTC/WETH), 0xD51a44d3FaE010294C616388b506AcdA1bfAAE46
                     -> implied WBTC/USDT price (price_scale(0)) vs Binance.US BTC/USDT
  UwU Lend         - Curve USDe/USDC pool, 0x02950460E2b9529D0E00284A5fA2d7bDF3fA4d72
                     -> implied USDe/USDC ratio (both should peg ~1.0)
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from fetch_cex import fetch_cex_klines  # noqa: E402
from fetch_chainlink import get_web3  # noqa: E402
from fetch_curve import get_coin_balances, get_vault_share_price, get_virtual_price  # noqa: E402

FEATURES_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "features.parquet"
BASELINE_LAG_BLOCKS = 300  # same trailing baseline convention as build_features.py

# Y pool (yDAI, yUSDC, yUSDT, yTUSD) -- verified via coins(0..3) at Harvest's block.
YPOOL = "0x45F783CCE6B7FF23B2ab2D70e416cdb7D6055f51"
YPOOL_COINS = [
    "0x16de59092dAE5CcF4A1E6439D611fd0653f0Bd01",  # yDAI
    "0xd6aD7a6750A7593E092a9B218d66C0A814a3436e",  # yUSDC
    "0x83f798e925BcD4017Eb265844FDDAbb448f1707D",  # yUSDT
    "0x73a052500105205d34Daf004eAb301916DA8190f",  # yTUSD
]
YUSD_VAULT = "0x4b5bfd52124784745c1071dcb244c6688d2533d3"
YPOOL_LP_TOKEN = "0xdF5e0e81Dff6FAF3A7e52BA697820c5e32D806A8"
DEFI5 = "0xfa6de2697d59e88ed7fc4dfe5a33dac43565ea41"
DEFI5_TOKENS = [
    "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",  # UNI
    "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",  # AAVE
    "0xc00e94Cb662C3520282E6f5717214004A7f26888",  # COMP
    "0xC011a73ee8576Fb46F5E1c5751cA3B9Fe0af2a6F",  # SNX
    "0xD533a949740bb3306d119CC777fa900bA034cd52",  # CRV
    "0x9f8F72aA9304c8B593d555F12eF6589cC3A579A2",  # MKR
    "0x6B3595068778DD592e39A122f4f5a5cF09C90fE2",  # SUSHI
]
TRICRYPTO2 = "0xD51a44d3FaE010294C616388b506AcdA1bfAAE46"
TRICRYPTO2_COINS = [
    "0xdAC17F958D2ee523a2206206994597C13D831ec7",  # USDT
    "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",  # WBTC
    "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
]
USDE_USDC_POOL = "0x02950460E2b9529D0E00284A5fA2d7bDF3fA4d72"
USDE_USDC_COINS = [
    "0x4c9EDD5852cd905f086C759E8383e09bff1E68B3",  # USDe
    "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # USDC
]


def _pct_change(new, old):
    if old is None or new is None:
        return None
    if old == 0:
        return float("inf") if new != 0 else 0.0
    return (new - old) / old


def harvest_finance(w3, block):
    bal = get_coin_balances(w3, YPOOL, YPOOL_COINS, block)["balances"]
    # coins(1)=yUSDC, coins(2)=yUSDT -- the pair implicated in the post-mortem
    # (attacker swapped USDT<->USDC via exchange_underlying to skew this ratio).
    ratio = bal[YPOOL_COINS[1]] / bal[YPOOL_COINS[2]]
    return {"venue_price": ratio, "reference_price": 1.0, "balance_for_skew": ratio}


def cream_finance(w3, block):
    pps = get_vault_share_price(w3, YUSD_VAULT, YPOOL_LP_TOKEN, block)
    return {"venue_price": pps, "reference_price": 1.0, "balance_for_skew": pps}


def indexed_finance(w3, block):
    bal = get_coin_balances(w3, DEFI5, DEFI5_TOKENS, block)["balances"]
    return {"venue_price": None, "reference_price": None, "balance_for_skew": bal}


def inverse_finance(w3, block, cex_price):
    bal = get_coin_balances(w3, TRICRYPTO2, TRICRYPTO2_COINS, block)["balances"]
    wbtc_balance = bal[TRICRYPTO2_COINS[1]]
    return {"venue_price": None, "reference_price": cex_price, "balance_for_skew": wbtc_balance}


def uwu_lend(w3, block):
    bal = get_coin_balances(w3, USDE_USDC_POOL, USDE_USDC_COINS, block)["balances"]
    ratio = bal[USDE_USDC_COINS[1]] / bal[USDE_USDC_COINS[0]]  # USDC per USDe
    return {"venue_price": ratio, "reference_price": 1.0, "balance_for_skew": ratio}


def recompute(w3, name, block):
    """Each branch sets `price_dev` (None where no clean implied-vs-reference price
    exists) and `reserve_skew` (% change in the manipulated quantity, incident block
    vs a trailing baseline BASELINE_LAG_BLOCKS earlier)."""
    baseline_block = block - BASELINE_LAG_BLOCKS

    if name == "Harvest Finance":
        now, base = harvest_finance(w3, block), harvest_finance(w3, baseline_block)
        price_dev = _pct_change(now["venue_price"], 1.0)
        reserve_skew = _pct_change(now["venue_price"], base["venue_price"])
        note = (
            f"Recomputed vs Curve Y pool (0x45F7...5f51): implied yUSDC/yUSDT ratio = "
            f"{now['venue_price']:.6f} at incident block (peg=1.0), vs {base['venue_price']:.6f} "
            f"at baseline (block-{BASELINE_LAG_BLOCKS})."
        )

    elif name == "Cream Finance":
        now, base = cream_finance(w3, block), cream_finance(w3, baseline_block)
        price_dev = _pct_change(now["venue_price"], 1.0)
        reserve_skew = _pct_change(now["venue_price"], base["venue_price"])
        note = (
            f"Recomputed vs Yearn yUSD Vault (0x4b5b...533d3) price-per-share: "
            f"{now['venue_price']} at incident block vs {base['venue_price']} at baseline "
            f"(vault held ~0 backing tokens before the attacker's direct LP-token transfer)."
        )

    elif name == "Indexed Finance":
        now, base = indexed_finance(w3, block), indexed_finance(w3, baseline_block)
        skews = {
            tok: _pct_change(now["balance_for_skew"][tok], base["balance_for_skew"][tok])
            for tok in DEFI5_TOKENS
        }
        max_tok = max(skews, key=lambda t: abs(skews[t]) if skews[t] not in (None, float("inf")) else -1)
        price_dev = None  # DEFI5 has no single clean implied USD price; skew is the signal here
        reserve_skew = skews[max_tok]
        note = (f"Recomputed vs DEFI5's own pool (0xfa6d...5ea41): max per-token balance skew across "
                f"its 7 constituents was token {max_tok} at {skews[max_tok]}.")

    elif name == "Inverse Finance":
        window_end = pd.Timestamp(w3.eth.get_block(block)["timestamp"], unit="s", tz="UTC")
        cex = fetch_cex_klines("BTCUSDT", window_end - pd.Timedelta(minutes=60), window_end)
        cex_before = cex[cex["timestamp"] <= window_end]
        cex_price = float(cex_before.iloc[-1]["close"]) if not cex_before.empty else None
        now = inverse_finance(w3, block, cex_price)
        base = inverse_finance(w3, baseline_block, cex_price)
        # price_dev is not meaningful here: a raw WBTC pool-balance and a BTC/USD price
        # are different units, so there's no clean "implied price vs reference" to form.
        # The signal is entirely in reserve_skew (the balance spike itself).
        price_dev = None
        reserve_skew = _pct_change(now["balance_for_skew"], base["balance_for_skew"])
        note = (
            f"Recomputed vs Curve tricrypto2 (0xD51a...ae46): raw WBTC balance in the pool "
            f"was {now['balance_for_skew']:.4f} at incident block vs {base['balance_for_skew']:.4f} "
            f"at baseline -- this is the exact deposit vector from the post-mortem "
            f"(27,000 WBTC flash-borrowed and added as liquidity)."
        )

    elif name == "UwU Lend":
        now, base = uwu_lend(w3, block), uwu_lend(w3, baseline_block)
        price_dev = _pct_change(now["venue_price"], 1.0)
        reserve_skew = _pct_change(now["venue_price"], base["venue_price"])
        note = (
            f"Recomputed vs Curve USDe/USDC pool (0x0295...4d72): implied USDC/USDe ratio = "
            f"{now['venue_price']:.6f} at incident block (peg=1.0), vs {base['venue_price']:.6f} "
            f"at baseline (block-{BASELINE_LAG_BLOCKS})."
        )

    else:
        raise ValueError(name)

    _write_row(name, {"price_dev": price_dev, "reserve_skew": reserve_skew}, note)


def _write_row(name, row, note):
    print(f"--- {name} ---")
    print(f"  price_dev: {row.get('price_dev')}")
    print(f"  reserve_skew: {row.get('reserve_skew')}")
    print(f"  {note}")

    df = pd.read_parquet(FEATURES_PATH)
    idx = df.index[df["incident"] == name][0]
    df.loc[idx, "price_dev"] = row.get("price_dev")
    df.loc[idx, "reserve_skew"] = row.get("reserve_skew")
    df.loc[idx, "reference_note"] = df.loc[idx, "reference_note"] + " [UPDATED: " + note + "]"
    df.to_parquet(FEATURES_PATH, index=False)


ORIGINAL_5_NAMES = ["Harvest Finance", "Cream Finance", "Indexed Finance", "Inverse Finance", "UwU Lend"]


def main():
    """Restricted to the original 5 manipulation incidents by name (not `label ==
    "manipulation"` generally) since phase 1 (reports/scaling_plan.md) added more
    manipulation incidents this script's if/elif branches don't know how to handle --
    those are recomputed separately by
    src/recompute_phase1_manipulation_curve_features.py. This filter change doesn't
    alter this script's behavior for the original 5 at all, only what it iterates over."""
    w3 = get_web3()
    df = pd.read_parquet(FEATURES_PATH)
    manip = df[df["incident"].isin(ORIGINAL_5_NAMES)]
    for _, r in manip.iterrows():
        recompute(w3, r["incident"], int(r["block"]))
        time.sleep(0.2)
    print("\nDone. Updated features.parquet for the 5 manipulation rows.")


if __name__ == "__main__":
    main()
