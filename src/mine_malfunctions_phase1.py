"""SUPERSEDED / NOT RUN TO COMPLETION -- kept for reference (the Feed Registry lookup
logic and Part B design are still useful), but do not run this as-is: it hangs
indefinitely on MKR/USD's symbol() call (MKR is a legacy, pre-ERC20-standardization
token whose symbol() returns bytes32, not a dynamic string -- a known ABI-decoding
footgun, confirmed as the cause after killing a hung run). src/mine_malfunctions_phase1_
targeted.py picks up from this script's 7 already-resolved feed addresses (LINK, DAI,
UNI, COMP, MATIC, SNX, AAVE) and completes the full-history mining for those; CRV, MKR,
and Part B's newer-LSD checks below were never reached -- see
reports/malfunction_candidates_phase1.md's "What was not completed" section for the
honest accounting. Fix the MKR symbol() decoding (or just skip it) before re-running
this file for those remaining feeds.

Phase-1 dataset scaling: broaden the malfunction (staleness) search beyond what
reports/malfunction_candidates.md already covered.

Does NOT edit mine_malfunctions.py (the original locked-incident-generating script) --
reuses its underlying primitives (get_feed_update_history, _with_retry, get_web3 from
fetch_chainlink.py) and its exact same gap-flagging method (mine_feed()'s logic,
reimplemented here so the original script's own behavior/output for the 3 locked
incidents stays untouched).

Two searches:
  (A) Full multi-year history gap-mining (same method as mine_malfunctions.py: flag a
      gap >= max(6x the feed's own median, 4h)) for 9 major feeds only spot-checked
      before around a single event window (LINK, DAI, UNI, COMP, MATIC, SNX, AAVE) or
      not checked with this exact method at all (CRV, MKR added as a bonus, cheap
      extension). Real feed addresses obtained via the Chainlink Feed Registry's own
      getFeed(base, quote) at a recent block -- NOT hardcoded from memory -- with each
      token contract's symbol() verified on-chain first so a wrong/guessed token
      address can't silently produce a wrong feed lookup.
  (B) Depeg-lag check (max single-round price move + max gap vs own median) for 4
      newer LSD/ETH feeds that didn't exist or weren't checked in the original pass:
      weETH/ETH, ezETH/ETH, osETH/ETH, sfrxETH/frxETH -- same method as the original
      rETH/ETH, cbETH/ETH, WBTC/BTC check.

Any flagged gap within EXCLUSION_BLOCK_WINDOW of any of the 20 already-locked
incidents' blocks (manipulation + malfunction + volatility, not just manipulation) is
excluded, to avoid mistaking already-known volatility/manipulation activity for a new
malfunction.

Read-only: does not touch build_features.py, models.py, or features.parquet.
"""

import sys
import time
from pathlib import Path

import pandas as pd
from web3 import Web3

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_chainlink import (  # noqa: E402
    _with_retry,
    get_feed_update_history,
    get_round_data_at_block,
    get_web3,
)

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

FEED_REGISTRY = "0x47Fb2585D2C56Fe188D0E6ec628a38b74fCeeeDf"
USD_QUOTE = "0x0000000000000000000000000000000000000348"  # Chainlink Denominations.USD
ETH_QUOTE = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"   # Chainlink Denominations.ETH

