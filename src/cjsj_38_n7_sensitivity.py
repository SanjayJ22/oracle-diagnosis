"""CJSJ item 38: label-agreement sensitivity. Rerun every analysis the paper reports on the verified 9 on the 7 incidents BOTH labelers call M
(Harvest Finance, Cream Finance, Inverse Finance, UwU Lend, ZunamiProtocol, CurveLlamaLend, ResupplyFi; Makina and BalancerBoostedPool2023 dropped), next to n=24 and n=9.
Same code and seeds as the earlier sections: LOOCV RF (150 trees, seed 0) with stratified bootstrap (2000, seed 0) as cjsj_09; permutation p as cjsj_23 (stratified 10-fold out-of-fold RF AUC with
40 trees, 1000 shuffles, same shuffle seeds); BN vs RF exact McNemar at .5 as cjsj_02 (LOOCV, RF 150 trees on ALW, production BN); minimum detectable AUC from a10_power_analysis (N_NEG 138).
Note: the 'strict-7' set used in earlier sections (verified M without math_enabled) is a DIFFERENT set (it keeps Makina and drops ResupplyFi and BalancerBoosted)."""
from cjsj_common import ensure_omp
ensure_omp()
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from cjsj_common import REPORTS, TAG_VERIFIED, write_section
import cjsj_eval as E
import cjsj_09_shortcuts as C9
import cjsj_23_permutation as C23
import a10_power_analysis as a10

INC7 = ["Harvest Finance", "Cream Finance", "Inverse Finance", "UwU Lend", "ZunamiProtocol", "CurveLlamaLend", "ResupplyFi"]
ETH, VEN = C9.GROUPS["ETH-market context only (7)"], C9.GROUPS["venue + localization"]


def perm(df, cols, y):
    X = E.feats(df, cols).values; obs = C23.cv_auc(X, y)
    null = np.concatenate(Parallel(n_jobs=8)(delayed(C23.null_chunk)(X, y, range(c, c + 125)) for c in range(0, C23.B, 125)))
    return obs, (1 + (null >= obs).sum()) / (1 + len(null))


