"""CJSJ item 32: intervals for the right panel of Figure 3 (forward-time false-alarm totals, 7 cutoffs, trained on all 24 attacks).
Feature sets: all features (ALW 8; BN full node set) / without market-context (venue only: reserve_skew + localization) / market-context only (6 features the BN has nodes for).
Models: BN (deterministic), RF (150 trees) with 30 random seeds, XGBoost with 30 seeds. XGBoost's published config is deterministic (no row/column sampling), so 30 seeds would
be identical; for this item XGBoost uses the same config with subsample 0.8 and colsample_bytree 0.8 and random_state = seed (reported as 'XGB (30 seeds)'); the deterministic XGB
(seed-free, as in Figure 3 so far) is shown alongside as 'XGB (deterministic)'.
Per seed: total false alarms = sum over the evaluable cutoffs of volatility test incidents with P >= .5. Intervals: (i) seed range = 2.5th-97.5th percentile over the 30 seeds;
(ii) incident bootstrap: the 138 volatility incidents are resampled with replacement (2000 reps), each replicate's total = sum over resampled incidents of that incident's false-alarm
count across the cutoffs where it is in the test set (seed-averaged); (iii) combined: incident bootstrap with a random seed drawn per replicate. Mean = average over seeds.
Raw: reports/cjsj_32_fig3_ci.csv."""
from cjsj_common import ensure_omp
ensure_omp()
import time
import numpy as np, pandas as pd
import xgboost as xgb
from joblib import Parallel, delayed
from cjsj_common import REPORTS, TAG_CONFOUNDED, write_section
import cjsj_eval as E
import cjsj_lc as LC
import cjsj_lcs as S

SETS = {"all features": S.FEATSETS["all features (baseline)"], "without market-context (venue only)": S.FEATSETS["no ETH-context, venue only (reserve_skew, localization)"],
        "market-context only": S.FEATSETS["ETH-context only (6 BN-compatible features)"]}
SEEDS = list(range(30))


def xgb_seeded(d, tr, te, cols, seed):
    X = E.feats(d, cols).values; yt = E.labels(d)[tr]; spw = float((yt == 0).sum()) / max(int((yt == 1).sum()), 1)
    g = xgb.XGBClassifier(**LC.XCFG, scale_pos_weight=spw, subsample=0.8, colsample_bytree=0.8, tree_method="hist", n_jobs=1, random_state=seed, verbosity=0).fit(X[tr], yt)
    return g.predict_proba(X[te])[:, 1]


def task(base, pos_inc, setname, model, seed):
    fs = SETS[setname]; per = np.zeros(len(base)); n = len(base)
    for c in E.CUTOFFS:
        cc = pd.Timestamp(c); ptr = int(base.incident.isin(pos_inc)[(base.dt < cc)].sum()); pte = int((base.incident.isin(pos_inc) & (base.dt >= cc)).sum())
        if ptr < 3 or pte < 2: continue
        neg = np.where((base.dt < cc) & (base.label == E.VOL))[0]; pos = np.where((base.dt < cc) & base.incident.isin(pos_inc))[0]; te = np.where(base.dt >= cc)[0]; tr = np.concatenate([neg, pos])
        if model == "BN": p = S.bn_scores(base, tr, te, fs["bn"])
        elif model == "RF": p = E.rf_proba(base, tr, te, cols=fs["ml"], n_est=150, seed=seed)
        elif model == "XGB (30 seeds)": p = xgb_seeded(base, tr, te, fs["ml"], seed)
        else: p = S.xgb_scores(base, tr, te, fs["ml"], True)
        isneg = base.label.values[te] == E.VOL; per[te[isneg]] += (p[isneg] >= .5)
    return setname, model, seed, per


def main():
    t0 = time.time(); base = E.load_base(); pos = E.positive_sets(base)["all 24 (audit baseline)"]; jobs = []
    for sn in SETS:
        jobs.append((sn, "BN", 0)); jobs.append((sn, "XGB (deterministic)", 0))
        jobs += [(sn, "RF", s) for s in SEEDS] + [(sn, "XGB (30 seeds)", s) for s in SEEDS]
    res = Parallel(n_jobs=8)(delayed(task)(base, pos, *j) for j in jobs)
    negidx = np.where(base.label.values == E.VOL)[0]; rows = []; rng = np.random.default_rng(0); B = 2000; L = []; Q = L.append; store = {}
    for sn in SETS:
        for m in ["BN", "RF", "XGB (30 seeds)", "XGB (deterministic)"]:
            per = np.array([r[3][negidx] for r in res if r[0] == sn and r[1] == m])          # seeds x 138 (false alarms per incident summed over cutoffs)
            tot = per.sum(1); avg = per.mean(0)
            boot = [avg[rng.integers(0, len(negidx), len(negidx))].sum() for _ in range(B)]
            comb = [per[rng.integers(0, len(per))][rng.integers(0, len(negidx), len(negidx))].sum() for _ in range(B)]
            st = dict(mean=tot.mean(), seed_lo=np.percentile(tot, 2.5), seed_hi=np.percentile(tot, 97.5), boot_lo=np.percentile(boot, 2.5), boot_hi=np.percentile(boot, 97.5), comb_lo=np.percentile(comb, 2.5), comb_hi=np.percentile(comb, 97.5), n_seeds=len(per))
            store[(sn, m)] = st; rows.append(dict(feature_set=sn, model=m, **st))
    pd.DataFrame(rows).to_csv(REPORTS / "cjsj_32_fig3_ci.csv", index=False)
    nte = sum(int(((base.dt >= pd.Timestamp(c)) & (base.label == E.VOL)).sum()) for c in E.CUTOFFS)
    Q(f"Training on all 24 attacks; false-alarm totals over the 7 cutoffs (489 volatility test incidents in total, {nte} counted across cutoffs); BN deterministic, RF and XGB 30 seeds. Intervals defined in the script docstring.")
    Q("")
    Q("| Feature set | Model | mean total false alarms | seed range (2.5-97.5%) | incident-bootstrap 95% CI | combined 95% CI |"); Q("|---|---|---|---|---|---|")
    for (sn, m), st in store.items():
        Q(f"| {sn} | {m} | {st['mean']:.1f} | [{st['seed_lo']:.0f}, {st['seed_hi']:.0f}] | [{st['boot_lo']:.1f}, {st['boot_hi']:.1f}] | [{st['comb_lo']:.1f}, {st['comb_hi']:.1f}] |")
    Q("")
    Q("Reading (computed): " + "; ".join(f"{m} with all features {store[('all features', m)]['mean']:.0f} [{store[('all features', m)]['comb_lo']:.0f}, {store[('all features', m)]['comb_hi']:.0f}] vs without market-context {store[('without market-context (venue only)', m)]['mean']:.1f} [{store[('without market-context (venue only)', m)]['comb_lo']:.1f}, {store[('without market-context (venue only)', m)]['comb_hi']:.1f}]" for m in ["BN", "RF", "XGB (30 seeds)"]) + ".")
    Q("")
    Q(f"(runtime {time.time() - t0:.0f}s; cjsj_32_fig3_ci.py)")
    body = "\n".join(L); print(body)
    write_section("cjsj_32_fig3_ci.py", "32", "Figure 3 right panel: 30-seed means with bootstrap intervals", TAG_CONFOUNDED, body)


if __name__ == "__main__":
    main()
