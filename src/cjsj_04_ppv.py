"""CJSJ item 4 (B7): precision / PPV at deployment prevalences 1%, 5%, 15% for BN, RF, XGBoost.

PPV(pi) = pi*TPR / (pi*TPR + (1-pi)*FPR), TPR/FPR measured on the benchmark at threshold .5:
  (a) LOOCV predictions from cjsj_03 (reports/cjsj_loocv_preds.csv), n=162 (24 pos / 138 neg)
  (b) forward-time split train<2024-01 / test>=2024-01 (13 pos / 70 neg), models refit here (XGB nested-tuned as in cjsj_03)
CIs: stratified bootstrap (positives and negatives resampled separately, 5000 reps, percentile). 'Conservative' bound uses
Wilson-lower TPR and Wilson-upper FPR (the benchmark has 0 false alarms for RF/XGB, so the point PPV is 1.0 and the upper FPR
bound is what limits it). Benchmark caveat: the 138 negatives are ETH/USD >=3-5% moves (audit C1), not a sample of the
anomalies a deployed detector would see, so the measured FPR is not a deployment FPR; a sensitivity table varies FPR.
"""
from cjsj_common import ensure_omp
ensure_omp()
import numpy as np, pandas as pd
from cjsj_common import REPORTS, TAG_CONFOUNDED, write_section
import cjsj_eval as E
import cjsj_03_xgb_heuristics as X3

PREV = (0.01, 0.05, 0.15)


def ppv(tpr, fpr, pi):
    d = pi * tpr + (1 - pi) * fpr
    return np.nan if d == 0 else pi * tpr / d


def boot_ppv(pos_flags, neg_flags, B=5000, seed=0):
    rng = np.random.default_rng(seed); out = {pi: [] for pi in PREV}
    for _ in range(B):
        tpr = rng.choice(pos_flags, len(pos_flags)).mean(); fpr = rng.choice(neg_flags, len(neg_flags)).mean()
        for pi in PREV: out[pi].append(ppv(tpr, fpr, pi))
    return {pi: np.nanpercentile(v, [2.5, 97.5]) for pi, v in out.items()}


def block(y, P, title, models):
    L = [f"#### {title}", ""]
    L += ["| Model | TPR (caught/positives) | FPR (FA/neg) | prevalence | PPV | 95% bootstrap CI | conservative PPV (Wilson) | false alarms per true alert |", "|---|---|---|---|---|---|---|---|"]
    for m in models:
        p = P[m]; ok = ~np.isnan(p); pr = (p[ok] >= .5).astype(int); yy = y[ok]
        pos = pr[yy == 1]; neg = pr[yy == 0]
        tp, fp, npos, nneg = int(pos.sum()), int(neg.sum()), len(pos), len(neg)
        tpr, fpr = tp / npos, fp / nneg
        tlo, _ = E.wilson(tp, npos); _, fhi = E.wilson(fp, nneg)
        ci = boot_ppv(pos, neg)
        for pi in PREV:
            v = ppv(tpr, fpr, pi); cons = ppv(tlo, fhi, pi)
            fa_per = ((1 - pi) * fpr) / (pi * tpr) if tpr > 0 else np.nan
            L.append(f"| {X3.DESC[m]} | {tp}/{npos} = {tpr:.3f} | {fp}/{nneg} = {fpr:.3f} | {pi:.0%} | {v:.3f} | [{ci[pi][0]:.3f}, {ci[pi][1]:.3f}] | {cons:.3f} | {fa_per:.2f} |")
    L.append("")
    L.append("Models with 0 observed false alarms have a degenerate bootstrap CI of [1, 1]; the Wilson-based conservative column is the informative bound.")
    L.append("")
    L.append("PPV sensitivity to the false-positive rate a deployed detector would face (TPR fixed at each model's measured TPR):")
    L += ["", "| Model | prevalence | FPR 0.5% | FPR 1% | FPR 2% | FPR 5% |", "|---|---|---|---|---|---|"]
    for m in models:
        p = P[m]; ok = ~np.isnan(p); pr = (p[ok] >= .5).astype(int); yy = y[ok]; tpr = pr[yy == 1].mean()
        for pi in PREV:
            L.append(f"| {X3.DESC[m]} | {pi:.0%} | " + " | ".join(f"{ppv(tpr, f, pi):.3f}" for f in (0.005, 0.01, 0.02, 0.05)) + " |")
    L.append("")
    return "\n".join(L)


def main():
    pr = pd.read_csv(REPORTS / "cjsj_loocv_preds.csv")
    base = E.load_base(); assert list(base.incident) == list(pr.incident), "run cjsj_03 first (row order mismatch)"
    y = pr.y.values.astype(int); n = len(y)
    P = {"BN": pr.p_bn.values, "RF": pr.p_rf.values, "XGB": pr.p_xgb.values}
    out = ["Prevalence = share of triggered anomalies that are manipulations. Benchmark prevalence is 24/162 = 14.8%; 15% row is approximately the benchmark itself; 1% and 5% are the audit/roadmap deployment scenarios (A0 will estimate the real value).", ""]
    out.append(block(y, P, "4a. LOOCV (n=162)", ["BN", "RF", "XGB"]))
    (tr, te), = E.forward_split(base, "2024-01-01")
    Pf = {"BN": np.full(n, np.nan), "RF": np.full(n, np.nan)}
    Pf["BN"][te] = E.bn_proba(base, tr, te); Pf["RF"][te] = E.rf_proba(base, tr, te, n_est=300)
    Px, _ = X3.run_outer(base, [(tr, te)]); Pf["XGB"] = Px["XGB"]
    out.append(block(y, Pf, "4b. Forward-time, train < 2024-01, test >= 2024-01 (13 pos / 70 neg)", ["BN", "RF", "XGB"]))
    body = "\n".join(out); print(body)
    write_section("cjsj_04_ppv.py", "4", "B7 PPV at 1%, 5%, 15% prevalence (BN, RF, XGBoost)", TAG_CONFOUNDED, body)


if __name__ == "__main__":
    main()
