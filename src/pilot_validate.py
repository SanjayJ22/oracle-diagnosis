"""Validate the three readers on 3 known attacks BEFORE any benign pull is used (writes pilot_validation.json).
Hard numbers come from post-mortems, not from this project's earlier readers."""
import json
from pathlib import Path
import numpy as np
import pilot_rpc as R
from pilot_lib import *

OUT = Path(__file__).resolve().parent.parent / "data" / "processed" / "pilot_validation.json"
res = []


def rec(name, source_of_truth, checks, ok):
    res.append(dict(name=name, truth=source_of_truth, checks=checks, passed=bool(ok)))
    print(("PASS" if ok else "FAIL"), name, checks, flush=True)


# 1. vault-rate reader: CurveLlamaLend / sDOLA (LlamaRisk + Curve governance post-mortem: pre-attack convertToAssets = 1.189)
T = 24566937
qa = new_qa("val_sdola"); verify_tx("0xb93506af8f1a39f6a31e2d34f5f6a262c2799fef6e338640f42ab8737ed3d8a4", T, qa)
v = VaultRate("0xb45ad160634c528Cc3D2926d9807104FA3157305", "sDOLA", T - 1)
p = v.series([T - 1, T], qa)
jump = p[1] / p[0] - 1
rec("vault_rate_reader/sDOLA", "LlamaRisk post-mortem: rate 1.189 pre-attack; note reports +13.79% jump",
    dict(T_minus_1=float(p[0]), T=float(p[1]), jump=float(jump), qa=qa.ok), 1.1885 < p[0] < 1.1895 and abs(jump - 0.1379) < 0.003 and qa.ok)

# 2. curve LP reader: Inverse Finance (BlockSec: oracle price 979 before the manipulation)
T = 14972419
qa = new_qa("val_inverse")
verify_tx("0x958236266991bc3fe3b77feaacea120f172c0708ad01c7a715b255f218f9313c", T, qa)
S_, Rf = TricryptoLP().series([T - 300, T - 1, T], qa)
rec("curve_lp_reader/Inverse", "BlockSec: oracle price 979 before manipulation",
    dict(S_T_minus_300=float(S_[0]), S_T_minus_1=float(S_[1]), S_T=float(S_[2]), Rfair_T_minus_1=float(Rf[1]), qa=qa.ok),
    abs(S_[0] - 979) < 1.5 and abs(S_[1] - 979) < 2.0 and qa.ok)

# 3. curve spot reader: UwU (oracle read get_p spot per QuillAudits). Identity: p_dy(i->j) * get_p(0) = 1 - fee for a 2-coin ng pool
T = 20061319; POOL = "0x02950460E2b9529D0E00284A5fA2d7bDF3fA4d72"
qa = new_qa("val_uwu")
pool = CurvePool(POOL, 0, 1, "USDe/USDC", T - 1)
blocks = [T - 300, T - 10, T - 1, T, T + 1, T + 20]
pdy = pool.series(blocks, qa)
gp = np.array([dec_uint(o) / 1e18 for o in R.eth_call_blocks(POOL, enc("get_p(uint256)", ["uint256"], [0]), blocks)])
fee = dec_uint(R.eth_call_many([(POOL, sel("fee()"))], T - 1)[0]) / 1e10
ident = pdy * gp
rec("curve_spot_reader/UwU", "pool's own get_p (what UwU's oracle read, QuillAudits): p_dy*get_p = 1-fee",
    dict(identity=[float(x) for x in ident], one_minus_fee=1 - fee, spot_T_minus_1=float(pdy[2]), spot_T=float(pdy[3]), qa=qa.ok),
    bool(np.all(np.abs(ident - (1 - fee)) < 2e-4)) and qa.ok)

json.dump(res, open(OUT, "w"), indent=1)
print("ALL PASS" if all(r["passed"] for r in res) else "SOME FAIL")
