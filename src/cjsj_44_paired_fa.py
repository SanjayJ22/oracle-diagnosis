"""CJSJ item 44: paired comparison of forward-time false-alarm totals (7 cutoffs, trained on all 24 attacks), RF - BN and XGBoost - BN, three feature sets (all features / venue only / market-context only).
Method = section 32 (cjsj_32_fig3_ci.py, same task function, feature sets, cutoffs, evaluability rule, 30 seeds for RF and XGBoost, BN deterministic): per-incident false-alarm counts summed over cutoffs
(volatility test incidents with P >= .5). Paired incident bootstrap (2000 reps): each replicate draws ONE seed index s, resamples the 138 volatility incidents with replacement ONCE and uses that SAME
resample for the ML model and the BN; difference = sum over resampled incidents of (model count - BN count). The BN is deterministic, so only the ML model's seed varies. Mean difference =
(mean over seeds of the model's total) - BN total. 'Excludes 0' = the 95% percentile interval does not contain 0. XGB (deterministic) = seed-free config as in Figure 3 (one run, so only incident resampling).
The bootstrap treats the 138 volatility incidents as exchangeable draws; forward-time test sets overlap across cutoffs (an incident is in the test set for every cutoff before its date), so counts are positively correlated."""
from cjsj_common import ensure_omp
ensure_omp()
import time
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from cjsj_common import REPORTS, TAG_CONFOUNDED, write_section
import cjsj_eval as E
import cjsj_32_fig3_ci as F

MODELS = ["BN", "RF", "XGB (30 seeds)", "XGB (deterministic)"]


def task_cuts(base, pos_inc, setname, model, seed, cuts):
    """cjsj_32_fig3_ci.task with an explicit cutoff list (identical logic, so results equal section 32's when cuts = E.CUTOFFS)."""
    fs = F.SETS[setname]; per = np.zeros(len(base))
    for c in cuts:
        cc = pd.Timestamp(c); ptr = int(base.incident.isin(pos_inc)[(base.dt < cc)].sum()); pte = int((base.incident.isin(pos_inc) & (base.dt >= cc)).sum())
        if ptr < 3 or pte < 2: continue
        neg = np.where((base.dt < cc) & (base.label == E.VOL))[0]; pos = np.where((base.dt < cc) & base.incident.isin(pos_inc))[0]; te = np.where(base.dt >= cc)[0]; tr = np.concatenate([neg, pos])
        if model == "BN": p = F.S.bn_scores(base, tr, te, fs["bn"])
        elif model == "RF": p = E.rf_proba(base, tr, te, cols=fs["ml"], n_est=150, seed=seed)
        elif model == "XGB (30 seeds)": p = F.xgb_seeded(base, tr, te, fs["ml"], seed)
        else: p = F.S.xgb_scores(base, tr, te, fs["ml"], True)
        isneg = base.label.values[te] == E.VOL; per[te[isneg]] += (p[isneg] >= .5)
    return setname, model, seed, per


def fa_arrays(base, pos_inc, cuts=None):
    """{(feature set, model): seeds x 138 array of per-incident false-alarm counts summed over the evaluable cutoffs} (BN and deterministic XGB have one row)."""
    cuts = list(E.CUTOFFS) if cuts is None else list(cuts); jobs = []
    for sn in F.SETS:
        jobs.append((sn, "BN", 0)); jobs.append((sn, "XGB (deterministic)", 0))
        jobs += [(sn, "RF", s) for s in F.SEEDS] + [(sn, "XGB (30 seeds)", s) for s in F.SEEDS]
    res = Parallel(n_jobs=8)(delayed(task_cuts)(base, pos_inc, *j, cuts) for j in jobs)
    negidx = np.where(base.label.values == E.VOL)[0]
    return {(sn, m): np.array([r[3][negidx] for r in res if r[0] == sn and r[1] == m]) for sn in F.SETS for m in MODELS}


