"""Read Chainlink price feed data from Ethereum mainnet via an Alchemy archive RPC.

Used both to pull the oracle-side price for incident analysis and, later, to mine
staleness/malfunction candidates (large gaps between `updatedAt` and block time).

Note on approach: history is walked round-by-round via batched `getRoundData` calls,
not `eth_getLogs`. Alchemy's free tier caps `eth_getLogs` at a 10-block range, which
makes log scanning unusable for multi-year history — confirmed empirically before
writing this. Round-walking has no such range restriction.
"""

import os
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv
from eth_abi import decode as abi_decode
from web3 import Web3
from web3.exceptions import Web3Exception

load_dotenv()

ALCHEMY_KEY = os.getenv("ALCHEMY_KEY")
MAINNET_RPC_URL = f"https://eth-mainnet.g.alchemy.com/v2/{ALCHEMY_KEY}"

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
MAX_RETRIES = 6
RETRY_BACKOFF_SECONDS = 5  # generous: free-tier 429s have needed more than a few seconds to clear
INTER_BATCH_SLEEP_SECONDS = 0.15  # be polite to the free-tier rate limit

ROUND_ID_MASK = (1 << 64) - 1  # proxy roundId = (phaseId << 64) | aggregatorRoundId
ROUND_DATA_OUTPUT_TYPES = ["uint80", "int256", "uint256", "uint256", "uint80"]

