"""G2 demonstration (task 37): reconstruct the attacked source's price after every pool event inside the attack block.

Free eth_getLogs only (one block per call, well inside the free tier's 10-block cap) + eth_call for the PRE-BLOCK state
(balances/A/fee at T-1) and END-OF-BLOCK state (at T) used ONLY to validate the replay. No traces, no paid tier.

Price = fee-free marginal price from the stableswap invariant on replayed balances (or the balance-weighted LP value for tricrypto2,
the quantity Inverse's feed read). Reported per pool: peak intra-block deviation vs pre-block price, block-close deviation,
whether A0's trigger (X = 0.5%, source price path only) fires on the intra-block path, and replay-vs-chain validation errors.
"""
import json
from pathlib import Path

import numpy as np
from eth_abi import decode as abi_decode
from eth_utils import keccak

import pilot_rpc as R
from pilot_lib import *

OUT = Path(__file__).resolve().parent.parent / "reports" / "pilot_g2_results.json"
X_TRIG = 0.005


def t0(sig):
    return "0x" + keccak(text=sig).hex()


SIG = {
    t0("TokenExchange(address,int128,uint256,int128,uint256)"): "exch",
    t0("TokenExchange(address,uint256,uint256,uint256,uint256)"): "exch",
    t0("TokenExchangeUnderlying(address,int128,uint256,int128,uint256)"): "exch_u",
    t0("RemoveLiquidityOne(address,int128,uint256,uint256,uint256)"): "rem1_ng",
    t0("AddLiquidity(address,uint256[],uint256[],uint256,uint256)"): "add_ng",
    t0("RemoveLiquidity(address,uint256[],uint256[],uint256)"): "rem_ng",
    t0("RemoveLiquidityImbalance(address,uint256[],uint256[],uint256,uint256)"): "remimb_ng",
    t0("AddLiquidity(address,uint256[3],uint256,uint256)"): "add_tri",
    t0("RemoveLiquidity(address,uint256[3],uint256)"): "rem_tri",
    t0("RemoveLiquidityOne(address,uint256,uint256,uint256)"): "rem1_tri",
}


def get_logs(addr, blk):
    r = R.batch_call([("eth_getLogs", [{"address": addr, "fromBlock": hex(blk), "toBlock": hex(blk)}])])[0]
    if "error" in r:
        raise RuntimeError(f"getLogs failed {addr} {blk}: {r['error']}")
    out = sorted(r["result"], key=lambda l: (int(l["transactionIndex"], 16), int(l["logIndex"], 16)))
    return out


def words(data):
    b = bytes.fromhex(data[2:])
    return [int.from_bytes(b[i:i + 32], "big", signed=False) for i in range(0, len(b), 32)]


def s128(x):
    return x - 2 ** 256 if x >= 2 ** 255 else x


# ---------------------------------------------------------------- stableswap engine
def get_D(xp, Ann):
    n = len(xp)
    S = sum(xp)
    D = S
    for _ in range(255):
        Dp = D
        for x in xp:
            Dp = Dp * D / (x * n)
        Dprev = D
        D = (Ann * S + Dp * n) * D / ((Ann - 1) * D + (n + 1) * Dp)
        if abs(D - Dprev) <= 1e-13 * D:
            break
    return D


def price_xp(xp, Ann, i, j):
    """Marginal price of coin i in coin j (units of j per i) in normalised (xp) space, fee-free."""
    n = len(xp)
    D = get_D(xp, Ann)
    prod = 1.0
    for x in xp:
        prod *= x / D                    # normalise to avoid overflow: D^{n+1}/(n^n prod x) = D / (n^n prod(x/D))
    Dp_full = D / ((n ** n) * prod)
    Fi = Ann + Dp_full / xp[i]
    Fj = Ann + Dp_full / xp[j]
    return Fi / Fj


