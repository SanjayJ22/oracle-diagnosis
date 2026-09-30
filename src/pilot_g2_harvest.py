"""Loose end (a): replay G2 on the value the Harvest fUSDC vault actually read.
Path (verified on chain): fUSDC.getPricePerFullShare = (cash + strategy.investedUnderlyingBalance()) / supply;
strategy.investedUnderlyingBalance = ycrvVault shares * ycrvVault.ppfs -> PriceConvertor.yCrvToUnderlying(yCRV, 1)
  = Curve Y zap 0xbBC81d23... .calc_withdraw_one_coin(yCRV, USDC) (single-sided withdrawal value incl. fee).
Engine re-implements that formula; validated against the zap at T-1 and T; event replay reuses pilot_g2.replay (balances exact to 1e-11).
"""
import json
from pathlib import Path
import numpy as np
import pilot_rpc as R
import pilot_g2 as G
from pilot_lib import *

OUT = Path(__file__).resolve().parent.parent / "reports" / "pilot_g2_harvest.json"
Y = "0x45F783CCE6B7FF23B2ab2D70e416cdb7D6055f51"; VAULT = "0xf0358e8c3CD5Fa238a29301d0bEa3D63A17bEdBE"
STRAT = "0xd55ada00494d96ce1029c201425249f9dfd216cc"; YCRV = "0xdF5e0e81Dff6FAF3A7e52BA697820c5e32D806A8"
YYV = "0xf2b223eb3d2b382ead8d85f3c1b7ef87c1d35f3a"; ZAP = "0xbBC81d23Ea2c3ec7e56D39296F0cbB648873a5d3"
T0 = 11129474; IDX = 1


def get_y_D(A, i, xp, D):
    n = len(xp); Ann = A * n; c = D; S = 0.0
    for k in range(n):
        if k != i:
            S += xp[k]; c = c * D / (xp[k] * n)
    c = c * D / (Ann * n); b = S + D / Ann; y = D
    for _ in range(255):
        yp = y; y = (y * y + c) / (2 * y + b - D)
        if abs(y - yp) <= 1e-13 * y:
            break
    return y


def calc_withdraw_one(xp, A, fee, supply, amount, i):
    n = len(xp); Ann = A * n
    D0 = G.get_D(xp, Ann); D1 = D0 - amount * D0 / supply
    new_y = get_y_D(A, i, xp, D1)
    f = fee * n / (4 * (n - 1)); red = list(xp)
    for j in range(n):
        dx = (xp[j] * D1 / D0 - new_y) if j == i else (xp[j] - xp[j] * D1 / D0)
        red[j] -= f * dx / 1.0
    return red[i] - get_y_D(A, i, red, D1)


def rdv(a, sig, blk, ty=[], v=[]):
    return dec_uint(R.eth_call_many([(a, enc(sig, ty, v))], blk)[0])


def vault_state(blk):
    return dict(cash=rdv(VAULT, "underlyingBalanceInVault()", blk) / 1e6, supply=rdv(VAULT, "totalSupply()", blk) / 1e6,
                ppfs_chain=rdv(VAULT, "getPricePerFullShare()", blk) / 1e6, invested_chain=rdv(STRAT, "investedUnderlyingBalance()", blk) / 1e6,
                yyv_shares=rdv(YYV, "balanceOf(address)", blk, ["address"], [STRAT]) / 1e18, yyv_ppfs=rdv(YYV, "getPricePerFullShare()", blk) / 1e18,
                lp_supply=rdv(YCRV, "totalSupply()", blk) / 1e18)


def run_block(T):
    sp = dict(G.POOLS["Harvest"], T=T)
    pre, post, path, flow = G.replay(sp)
    vs = vault_state(T - 1); vs_post = vault_state(T)
    amount = vs["yyv_shares"] * vs["yyv_ppfs"]
    def invested(bal, st):
        xp = [bal[k] * st["ppfs"][k] for k in range(4)]
        return calc_withdraw_one(xp, st["A"], st["fee"], vs["lp_supply"], amount, IDX)
    def pps(inv):
        return (vs["cash"] + inv) / vs["supply"]
    # validation: engine on on-chain balances vs the on-chain strategy value (needs same vault state at that block)
    val = []
    for blk, st, v in ((T - 1, pre, vs), (T, post, vs_post)):
        amt = v["yyv_shares"] * v["yyv_ppfs"]
        xp = [st["bal"][k] * st["ppfs"][k] for k in range(4)]
        eng = calc_withdraw_one(xp, st["A"], st["fee"], v["lp_supply"], amt, IDX)
        val.append(dict(offset=blk - T, engine_invested=eng, chain_invested=v["invested_chain"], relerr=abs(eng - v["invested_chain"]) / v["invested_chain"],
                        engine_pps=(v["cash"] + eng) / v["supply"], chain_pps=v["ppfs_chain"]))
    inv0 = invested(path[0]["bal"], pre); p0 = pps(inv0)
    states = [dict(ev=s["ev"], invested=invested(s["bal"], pre)) for s in path]
    for s in states:
        s["invested_dev"] = (s["invested"] - inv0) / inv0; s["pps"] = pps(s["invested"]); s["pps_dev"] = (s["pps"] - p0) / p0
    kpk = int(np.argmax([abs(s["pps_dev"]) for s in states]))
    return dict(T=T, validation=val, invested_pre=inv0, pps_pre=p0,
                peak_pps_dev=states[kpk]["pps_dev"], peak_invested_dev=states[kpk]["invested_dev"], peak_at=states[kpk]["ev"],
                close_pps_dev_chain=(vs_post["ppfs_chain"] - vs["ppfs_chain"]) / vs["ppfs_chain"], states=states)


if __name__ == "__main__":
    res = []
    for T in [T0, T0 + 3, T0 + 4, T0 + 6, T0 + 7]:
        r = run_block(T); res.append(r)
        v = r["validation"]
        print(f"T{T-T0:+d}: engine-vs-zap relerr pre {v[0]['relerr']:.2e} post {v[1]['relerr']:.2e} | pps engine/chain pre {v[0]['engine_pps']:.6f}/{v[0]['chain_pps']:.6f} "
              f"| peak PPS dev {r['peak_pps_dev']:.4%} (invested {r['peak_invested_dev']:.4%}) at '{r['peak_at']}' | chain close PPS dev {r['close_pps_dev_chain']:.4%}", flush=True)
    OUT.write_text(json.dumps(res, indent=1, default=str))
