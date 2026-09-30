"""CJSJ item 12: learning curve. Subsample k training positives (pool = verified M, k in {2,3,4,6,9}; pool = all 24, k in 2..20),
all 138 negatives, 30 seeds per k, held-out scoring as in cjsj_lc.py. Reports false alarms (of 138) and recall vs k for BN, RF, XGB (fixed
config) with 95% bootstrap CIs over the 30 seeds. The CI captures subsampling/fold randomness only, NOT incident-sampling variance (the
pool itself is fixed and tiny), so it is narrower than the true uncertainty.
Raw per-seed results: reports/cjsj_12_learning_curve.csv."""
from cjsj_common import ensure_omp
ensure_omp()
import time
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from cjsj_common import REPORTS, TAG_CONFOUNDED, TAG_VERIFIED, write_section
import cjsj_eval as E
import cjsj_lc as LC

SEEDS = range(30)
POOLS = {"verified M (9)": [2, 3, 4, 6, 9], "all 24": [2, 3, 4, 5, 6, 8, 10, 12, 14, 16, 18, 20]}


def task(df, pool_pos, k, seed):
    r, nn, npool = LC.protocol(df, pool_pos, n_sub=k, seed=1000 * k + seed)
    return k, seed, r, nn, npool


def main():
    t0 = time.time(); base = E.load_base(); sets = E.positive_sets(base); rows = []
    for pname, ks in POOLS.items():
        pool = sets["verified M (9)"] if pname.startswith("verified") else sets["all 24 (audit baseline)"]
        df = E.subset(base, pool)
        res = Parallel(n_jobs=8)(delayed(task)(df, pool, k, s) for k in ks for s in SEEDS)
        for k, s, r, nn, npool in res:
            for m, (fa, rec) in r.items(): rows.append(dict(pool=pname, k=k, seed=s, model=m, fa=fa, n_neg=nn, recall=rec, n_pool=npool))
        print(pname, "done", f"{time.time() - t0:.0f}s", flush=True)
    R = pd.DataFrame(rows); R.to_csv(REPORTS / "cjsj_12_learning_curve.csv", index=False)
    L = []; Q = L.append
    Q("Protocol: `cjsj_lc.py` (10-fold over negatives, leave-one-out over the pool positives; XGB fixed config, not nested-tuned). 30 seeds per (pool, k). CIs are 95% percentile bootstrap over seeds (subsampling variance only).")
    Q("")
    summ = {}
    for pname, ks in POOLS.items():
        Q(f"#### Pool: {pname} (recall is over the pool's positives, each held out once; false alarms are out of 138)"); Q("")
        Q("| k training positives | BN FA [CI] | RF FA [CI] | XGB FA [CI] | BN recall [CI] | RF recall [CI] | XGB recall [CI] |"); Q("|---|---|---|---|---|---|---|")
        for k in ks:
            cells = {}
            for m in LC.MODELS:
                d = R[(R.pool == pname) & (R.k == k) & (R.model == m)]
                cells[(m, "fa")] = LC.boot_mean(d.fa.values); cells[(m, "rec")] = LC.boot_mean(d.recall.values); summ[(pname, k, m)] = (cells[(m, "fa")], cells[(m, "rec")])
            f = lambda t, p=1: f"{t[0]:.{p}f} [{t[1]:.{p}f}, {t[2]:.{p}f}]"
            Q(f"| {k} | " + " | ".join(f(cells[(m, "fa")]) for m in LC.MODELS) + " | " + " | ".join(f(cells[(m, 'rec')], 2) for m in LC.MODELS) + " |")
        Q("")
    Q("#### Degradation summary (computed): change from the smallest to the largest k")
    Q("")
    Q("| Pool | Model | FA at k_min -> k_max | recall at k_min -> k_max | worst FA over k (mean) |"); Q("|---|---|---|---|---|")
    for pname, ks in POOLS.items():
        for m in LC.MODELS:
            a, b = summ[(pname, ks[0], m)], summ[(pname, ks[-1], m)]
            worst = max(summ[(pname, k, m)][0][0] for k in ks)
            Q(f"| {pname} | {m} | {a[0][0]:.1f} -> {b[0][0]:.1f} | {a[1][0]:.2f} -> {b[1][0]:.2f} | {worst:.1f} |")
    Q("")
    Q(f"(runtime {time.time() - t0:.0f}s; cjsj_12_learning_curve.py)")
    body = "\n".join(L); print(body)
    write_section("cjsj_12_learning_curve.py", "12", "Learning curve: false alarms and recall vs training positives (BN, RF, XGBoost)", TAG_CONFOUNDED + "; verified-M pool rows are verified-label runs (negatives unchanged)", body)


if __name__ == "__main__":
    main()