# ---------------------------------------------------------------- pool specs
POOLS = {
    "Harvest": dict(addr="0x45F783CCE6B7FF23B2ab2D70e416cdb7D6055f51", T=11129474, kind="v1_y", n=4, i=1, j=2, iu=2, ju=1),
    "UwU": dict(addr="0x02950460E2b9529D0E00284A5fA2d7bDF3fA4d72", T=20061319, kind="ng", n=2, i=0, j=1),
    "Zunami": dict(addr="0x68934F60758243eafAf4D2cFeD27BF8010bede3a", T=17908950, kind="ng", n=2, i=0, j=1),
    "Makina": dict(addr="0x32e616f4f17d43f9a5cd9be0e294727187064cb3", T=24273362, kind="ng", n=2, i=0, j=1),
}


def rd(addr, sig, types, vals, blk):
    return dec_uint(R.eth_call_many([(addr, enc(sig, types, vals))], blk)[0])


def idx_call(addr, name, k, blk):
    """coins/balances with uint256 index, falling back to int128 (pre-2021 Vyper pools)."""
    for t in ("uint256", "int128"):
        o = R.eth_call_many([(addr, enc(f"{name}({t})", [t], [k]))], blk)[0]
        if o not in (None, "0x"):
            return o
    raise RuntimeError(f"{name}({k}) unreadable on {addr} @ {blk}")


def pool_state(sp, blk):
    a, n = sp["addr"], sp["n"]
    coins = [dec_addr(idx_call(a, "coins", k, blk)) for k in range(n)]
    dec = [int(rd(c, "decimals()", [], [], blk)) for c in coins]
    bal = [dec_uint(idx_call(a, "balances", k, blk)) / 10 ** dec[k] for k in range(n)]
    if sp["kind"] == "ng":
        A = rd(a, "A_precise()", [], [], blk) / 100.0
        ppfs = [1.0] * n
    else:
        A = float(rd(a, "A()", [], [], blk))
        ppfs = [rd(c, "getPricePerFullShare()", [], [], blk) / 1e18 for c in coins]
    return dict(coins=coins, dec=dec, bal=bal, A=A, fee=rd(a, "fee()", [], [], blk) / 1e10, admin=rd(a, "admin_fee()", [], [], blk) / 1e10, ppfs=ppfs)


def chain_price(sp, st, blk):
    """On-chain reference for the engine: 1/get_p where the pool has it, else get_dy/(1-fee) (fee-free equivalent)."""
    a = sp["addr"]
    o = R.eth_call_many([(a, enc("get_p(uint256)", ["uint256"], [0]))], blk)[0]
    if o not in (None, "0x") and sp["kind"] == "ng" and sp["n"] == 2:
        return 1 / (dec_uint(o) / 1e18), "1/get_p(0)"
    d = enc("get_dy(int128,int128,uint256)", ["int128", "int128", "uint256"], [sp["i"], sp["j"], 10 ** st["dec"][sp["i"]]])
    dy = dec_uint(R.eth_call_many([(a, d)], blk)[0]) / 10 ** st["dec"][sp["j"]]
    return dy / (1 - st["fee"]), "get_dy/(1-fee)"


def prices(sp, st, bal):
    n = sp["n"]
    xp = [bal[k] * st["ppfs"][k] for k in range(n)]                 # underlying-value, 18-dec-normalised token units
    Ann = st["A"] * n
    out = {}
    out["S"] = price_xp(xp, Ann, sp["i"], sp["j"]) * st["ppfs"][sp["i"]] / st["ppfs"][sp["j"]]    # token-unit price i in j (ng: ppfs=1)
    if sp["kind"] == "v1_y":
        out["S_u"] = price_xp(xp, Ann, sp["iu"], sp["ju"])             # underlying USDT->USDC (what the Harvest swaps moved)
    return out


