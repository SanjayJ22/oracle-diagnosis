"""Batched, cached JSON-RPC layer for the matched-negative pilot (A0/A1, G1 block-close).

Read-only: eth_call, eth_getBlockByNumber, eth_getTransactionReceipt, eth_blockNumber.
Every response is cached in data/raw/pilot_cache.sqlite (data/ is git-ignored), so re-runs and
QA re-checks cost nothing. Every call is also counted so the pilot can report its RPC footprint.
"""
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
URL = f"https://eth-mainnet.g.alchemy.com/v2/{os.getenv('ALCHEMY_KEY')}"
CACHE = Path(__file__).resolve().parent.parent / "data" / "raw" / "pilot_cache.sqlite"
BATCH = 20            # requests per HTTP batch
MAX_RETRIES = 14
_lock = threading.Lock()
_stats = {"rpc_requests": 0, "cache_hits": 0, "http_calls": 0, "retries": 0}


def _db():
    con = sqlite3.connect(CACHE, timeout=60, check_same_thread=False)
    con.execute("CREATE TABLE IF NOT EXISTS c (k TEXT PRIMARY KEY, v TEXT)")
    return con


_con = _db()


def stats():
    return dict(_stats)


def _key(method, params):
    return method + "|" + json.dumps(params, sort_keys=True)


def _get(k):
    with _lock:
        r = _con.execute("SELECT v FROM c WHERE k=?", (k,)).fetchone()
    return None if r is None else json.loads(r[0])


def _put(items):
    with _lock:
        _con.executemany("INSERT OR REPLACE INTO c VALUES (?,?)", [(k, json.dumps(v)) for k, v in items])
        _con.commit()


CU_COST = {"eth_call": 26, "eth_getBlockByNumber": 16, "eth_getTransactionReceipt": 15, "eth_getCode": 19, "eth_blockNumber": 10}
BUDGET_CU_PER_S = 420          # free tier is ~500 CU/s; stay under it so 429 backoffs never dominate
_next_ok = [0.0]


def _throttle(batch):
    cost = sum(CU_COST.get(b["method"], 26) for b in batch)
    with _lock:
        now = time.time()
        wait = max(0.0, _next_ok[0] - now)
        _next_ok[0] = max(now, _next_ok[0]) + cost / BUDGET_CU_PER_S
    if wait:
        time.sleep(wait)


def _post(batch):
    for attempt in range(MAX_RETRIES):
        try:
            _throttle(batch)
            _stats["http_calls"] += 1
            r = requests.post(URL, json=batch, timeout=60)
            if r.status_code == 429:
                raise RuntimeError("429")
            r.raise_for_status()
            out = r.json()
            if isinstance(out, dict):  # provider-level error for whole batch
                raise RuntimeError(str(out)[:200])
            if any(isinstance(o, dict) and o.get("error", {}).get("code") == 429 for o in out):
                raise RuntimeError("429 in batch")
            return out
        except Exception:
            _stats["retries"] += 1
            with _lock:
                _next_ok[0] = max(_next_ok[0], time.time()) + min(60, 2.0 * 2 ** attempt)   # penalise the shared bucket
    raise RuntimeError("RPC failed after retries")


def batch_call(reqs):
    """reqs: list of (method, params). Returns list of results (None for reverted/error, with error text
    cached as {'error': ...}). Order preserved."""
    keys = [_key(m, p) for m, p in reqs]
    res = [None] * len(reqs)
    todo = []
    for i, k in enumerate(keys):
        v = _get(k)
        if v is not None:
            res[i] = v
            _stats["cache_hits"] += 1
        else:
            todo.append(i)
    for s in range(0, len(todo), BATCH):
        chunk = todo[s:s + BATCH]
        payload = [{"jsonrpc": "2.0", "id": j, "method": reqs[i][0], "params": reqs[i][1]} for j, i in enumerate(chunk)]
        out = _post(payload)
        _stats["rpc_requests"] += len(chunk)
        by_id = {o["id"]: o for o in out}
        new = []
        for j, i in enumerate(chunk):
            o = by_id[j]
            v = {"error": o["error"].get("message", "err")} if "error" in o else {"result": o["result"]}
            tries = 0
            while "error" in v and "revert" not in v["error"].lower() and tries < 4:      # transient provider error: retry, never cache
                tries += 1
                time.sleep(2 * tries)
                o2 = _post([{"jsonrpc": "2.0", "id": 0, "method": reqs[i][0], "params": reqs[i][1]}])[0]
                v = {"error": o2["error"].get("message", "err")} if "error" in o2 else {"result": o2["result"]}
            res[i] = v
            if "error" not in v or "revert" in v["error"].lower():                          # cache results and deterministic reverts only
                new.append((keys[i], v))
        _put(new)
    return res


def eth_call_many(calls, block):
    """calls: list of (to, data_hex). Returns list of hex results or None on revert."""
    rs = batch_call([("eth_call", [{"to": to, "data": data}, hex(block)]) for to, data in calls])
    return [r.get("result") if "result" in r else None for r in rs]


def eth_call_blocks(to, data, blocks):
    rs = batch_call([("eth_call", [{"to": to, "data": data}, hex(b)]) for b in blocks])
    return [r.get("result") if "result" in r else None for r in rs]


def get_block(n):
    return batch_call([("eth_getBlockByNumber", [hex(n), False])])[0].get("result")


def get_blocks(ns):
    rs = batch_call([("eth_getBlockByNumber", [hex(n), False]) for n in ns])
    return [r.get("result") for r in rs]


def get_receipt(tx):
    return batch_call([("eth_getTransactionReceipt", [tx])])[0].get("result")


def latest_block():
    # never cached (volatile)
    r = _post([{"jsonrpc": "2.0", "id": 0, "method": "eth_blockNumber", "params": []}])
    return int(r[0]["result"], 16)
