"""CJSJ item 41: forward-time January 2024 cutoff over 30 RF seeds, 150 and 300 trees (ALW features, trained on all 24 attacks + earlier volatility incidents).
Per seed: RF false alarms on the 70 test volatility incidents; exact McNemar p of RF vs BN on the 83 test incidents (13 attacks + 70 volatility; correctness at .5, as the audit's 0.0044); and the
Holm-adjusted p, where Holm is applied across the 7 audit cutoffs for that seed (the audit's correction: the 2024-01 result was the only one to survive it). The BN is deterministic.
'Share of seeds with Holm p < .05' is the fraction of seeds for which the January 2024 cutoff is significant after that correction."""
from cjsj_common import ensure_omp
ensure_omp()
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from cjsj_common import REPORTS, TAG_CONFOUNDED, write_section
import cjsj_eval as E
from cjsj_03_xgb_heuristics import holm

SEEDS = list(range(30)); CUT = "2024-01-01"


def rf_seed(base, y, pos, trees, seed):
    out = {}
    for c in E.CUTOFFS:
        cc = pd.Timestamp(c); ptr = int(base.incident.isin(pos)[(base.dt < cc)].sum()); pte = int((base.incident.isin(pos) & (base.dt >= cc)).sum())
        if ptr < 3 or pte < 2: continue
        neg = np.where((base.dt < cc) & (base.label == E.VOL))[0]; ps = np.where((base.dt < cc) & base.incident.isin(pos))[0]; te = np.where(base.dt >= cc)[0]
        out[c] = (te, E.rf_proba(base, np.concatenate([neg, ps]), te, n_est=trees, seed=seed))
    return trees, seed, out