def replay(sp):
    T = sp["T"]
    pre, post = pool_state(sp, T - 1), pool_state(sp, T)
    st = pre
    n, dec, ppfs = sp["n"], st["dec"], st["ppfs"]
    bal = list(pre["bal"])
    path = [dict(ev="pre-block", tx=None, bal=list(bal), **prices(sp, st, bal))]
    flow = {"USDT_sold_underlying": 0.0, "added": [0.0] * n}
    for lg in get_logs(sp["addr"], T):
        kind = SIG.get(lg["topics"][0])
        w = words(lg["data"])
        tx = lg["transactionHash"]
        if kind in ("exch", "exch_u"):
            si, ts, bi, tb = s128(w[0]), w[1], s128(w[2]), w[3]
            ts_t, tb_t = ts / 10 ** dec[si], tb / 10 ** dec[bi]
            if kind == "exch_u":                                        # underlying units -> yToken units
                in_y, out_y = ts_t / ppfs[si], tb_t / ppfs[bi]
            else:
                in_y, out_y = ts_t, tb_t
            gross = out_y / (1 - st["fee"])
            bal[si] += in_y
            bal[bi] -= out_y + gross * st["fee"] * st["admin"]
            if kind == "exch_u" and si == sp.get("iu"):
                flow["USDT_sold_underlying"] += ts_t
            label = f"{kind} {si}->{bi} sold={ts_t:,.0f}"
        elif kind == "add_ng":
            amts, fees = abi_decode(["uint256[]", "uint256[]", "uint256", "uint256"], bytes.fromhex(lg["data"][2:]))[:2]
            for k in range(n):
                bal[k] += amts[k] / 10 ** dec[k] - fees[k] / 10 ** dec[k] * st["admin"]
                flow["added"][k] += amts[k] / 10 ** dec[k]
            label = "add_liquidity " + ",".join(f"{a / 10 ** dec[k]:,.0f}" for k, a in enumerate(amts))
        elif kind == "rem_ng":
            amts = abi_decode(["uint256[]", "uint256[]", "uint256"], bytes.fromhex(lg["data"][2:]))[0]
            for k in range(n):
                bal[k] -= amts[k] / 10 ** dec[k]
            label = "remove_liquidity"
        elif kind == "remimb_ng":                                        # RemoveLiquidityImbalance (was silently skipped before 2026-09-30 fix)
            amts, fees = abi_decode(["uint256[]", "uint256[]", "uint256", "uint256"], bytes.fromhex(lg["data"][2:]))[:2]
            for k in range(n):
                bal[k] -= amts[k] / 10 ** dec[k] + fees[k] / 10 ** dec[k] * st["admin"]
            label = "remove_imbalance " + ",".join(f"{a / 10 ** dec[k]:,.3f}" for k, a in enumerate(amts))
        elif kind == "rem1_ng":
            tid, tok, coin, sup = s128(w[0]), w[1], w[2], w[3]
            bal[tid] -= coin / 10 ** dec[tid]
            label = f"remove_one coin{tid} {coin / 10 ** dec[tid]:,.0f}"
        else:
            continue                                                     # Transfer/Approval/unknown: no pool-balance effect
        path.append(dict(ev=label, tx=tx, bal=list(bal), **prices(sp, st, bal)))
    return pre, post, path, flow


def summarize(name, sp):
    pre, post, path, flow = replay(sp)
    keys = ["S"] + (["S_u"] if sp["kind"] == "v1_y" else [])
    res = {"pool": name, "T": sp["T"], "n_events_replayed": len(path) - 1, "flow": flow, "series": {}}
    val = []
    for blk, stx in ((sp["T"] - 1, pre), (sp["T"], post)):
        ref, lab = chain_price(sp, stx, blk)
        eng = prices(sp, stx, stx["bal"])["S"]
        val.append(dict(block_offset=blk - sp["T"], engine=eng, chain=ref, chain_ref=lab, relerr=abs(eng - ref) / ref))
    res["engine_validation"] = val
    for k in keys:
        p0 = path[0][k]
        devs = [abs(s[k] - p0) / p0 for s in path]
        kpk = int(np.argmax(devs))
        chain_pre = prices(sp, pre, pre["bal"])[k]
        chain_post = prices(sp, post, post["bal"])[k]                   # engine applied to ON-CHAIN balances at T (block close)
        res["series"][k] = dict(
            pre_price=p0, peak_dev=devs[kpk], peak_at=path[kpk]["ev"], peak_tx=path[kpk]["tx"], peak_price=path[kpk][k],
            block_close_price_replayed=path[-1][k], block_close_dev_replayed=abs(path[-1][k] - p0) / p0,
            block_close_price_chain_balances=chain_post, block_close_dev_chain=abs(chain_post - chain_pre) / chain_pre,
            replay_vs_chain_close_relerr=abs(path[-1][k] - chain_post) / chain_post,
            g1_fires=bool(abs(chain_post - chain_pre) / chain_pre >= X_TRIG), g2_fires=bool(devs[kpk] >= X_TRIG),
            path=[dict(ev=s["ev"], price=s[k], dev=devs[i]) for i, s in enumerate(path)])
    res["balance_replay_relerr_at_close"] = [abs(a - b) / max(b, 1e-9) for a, b in zip(path[-1]["bal"], post["bal"])]
    return res


