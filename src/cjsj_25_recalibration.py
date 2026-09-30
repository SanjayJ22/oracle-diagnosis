"""CJSJ item 25: BN recalibration (Platt and isotonic), fit INSIDE LOOCV folds.
For every outer LOOCV fold i (n=162, 24 manipulations, the audit benchmark): (1) the BN is fit on the other 161 rows and scores held-out row i (raw score);
(2) a calibrator is fit on the BN's out-of-fold scores for those 161 rows from an inner stratified 10-fold cross-validation (so the calibrator never sees row i
and never sees in-sample BN scores); (3) it is applied to row i's raw score. Platt = unpenalized logistic regression on logit(clip(p, 1e-4, 1-1e-4));
isotonic = sklearn IsotonicRegression(out_of_bounds='clip'). Metrics with 2000-rep bootstrap over incidents (95% percentile): Brier (per-class mean (p-y)^2),
log-loss, 6-bin ECE, calibration slope/intercept (logistic regression of y on logit(p)), AUC; Murphy decomposition Brier = REL - RES + UNC + within-bin term
(bins [0,.1,.3,.5,.7,.9,1]). Figure: reports/figures/fig_bn_recalibration.png. Raw outer scores are checked against reports/cjsj_loocv_preds.csv (cjsj_03)."""
from cjsj_common import ensure_omp
ensure_omp()
import time
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from joblib import Parallel, delayed
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold
from cjsj_common import REPORTS, TAG_CONFOUNDED, write_section
import cjsj_eval as E

EDGES = np.array([0, .1, .3, .5, .7, .9, 1.0000001]); B = 2000


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4); return np.log(p / (1 - p))


def platt_fit(s, y):
    return LogisticRegression(penalty=None, max_iter=2000).fit(logit(s).reshape(-1, 1), y)


def outer(df, i):
    n = len(df); tr = np.delete(np.arange(n), i); y = E.labels(df)
    raw = float(E.bn_proba(df, tr, np.array([i]))[0])
    oof = np.zeros(len(tr)); yt = y[tr]
    for a, b in StratifiedKFold(10, shuffle=True, random_state=0).split(np.zeros(len(tr)), yt):
        oof[b] = E.bn_proba(df, tr[a], tr[b])
    pl = platt_fit(oof, yt); iso = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip").fit(oof, yt)
    return i, raw, float(pl.predict_proba(logit(np.array([raw])).reshape(-1, 1))[0, 1]), float(iso.predict([raw])[0])


def bins(p, y):
    idx = np.digitize(p, EDGES) - 1
    return [(int((idx == b).sum()), p[idx == b].mean() if (idx == b).any() else np.nan, y[idx == b].mean() if (idx == b).any() else np.nan) for b in range(len(EDGES) - 1)]


def ece(p, y):
    return sum(c / len(p) * abs(o - m) for c, m, o in bins(p, y) if c)


def logloss(p, y):
    q = np.clip(p, 1e-6, 1 - 1e-6); return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))


def slope_int(p, y):
    try:
        m = LogisticRegression(penalty=None, max_iter=2000).fit(logit(p).reshape(-1, 1), y); return float(m.coef_[0, 0]), float(m.intercept_[0])
    except Exception:
        return np.nan, np.nan


def murphy(p, y):
    n = len(p); obar = y.mean(); rel = res = 0.0
    for c, m, o in bins(p, y):
        if c: rel += c * (m - o) ** 2 / n; res += c * (o - obar) ** 2 / n
    unc = obar * (1 - obar); brier = float(np.mean((p - y) ** 2))
    return brier, rel, res, unc, brier - (rel - res + unc)


def stats_of(p, y):
    sl, ic = slope_int(p, y); return dict(brier=float(np.mean((p - y) ** 2)), ll=logloss(p, y), ece=ece(p, y), slope=sl, icpt=ic, auc=roc_auc_score(y, p))