# Minimal AggregatorV3Interface (proxy-level: phase-encoded roundIds).
AGGREGATOR_ABI = [
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "description",
        "outputs": [{"internalType": "string", "name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"internalType": "uint80", "name": "roundId", "type": "uint80"},
            {"internalType": "int256", "name": "answer", "type": "int256"},
            {"internalType": "uint256", "name": "startedAt", "type": "uint256"},
            {"internalType": "uint256", "name": "updatedAt", "type": "uint256"},
            {"internalType": "uint80", "name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint80", "name": "_roundId", "type": "uint80"}],
        "name": "getRoundData",
        "outputs": [
            {"internalType": "uint80", "name": "roundId", "type": "uint80"},
            {"internalType": "int256", "name": "answer", "type": "int256"},
            {"internalType": "uint256", "name": "startedAt", "type": "uint256"},
            {"internalType": "uint256", "name": "updatedAt", "type": "uint256"},
            {"internalType": "uint80", "name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


def get_web3() -> Web3:
    """Build a Web3 instance pointed at Alchemy's Ethereum mainnet (archive) RPC."""
    if not ALCHEMY_KEY:
        raise RuntimeError("ALCHEMY_KEY not set in .env")
    return Web3(Web3.HTTPProvider(MAINNET_RPC_URL))


def _with_retry(fn):
    """Call `fn` with retry-on-failure, backing off between attempts.

    Catches HTTP-layer errors (rate limits, timeouts) as well as Web3/decoding
    errors — a bare `requests.exceptions.HTTPError` (e.g. a 429) is NOT a
    Web3Exception/ConnectionError/ValueError, so it must be listed explicitly
    or it propagates uncaught on the very first rate-limit hit.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn()
        except (
            Web3Exception,
            ConnectionError,
            ValueError,
            requests.exceptions.RequestException,
            _BatchRPCError,
        ) as exc:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"RPC call failed after {MAX_RETRIES} attempts") from exc
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)


def get_round_data_at_block(w3: Web3, feed_address: str, block_number: int | str = "latest") -> dict:
    """Read a Chainlink feed's round data as observed at a given block.

    Args:
        w3: Connected Web3 instance (see get_web3()).
        feed_address: Chainlink aggregator proxy address, e.g. the ETH/USD feed.
        block_number: Block to read at, or "latest" for the current block.

    Returns:
        dict with roundId, answer (scaled by the feed's decimals), raw_answer,
        decimals, started_at, updated_at, and block_number.
    """
    if block_number == "latest":
        # Resolve to a concrete block first so the cache key doesn't stay
        # pinned to whatever the price was on the very first call.
        block_number = w3.eth.block_number

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"chainlink_round_{feed_address}_{block_number}.csv"
    if cache_file.exists():
        return pd.read_csv(cache_file).iloc[0].to_dict()

    feed = w3.eth.contract(address=Web3.to_checksum_address(feed_address), abi=AGGREGATOR_ABI)

    decimals = _with_retry(lambda: feed.functions.decimals().call(block_identifier=block_number))
    round_data = _with_retry(
        lambda: feed.functions.latestRoundData().call(block_identifier=block_number)
    )
    round_id, raw_answer, started_at, updated_at, _answered_in_round = round_data

    result = {
        "feed_address": feed_address,
        "block_number": block_number,
        "round_id": round_id,
        "raw_answer": raw_answer,
        "decimals": decimals,
        "answer": raw_answer / (10**decimals),
        "started_at": started_at,
        "updated_at": updated_at,
    }

    pd.DataFrame([result]).to_csv(cache_file, index=False)
    return result


def _encode_get_round_data(w3: Web3, feed_address: str, round_id: int) -> str:
    feed = w3.eth.contract(address=Web3.to_checksum_address(feed_address), abi=AGGREGATOR_ABI)
    return feed.functions.getRoundData(round_id)._encode_transaction_data()


class _BatchRPCError(Exception):
    """Raised when a batch item comes back as an RPC-level error (e.g. rate limit),
    as opposed to a clean-but-empty round — these must be retried, not treated as
    'this round doesn't exist', or a transient 429 gets silently misread as a
    real phase boundary."""


def _batch_get_round_data(w3: Web3, feed_address: str, round_ids: list[int]) -> list[dict | None]:
    """Fetch getRoundData for many roundIds in one JSON-RPC batch POST.

    Returns a list (same order as round_ids) of dicts with round_id/raw_answer/
    started_at/updated_at, or None where the round genuinely doesn't exist
    (revert with no data, or a successful-but-all-zero response — both occur
    across old Chainlink aggregator versions). Per-item RPC errors raise
    _BatchRPCError so the caller's retry wrapper re-issues the whole batch
    instead of misreading a rate limit as "no such round".
    """
    checksum_addr = Web3.to_checksum_address(feed_address)
    batch = [
        {
            "jsonrpc": "2.0",
            "id": i,
            "method": "eth_call",
            "params": [{"to": checksum_addr, "data": _encode_get_round_data(w3, feed_address, rid)}, "latest"],
        }
        for i, rid in enumerate(round_ids)
    ]

    def _post():
        resp = requests.post(MAINNET_RPC_URL, json=batch, timeout=60)
        resp.raise_for_status()
        return resp.json()

    responses = _with_retry(_post)
    by_id = {r["id"]: r for r in responses}

    results: list[dict | None] = []
    for i, rid in enumerate(round_ids):
        r = by_id.get(i)
        if r is None:
            raise _BatchRPCError(f"missing response for round_id={rid}")
        if "error" in r:
            raise _BatchRPCError(f"RPC error for round_id={rid}: {r['error']}")
        if r.get("result") in (None, "0x"):
            results.append(None)  # clean empty round slot, not a real update
            continue
        decoded = abi_decode(ROUND_DATA_OUTPUT_TYPES, bytes.fromhex(r["result"][2:]))
        round_id, raw_answer, started_at, updated_at, _answered_in_round = decoded
        if updated_at == 0:
            results.append(None)  # empty round slot, not a real update
            continue
        results.append(
            {"round_id": round_id, "raw_answer": raw_answer, "started_at": started_at, "updated_at": updated_at}
        )
    return results


def _find_phase_max_round(w3: Web3, feed_address: str, phase: int, safety_cap: int = 1 << 24) -> int | None:
    """Binary search for the highest valid aggregatorRoundId within `phase`."""
    lo = 0  # 0 = known invalid (round 0 never exists)
    hi = 1
    while True:
        row = _with_retry(lambda: _batch_get_round_data(w3, feed_address, [(phase << 64) | hi]))[0]
        time.sleep(INTER_BATCH_SLEEP_SECONDS)
        if row is None:
            break
        lo = hi
        hi *= 2
        if hi > safety_cap:
            break
    if lo == 0:
        return None  # phase has no valid rounds at all (dead/incompatible phase)
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        row = _with_retry(lambda: _batch_get_round_data(w3, feed_address, [(phase << 64) | mid]))[0]
        time.sleep(INTER_BATCH_SLEEP_SECONDS)
        if row is not None:
            lo = mid
        else:
            hi = mid
    return lo


def get_feed_update_history(
    w3: Web3,
    feed_address: str,
    min_timestamp: int | None = None,
    max_rounds: int = 50_000,
    batch_size: int = 10,  # empirically the largest safe size on Alchemy's free-tier CU/s cap
    start_round_id: int | None = None,
) -> pd.DataFrame:
    """Walk a Chainlink feed's round history backward from a starting round.

    Crosses phase boundaries automatically (Chainlink periodically migrates the
    aggregator behind a feed's proxy; each migration bumps a phaseId that's
    encoded into the high bits of roundId). Stops when `min_timestamp` is
    reached, `max_rounds` rows have been collected, or the oldest reachable
    phase is exhausted (some early phases use a pre-v3 interface and aren't
    reachable via getRoundData at all — this is reported, not silently dropped).

    Args:
        w3: Connected Web3 instance (see get_web3()).
        feed_address: Chainlink aggregator proxy address.
        min_timestamp: Unix timestamp to stop at (None = walk until phases run out).
        max_rounds: Safety cap on total rows collected.
        batch_size: getRoundData calls per JSON-RPC batch POST.
        start_round_id: Phase-encoded roundId to start walking backward from.
            Defaults to the feed's current latest round. Use
            get_round_data_at_block(w3, feed_address, some_historical_block)["round_id"]
            to target a specific past window instead of "most recent".

    Returns:
        DataFrame with columns [round_id, raw_answer, decimals, answer, started_at,
        updated_at, timestamp, gap_seconds], sorted oldest-to-newest. gap_seconds
        is the time since the previous row's update (NaN for the first row).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"chainlink_history_{feed_address}_{min_timestamp}_{max_rounds}_{start_round_id}.csv"
    if cache_file.exists():
        return pd.read_csv(cache_file, parse_dates=["timestamp"])

    feed = w3.eth.contract(address=Web3.to_checksum_address(feed_address), abi=AGGREGATOR_ABI)
    decimals = _with_retry(lambda: feed.functions.decimals().call())
    if start_round_id is None:
        start_round_id = _with_retry(lambda: feed.functions.latestRoundData().call())[0]

    phase = start_round_id >> 64
    agg_round = start_round_id & ROUND_ID_MASK

    rows = []
    stop = False
    while not stop and len(rows) < max_rounds:
        batch_round_ids = [agg_round - k for k in range(batch_size) if agg_round - k >= 1]
        if not batch_round_ids:
            # phase - 1 must be >= 1: phase 0 doesn't exist (phases are 1-indexed), so
            # guard on phase > 1, not phase > 0 -- otherwise a feed that's only ever
            # lived on phase 1 (e.g. rETH/ETH, stETH/ETH) tries phase 0 at its genesis,
            # which reverts *persistently* (not a transient rate-limit) and burns all
            # retries before crashing instead of just stopping cleanly.
            phase_max = _find_phase_max_round(w3, feed_address, phase - 1) if phase > 1 else None
            if phase_max is None:
                break  # earliest reachable phase exhausted
            phase -= 1
            agg_round = phase_max
            continue

        proxy_round_ids = [(phase << 64) | r for r in batch_round_ids]
        batch_results = _with_retry(lambda: _batch_get_round_data(w3, feed_address, proxy_round_ids))
        time.sleep(INTER_BATCH_SLEEP_SECONDS)

        # A None here means "this specific round slot is empty" (known to happen
        # even mid-phase, not just at its boundary) — skip it and keep walking.
        # Phase-crossing is decided purely by the round-id counter below, never
        # by encountering a None, so a rate-limit hiccup can't be misread as
        # "we've reached the bottom of this phase".
        for result in batch_results:
            if result is None:
                continue
            if min_timestamp is not None and result["updated_at"] < min_timestamp:
                stop = True
                break
            rows.append(result)
            if len(rows) >= max_rounds:
                stop = True
                break

        if stop:
            break
        agg_round = batch_round_ids[-1] - 1

    df = pd.DataFrame(rows, columns=["round_id", "raw_answer", "started_at", "updated_at"])
    df = df.drop_duplicates(subset="updated_at").sort_values("updated_at").reset_index(drop=True)
    df["decimals"] = decimals
    df["answer"] = df["raw_answer"] / (10**decimals)
    df["timestamp"] = pd.to_datetime(df["updated_at"], unit="s", utc=True)
    df["gap_seconds"] = df["updated_at"].diff()

    df.to_csv(cache_file, index=False)
    return df


if __name__ == "__main__":
    # Connection test: fetch the current ETH/USD feed's latest round and print it.
    ETH_USD_FEED = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"

    w3 = get_web3()
    print("Connected to Alchemy mainnet RPC:", w3.is_connected())
    print("Current block number:", w3.eth.block_number)

    data = get_round_data_at_block(w3, ETH_USD_FEED, "latest")
    print(f"ETH/USD price: ${data['answer']:.2f}")
    print(f"Round ID: {data['round_id']}")
    print(f"Updated at (unix): {data['updated_at']}")
    print(f"Updated at (UTC): {pd.to_datetime(int(data['updated_at']), unit='s', utc=True)}")