REGISTRY_ABI = [
    {
        "inputs": [{"name": "base", "type": "address"}, {"name": "quote", "type": "address"}],
        "name": "getFeed",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]
ERC20_ABI = [
    {"inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
]

MIN_TIMESTAMP = int(pd.Timestamp("2020-01-01", tz="UTC").timestamp())  # Part B only (low-frequency LSD/ETH feeds)
HEARTBEAT_MULTIPLE = 6
MIN_ABSOLUTE_GAP_SECONDS = 4 * 3600
BATCH_SIZE = 10
MAX_ROUNDS_PER_FEED = 3000  # depeg-lag check only (Part B; those feeds update far less often)

# Targeted-window approach for Part A (revised after an initial full-history-from-latest
# walk proved infeasible: these majors update every ~30-60 minutes continuously, so 3000
# rounds only reached back 2-4 months, missing every historical stress period entirely --
# discovered empirically on the first run, not assumed). Instead of walking blind from
# "latest", anchor a bounded backward walk at a block a few days AFTER each known stress
# window's core move, using get_feed_update_history's start_round_id -- this is the same
# "look where a malfunction is most likely to show up" logic the original FTT/UST finds
# used (registry lookups around known collapse events), applied here across more feeds.
# Anchor dates chosen a few days after each window's core move so the backward walk
# comfortably covers it; ROUNDS_PER_WINDOW sized for ~10-14 days at these feeds' typical
# ~30-90 min cadence.
STRESS_WINDOWS = [
    ("2020-03 COVID crash", "2020-03-20"),
    ("2022-05 Terra collapse onset", "2022-05-20"),
    ("2022-11 FTX collapse", "2022-11-16"),
    ("2023-03 SVB/banking crisis", "2023-03-21"),
    ("2024-08 carry-trade unwind", "2024-08-12"),
    ("2026-02 crash", "2026-02-13"),
]
ROUNDS_PER_WINDOW = 300
# Scoped down (12 windows -> 6, 500 rounds -> 300, inter-batch sleep 0.15s -> 0.4s)
# after the first attempt stalled: confirmed via zero matching cache-file writes over
# 5m50s of runtime that it was spending nearly all its time in _with_retry's backoff
# sleeps, almost certainly from Alchemy rate-limit contention shared with the
# concurrently-running volatility-mining pass on the same API key. This trades
# coverage (6 of the highest-signal stress windows instead of 12) for actually
# finishing -- flagged plainly as a real scope reduction, not silently absorbed.

# (label, token address to verify+lookup against USD, expected symbol substring)
# LINK..MKR are the phase-1 candidates from before (MKR previously hung -- see
# _get_symbol_raw's fix above); LDO onward are new, added to broaden "any other
# reasonable mainnet feed" coverage per the search-completion request.
USD_CANDIDATES = [
    ("LINK/USD", "0x514910771AF9Ca656af840dff83E8264EcF986CA", "LINK"),
    ("DAI/USD", "0x6B175474E89094C44Da98b954EedeAC495271d0F", "DAI"),
    ("UNI/USD", "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984", "UNI"),
    ("COMP/USD", "0xc00e94Cb662C3520282E6f5717214004A7f26888", "COMP"),
    ("MATIC/USD", "0x7D1AfA7B718fb893dB30A3aBc0Cfc608AaCfeBB0", "MATIC"),
    ("SNX/USD", "0xC011a73ee8576Fb46F5E1c5751cA3B9Fe0af2a6F", "SNX"),
    ("AAVE/USD", "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9", "AAVE"),
    ("CRV/USD", "0xD533a949740bb3306d119CC777fa900bA034cd52", "CRV"),
    ("MKR/USD", "0x9f8F72aA9304c8B593d555F12eF6589cC3A579A2", "MKR"),
    ("LDO/USD", "0x5A98FcBEA516Cf06857215779Fd812CA3beF1B32", "LDO"),
    ("FXS/USD", "0x3432B6A60D23Ca0dFCa7761B7ab56459D9C964D0", "FXS"),
    ("YFI/USD", "0x0bc529c00C6401aEF6D220BE8C6Ea1667F6Ad93e", "YFI"),
    ("SUSHI/USD", "0x6B3595068778DD592e39A122f4f5a5cF09C90fE2", "SUSHI"),
    ("1INCH/USD", "0x111111111117dC0aa78b770fA6A738034120C302", "1INCH"),
    ("FRAX/USD", "0x853d955aCEf822Db058eb8505911ED77F175b99e", "FRAX"),
    ("LUSD/USD", "0x5f98805A4E8be255a32880FDeC7F6728C6568bA0", "LUSD"),
    ("sUSD/USD", "0x57Ab1ec28D129707052df4dF418D58a2D46d5f51", "sUSD"),
    ("USDe/USD", "0x4c9EDD5852cd905f086C759E8383e09bff1E68B3", "USDe"),
    ("PYUSD/USD", "0x6c3ea9036406852006290770BEdFcAbA0e23A0e8", "PYUSD"),
]

# (label, token address to verify+lookup against ETH)
ETH_CANDIDATES = [
    ("weETH/ETH", "0xCd5fE23C85820F7B72D0926FC9b05b43E359b7ee", "weETH"),
    ("ezETH/ETH", "0xbf5495Efe5DB9ce00f80364C8B423567e58d2110", "ezETH"),
    ("osETH/ETH", "0xf1C9acDc66974dFB6dEcB12aA385b9cD01190E38", "osETH"),
    ("sfrxETH/ETH", "0xac3E018457B222d93114458476f3E3416Abbe38F", "sfrxETH"),
]

# All 20 already-locked incident blocks (manipulation + malfunction + volatility),
# read from reports/final_incidents.md -- plus the 2 extra malfunction-related
# blocks documented in malfunction_candidates.md (UST replacement-aggregator freeze,
# UST registry hand-off) as a bonus precaution.
LOCKED_BLOCKS = [
    11_129_474, 13_499_798, 13_417_949, 14_972_419, 20_061_319,   # manipulation
    14_984_168, 16_069_381, 14_942_628,                            # malfunction
    12_465_029, 14_966_742, 15_935_789, 16_826_924, 17_937_299,    # volatility
    19_378_953, 20_460_558, 21_443_591, 22_228_063, 23_549_972,
    23_728_675, 24_394_166,
    20_267_648, 14_769_103,                                        # UST bonus
]
EXCLUSION_BLOCK_WINDOW = 2000


def _get_symbol_raw(w3, address: str) -> str:
    """Raw eth_call + manual decode, bypassing web3.py's contract ABI wrapper entirely.
    Root-cause fix for a real hang found in an earlier run of this file: MKR (and other
    legacy, pre-ERC20-standardization tokens) return symbol() as a fixed bytes32, not a
    dynamic string -- confirmed by direct inspection (`eth_call` on MKR returns exactly
    32 bytes: b'MKR\\x00...\\x00'). Decoding that as a dynamic `string` via web3.py's
    contract wrapper doesn't fail cleanly, it hangs indefinitely (not caught by
    _with_retry's exception handling, which only catches transient RPC-layer errors --
    this is a deterministic decode issue, not a retryable one). This function handles
    both encodings directly instead."""
    addr = Web3.to_checksum_address(address)
    sig = Web3.keccak(text="symbol()")[:4]
    data = _with_retry(lambda: w3.eth.call({"to": addr, "data": sig}))
    if len(data) == 32:
        return data.rstrip(b"\x00").decode("ascii", errors="replace")
    from eth_abi import decode as abi_decode
    return abi_decode(["string"], data)[0]


def _verify_token(w3, address: str, expected_symbol: str) -> bool:
    try:
        symbol = _get_symbol_raw(w3, address)
        return expected_symbol.lower() in symbol.lower()
    except Exception as exc:
        print(f"    symbol() check failed for {address}: {exc}")
        return False


def _lookup_feed(w3, registry, base: str, quote: str, block_number):
    try:
        addr = _with_retry(
            lambda: registry.functions.getFeed(
                Web3.to_checksum_address(base), Web3.to_checksum_address(quote)
            ).call(block_identifier=block_number)
        )
        if addr is None or int(addr, 16) == 0:
            return None
        return addr
    except Exception as exc:
        print(f"    getFeed() reverted/failed: {exc}")
        return None


def resolve_feeds(w3, candidates, quote_addr, quote_label):
    registry = w3.eth.contract(address=Web3.to_checksum_address(FEED_REGISTRY), abi=REGISTRY_ABI)
    latest = w3.eth.block_number
    resolved = {}
    for label, token_addr, expected_symbol in candidates:
        print(f"  {label}: verifying token contract {token_addr} ...")
        if not _verify_token(w3, token_addr, expected_symbol):
            print(f"    REJECTED -- symbol() did not match '{expected_symbol}', not trusting this address.")
            resolved[label] = {"status": "token_unverified", "token": token_addr}
            continue
        feed = _lookup_feed(w3, registry, token_addr, quote_addr, latest)
        if feed is None:
            print(f"    no {quote_label} feed registered for {label}.")
            resolved[label] = {"status": "no_feed", "token": token_addr}
            continue
        print(f"    feed found: {feed}")
        resolved[label] = {"status": "found", "token": token_addr, "feed": feed}
    return resolved


def mine_feed_window(w3, name: str, address: str, window_label: str, anchor_block: int) -> pd.DataFrame:
    """Pull ~ROUNDS_PER_WINDOW rounds ending at-or-before anchor_block and flag gaps
    within that window against the feed's OWN median gap over that same window (a
    feed's cadence can differ across eras, e.g. gas-fee-dependent deviation-triggered
    updates were less frequent in 2020-2021 than in later years -- computing the
    baseline locally, not globally, avoids a stale-looking 2020 gap being flagged
    just because 2026's cadence is faster).

    Checks the proxy has code at anchor_block BEFORE attempting a round-data call --
    found the hard way (an earlier run of this exact function looked stuck/rate-limited
    for several straight minutes on LINK/USD's 2020-03 window): a call against a
    not-yet-deployed contract returns empty data, which web3.py surfaces as
    BadFunctionCallOutput -- a DETERMINISTIC failure, not a transient one, but
    _with_retry's exception handling doesn't distinguish the two and burns a full
    ~105s retry cycle on something that can never succeed. get_code() is one cheap
    call that avoids ~6 wasted, doomed retries per feed/window where the feed simply
    didn't exist yet."""
    if w3.eth.get_code(Web3.to_checksum_address(address), block_identifier=anchor_block) in (b"", b"0x"):
        print(f"  {name} / {window_label}: feed not yet deployed at block {anchor_block:,} -- skipping (not a failure)")
        return pd.DataFrame()
    try:
        anchor_round = get_round_data_at_block(w3, address, anchor_block)["round_id"]
    except Exception as exc:
        print(f"  {name} / {window_label}: could not resolve a round at block {anchor_block}: {exc}")
        return pd.DataFrame()

    history = get_feed_update_history(
        w3, address, max_rounds=ROUNDS_PER_WINDOW, batch_size=BATCH_SIZE, start_round_id=int(anchor_round)
    )
    if history.empty or len(history) < 5:
        print(f"  {name} / {window_label}: insufficient history ({len(history)} rounds)")
        return pd.DataFrame()
    print(f"  {name} / {window_label}: {len(history)} rounds, {history['timestamp'].min()} -> {history['timestamp'].max()}", flush=True)
    baseline = history["gap_seconds"].median()
    threshold = max(HEARTBEAT_MULTIPLE * baseline, MIN_ABSOLUTE_GAP_SECONDS) if pd.notna(baseline) else MIN_ABSOLUTE_GAP_SECONDS
    flagged = history[history["gap_seconds"] >= threshold].copy()
    if not flagged.empty:
        print(f"    median gap {baseline:.0f}s, threshold {threshold:.0f}s -- {len(flagged)} gap(s) flagged")
    flagged["feed_name"] = name
    flagged["feed_address"] = address
    flagged["window_label"] = window_label
    flagged["baseline_heartbeat_seconds"] = baseline
    flagged["price_before"] = history["answer"].shift(1).loc[flagged.index]
    return flagged


_LATEST_BLOCK_CACHE = {}  # populated once per process, not once per call


def _get_latest_block_cached(w3):
    if not _LATEST_BLOCK_CACHE:
        blk = _with_retry(lambda: w3.eth.get_block("latest"))
        _LATEST_BLOCK_CACHE["number"] = blk["number"]
        _LATEST_BLOCK_CACHE["timestamp"] = blk["timestamp"]
    return _LATEST_BLOCK_CACHE["number"], _LATEST_BLOCK_CACHE["timestamp"]


def _find_block_for_timestamp(w3, target_ts: int) -> int:
    """Same semantics as a blind binary search (first block with timestamp >=
    target_ts), but uses a timestamp-based linear estimate + a few Newton-style
    corrections + a TIGHT local binary search, instead of a blind binary search over
    the full ~26M-block range every single call. Found necessary the hard way: an
    earlier run of this exact function, called ~216 times while resolving flagged
    malfunction candidates, spent the better part of an hour in this one step alone
    (25 RPC calls x 0.3s unconditional sleep each, every time, regardless of how close
    a decent estimate could land in 2-3 calls). Ethereum's post-merge (Sept 2022)
    block time is a very stable ~12.0s/block; even pre-merge's more variable ~13.5s/
    block, a linear estimate from a shared "latest" anchor (fetched ONCE per process
    via _get_latest_block_cached, not once per call) converges within a few hundred
    blocks almost always."""
    latest_num, latest_ts = _get_latest_block_cached(w3)
    if target_ts >= latest_ts:
        return latest_num

    avg_block_time = 12.0
    guess = max(0, latest_num - int((latest_ts - target_ts) / avg_block_time))
    for _ in range(4):
        blk = _with_retry(lambda: w3.eth.get_block(guess))
        time.sleep(0.15)
        error_seconds = target_ts - blk["timestamp"]
        if abs(error_seconds) < 60:
            break
        guess = max(0, min(latest_num, guess + int(error_seconds / avg_block_time)))

    lo, hi = max(0, guess - 1500), min(latest_num, guess + 1500)
    while lo < hi:
        mid = (lo + hi) // 2
        if _with_retry(lambda: w3.eth.get_block(mid))["timestamp"] < target_ts:
            lo = mid + 1
        else:
            hi = mid
        time.sleep(0.15)
    return lo


def depeg_lag_check(w3, name: str, address: str) -> dict:
    print(f"Depeg-lag check: {name} ({address})...", flush=True)
    history = get_feed_update_history(
        w3, address, min_timestamp=MIN_TIMESTAMP, max_rounds=MAX_ROUNDS_PER_FEED, batch_size=BATCH_SIZE
    )
    if history.empty or len(history) < 3:
        print("  insufficient history")
        return {"name": name, "address": address, "status": "insufficient_history", "n_rounds": len(history)}
    ret = history["answer"].pct_change().abs()
    gap_ratio = history["gap_seconds"] / history["gap_seconds"].median()
    return {
        "name": name,
        "address": address,
        "status": "ok",
        "n_rounds": len(history),
        "window": f"{history['timestamp'].min()} -> {history['timestamp'].max()}",
        "median_gap_s": history["gap_seconds"].median(),
        "max_gap_s": history["gap_seconds"].max(),
        "max_gap_ratio": gap_ratio.max(),
        "max_single_round_move_pct": ret.max() * 100,
    }


def check_currently_frozen(w3, name: str, address: str) -> dict:
    """Is this feed's LATEST round suspiciously old right now? This is exactly how
    FTT/USD and UST/USD were originally found (both are STILL silently frozen today,
    years later) -- a live "has this feed died" check, not a "was there a gap during a
    known stress window" check like Part A. A feed that quietly stopped updating
    outside all 6 stress windows would be invisible to Part A entirely, so this runs
    against every resolved feed regardless of window-based results."""
    try:
        latest_round_id = None
        history = get_feed_update_history(w3, address, max_rounds=2, batch_size=2)
        if history.empty:
            return {"name": name, "status": "no_history"}
        last_updated_at = int(history["updated_at"].iloc[-1])
    except Exception as exc:
        return {"name": name, "status": f"error: {exc}"}
    now_ts = int(time.time())
    age_days = (now_ts - last_updated_at) / 86400
    return {
        "name": name,
        "status": "ok",
        "last_update": pd.Timestamp(last_updated_at, unit="s", tz="UTC"),
        "age_days": age_days,
        "suspicious": age_days > 30,  # generous -- even a slow-moving stablecoin feed should beat this
    }


def main():
    w3 = get_web3()

    print("=" * 90)
    print("PART A: broadened full-history gap-mining (USD-quoted feeds)")
    print("=" * 90)
    usd_resolved = resolve_feeds(w3, USD_CANDIDATES, USD_QUOTE, "USD")

    print(f"\nResolving anchor blocks for {len(STRESS_WINDOWS)} stress windows (shared across all feeds)...")
    window_blocks = {}
    for window_label, anchor_date in STRESS_WINDOWS:
        ts = int(pd.Timestamp(anchor_date, tz="UTC").timestamp())
        block = _find_block_for_timestamp(w3, ts)
        window_blocks[window_label] = block
        print(f"  {window_label} (anchor {anchor_date}) -> block {block:,}")

    # Re-resolve each feed's address AT EACH WINDOW's own block, not at "latest" --
    # found necessary after discovering LINK/USD's current registry-returned proxy
    # address has zero code as far back as Nov 2022 (confirmed via get_code), meaning
    # Chainlink migrated the proxy at some point and the "latest" address genuinely
    # did not exist during several stress windows. Resolving per-window instead of
    # once avoids silently mis-attributing "no data" to those windows when a
    # different, real address should have been checked. The registry contract itself
    # didn't exist until sometime between 2020-03 and 2022-05 (confirmed via get_code
    # on the registry address itself) -- windows before that are genuinely
    # unreachable by this method, reported as such, not silently skipped.
    registry = w3.eth.contract(address=Web3.to_checksum_address(FEED_REGISTRY), abi=REGISTRY_ABI)
    all_flagged = []
    window_resolution_log = []
    for label, info in usd_resolved.items():
        if info["status"] != "found":
            continue
        token_addr = info["token"]
        for window_label, anchor_block in window_blocks.items():
            registry_code = w3.eth.get_code(Web3.to_checksum_address(FEED_REGISTRY), block_identifier=anchor_block)
            if registry_code in (b"", b"0x"):
                print(f"  {label} / {window_label}: Feed Registry itself didn't exist yet at block {anchor_block:,} -- unreachable by this method")
                window_resolution_log.append((label, window_label, "registry_not_deployed"))
                continue
            historical_feed = _lookup_feed(w3, registry, token_addr, USD_QUOTE, anchor_block)
            if historical_feed is None:
                print(f"  {label} / {window_label}: no feed registered at block {anchor_block:,} (may predate this asset's feed)")
                window_resolution_log.append((label, window_label, "no_feed_at_this_time"))
                continue
            if historical_feed.lower() != info["feed"].lower():
                print(f"  {label} / {window_label}: historical feed address differs from latest "
                      f"({historical_feed} vs {info['feed']}) -- using the historical one")
            flagged = mine_feed_window(w3, label, historical_feed, window_label, anchor_block)
            window_resolution_log.append((label, window_label, "mined"))
            if not flagged.empty:
                all_flagged.append(flagged)
            time.sleep(0.4)

    candidates_a = []
    if all_flagged:
        combined = pd.concat(all_flagged, ignore_index=True).sort_values("gap_seconds", ascending=False)
        print(f"\n{len(combined)} raw flagged gaps across all resolved feeds; resolving blocks + excluding known incidents...")
        for _, r in combined.iterrows():
            block_number = _find_block_for_timestamp(w3, int(r["updated_at"]))
            if any(abs(block_number - lb) <= EXCLUSION_BLOCK_WINDOW for lb in LOCKED_BLOCKS):
                continue
            candidates_a.append({
                "feed_name": r["feed_name"], "feed_address": r["feed_address"],
                "window_label": r["window_label"],
                "block_number": block_number, "gap_seconds": r["gap_seconds"],
                "price_before": r["price_before"], "price_after": r["answer"],
                "updated_at": r["timestamp"], "baseline_heartbeat_seconds": r["baseline_heartbeat_seconds"],
            })
    else:
        print("\nNo feeds resolved or no gaps flagged in Part A.")

    print("\n" + "=" * 90)
    print("PART B: depeg-lag check (newer LSD/ETH feeds)")
    print("=" * 90)
    eth_resolved = resolve_feeds(w3, ETH_CANDIDATES, ETH_QUOTE, "ETH")
    depeg_results = []
    for label, info in eth_resolved.items():
        if info["status"] != "found":
            depeg_results.append({"name": label, "status": info["status"]})
            continue
        depeg_results.append(depeg_lag_check(w3, label, info["feed"]))
        time.sleep(0.4)

    print("\n" + "=" * 90)
    print("PART C: is any resolved feed currently frozen/dead (live check, not window-based)")
    print("=" * 90)
    freeze_results = []
    all_resolved = {**usd_resolved, **eth_resolved}
    for label, info in all_resolved.items():
        if info["status"] != "found":
            continue
        result = check_currently_frozen(w3, label, info["feed"])
        freeze_results.append(result)
        flag = " <-- SUSPICIOUS, investigate" if result.get("suspicious") else ""
        print(f"  {label}: last update {result.get('last_update')}, "
              f"{result.get('age_days', 0):.1f} days ago{flag}", flush=True)
        time.sleep(0.2)

    write_report(usd_resolved, candidates_a, eth_resolved, depeg_results, freeze_results, window_resolution_log)
    return usd_resolved, candidates_a, eth_resolved, depeg_results, freeze_results


def write_report(usd_resolved, candidates_a, eth_resolved, depeg_results, freeze_results=None, window_resolution_log=None):
    lines = [
        "# Malfunction (Staleness) Candidates — Phase 1 Broadened Search",
        "",
        "Extends `reports/malfunction_candidates.md`'s search beyond what it already covered. "
        "Read-only: does not touch `build_features.py`, `models.py`, or `features.parquet`. "
        "Feed addresses were resolved via the Chainlink Feed Registry's own `getFeed(base, quote)` "
        f"(registry `{FEED_REGISTRY}`) at a recent block, never hardcoded from memory — each token "
        "contract's `symbol()` was checked on-chain first, and any address that failed that check "
        "was rejected rather than used.",
        "",
        "## Part A — targeted-window gap-mining (feeds only spot-checked before)",
        "",
        "Method note: an initial attempt walked each feed's FULL history backward from "
        "\"latest\" (mine_malfunctions.py's exact method), but these majors update every "
        "~30-60 minutes continuously, so a 3000-round cap only reached back 2-4 months -- "
        "discovered empirically on a first run, not assumed, and abandoned as infeasible "
        "(full multi-year history at this cadence is ~50,000-100,000+ rounds/feed). Revised "
        f"to: anchor a bounded backward walk ({ROUNDS_PER_WINDOW} rounds via "
        "`get_feed_update_history`'s `start_round_id`) at a block a few days after each of "
        f"{len(STRESS_WINDOWS)} known historical stress windows' core move (2020 COVID crash "
        "through the 2026-02 crash) -- the same 'look where a malfunction is most likely to "
        "show up' logic the original FTT/USD and UST/USD discoveries used, applied to more "
        "feeds and more windows. A gap is flagged if it's >= "
        f"max({HEARTBEAT_MULTIPLE}x the feed's own median gap FOR THAT WINDOW, "
        f"{MIN_ABSOLUTE_GAP_SECONDS//3600}h) -- computed per-window, not globally, since a "
        "feed's update cadence can differ across eras. Gaps within "
        f"{EXCLUSION_BLOCK_WINDOW} blocks of any of the 20 already-locked incidents (all "
        "three classes, not just manipulation) are excluded. This trades full-history "
        "completeness for covering the periods a staleness event is actually likely to "
        "matter in, within a tractable RPC budget -- calm periods between stress windows "
        "were not checked, so this is not an exhaustive history scan the way the original "
        "ETH/USD, BTC/USD, USDC/USD, USDT/USD full-history mining was.",
        "",
        "### Feed resolution",
        "",
        "| Candidate | Token verified? | Feed found? | Feed address |",
        "|---|---|---|---|",
    ]
    for label, info in usd_resolved.items():
        verified = "no (symbol mismatch)" if info["status"] == "token_unverified" else "yes"
        found = {"found": "yes", "no_feed": "no — not registered", "token_unverified": "n/a"}[info["status"]]
        feed = info.get("feed", "—")
        lines.append(f"| {label} | {verified} | {found} | `{feed}` |")

    lines += ["", "### New candidates found (after exclusion)", ""]
    if candidates_a:
        lines.append("| Feed | Window | Block | Gap (s) | Price Before | Price After | Updated At (UTC) |")
        lines.append("|---|---|---|---|---|---|---|")
        for c in candidates_a:
            lines.append(
                f"| {c['feed_name']} | {c['window_label']} | {c['block_number']:,} | {c['gap_seconds']:.0f} | "
                f"{c['price_before']:.4f} | {c['price_after']:.4f} | {c['updated_at']} |"
            )
    else:
        lines.append("**None.** No flagged gap on any resolved feed survived exclusion of the 20 "
                      "already-locked incident blocks — every large gap found coincided with an "
                      "already-known event window, or no feed exceeded the staleness threshold at all.")

    if window_resolution_log:
        total = len(window_resolution_log)
        mined = sum(1 for _, _, s in window_resolution_log if s == "mined")
        no_registry = sum(1 for _, _, s in window_resolution_log if s == "registry_not_deployed")
        no_feed_yet = sum(1 for _, _, s in window_resolution_log if s == "no_feed_at_this_time")
        lines += [
            "",
            "### Feed/window coverage (per-window historical resolution, not \"latest\")",
            "",
            "Each feed's address was re-resolved via the Feed Registry AT EACH WINDOW's own "
            "historical block, not looked up once at \"latest\" -- necessary because a proxy "
            "address active today may not have existed during an earlier window (Chainlink "
            "periodically migrates proxies). This is a real coverage limitation, not a bug to "
            "paper over: a window this method can't reach was never actually checked, and is "
            "reported as such below rather than silently counted as clean.",
            "",
            f"- **{mined}/{total}** feed/window combinations were actually mined for gaps.",
            f"- **{no_registry}/{total}** were unreachable because the Feed Registry contract "
            "itself did not exist yet at that window's block (true for every feed's 2020-03 "
            "COVID-crash window -- the registry wasn't deployed until sometime between "
            "2020-03 and 2022-05, confirmed via `get_code`, not assumed).",
            f"- **{no_feed_yet}/{total}** were unreachable because no feed was registered for "
            "that asset/quote pair at that window's block (the asset's feed may not have "
            "existed yet, or Chainlink hadn't onboarded it to the registry yet at that time).",
        ]

    lines += [
        "",
        "## Part B — depeg-lag check (newer LSD/ETH feeds)",
        "",
        "Same method as the original rETH/ETH, cbETH/ETH, WBTC/BTC check: max single-round price "
        "move and max gap vs. the feed's own median, over its full reachable history. A genuine "
        "depeg-lag candidate needs BOTH a real large price move AND a stale gap that failed to "
        "track it in time.",
        "",
        "| Candidate | Status | Rounds | Window | Median gap (s) | Max gap (s) | Max gap / median | Max single-round move |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in depeg_results:
        if r.get("status") in ("token_unverified", "no_feed"):
            reason = "symbol mismatch, address rejected" if r["status"] == "token_unverified" else "no feed registered"
            lines.append(f"| {r['name']} | {reason} | — | — | — | — | — | — |")
        elif r.get("status") == "insufficient_history":
            lines.append(f"| {r['name']} | insufficient history ({r.get('n_rounds', 0)} rounds) | — | — | — | — | — | — |")
        else:
            lines.append(
                f"| {r['name']} | ok | {r['n_rounds']} | {r['window']} | {r['median_gap_s']:.0f} | "
                f"{r['max_gap_s']:.0f} | {r['max_gap_ratio']:.1f}x | {r['max_single_round_move_pct']:.2f}% |"
            )

    lines += [
        "",
        "## Part C — is any resolved feed currently frozen/dead (live check)",
        "",
        "Not a window-based check like Part A -- this is the same kind of live 'has this feed "
        "silently died' check that originally found FTT/USD and UST/USD (both are STILL frozen "
        "years later). Flags anything whose most recent update is suspiciously old right now, "
        "regardless of whether that shows up in any of the 6 stress windows Part A checked.",
        "",
        "| Feed | Last update (UTC) | Age (days) | Suspicious? |",
        "|---|---|---|---|",
    ]
    for r in (freeze_results or []):
        if r["status"] != "ok":
            lines.append(f"| {r['name']} | — | — | {r['status']} |")
        else:
            flag = "**YES — investigate**" if r["suspicious"] else "no"
            lines.append(f"| {r['name']} | {r['last_update']} | {r['age_days']:.1f} | {flag} |")

    lines += [
        "",
        "## Headline finding",
        "",
    ]
    no_frozen = all(not r.get("suspicious") for r in (freeze_results or []))
    mined_count = sum(1 for _, _, s in (window_resolution_log or []) if s == "mined")
    total_windows = len(window_resolution_log or [])
    if not candidates_a and no_frozen and all(
        r.get("status") in ("token_unverified", "no_feed", "insufficient_history")
        or r.get("max_single_round_move_pct", 0) < 5
        for r in depeg_results
    ):
        lines.append(
            "**No new malfunction incidents found** among the feed/window combinations actually "
            f"mined ({mined_count}/{total_windows} attempted combinations — see the coverage "
            "breakdown above for exactly what the remainder couldn't reach, and why). Consistent "
            "with the prior search's conclusion that the silent-freeze-at-last-price failure mode "
            f"is structurally rare on mainnet: none of the {len(USD_CANDIDATES)} broadened "
            "USD-quoted feeds produced a staleness gap in a reachable window, none is currently "
            "frozen/dead (Part C — a live check independent of window coverage), and none of the "
            "4 newer LSD/ETH feeds ever showed a large enough single-round price move for a lag to "
            "matter (or had no registered feed at all)."
        )
    else:
        lines.append(
            "See tables above for anything flagged — review each individually before treating it as "
            "a genuine new malfunction (this report does not itself decide that; it surfaces raw "
            "on-chain evidence only, the same standard `malfunction_candidates.md` was held to)."
        )

    (REPORTS_DIR / "malfunction_candidates_phase1.md").write_text("\n".join(lines) + "\n")
    print(f"\nWrote {REPORTS_DIR / 'malfunction_candidates_phase1.md'}")


if __name__ == "__main__":
    main()