def main():
    t0 = time.time(); df = E.load_base(); y = E.labels(df); n = len(df)
    res = Parallel(n_jobs=8)(delayed(outer)(df, i) for i in range(n)); res.sort()
    P = {"raw BN": np.array([r[1] for r in res]), "Platt": np.array([r[2] for r in res]), "isotonic": np.array([r[3] for r in res])}
    ref = pd.read_csv(REPORTS / "cjsj_loocv_preds.csv").p_bn.values
    chk = np.abs(P["raw BN"] - ref).max()
    rng = np.random.default_rng(0); boots = {k: {m: [] for m in ("brier", "ll", "ece", "slope", "icpt", "auc")} for k in P}; d_b = {k: [] for k in ("Platt", "isotonic")}; d_e = {k: [] for k in ("Platt", "isotonic")}
    for _ in range(B):
        s = rng.integers(0, n, n); ys = y[s]
        if ys.sum() == 0: continue
        st = {k: stats_of(P[k][s], ys) for k in P}
        for k in P:
            for m in boots[k]: boots[k][m].append(st[k][m])
        for k in ("Platt", "isotonic"): d_b[k].append(st[k]["brier"] - st["raw BN"]["brier"]); d_e[k].append(st[k]["ece"] - st["raw BN"]["ece"])
    L = []; Q = L.append
    Q(f"Nested LOOCV recalibration, n={n}, {int(y.sum())} manipulations. Max |raw outer score - cjsj_03 stored BN score| = {chk:.2e}. Bootstrap: {B} resamples of incidents (calibrator fixed as fit in its fold).")
    Q("")
    Q("#### 25a. Metrics before and after (95% bootstrap CI)"); Q("")
    Q("| Variant | Brier | log-loss | ECE (6 bins) | calibration slope | calibration intercept | AUC |"); Q("|---|---|---|---|---|---|---|")
    S0 = {k: stats_of(P[k], y) for k in P}; ci = lambda k, m, p=3: f"{S0[k][m]:.{p}f} [{np.nanpercentile(boots[k][m], 2.5):.{p}f}, {np.nanpercentile(boots[k][m], 97.5):.{p}f}]"
    for k in P: Q(f"| {k} | {ci(k, 'brier')} | {ci(k, 'll')} | {ci(k, 'ece')} | {ci(k, 'slope', 2)} | {ci(k, 'icpt', 2)} | {ci(k, 'auc')} |")
    Q("")
    Q("Paired change vs raw BN: " + "; ".join(f"{k}: Brier {S0[k]['brier'] - S0['raw BN']['brier']:+.3f} [{np.percentile(d_b[k], 2.5):+.3f}, {np.percentile(d_b[k], 97.5):+.3f}], ECE {S0[k]['ece'] - S0['raw BN']['ece']:+.3f} [{np.percentile(d_e[k], 2.5):+.3f}, {np.percentile(d_e[k], 97.5):+.3f}]" for k in ("Platt", "isotonic")) + ".")
    Q("")
    Q("#### 25b. Brier decomposition (Murphy, 6 bins): Brier = REL - RES + UNC + within-bin term"); Q("")
    Q("| Variant | Brier | REL (lower is better) | RES (higher is better) | UNC | within-bin term |"); Q("|---|---|---|---|---|---|")
    for k in P:
        b, rel, rs, unc, wb = murphy(P[k], y); Q(f"| {k} | {b:.4f} | {rel:.4f} | {rs:.4f} | {unc:.4f} | {wb:+.4f} |")
    Q("")
    Q("#### 25c. Reliability, per bin (n, mean predicted, observed)"); Q("")
    Q("| Variant | bin | n | mean predicted | observed |"); Q("|---|---|---|---|---|")
    for k in P:
        for b, (c, m, o) in enumerate(bins(P[k], y)):
            if c: Q(f"| {k} | [{EDGES[b]:.1f}, {min(EDGES[b + 1], 1):.1f}) | {c} | {m:.3f} | {o:.3f} |")
    Q("")
    Q("Figure: `reports/figures/fig_bn_recalibration.png`.")
    Q(f"Distinct calibrated output values: raw {len(np.unique(np.round(P['raw BN'], 4)))}, Platt {len(np.unique(np.round(P['Platt'], 4)))}, isotonic {len(np.unique(np.round(P['isotonic'], 4)))} (the BN posterior is nearly binary, so recalibration mostly rescales two clusters).")
    Q("")
    Q(f"(runtime {time.time() - t0:.0f}s; cjsj_25_recalibration.py)")
    # figure
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb"})
    fig, ax = plt.subplots(1, 3, figsize=(11.5, 3.9), sharey=True); col = {"raw BN": "#2a78d6", "Platt": "#eb6834", "isotonic": "#1baf7a"}; mk = {"raw BN": "o", "Platt": "s", "isotonic": "^"}
    rng2 = np.random.default_rng(1)
    for a, k in zip(ax, P):
        a.plot([0, 1], [0, 1], color="#9a9994", ls="--", lw=1)
        for b in range(len(EDGES) - 1):
            idx = (np.digitize(P[k], EDGES) - 1) == b
            if not idx.any(): continue
            m, o = P[k][idx].mean(), y[idx].mean(); bs = [y[idx][rng2.integers(0, idx.sum(), idx.sum())].mean() for _ in range(500)]
            a.errorbar(m, o, yerr=[[o - np.percentile(bs, 2.5)], [np.percentile(bs, 97.5) - o]], fmt="none", ecolor=col[k], capsize=3, lw=1.3)
            a.plot(m, o, mk[k], color=col[k], ms=8, mec="#fcfcfb", mew=1.4); a.annotate(f"n={int(idx.sum())}", (m, o), textcoords="offset points", xytext=(5, 6), fontsize=8, color="#52514e")
        a.set_title(f"{k}  (slope {S0[k]['slope']:.2f}, Brier {S0[k]['brier']:.3f})", loc="left", fontsize=10); a.set_xlabel("predicted P(manipulation)"); a.grid(color="#e6e5e1", lw=.6); a.set_xlim(-.03, 1.03); a.set_ylim(-.05, 1.05)
    ax[0].set_ylabel("observed rate (95% bootstrap CI per bin)")
    fig.suptitle("BN reliability before and after nested-LOOCV recalibration (n=162; within-benchmark, confounded data)", fontsize=10, x=0.01, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.93]); (REPORTS / "figures").mkdir(exist_ok=True); fig.savefig(REPORTS / "figures" / "fig_bn_recalibration.png", dpi=160); plt.close(fig)
    body = "\n".join(L); print(body)
    write_section("cjsj_25_recalibration.py", "25", "BN recalibration (Platt, isotonic) inside LOOCV folds", TAG_CONFOUNDED, body)


if __name__ == "__main__":
    main()
