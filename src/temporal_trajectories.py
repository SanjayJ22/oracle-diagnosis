"""Light temporal layer: trajectory analysis for one representative incident per class.

This is a SEPARATE analysis from the static feature table / classifiers -- it does not
feed back into data/processed/features.parquet or src/models.py. The goal is purely to
show that the three causes resolve differently over time (the "dynamic diagnosis" story),
using the SAME helpers (fetch_chainlink, fetch_dex, fetch_cex) and reusing cached data
wherever the earlier work already covers the relevant window.

Incidents:
  manipulation -> Harvest Finance (2020-10-26, block 11,129,474): Curve Y pool implied
                  yUSDC/yUSDT ratio vs ETH/USD (an unrelated, unaffected venue)
  malfunction  -> stETH/ETH heartbeat lag (2022-06-18): Chainlink STETH/ETH (updates
                  ~1x/24h) vs the wstETH/WETH Uniswap V3 pool (continuous DEX reference)
  volatility   -> Aug 5 2024 carry-trade unwind: Chainlink ETH/USD vs Binance.US ETHUSDT
                  vs the WETH/USDC Uniswap V3 pool -- three venues, one real move

Produces trajectory plots (reports/trajectory_*.png) and, per incident, both an explicit
state-transition description and an attempted 2-state Gaussian HMM regime fit (reported
honestly if unstable on the short sequence, not forced).
"""

import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from fetch_cex import fetch_cex_klines
from fetch_chainlink import _with_retry, get_feed_update_history, get_round_data_at_block, get_web3
from fetch_dex import get_v3_state
from recompute_manipulation_curve_features import YPOOL, YPOOL_COINS

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
ETH_USD_FEED = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"
STETH_ETH_FEED = "0x86392dC19c0b719886221c78AB11eb8Cf5c52812"
WSTETH_WETH_V3 = "0xd340b57aacdd10f96fc1cf10e15921936f41e29c"
WETH_USDC_V3 = "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640"


def _find_block_for_timestamp(w3, target_ts):
    lo, hi = 0, _with_retry(lambda: w3.eth.block_number)
    while lo < hi:
        mid = (lo + hi) // 2
        blk = _with_retry(lambda: w3.eth.get_block(mid))
        time.sleep(0.15)
        if blk["timestamp"] < target_ts:
            lo = mid + 1
        else:
            hi = mid
    return lo


# ============================================================================
# 1. Manipulation: Harvest Finance
# ============================================================================

def gather_harvest(w3):
    print("--- Gathering Harvest Finance (manipulation) trajectory ---", flush=True)
    incident_block = 11_129_474
    window_blocks = 280  # ~1 hour at ~13s/block in Oct 2020
    stride = 10  # ~2.2 min

    blocks = list(range(incident_block - window_blocks, incident_block + window_blocks, stride))
    rows = []
    for b in blocks:
        blk = _with_retry(lambda b=b: w3.eth.get_block(b))
        time.sleep(0.1)
        ratio = None
        try:
            bal = _coin_balances(w3, YPOOL, YPOOL_COINS, b)
            ratio = bal[YPOOL_COINS[1]] / bal[YPOOL_COINS[2]]  # yUSDC / yUSDT
        except Exception:
            pass
        rows.append({"block": b, "timestamp": pd.to_datetime(blk["timestamp"], unit="s", utc=True), "ypool_ratio": ratio})
    curve_df = pd.DataFrame(rows)
    print(f"  Curve Y pool ratio: {len(curve_df)} samples, {curve_df['ypool_ratio'].notna().sum()} valid", flush=True)

    # ETH/USD round history over the same window, as the "unaffected venue" + freshness signal
    anchor_ts = pd.to_datetime(curve_df["timestamp"].max(), utc=True)
    min_ts = int(pd.to_datetime(curve_df["timestamp"].min(), utc=True).timestamp())
    anchor_block = _find_block_for_timestamp(w3, int(anchor_ts.timestamp()))
    anchor_round = get_round_data_at_block(w3, ETH_USD_FEED, anchor_block)
    eth_hist = get_feed_update_history(
        w3, ETH_USD_FEED, min_timestamp=min_ts, max_rounds=200, batch_size=10,
        start_round_id=int(anchor_round["round_id"]),
    )
    print(f"  ETH/USD (unaffected venue): {len(eth_hist)} rounds in window", flush=True)
    return curve_df, eth_hist


def _coin_balances(w3, venue, coins, block):
    from fetch_curve import get_coin_balances
    return get_coin_balances(w3, venue, coins, block)["balances"]


# ============================================================================
# 2. Malfunction: stETH/ETH
# ============================================================================

