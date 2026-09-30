"""Read Uniswap V2/V3 pool state on Ethereum mainnet via an Alchemy archive RPC.

Used to compute cross-venue spread (DEX price vs CEX/oracle price) and reserve-imbalance
("reserve_skew") features for incident analysis. Same retry + on-disk cache pattern as
fetch_cex.py and fetch_chainlink.py. Reuses fetch_chainlink.get_web3() rather than
re-deriving the Alchemy connection, since it's the same RPC either way.
"""

import time
from pathlib import Path

import pandas as pd
from web3 import Web3
from web3.exceptions import Web3Exception

from fetch_chainlink import get_web3  # noqa: F401 (re-exported for convenience)

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
MAX_RETRIES = 6
RETRY_BACKOFF_SECONDS = 5
INTER_CALL_SLEEP_SECONDS = 0.15

ERC20_ABI = [
    {"inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
]

UNISWAP_V2_PAIR_ABI = [
    {"inputs": [], "name": "token0", "outputs": [{"name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token1", "outputs": [{"name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {
        "inputs": [],
        "name": "getReserves",
        "outputs": [
            {"name": "reserve0", "type": "uint112"},
            {"name": "reserve1", "type": "uint112"},
            {"name": "blockTimestampLast", "type": "uint32"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

UNISWAP_V3_POOL_ABI = [
    {"inputs": [], "name": "token0", "outputs": [{"name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token1", "outputs": [{"name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "liquidity", "outputs": [{"name": "", "type": "uint128"}], "stateMutability": "view", "type": "function"},
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "observationIndex", "type": "uint16"},
            {"name": "observationCardinality", "type": "uint16"},
            {"name": "observationCardinalityNext", "type": "uint16"},
            {"name": "feeProtocol", "type": "uint8"},
            {"name": "unlocked", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "secondsAgos", "type": "uint32[]"}],
        "name": "observe",
        "outputs": [
            {"name": "tickCumulatives", "type": "int56[]"},
            {"name": "secondsPerLiquidityCumulativeX128s", "type": "uint160[]"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


def _with_retry(fn):
    """Call `fn` with retry-on-failure, backing off between attempts."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn()
        except (Web3Exception, ConnectionError, ValueError) as exc:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"RPC call failed after {MAX_RETRIES} attempts") from exc
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)


def _decimals(w3: Web3, token_address: str, block_number: int) -> int:
    token = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
    return _with_retry(lambda: token.functions.decimals().call(block_identifier=block_number))


def get_v2_reserves(w3: Web3, pool_address: str, block_number: int) -> dict:
    """Read a Uniswap V2 pair's reserves at a historical block.

    Returns dict with token0/token1 addresses+decimals, raw and decimal-adjusted
    reserves, and price (token1 per token0, decimal-adjusted).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"dex_v2_{pool_address}_{block_number}.csv"
    if cache_file.exists():
        return pd.read_csv(cache_file).iloc[0].to_dict()

    pool = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=UNISWAP_V2_PAIR_ABI)
    token0 = _with_retry(lambda: pool.functions.token0().call(block_identifier=block_number))
    time.sleep(INTER_CALL_SLEEP_SECONDS)
    token1 = _with_retry(lambda: pool.functions.token1().call(block_identifier=block_number))
    time.sleep(INTER_CALL_SLEEP_SECONDS)
    reserve0, reserve1, _ts = _with_retry(lambda: pool.functions.getReserves().call(block_identifier=block_number))
    time.sleep(INTER_CALL_SLEEP_SECONDS)
    dec0 = _decimals(w3, token0, block_number)
    time.sleep(INTER_CALL_SLEEP_SECONDS)
    dec1 = _decimals(w3, token1, block_number)

    adj_reserve0 = reserve0 / (10**dec0)
    adj_reserve1 = reserve1 / (10**dec1)
    price = adj_reserve1 / adj_reserve0 if adj_reserve0 else float("nan")

    result = {
        "pool_address": pool_address,
        "block_number": block_number,
        "token0": token0,
        "token1": token1,
        "decimals0": dec0,
        "decimals1": dec1,
        "reserve0_raw": reserve0,
        "reserve1_raw": reserve1,
        "reserve0": adj_reserve0,
        "reserve1": adj_reserve1,
        "price_1_per_0": price,
    }
    pd.DataFrame([result]).to_csv(cache_file, index=False)
    return result


def get_v3_state(w3: Web3, pool_address: str, block_number: int) -> dict:
    """Read a Uniswap V3 pool's slot0 + liquidity at a historical block.

    Returns dict with token0/token1 addresses+decimals, sqrtPriceX96, tick,
    liquidity, and price (token1 per token0, decimal-adjusted, derived from
    sqrtPriceX96).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"dex_v3_{pool_address}_{block_number}.csv"
    if cache_file.exists():
        return pd.read_csv(cache_file).iloc[0].to_dict()

    pool = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=UNISWAP_V3_POOL_ABI)
    token0 = _with_retry(lambda: pool.functions.token0().call(block_identifier=block_number))
    time.sleep(INTER_CALL_SLEEP_SECONDS)
    token1 = _with_retry(lambda: pool.functions.token1().call(block_identifier=block_number))
    time.sleep(INTER_CALL_SLEEP_SECONDS)
    slot0 = _with_retry(lambda: pool.functions.slot0().call(block_identifier=block_number))
    time.sleep(INTER_CALL_SLEEP_SECONDS)
    liquidity = _with_retry(lambda: pool.functions.liquidity().call(block_identifier=block_number))
    time.sleep(INTER_CALL_SLEEP_SECONDS)
    dec0 = _decimals(w3, token0, block_number)
    time.sleep(INTER_CALL_SLEEP_SECONDS)
    dec1 = _decimals(w3, token1, block_number)

    sqrt_price_x96 = slot0[0]
    # price of token0 in terms of token1, raw (Q64.96 -> float), then decimal-adjusted
    raw_price = (sqrt_price_x96 / (2**96)) ** 2
    price = raw_price * (10**dec0) / (10**dec1)

    result = {
        "pool_address": pool_address,
        "block_number": block_number,
        "token0": token0,
        "token1": token1,
        "decimals0": dec0,
        "decimals1": dec1,
        "sqrt_price_x96": sqrt_price_x96,
        "tick": slot0[1],
        "liquidity": liquidity,
        "price_1_per_0": price,
    }
    pd.DataFrame([result]).to_csv(cache_file, index=False)
    return result


def get_v3_twap(w3: Web3, pool_address: str, block_number: int, window_seconds: int = 1800):
    """Time-weighted average price over the `window_seconds` immediately
    preceding `block_number`, via Uniswap V3's built-in `observe()` oracle --
    the on-chain TWAP mechanism, not a manual multi-block sample. Both requested
    offsets (`window_seconds` ago, and 0 i.e. "now") are read AT
    `block_identifier=block_number` -- using that block's own historical state,
    which only ever contains observations from ITS OWN past, so this is
    strictly trailing / no-lookahead by construction, the same guarantee every
    other point-in-time read in this project already has.

    Returns a dict (mirroring get_v3_state's shape, plus avg_tick/window_seconds)
    or None (NOT raised) if the pool cannot answer -- most commonly because it
    doesn't have enough stored observation history at that block to cover the
    requested window (Uniswap V3 pools default to a small observation-slot
    cardinality unless someone explicitly grew it; requesting further back than
    what's stored reverts with "OLD", a real and common limitation, not a bug).

    Uses a SHORT, bounded retry (not the shared _with_retry's full 6-attempt
    exponential backoff) deliberately: an "OLD" revert is a persistent contract
    state, not a transient network hiccup, and retrying it 6 times before
    giving up would burn ~105s per doomed call -- the exact mistake already
    identified and fixed elsewhere in this project (get_code() pre-checks
    before not-yet-deployed-contract calls, e.g.)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"dex_v3_twap_{pool_address}_{block_number}_{window_seconds}.csv"
    if cache_file.exists():
        row = pd.read_csv(cache_file).iloc[0]
        return None if pd.isna(row.get("price_1_per_0")) else row.to_dict()

    pool = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=UNISWAP_V3_POOL_ABI)

    tick_cumulatives = None
    for attempt in range(2):
        try:
            tick_cumulatives, _ = pool.functions.observe([window_seconds, 0]).call(block_identifier=block_number)
            break
        except (Web3Exception, ConnectionError, ValueError):
            if attempt == 0:
                time.sleep(2)
                continue
            pd.DataFrame([{"price_1_per_0": None}]).to_csv(cache_file, index=False)
            return None

    avg_tick = (tick_cumulatives[1] - tick_cumulatives[0]) / window_seconds
    token0 = _with_retry(lambda: pool.functions.token0().call(block_identifier=block_number))
    time.sleep(INTER_CALL_SLEEP_SECONDS)
    token1 = _with_retry(lambda: pool.functions.token1().call(block_identifier=block_number))
    time.sleep(INTER_CALL_SLEEP_SECONDS)
    dec0 = _decimals(w3, token0, block_number)
    time.sleep(INTER_CALL_SLEEP_SECONDS)
    dec1 = _decimals(w3, token1, block_number)

    raw_price = 1.0001 ** avg_tick
    price = raw_price * (10**dec0) / (10**dec1)

    result = {
        "pool_address": pool_address,
        "block_number": block_number,
        "window_seconds": window_seconds,
        "token0": token0,
        "token1": token1,
        "decimals0": dec0,
        "decimals1": dec1,
        "avg_tick": avg_tick,
        "price_1_per_0": price,
    }
    pd.DataFrame([result]).to_csv(cache_file, index=False)
    return result


if __name__ == "__main__":
    # Connection test: read the WETH/USDC 0.05% V3 pool's current state.
    WETH_USDC_V3 = "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640"
    w3 = get_web3()
    latest_block = w3.eth.block_number
    print("Connected, latest block:", latest_block)

    state = get_v3_state(w3, WETH_USDC_V3, latest_block)
    print(f"WETH/USDC V3 pool @ block {latest_block}:")
    print(f"  token0={state['token0']} token1={state['token1']}")
    print(f"  price (token1 per token0): {state['price_1_per_0']:.2f}")
    print(f"  liquidity: {state['liquidity']}")
