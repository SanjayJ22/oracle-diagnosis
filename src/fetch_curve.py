"""Read the actual manipulated venue's state for the 5 locked manipulation incidents.

The alignment probe on the Chainlink/Binance.US/Uniswap feature set showed no spike for
any of the 5 manipulation incidents -- because none of them touched a Uniswap pool or a
broadly-traded market price. Confirmed per-incident (post-mortems, cross-checked on-chain):
  - Harvest Finance: Curve Y pool (yDAI/yUSDC/yUSDT/yTUSD) balance ratio
  - Cream Finance:   Yearn yUSD Vault price-per-share (LP-token balance / share supply)
  - Indexed Finance: DEFI5's own Balancer-style weighted pool (not Curve) balances
  - Inverse Finance: Curve tricrypto2 (USDT/WBTC/WETH) balances
  - UwU Lend:        Curve USDe/USDC pool balances

Rather than build general Curve pool support, this reads exactly these venues via two
generic primitives that work across all of them regardless of pool age/interface:
  - get_coin_balances(): raw ERC20 balanceOf(venue_address) per coin -- always available,
    sidesteps balances(i) ABI drift across old (int128 index) vs new (uint256 index)
    Curve pool versions entirely.
  - get_virtual_price(): Curve-specific optional enrichment; returns None (not raised) if
    the pool doesn't expose it, per "flag and move on rather than forcing it".
  - get_vault_share_price(): for the Cream Finance vault-accounting case specifically.

Same retry + on-disk cache pattern as fetch_chainlink.py / fetch_dex.py.
"""

import hashlib
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
    {"inputs": [{"name": "a", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]

VIRTUAL_PRICE_ABI = [
    {"inputs": [], "name": "get_virtual_price", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]


def _with_retry(fn):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn()
        except (Web3Exception, ConnectionError, ValueError) as exc:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"RPC call failed after {MAX_RETRIES} attempts") from exc
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)


def get_coin_balances(w3: Web3, venue_address: str, coin_addresses: list[str], block_number: int) -> dict:
    """Read raw ERC20 balanceOf(venue_address) for each coin, decimal-adjusted.

    Works for any venue holding tokens -- a Curve pool, a Yearn vault, a Balancer-style
    weighted pool -- since balanceOf() is universal, unlike each pool's own custom
    balances(i)/getBalance(token) methods which vary across versions and pool types.

    Returns dict: {"balances": {coin_address: adjusted_balance, ...}, "raw": {...}}
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Hash the coin list rather than concatenating addresses -- DEFI5's 7-token list
    # blew past macOS's 255-char filename limit when joined directly.
    coins_key = hashlib.md5("_".join(c.lower() for c in coin_addresses).encode()).hexdigest()[:12]
    cache_file = CACHE_DIR / f"curve_balances_{venue_address}_{coins_key}_{block_number}.csv"
    if cache_file.exists():
        stored = pd.read_csv(cache_file)
        return {
            "balances": dict(zip(stored["coin"], stored["balance"])),
            "raw": dict(zip(stored["coin"], stored["raw_balance"])),
        }

    venue_cs = Web3.to_checksum_address(venue_address)
    rows = []
    for coin in coin_addresses:
        token = w3.eth.contract(address=Web3.to_checksum_address(coin), abi=ERC20_ABI)
        raw_bal = _with_retry(lambda t=token: t.functions.balanceOf(venue_cs).call(block_identifier=block_number))
        time.sleep(INTER_CALL_SLEEP_SECONDS)
        dec = _with_retry(lambda t=token: t.functions.decimals().call(block_identifier=block_number))
        time.sleep(INTER_CALL_SLEEP_SECONDS)
        rows.append({"coin": coin, "raw_balance": raw_bal, "decimals": dec, "balance": raw_bal / (10**dec)})

    pd.DataFrame(rows).to_csv(cache_file, index=False)
    return {
        "balances": {r["coin"]: r["balance"] for r in rows},
        "raw": {r["coin"]: r["raw_balance"] for r in rows},
    }


def get_virtual_price(w3: Web3, pool_address: str, block_number: int) -> float | None:
    """Curve-specific enrichment: LP share value in underlying-asset terms.

    Returns None (does not raise) if the pool doesn't expose get_virtual_price() at this
    block -- some pool versions/ages genuinely don't have it; flag and move on rather
    than forcing it, per instructions.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"curve_vprice_{pool_address}_{block_number}.csv"
    if cache_file.exists():
        val = pd.read_csv(cache_file).iloc[0]["virtual_price"]
        return None if pd.isna(val) else float(val)

    pool = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=VIRTUAL_PRICE_ABI)
    try:
        raw = _with_retry(lambda: pool.functions.get_virtual_price().call(block_identifier=block_number))
        value = raw / 1e18
    except RuntimeError:
        value = None

    pd.DataFrame([{"virtual_price": value}]).to_csv(cache_file, index=False)
    return value


def get_vault_share_price(w3: Web3, vault_address: str, underlying_token_address: str, block_number: int) -> float | None:
    """Yearn-v1-style vault accounting: underlying tokens held / shares outstanding.

    Used for Cream Finance specifically -- the manipulated quantity was the yUSD
    Vault's price-per-share, not a Curve pool's own state (the Curve Y pool itself
    wasn't touched; LP tokens were transferred directly into the vault).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"curve_vault_pps_{vault_address}_{underlying_token_address}_{block_number}.csv"
    if cache_file.exists():
        val = pd.read_csv(cache_file).iloc[0]["price_per_share"]
        return None if pd.isna(val) else float(val)

    vault_cs = Web3.to_checksum_address(vault_address)
    underlying_token = w3.eth.contract(address=Web3.to_checksum_address(underlying_token_address), abi=ERC20_ABI)
    # The vault contract IS the share token (Yearn v1 pattern: one contract, both the
    # vault and its own ERC20 share supply), so totalSupply() is called on vault_cs.
    vault_token = w3.eth.contract(address=vault_cs, abi=ERC20_ABI)
    try:
        raw_bal = _with_retry(lambda: underlying_token.functions.balanceOf(vault_cs).call(block_identifier=block_number))
        time.sleep(INTER_CALL_SLEEP_SECONDS)
        supply = _with_retry(lambda: vault_token.functions.totalSupply().call(block_identifier=block_number))
        value = (raw_bal / supply) if supply else None
    except RuntimeError:
        value = None

    pd.DataFrame([{"price_per_share": value}]).to_csv(cache_file, index=False)
    return value


if __name__ == "__main__":
    # Connection test: Cream Finance's yUSD vault price-per-share, before vs at the attack block.
    w3 = get_web3()
    VAULT = "0x4b5bfd52124784745c1071dcb244c6688d2533d3"
    YPOOL_LP = "0xdF5e0e81Dff6FAF3A7e52BA697820c5e32D806A8"

    for label, block in [("before", 13_499_797), ("attack block", 13_499_798)]:
        pps = get_vault_share_price(w3, VAULT, YPOOL_LP, block)
        print(f"yUSD vault price-per-share ({label}, block {block}): {pps}")