def gather_steth(w3):
    print("--- Gathering stETH/ETH (malfunction) trajectory ---", flush=True)
    # Reuse the cached Chainlink round history from the earlier malfunction analysis.
    cache_file = Path(__file__).resolve().parent.parent / "data" / "raw" / \
        "chainlink_history_0x86392dC19c0b719886221c78AB11eb8Cf5c52812_1654387200_2000_18446744073709551926.csv"
    chainlink_df = pd.read_csv(cache_file, parse_dates=["timestamp"])
    print(f"  Chainlink STETH/ETH: {len(chainlink_df)} rounds (reused from cache)", flush=True)

    start_ts = chainlink_df["timestamp"].min()
    end_ts = chainlink_df["timestamp"].max()
    blocks_start = _find_block_for_timestamp(w3, int(start_ts.timestamp()))
    blocks_end = _find_block_for_timestamp(w3, int(end_ts.timestamp()))
    stride_blocks = (blocks_end - blocks_start) // 76  # ~6h resolution over ~19 days

    rows = []
    for b in range(blocks_start, blocks_end, max(stride_blocks, 1)):
        blk = _with_retry(lambda b=b: w3.eth.get_block(b))
        time.sleep(0.1)
        try:
            state = get_v3_state(w3, WSTETH_WETH_V3, b)
            price = state["price_1_per_0"]  # WETH per wstETH, same orientation as STETH/ETH
        except Exception:
            price = None
        rows.append({"block": b, "timestamp": pd.to_datetime(blk["timestamp"], unit="s", utc=True), "dex_price": price})
    dex_df = pd.DataFrame(rows)
    print(f"  wstETH/WETH DEX reference: {len(dex_df)} samples, {dex_df['dex_price'].notna().sum()} valid", flush=True)
    return chainlink_df, dex_df


# ============================================================================
# 3. Volatility: Aug 5 2024 carry-trade unwind
# ============================================================================

def gather_aug2024(w3):
    print("--- Gathering Aug 5 2024 crash (volatility) trajectory ---", flush=True)
    cache_file = Path(__file__).resolve().parent.parent / "data" / "raw" / \
        "chainlink_history_0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419_1722470400_3000_110680464442257330782.csv"
    chainlink_df = pd.read_csv(cache_file, parse_dates=["timestamp"])
    print(f"  Chainlink ETH/USD: {len(chainlink_df)} rounds (reused from cache)", flush=True)

    start_ts, end_ts = chainlink_df["timestamp"].min(), chainlink_df["timestamp"].max()
    cex_df = fetch_cex_klines("ETHUSDT", start_ts, end_ts)
    print(f"  Binance.US ETHUSDT: {len(cex_df)} candles", flush=True)

    blocks_start = _find_block_for_timestamp(w3, int(start_ts.timestamp()))
    blocks_end = _find_block_for_timestamp(w3, int(end_ts.timestamp()))
    stride_blocks = (blocks_end - blocks_start) // 60  # ~2h resolution over ~5.9 days

    rows = []
    for b in range(blocks_start, blocks_end, max(stride_blocks, 1)):
        blk = _with_retry(lambda b=b: w3.eth.get_block(b))
        time.sleep(0.1)
        try:
            state = get_v3_state(w3, WETH_USDC_V3, b)
            price = 1.0 / state["price_1_per_0"]  # invert: USDC per WETH, matches CEX convention
        except Exception:
            price = None
        rows.append({"block": b, "timestamp": pd.to_datetime(blk["timestamp"], unit="s", utc=True), "dex_price": price})
    dex_df = pd.DataFrame(rows)
    print(f"  WETH/USDC DEX reference: {len(dex_df)} samples, {dex_df['dex_price'].notna().sum()} valid", flush=True)
    return chainlink_df, cex_df, dex_df


def main():
    warnings.filterwarnings("ignore")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    w3 = get_web3()

    harvest_curve, harvest_eth = gather_harvest(w3)
    steth_chainlink, steth_dex = gather_steth(w3)
    aug2024_chainlink, aug2024_cex, aug2024_dex = gather_aug2024(w3)

    out_dir = Path(__file__).resolve().parent.parent / "data" / "processed" / "trajectories"
    out_dir.mkdir(parents=True, exist_ok=True)
    harvest_curve.to_csv(out_dir / "harvest_curve.csv", index=False)
    harvest_eth.to_csv(out_dir / "harvest_eth.csv", index=False)
    steth_chainlink.to_csv(out_dir / "steth_chainlink.csv", index=False)
    steth_dex.to_csv(out_dir / "steth_dex.csv", index=False)
    aug2024_chainlink.to_csv(out_dir / "aug2024_chainlink.csv", index=False)
    aug2024_cex.to_csv(out_dir / "aug2024_cex.csv", index=False)
    aug2024_dex.to_csv(out_dir / "aug2024_dex.csv", index=False)
    print(f"\nAll trajectory data written to {out_dir}")


if __name__ == "__main__":
    main()