def main():
    base = E.load_base(); sets = E.positive_sets(base); ver = set(sets["verified M (9)"]); assert set(INC7) <= ver and len(ver - set(INC7)) == 2
    S = {"n=24": sets["all 24 (audit baseline)"], "n=9 (verified)": sets["verified M (9)"], "n=7 (both labelers M)": INC7}
    R = {}; L = []; Q = L.append
    for name, pos in S.items():
        df = E.subset(base, pos); y = E.labels(df); n = int(y.sum()); r = {}
        pe, pv = C9.rf_loocv(df, ETH), C9.rf_loocv(df, VEN); r["eth"] = C9.boot(y, [pe], lambda yy, pp: C9.auc(yy, pp)); r["ven"] = C9.boot(y, [pv], lambda yy, pp: C9.auc(yy, pp))
        r["diff"] = C9.boot(y, [pe, pv], lambda yy, p1, p2: C9.auc(yy, p1) - C9.auc(yy, p2))
        r["perm_eth"] = perm(df, ETH, y); r["perm_ven"] = perm(df, VEN, y)
        lo = E.loocv_splits(len(df)); prf = E.cv_predict(df, E.rf_proba, lo, n_est=150); pbn = E.cv_predict(df, E.bn_proba, lo)
        r["mcn"] = E.mcnemar(y, pbn, prf); r["bn"] = E.summ(y, pbn); r["rf"] = E.summ(y, prf); r["mde"] = a10.auc_mde(n, 138); r["n"] = n; R[name] = r
        print(name, "done", flush=True)
    f = lambda t: f"{t[0]:.3f} [{t[1]:.3f}, {t[2]:.3f}]"; fd = lambda t: f"{t[0]:+.3f} [{t[1]:+.3f}, {t[2]:+.3f}]"
    Q("Positive sets: n=24 = all attacks; n=9 = verified M; n=7 = the seven incidents both labelers call M (Harvest, Cream, Inverse, UwU, Zunami, CurveLlamaLend, ResupplyFi). 138 volatility negatives in every set.")
    Q("")
    Q("#### 38a. Side-by-side"); Q("")
    Q("| Quantity (paper value for n=9) | n=24 | n=9 | n=7 |"); Q("|---|---|---|---|")
    rows = [("RF market-context-only LOOCV AUC [95% CI] (0.917 [0.802, 0.989])", lambda r: f(r["eth"])), ("RF venue+localization LOOCV AUC [95% CI] (0.808)", lambda r: f(r["ven"])),
            ("market-context minus venue AUC [95% paired CI]", lambda r: fd(r["diff"])),
            ("permutation p, market-context (10-fold AUC; 1000 shuffles)", lambda r: f"{r['perm_eth'][1]:.4f} (AUC {r['perm_eth'][0]:.3f})"), ("permutation p, venue+localization", lambda r: f"{r['perm_ven'][1]:.4f} (AUC {r['perm_ven'][0]:.3f})"),
            ("BN vs RF exact McNemar: BN-only / RF-only errors, p (0.688)", lambda r: f"{r['mcn'][0]} / {r['mcn'][1]}, p = {r['mcn'][2]:.3f}"),
            ("BN: caught / false alarms / accuracy", lambda r: f"{r['bn']['tp']}/{r['n']} / {r['bn']['fp']} / {r['bn']['acc']:.3f}"), ("RF: caught / false alarms / accuracy", lambda r: f"{r['rf']['tp']}/{r['n']} / {r['rf']['fp']} / {r['rf']['acc']:.3f}"),
            ("minimum detectable AUC, single test, power .80 (0.745)", lambda r: f"{r['mde']:.3f}")]
    for lab, fn in rows: Q(f"| {lab} | " + " | ".join(fn(R[k]) for k in S) + " |")
    Q("")
    Q("#### 38b. Does anything change direction, or stop overlapping the n=9 value? (computed)"); Q("")
    a, b = R["n=9 (verified)"], R["n=7 (both labelers M)"]
    inside = lambda v, t: t[1] <= v <= t[2]; overlap = lambda s, t: not (s[2] < t[1] or t[2] < s[1])
    for key, lab in [("eth", "market-context AUC"), ("ven", "venue AUC")]:
        Q(f"- {lab}: n=7 {f(b[key])} vs n=9 {f(a[key])}; n=9 point value inside the n=7 CI: {inside(a[key][0], b[key])}; CIs overlap: {overlap(a[key], b[key])}; n=7 point inside the n=9 CI: {inside(b[key][0], a[key])}.")
    d9, d7 = a["diff"], b["diff"]
    Q(f"- Direction of market-context minus venue AUC: n=9 {d9[0]:+.3f}, n=7 {d7[0]:+.3f} ({'same direction' if np.sign(d9[0]) == np.sign(d7[0]) else 'OPPOSITE direction'}); CI of the difference excludes 0: n=9 {not (d9[1] <= 0 <= d9[2])}, n=7 {not (d7[1] <= 0 <= d7[2])}.")
    Q(f"- Permutation p: market-context n=9 {a['perm_eth'][1]:.4f} vs n=7 {b['perm_eth'][1]:.4f}; venue n=9 {a['perm_ven'][1]:.4f} vs n=7 {b['perm_ven'][1]:.4f} (threshold .05: market-context {'unchanged' if (a['perm_eth'][1] < .05) == (b['perm_eth'][1] < .05) else 'CHANGES'}, venue {'unchanged' if (a['perm_ven'][1] < .05) == (b['perm_ven'][1] < .05) else 'CHANGES'}).")
    fewer = lambda m: "BN" if m[0] < m[1] else ("RF" if m[1] < m[0] else "tie")
    Q(f"- BN vs RF McNemar: n=9 {a['mcn'][0]} / {a['mcn'][1]} errors, p = {a['mcn'][2]:.3f}; n=7 {b['mcn'][0]} / {b['mcn'][1]}, p = {b['mcn'][2]:.3f}; model with fewer unique errors: n=9 {fewer(a['mcn'])}, n=7 {fewer(b['mcn'])} (significance at .05: n=9 {a['mcn'][2] < .05}, n=7 {b['mcn'][2] < .05}).")
    Q(f"- Minimum detectable AUC: n=9 {a['mde']:.3f}, n=7 {b['mde']:.3f}, n=24 {R['n=24']['mde']:.3f}.")
    Q("")
    body = "\n".join(L); print(body)
    write_section("cjsj_38_n7_sensitivity.py", "38", "Label-agreement sensitivity: the 7 incidents both labelers call M (n=24 / n=9 / n=7)", TAG_VERIFIED + "; the n=24 column is within-benchmark (confounded data, see research_audit.md)", body)


if __name__ == "__main__":
    main()
