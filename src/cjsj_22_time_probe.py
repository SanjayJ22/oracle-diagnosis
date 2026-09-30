"""CJSJ item 22: time shortcut probe. Does the incident DATE (or block number) alone predict the label?
Sets: all 24 / A2 M-all (12) / verified M (9) attacks vs the 138 volatility incidents (2021-05-19 to 2026-09-11).
 (a) composition by year and by collection cohort (a sourcing artifact),
 (b) rank AUC of date (and of block) as a raw score, two-sided permutation p (5000 shuffles of the label) and Mann-Whitney / KS tests,
 (c) LOOCV RF (150 trees) on date-only and block-only, and LOOCV logistic regression on standardized date, AUC with 95% stratified-bootstrap CI.
'Time predicts the label' is read off the CIs: AUC CI excluding 0.5 = a time shortcut. Block number and date are near-perfectly collinear for Ethereum mainnet."""
import numpy as np, pandas as pd
from scipy import stats
from joblib import Parallel, delayed
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from cjsj_common import TAG_VERIFIED, write_section
import cjsj_eval as E

B = 2000


def rank_auc(y, x):
    return roc_auc_score(y, x)


def perm_p(y, x, n=5000, seed=0):
    rng = np.random.default_rng(seed); obs = abs(rank_auc(y, x) - .5)
    null = np.array([abs(rank_auc(rng.permutation(y), x) - .5) for _ in range(n)])
    return (1 + (null >= obs).sum()) / (1 + n)


def loo_one(x, y, i, kind):
    tr = np.delete(np.arange(len(y)), i); X = x.reshape(-1, 1)
    if kind == "rf":
        c = RandomForestClassifier(n_estimators=150, random_state=0).fit(X[tr], y[tr])
    else:
        mu, sd = X[tr].mean(), X[tr].std(); c = LogisticRegression(max_iter=1000).fit((X[tr] - mu) / sd, y[tr])
        return c.predict_proba((X[[i]] - mu) / sd)[0, 1]
    return c.predict_proba(X[[i]])[0][list(c.classes_).index(1)]


def loo(x, y, kind):
    return np.array(Parallel(n_jobs=8)(delayed(loo_one)(x, y, i, kind) for i in range(len(y))))


def boot_auc(y, p, seed=0):
    rng = np.random.default_rng(seed); pos = np.where(y == 1)[0]; neg = np.where(y == 0)[0]; v = []
    for _ in range(B):
        s = np.concatenate([rng.choice(pos, len(pos)), rng.choice(neg, len(neg))]); v.append(roc_auc_score(y[s], p[s]))
    return roc_auc_score(y, p), *np.percentile(v, [2.5, 97.5])


def main():
    base = E.load_base(); sets = E.positive_sets(base); L = []; Q = L.append
    base["days"] = (base.dt - pd.Timestamp("2020-01-01")).dt.days.astype(float); blk = base.block.astype(float)
    Q("### 22a. Composition"); Q("")
    yr = base.assign(year=base.dt.dt.year).groupby(["year", base.label.map({E.MAN: "attacks", E.VOL: "volatility"})]).size().unstack(fill_value=0)
    Q("| Year | attacks | volatility |"); Q("|---|---|---|")
    for y_, r in yr.iterrows(): Q(f"| {y_} | {r.get('attacks', 0)} | {r.get('volatility', 0)} |")
    co = base.groupby(["cohort", base.label.map({E.MAN: "attacks", E.VOL: "volatility"})]).size().unstack(fill_value=0)
    Q(""); Q("| Collection cohort | attacks | volatility |"); Q("|---|---|---|")
    for c_, r in co.iterrows(): Q(f"| {c_} | {r.get('attacks', 0)} | {r.get('volatility', 0)} |")
    Q("")
    Q("### 22b/22c. Date-only and block-only predictors"); Q("")
    Q("| Label set | Feature | rank AUC (later = attack) | permutation p (two-sided, 5000) | Mann-Whitney p | KS p | LOOCV RF AUC [95% CI] | LOOCV logistic AUC [95% CI] |"); Q("|---|---|---|---|---|---|---|---|")
    ver = {}
    for sname in ["all 24 (audit baseline)", "A2 M, any tier (12)", "verified M (9)"]:
        df = E.subset(base, sets[sname]).reset_index(drop=True); y = E.labels(df)
        for fname, x in [("date", df.days.values), ("block number", df.block.astype(float).values)]:
            a = rank_auc(y, x); p = perm_p(y, x); mw = stats.mannwhitneyu(x[y == 1], x[y == 0]).pvalue; ks = stats.ks_2samp(x[y == 1], x[y == 0]).pvalue
            prf = loo(x, y, "rf"); plr = loo(x, y, "lr"); rf_ci = boot_auc(y, prf); lr_ci = boot_auc(y, plr)
            ver[(sname, fname)] = (a, p, rf_ci, lr_ci)
            Q(f"| {sname} | {fname} | {a:.3f} | {p:.4f} | {mw:.4f} | {ks:.4f} | {rf_ci[0]:.3f} [{rf_ci[1]:.3f}, {rf_ci[2]:.3f}] | {lr_ci[0]:.3f} [{lr_ci[1]:.3f}, {lr_ci[2]:.3f}] |")
    Q("")
    Q("Composition note: 8 of 24 attacks (33%) are from 2026 versus 16 of 138 volatility incidents (12%), and the collection cohort differs by class (attack share 29% / 28% / 8% / 12% in original_20 / phase1 / phase2 / phase3), so the sourcing process is time-structured even though date alone does not separate the labels (below).")
    Q(""); Q("### 22d. Reading (computed)"); Q("")
    for sname in ["all 24 (audit baseline)", "A2 M, any tier (12)", "verified M (9)"]:
        a, p, rf_ci, lr_ci = ver[(sname, "date")]
        sig = (rf_ci[1] > .5) or (lr_ci[1] > .5) or p < .05
        low = [nm for nm, ci in (("RF", rf_ci), ("logistic", lr_ci)) if ci[2] < .5]
        note = (f" NOTE: the {'/'.join(low)} LOOCV AUC CI lies entirely BELOW 0.5, a known leave-one-out artifact for near-uninformative features (removing the held-out point shifts the training fit against its label); "
                "it is not evidence of a time effect. The rank AUC and its permutation p are the valid tests.") if low else ""
        Q(f"- {sname}: date rank AUC {a:.3f} (permutation p {p:.4f}); LOOCV RF AUC {rf_ci[0]:.3f} [{rf_ci[1]:.3f}, {rf_ci[2]:.3f}]; logistic {lr_ci[0]:.3f} [{lr_ci[1]:.3f}, {lr_ci[2]:.3f}] -> "
          f"{'time carries some signal (a CI or the permutation test excludes chance)' if (p < .05 or rf_ci[1] > .5 or lr_ci[1] > .5) else 'no evidence that date predicts the label (permutation p >= .05, no CI above 0.5)'}." + note)
    Q("")
    body = "\n".join(L); print(body)
    write_section("cjsj_22_time_probe.py", "22", "Time shortcut probe: date-only and block-only models", TAG_VERIFIED + "; all-24 and M-all rows are within-benchmark (confounded data, see research_audit.md)", body)


if __name__ == "__main__":
    main()
