"""CJSJ item 10: XGBoost added to the verified-M forward-time run (extends cjsj_02 section B).
Sets: verified M (9) [primary], verified M strict (7), A2 M any tier (12); negatives = the same 138 volatility incidents.
Per cutoff (audit skip rule): BN / RF / nested-tuned XGB accuracy, manipulations caught, false alarms, exact McNemar for
XGB-vs-BN, XGB-vs-RF, BN-vs-RF, then Holm across the evaluable cutoffs (per comparison)."""
from cjsj_common import ensure_omp
ensure_omp()
import numpy as np
from cjsj_common import TAG_VERIFIED, write_section
import cjsj_eval as E
from cjsj_fwd import forward_all, cell
from cjsj_03_xgb_heuristics import holm


def block(name, df):
    y = E.labels(df); R = forward_all(df); L = [f"#### {name}: n={len(df)}, positives={int(y.sum())}", ""]
    L += ["| Cutoff | train n (pos) | test n (pos) | BN acc / caught / FA | RF acc / caught / FA | XGB acc / caught / FA | McNemar p: XGB vs BN | XGB vs RF | BN vs RF |", "|---|---|---|---|---|---|---|---|---|"]
    ps = {"xb": [], "xr": [], "br": []}; cuts = []
    for r in R:
        if not r["ok"]:
            L.append(f"| {r['cut'][:7]} | {r['ntr']} ({r['ptr']}) | {r['nte']} ({r['pte']}) | skipped | skipped | skipped | | | |"); continue
        P = r["P"]; s = {m: cell(y, P[m], r["te"]) for m in P}
        f = lambda m: f"{s[m]['acc']:.3f} / {s[m]['tp']}/{s[m]['npos']} / {s[m]['fp']}/{s[m]['nneg']}"
        m = np.zeros(len(y), bool); m[r["te"]] = True
        pxb = E.mcnemar(y, P["XGB"], P["BN"], mask=m)[2]; pxr = E.mcnemar(y, P["XGB"], P["RF"], mask=m)[2]; pbr = E.mcnemar(y, P["BN"], P["RF"], mask=m)[2]
        ps["xb"].append(pxb); ps["xr"].append(pxr); ps["br"].append(pbr); cuts.append(r["cut"][:7])
        L.append(f"| {r['cut'][:7]} | {r['ntr']} ({r['ptr']}) | {r['nte']} ({r['pte']}) | {f('BN')} | {f('RF')} | {f('XGB')} | {pxb:.3f} | {pxr:.3f} | {pbr:.3f} |")
    L.append("")
    if ps["xb"]:
        L.append("Holm-adjusted p across the evaluable cutoffs (" + ", ".join(cuts) + "): " + "; ".join(
            f"{lab} {', '.join(f'{v:.3f}' for v in holm(np.array(ps[k])))}" for k, lab in [("xb", "XGB vs BN"), ("xr", "XGB vs RF"), ("br", "BN vs RF")]))
    L.append(""); return "\n".join(L)


def main():
    base = E.load_base(); sets = E.positive_sets(base); out = []
    out.append("Positives restricted as labeled; negatives unchanged (138 volatility, audit C1-C3 still apply). XGB = nested-tuned as in cjsj_03 (inner stratified K-fold on the training rows only; with 3-7 training positives K is 3-5).")
    out.append("")
    for name in ["verified M (9)", "verified M strict, no math_enabled (7)", "A2 M, any tier (12)"]:
        out.append(block(name, E.subset(base, sets[name])))
    body = "\n".join(out); print(body)
    write_section("cjsj_10_verified_xgb_forward.py", "10", "XGBoost added to the verified-M forward-time run", TAG_VERIFIED, body)


if __name__ == "__main__":
    main()