def main():
    base = E.load_base(); pos = E.positive_sets(base)["all 24 (audit baseline)"]; y = E.labels(base); n = len(base)
    bn = {}
    for c in E.CUTOFFS:
        cc = pd.Timestamp(c); ptr = int(base.incident.isin(pos)[(base.dt < cc)].sum()); pte = int((base.incident.isin(pos) & (base.dt >= cc)).sum())
        if ptr < 3 or pte < 2: continue
        neg = np.where((base.dt < cc) & (base.label == E.VOL))[0]; ps = np.where((base.dt < cc) & base.incident.isin(pos))[0]; te = np.where(base.dt >= cc)[0]
        p = np.full(n, np.nan); p[te] = E.bn_proba(base, np.concatenate([neg, ps]), te); bn[c] = p
    res = Parallel(n_jobs=8)(delayed(rf_seed)(base, y, pos, t, s) for t in (150, 300) for s in SEEDS)
    L = []; Q = L.append; rows = []
    for t in (150, 300):
        for s in SEEDS:
            o = [r[2] for r in res if r[0] == t and r[1] == s][0]; ps = []; fa = None
            for c, (te, pr) in o.items():
                pf = np.full(n, np.nan); pf[te] = pr; m = np.zeros(n, bool); m[te] = True; n1, n2, p = E.mcnemar(y, bn[c], pf, mask=m); ps.append(p)
                if c == CUT: isneg = base.label.values[te] == E.VOL; fa = int((pr[isneg] >= .5).sum()); k = len(ps) - 1; u = (n1, n2)
            adj = holm(np.array(ps)); rows.append(dict(trees=t, seed=s, fa=fa, bn_only=u[0], rf_only=u[1], p=ps[k], holm=adj[k], n_cut=len(ps)))
    R = pd.DataFrame(rows); R.to_csv(REPORTS / "cjsj_41_jan2024_seeds.csv", index=False)
    bn_fa = int(((bn[CUT][base.dt >= CUT] >= .5) & (base.label[base.dt >= CUT] == E.VOL).values).sum()); nneg = int(((base.dt >= CUT) & (base.label == E.VOL)).sum())
    Q(f"January 2024 cutoff: train on {int(((base.dt < CUT)).sum())} earlier incidents (all-24 attack labels), test on {int((base.dt >= CUT).sum())} later ones ({nneg} volatility). BN false alarms: {bn_fa} of {nneg} (deterministic). 30 seeds per forest size; Holm across the 7 cutoffs per seed.")
    Q("")
    Q("#### 41a. RF false alarms at the January 2024 cutoff (of 70)"); Q("")
    Q("| Trees | mean | median | sd | min-max | 10th-90th pct | seeds with >= 16 | seed 0 |"); Q("|---|---|---|---|---|---|---|---|")
    for t in (150, 300):
        d = R[R.trees == t]; Q(f"| {t} | {d.fa.mean():.1f} | {d.fa.median():.0f} | {d.fa.std():.1f} | {d.fa.min()}-{d.fa.max()} | {d.fa.quantile(.1):.0f}-{d.fa.quantile(.9):.0f} | {(d.fa >= 16).mean():.0%} | {d[d.seed == 0].fa.iloc[0]} |")
    Q("")
    Q("Distribution (count of seeds by false-alarm total): " + "; ".join(f"{t} trees: " + ", ".join(f"{k}: {v}" for k, v in R[R.trees == t].fa.value_counts().sort_index().items()) for t in (150, 300)) + ".")
    Q("")
    Q("#### 41b. Exact McNemar p, RF vs BN, at that cutoff"); Q("")
    Q("| Trees | median raw p | range of raw p | share of seeds with raw p < .05 | median Holm-adjusted p (7 cutoffs) | range | **share of seeds with Holm p < .05** | BN-only / RF-only errors (median) |"); Q("|---|---|---|---|---|---|---|---|")
    for t in (150, 300):
        d = R[R.trees == t]; Q(f"| {t} | {d.p.median():.4f} | {d.p.min():.4f}-{d.p.max():.4f} | {(d.p < .05).mean():.0%} | {d.holm.median():.3f} | {d.holm.min():.3f}-{d.holm.max():.3f} | **{(d.holm < .05).mean():.0%}** | {d.bn_only.median():.0f} / {d.rf_only.median():.0f} |")
    Q("")
    # audit ordering: training rows in the data's own order (forward_time.py), seed 0, 300 trees
    cc = pd.Timestamp(CUT); tr_a = np.where(base.dt < cc)[0]; te_a = np.where(base.dt >= cc)[0]; pa = E.rf_proba(base, tr_a, te_a, n_est=300, seed=0); pf = np.full(n, np.nan); pf[te_a] = pa; mk = np.zeros(n, bool); mk[te_a] = True
    a1, a2, ap = E.mcnemar(y, bn[CUT], pf, mask=mk); afa = int((pa[base.label.values[te_a] == E.VOL] >= .5).sum())
    Q(f"Audit ordering (forward_time.py: training rows in the data's own order, 300 trees, seed 0): {afa} false alarms, {a1} BN-only vs {a2} RF-only errors, raw p = {ap:.4f}. The forest depends on row order as well as on the seed, so the audit's single run is one draw from the same distribution as the seeds above; the helper used elsewhere in this project (negatives then positives) gives a different draw for seed 0.")
    Q("")
    d3 = R[(R.trees == 300) & (R.seed == 0)].iloc[0]
    Q(f"Reading (computed): the paper's single-run figures (16 false alarms, p = 0.0044) are reproduced only with the audit's row ordering (above); with the project helper's ordering the same seed gives {d3.fa} false alarms and p = {d3.p:.4f}. Across 30 seeds RF raises {R[R.trees == 300].fa.mean():.1f} (300 trees) and {R[R.trees == 150].fa.mean():.1f} (150 trees) false alarms on average; the BN-vs-RF difference is significant after Holm in {(R[R.trees == 300].holm < .05).mean():.0%} of 300-tree seeds and {(R[R.trees == 150].holm < .05).mean():.0%} of 150-tree seeds.")
    Q("")
    body = "\n".join(L); print(body)
    write_section("cjsj_41_jan2024_seeds.py", "41", "January 2024 cutoff over 30 RF seeds: false alarms and BN-vs-RF McNemar with Holm", TAG_CONFOUNDED, body)


if __name__ == "__main__":
    main()