# ---------------------------------------------------------------- tricrypto2 (Inverse): balance-weighted LP value
def inverse():
    T = 14972419
    POOL, LP, YV = TRICRYPTO2, CRV3CRYPTO, YV3CRYPTO
    dec = [6, 8, 18]
    def state(b):
        bal = [rd(POOL, "balances(uint256)", ["uint256"], [k], b) / 10 ** dec[k] for k in range(3)]
        sup = rd(LP, "totalSupply()", [], [], b) / 1e18
        return bal, sup
    feeds = {k: ChainlinkFeed(a, k) for k, a in CL_FEEDS.items()}
    qa = new_qa("g2_inverse_feeds")
    px = {k: feeds[k].series([T - 1], qa)[0][0] for k in feeds}
    ppfs = rd(YV, "pricePerShare()", [], [], T - 1) / 1e18
    S = lambda bal, sup: ppfs * (bal[0] * px["USDT"] + bal[1] * px["BTC"] + bal[2] * px["ETH"]) / sup
    bal, sup = state(T - 1)
    bal_post, sup_post = state(T)
    path = [dict(ev="pre-block", tx=None, S=S(bal, sup))]
    for lg in get_logs(POOL, T):
        kind = SIG.get(lg["topics"][0]); w = words(lg["data"]); tx = lg["transactionHash"]
        if kind == "exch":
            si, ts, bi, tb = w[0], w[1], w[2], w[3]
            bal[si] += ts / 10 ** dec[si]; bal[bi] -= tb / 10 ** dec[bi]; label = f"exch {si}->{bi} sold={ts / 10 ** dec[si]:,.0f}"
        elif kind == "add_tri":
            amts = w[:3]; sup = w[-1] / 1e18
            for k in range(3):
                bal[k] += amts[k] / 10 ** dec[k]
            label = "add_liquidity " + ",".join(f"{a / 10 ** dec[k]:,.0f}" for k, a in enumerate(amts))
        elif kind == "rem_tri":
            amts = w[:3]; sup = w[-1] / 1e18
            for k in range(3):
                bal[k] -= amts[k] / 10 ** dec[k]
            label = "remove_liquidity"
        elif kind == "rem1_tri":
            label = "remove_one (unhandled)"
        else:
            continue
        path.append(dict(ev=label, tx=tx, S=S(bal, sup)))
    p0 = path[0]["S"]; devs = [abs(s["S"] - p0) / p0 for s in path]; k = int(np.argmax(devs))
    chain_post = S(bal_post, sup_post)
    return {"pool": "Inverse", "T": T, "n_events_replayed": len(path) - 1, "series": {"S": dict(
        pre_price=p0, peak_dev=devs[k], peak_at=path[k]["ev"], peak_tx=path[k]["tx"], peak_price=path[k]["S"],
        block_close_price_replayed=path[-1]["S"], block_close_dev_replayed=abs(path[-1]["S"] - p0) / p0,
        block_close_price_chain_balances=chain_post, block_close_dev_chain=abs(chain_post - p0) / p0,
        replay_vs_chain_close_relerr=abs(path[-1]["S"] - chain_post) / chain_post,
        g1_fires=bool(abs(chain_post - p0) / p0 >= X_TRIG), g2_fires=bool(devs[k] >= X_TRIG),
        path=[dict(ev=s["ev"], price=s["S"], dev=devs[i]) for i, s in enumerate(path)])},
        "balance_replay_relerr_at_close": [abs(a - b) / max(b, 1e-9) for a, b in zip(bal, bal_post)]}


