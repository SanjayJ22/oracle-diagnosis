"""CJSJ item 35: is the market-context shortcut model-specific? LOOCV AUC (stratified bootstrap 95% CI, 2000 reps) of four model families using ONLY market-context features,
all 24 and verified M (9), negatives = the 138 volatility incidents. Features: the 7 audit ETH-context features (heartbeat_elapsed, congestion, ref_realized_vol, temporal_* x4) for
logistic regression, XGBoost and Gaussian naive Bayes; the BN uses its 6 nodes for these features (it has no node for temporal_gap_trend). The same models on venue features
(reserve_skew + reserve_skew_localization; BN with those two nodes) are shown for comparison; RF (item 9) is repeated for reference. Logistic regression: median imputation and
standardization fit on the training fold, C=1. Naive Bayes: sklearn GaussianNB on the same standardized features. XGB: fixed config (cjsj_lc), scale_pos_weight neg/pos.
LOOCV AUC is biased downward for near-uninformative features (leave-one-out artifact), so values near or below 0.5 are not evidence of anti-signal."""
from cjsj_common import ensure_omp
ensure_omp()
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import GaussianNB
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score
from cjsj_common import TAG_VERIFIED, write_section
import cjsj_eval as E
import cjsj_lcs as S

ETH7 = ["heartbeat_elapsed", "congestion", "ref_realized_vol", "temporal_deviation_persistence", "temporal_slope", "temporal_step_change_count", "temporal_gap_trend"]
ETH6 = S.ETH6; VEN = ["reserve_skew", "reserve_skew_localization"]; B = 2000


def prep(d, cols, tr, te):
    X = E.feats(d, cols); med = X.iloc[tr].median(); sc = StandardScaler().fit(X.iloc[tr].fillna(med))
    return sc.transform(X.iloc[tr].fillna(med)), sc.transform(X.iloc[te].fillna(med))


def score(d, tr, te, model, cols, bn_keep):
    y = E.labels(d)[tr]
    if model == "BN": return S.bn_scores(d, np.asarray(tr), np.asarray(te), bn_keep)
    if model == "XGB": return S.xgb_scores(d, np.asarray(tr), np.asarray(te), cols, True)
    if model == "RF": return E.rf_proba(d, tr, te, cols=cols, n_est=150)
    Xt, Xe = prep(d, cols, tr, te)
    m = LogisticRegression(max_iter=2000).fit(Xt, y) if model == "LR" else GaussianNB().fit(Xt, y)
    return m.predict_proba(Xe)[:, 1]


def loocv(d, model, cols, bn_keep):
    n = len(d); idx = np.arange(n)
    r = Parallel(n_jobs=8)(delayed(score)(d, np.delete(idx, i), np.array([i]), model, cols, bn_keep) for i in idx)
    return np.array([x[0] for x in r])


def boot(y, p, seed=0):
    rng = np.random.default_rng(seed); pos = np.where(y == 1)[0]; neg = np.where(y == 0)[0]; v = []
    for _ in range(B): s = np.concatenate([rng.choice(pos, len(pos)), rng.choice(neg, len(neg))]); v.append(roc_auc_score(y[s], p[s]))
    return roc_auc_score(y, p), *np.percentile(v, [2.5, 97.5])


def main():
    base = E.load_base(); sets = E.positive_sets(base); L = []; Q = L.append; res = {}
    for sname in ["all 24 (audit baseline)", "verified M (9)"]:
        d = E.subset(base, sets[sname]); y = E.labels(d)
        for fsname, cols, keep in [("market-context only", ETH7, ETH6), ("venue features (reserve_skew + localization)", VEN, VEN)]:
            for m in ["LR", "XGB", "NB", "BN", "RF"]:
                p = loocv(d, m, cols, keep); res[(sname, fsname, m)] = boot(y, p)
    Q("LOOCV AUC [stratified bootstrap 95% CI]; negatives = 138 volatility incidents.")
    Q("")
    Q("| Label set | Features | Logistic regression | XGBoost | Gaussian naive Bayes | BN | Random forest (reference) |"); Q("|---|---|---|---|---|---|---|")
    f = lambda t: f"{t[0]:.3f} [{t[1]:.3f}, {t[2]:.3f}]"
    for sname in ["all 24 (audit baseline)", "verified M (9)"]:
        for fsname in ["market-context only", "venue features (reserve_skew + localization)"]:
            Q(f"| {sname} | {fsname} | " + " | ".join(f(res[(sname, fsname, m)]) for m in ["LR", "XGB", "NB", "BN", "RF"]) + " |")
    Q("")
    Q("Note: logistic regression on the SIGNED venue features (AUC 0.042 on all 24) is misspecified, not informative: attack reserve_skew values are large in both directions (e.g. about -1 for drains, clipped +3 for Cream) while the model is linear in the signed value; the BN, RF and XGBoost thresholds act on magnitude or split freely. The BN's market-context AUC below 0.5 (0.35 / 0.33) means it extracts no usable signal from those features (fixed thresholds), consistent with it being inert on them.")
    Q("")
    Q("Reading (computed): market-context-only AUC CI lower bound > 0.5 for " + ", ".join(f"{m} ({s.split(' (')[0]})" for s in ["all 24 (audit baseline)", "verified M (9)"] for m in ["LR", "XGB", "NB", "BN", "RF"] if res[(s, 'market-context only', m)][1] > .5) +
      "; not above chance for " + (", ".join(f"{m} ({s.split(' (')[0]})" for s in ["all 24 (audit baseline)", "verified M (9)"] for m in ["LR", "XGB", "NB", "BN", "RF"] if res[(s, 'market-context only', m)][1] <= .5) or "none") + ".")
    Q("")
    body = "\n".join(L); print(body)
    write_section("cjsj_35_shortcut_models.py", "35", "Is the market-context shortcut model-specific? (LR, XGBoost, naive Bayes, BN)", TAG_VERIFIED + "; all-24 rows are within-benchmark (confounded data, see research_audit.md)", body)


if __name__ == "__main__":
    main()