def summarize(per_all, B=2000):
    """Section 32 intervals (same definitions, same rng stream and order as cjsj_32)."""
    rng = np.random.default_rng(0); store = {}
    for sn in F.SETS:
        for m in MODELS:
            per = per_all[(sn, m)]; n = per.shape[1]; tot = per.sum(1); avg = per.mean(0)
            boot = [avg[rng.integers(0, n, n)].sum() for _ in range(B)]
            comb = [per[rng.integers(0, len(per))][rng.integers(0, n, n)].sum() for _ in range(B)]
            store[(sn, m)] = dict(mean=tot.mean(), seed_lo=np.percentile(tot, 2.5), seed_hi=np.percentile(tot, 97.5), boot_lo=np.percentile(boot, 2.5), boot_hi=np.percentile(boot, 97.5),
                                  comb_lo=np.percentile(comb, 2.5), comb_hi=np.percentile(comb, 97.5), n_seeds=len(per))
    return store


def paired(A, bn_row, B=2000, seed=1):
    """Differences (model - BN) over B paired replicates: one seed draw and one shared incident resample per replicate."""
    rng = np.random.default_rng(seed); n = A.shape[1]; d = []
    for _ in range(B):
        s = rng.integers(len(A)); idx = rng.integers(0, n, n); d.append(A[s][idx].sum() - bn_row[idx].sum())
    return np.array(d)


def main():
    t0 = time.time(); base = E.load_base(); pos = E.positive_sets(base)["all 24 (audit baseline)"]
    per = fa_arrays(base, pos); L = []; Q = L.append; rows = []
    Q("Paired incident bootstrap (2000 reps); difference = model total false alarms minus BN total false alarms over the 7 forward cutoffs (all 24 attacks in training). Positive = more false alarms than the BN.")
    Q("")
    Q("| Feature set | Comparison | BN total | model mean total (seed range) | mean difference | paired 95% CI | excludes 0? | share of replicates with difference > 0 | per-seed difference range (2.5-97.5%) |"); Q("|---|---|---|---|---|---|---|---|---|")
    for sn in F.SETS:
        bn = per[(sn, "BN")][0]; bt = bn.sum()
        for m in ["RF", "XGB (30 seeds)", "XGB (deterministic)"]:
            A = per[(sn, m)]; d = paired(A, bn); lo, hi = np.percentile(d, [2.5, 97.5]); tot = A.sum(1); md = tot.mean() - bt; sd = np.percentile(tot - bt, [2.5, 97.5])
            ex = "yes" if (lo > 0 or hi < 0) else "no"
            rows.append(dict(feature_set=sn, comparison=f"{m} - BN", bn_total=bt, model_mean=tot.mean(), mean_diff=md, ci_lo=lo, ci_hi=hi, excludes0=ex, frac_pos=(d > 0).mean()))
            Q(f"| {sn} | {m} - BN | {bt:.0f} | {tot.mean():.1f} [{np.percentile(tot, 2.5):.0f}, {np.percentile(tot, 97.5):.0f}] | {md:+.1f} | [{lo:+.1f}, {hi:+.1f}] | {ex} | {(d > 0).mean():.1%} | [{sd[0]:+.0f}, {sd[1]:+.0f}] |")
    r = pd.DataFrame(rows); r.to_csv(REPORTS / "cjsj_44_paired_fa.csv", index=False)
    Q("")
    Q("Reading (computed): " + "; ".join(f"{x.feature_set}: {x.comparison} {x.mean_diff:+.1f} [{x.ci_lo:+.1f}, {x.ci_hi:+.1f}] ({'excludes' if x.excludes0 == 'yes' else 'includes'} 0)" for x in r.itertuples()) + ".")
    Q("")
    Q(f"(runtime {time.time() - t0:.0f}s; cjsj_44_paired_fa.py; raw CSV reports/cjsj_44_paired_fa.csv)")
    body = "\n".join(L); print(body)
    write_section("cjsj_44_paired_fa.py", "44", "Paired forward-time false-alarm differences, RF-BN and XGBoost-BN (section 32 method)", TAG_CONFOUNDED, body)


if __name__ == "__main__":
    main()