if __name__ == "__main__" and len(__import__("sys").argv) == 1:
    results = []
    for name, sp in POOLS.items():
        results.append(summarize(name, sp))
    results.append(inverse())
    OUT.write_text(json.dumps(results, indent=1, default=str))
    for r in results:
        for k, s in r["series"].items():
            print(f"{r['pool']:8s} {k:4s} events={r['n_events_replayed']:2d} pre={s['pre_price']:.6g} peak_dev={s['peak_dev']:.4%} at '{s['peak_at']}' "
                  f"| close_dev(chain)={s['block_close_dev_chain']:.4%} | G1 fires={s['g1_fires']} G2 fires={s['g2_fires']} "
                  f"| replay-vs-chain close relerr={s['replay_vs_chain_close_relerr']:.2e}")
        print("   engine vs chain:", [(v["block_offset"], f"{v['relerr']:.1e}") for v in r.get("engine_validation", [])])
        print("   balance replay relerr at close:", [f"{x:.1e}" for x in r["balance_replay_relerr_at_close"]], r.get("flow", ""))


# ---------------------------------------------------------------- neighbouring-block scan (Harvest and UwU, the two G1 misses)
STATE_KINDS = {"exch", "exch_u", "rem1_ng", "add_ng", "rem_ng", "remimb_ng"}


def active_blocks(addr, lo, hi):
    """Blocks in [lo, hi] with >= 1 state-changing pool event; eth_getLogs in <=10-block windows (free tier)."""
    counts = {}
    for s in range(lo, hi + 1, 10):
        e = min(s + 9, hi)
        r = R.batch_call([("eth_getLogs", [{"address": addr, "fromBlock": hex(s), "toBlock": hex(e)}])])[0]
        if "error" in r:
            raise RuntimeError(r["error"])
        for lg in r["result"]:
            if SIG.get(lg["topics"][0]) in STATE_KINDS:
                b = int(lg["blockNumber"], 16)
                counts[b] = counts.get(b, 0) + 1
    return counts


def scan(name, lo_off, hi_off):
    sp = POOLS[name]; T = sp["T"]
    act = active_blocks(sp["addr"], T + lo_off, T + hi_off)
    rows = []
    for b in sorted(act):
        try:
            r = summarize(f"{name}@T{b - T:+d}", dict(sp, T=b))
        except Exception as ex:                                        # record, do not abort the scan
            rows.append(dict(block=b, offset=b - T, n_events=act[b], error=str(ex)[:160]))
            continue
        key = "S_u" if "S_u" in r["series"] else "S"
        s = r["series"][key]
        rows.append(dict(block=b, offset=b - T, n_events=r["n_events_replayed"], peak_dev=s["peak_dev"], peak_at=s["peak_at"],
                         close_dev=s["block_close_dev_chain"], g1_fires=s["g1_fires"], g2_fires=s["g2_fires"], series_key=key,
                         flow=r["flow"], replay_close_relerr=s["replay_vs_chain_close_relerr"]))
    return rows


def run_scan():
    scans = {"Harvest": scan("Harvest", -12, 40), "UwU": scan("UwU", -330, 30)}
    (OUT.parent / "pilot_g2_scan.json").write_text(json.dumps(scans, indent=1, default=str))
    for nm, rows in scans.items():
        print(f"\n{nm}: {len(rows)} active blocks in scan window")
        for r in rows:
            if "error" in r:
                print(f"  T{r['offset']:+4d} ERROR {r['error']}"); continue
            print(f"  T{r['offset']:+4d} ev={r['n_events']:2d} peak_dev={r['peak_dev']:.4%} close_dev={r['close_dev']:.4%} G1={r['g1_fires']} G2={r['g2_fires']}  {r['peak_at']}")


if __name__ == "__main__" and len(__import__("sys").argv) > 1 and __import__("sys").argv[1] == "scan":
    run_scan()
