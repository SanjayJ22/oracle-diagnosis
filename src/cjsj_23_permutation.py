"""CJSJ item 23: permutation-test p-values (1000 label shuffles) for the ETH-context AUCs and the venue AUCs, on all 24 / A2 M-all (12) / verified M (9).
Statistic: out-of-fold AUC of a RandomForest (40 trees, seed 0) under stratified 10-fold CV with a FIXED fold seed; the observed statistic and every
shuffled statistic use the identical procedure (label vector permuted across all rows, fold assignment re-stratified on the permuted labels), so the p-value is
exact for that statistic: p = (1 + #{null >= observed}) / (1 + 1000). Minimum attainable p is 1/1001 = 0.000999. This CV statistic differs slightly from the
LOOCV AUCs of item 9 (shown for reference); 40 trees and 10-fold are used to keep 18 tests x 1000 shuffles tractable.
Feature groups: as item 9 (ETH-market context 7, heartbeat alone, temporal 4, reserve_skew, localization, venue+localization)."""
from cjsj_common import ensure_omp
ensure_omp()
import time
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import roc_auc_score
from cjsj_common import TAG_VERIFIED, write_section
import cjsj_eval as E
from cjsj_09_shortcuts import GROUPS

B = 1000


def cv_auc(X, y, seed=0):
    oof = np.zeros(len(y))
    for tr, te in StratifiedKFold(10, shuffle=True, random_state=seed).split(X, y):
        med = np.nanmedian(X[tr], axis=0); Xt = np.where(np.isnan(X[tr]), med, X[tr]); Xe = np.where(np.isnan(X[te]), med, X[te])
        c = RandomForestClassifier(n_estimators=40, random_state=0, n_jobs=1).fit(Xt, y[tr]); oof[te] = c.predict_proba(Xe)[:, list(c.classes_).index(1)]
    return roc_auc_score(y, oof)


def null_chunk(X, y, seeds):
    out = []
    for s in seeds:
        yp = np.random.default_rng(s).permutation(y); out.append(cv_auc(X, yp))
    return out


def main():
    t0 = time.time(); base = E.load_base(); sets = E.positive_sets(base); rows = []
    for sname in ["all 24 (audit baseline)", "A2 M, any tier (12)", "verified M (9)"]:
        df = E.subset(base, sets[sname]); y = E.labels(df)
        for g, cols in GROUPS.items():
            X = E.feats(df, cols).values; obs = cv_auc(X, y)
            null = np.concatenate(Parallel(n_jobs=8)(delayed(null_chunk)(X, y, range(c, c + 125)) for c in range(0, B, 125)))
            rows.append(dict(sset=sname, group=g, obs=obs, p=(1 + (null >= obs).sum()) / (1 + len(null)), null_mean=null.mean(), null_p95=np.percentile(null, 95), null_max=null.max()))
            print(sname, g, f"{obs:.3f}", f"{rows[-1]['p']:.4f}", f"{time.time() - t0:.0f}s", flush=True)
    R = pd.DataFrame(rows); R.to_csv(E.REPORTS / "cjsj_23_permutation.csv", index=False)
    L = []; Q = L.append
    Q(f"{B} label shuffles per test; minimum p = {1 / (B + 1):.6f}. Statistic = stratified 10-fold out-of-fold RF AUC (fixed fold seed).")
    Q("")
    Q("| Label set | Feature group | observed AUC (10-fold) | permutation p | null mean | null 95th pct | null max |"); Q("|---|---|---|---|---|---|---|")
    for r in R.itertuples():
        Q(f"| {r.sset} | {r.group} | {r.obs:.3f} | {'<= ' + format(1 / (B + 1), '.4f') if r.p <= 1 / (B + 1) + 1e-12 else format(r.p, '.4f')} | {r.null_mean:.3f} | {r.null_p95:.3f} | {r.null_max:.3f} |")
    Q("")
    Q(f"Tests with p < .05: {int((R.p < .05).sum())} of {len(R)}; ETH-market context (7): " + ", ".join(f"{r.sset.split(' (')[0]} p={r.p:.4f}" for r in R[R.group.str.startswith('ETH-market')].itertuples()) +
      "; venue + localization: " + ", ".join(f"{r.sset.split(' (')[0]} p={r.p:.4f}" for r in R[R.group == 'venue + localization'].itertuples()) + ".")
    Q("")
    Q(f"(runtime {time.time() - t0:.0f}s; cjsj_23_permutation.py)")
    body = "\n".join(L); print(body)
    write_section("cjsj_23_permutation.py", "23", "Permutation tests for the ETH-context and venue AUCs", TAG_VERIFIED + "; all-24 and M-all rows are within-benchmark (confounded data, see research_audit.md)", body)


if __name__ == "__main__":
    main()
