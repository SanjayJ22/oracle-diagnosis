"""CJSJ item 20: fairness check on the learning curve. Does the BN's recall advantage at small k survive a fair operating point?

Same held-out protocol as item 12 (cjsj_lcs.py: 10-fold over negatives, leave-one-out over pool positives, 30 seeds, random subsample of k training
positives). Variants: RF unweighted / RF class_weight='balanced'; XGB scale_pos_weight=1 / =neg:pos; each at threshold 0.5 and at the fold's TRAINING PREVALENCE.
MAIN comparison: recall at MATCHED false alarms: for every (pool, k, seed) the BN's false-alarm count (threshold .5) is taken as the budget and each
model's threshold is moved so it admits exactly that many false alarms (ties split proportionally); compare with the BN's recall at .5. Also reported: recall
at 0 false alarms, AUC, and each variant's native (FA, recall). CIs: 95% bootstrap over seeds; paired differences use the same seeds.
Caveats: out-of-fold scores from 10 different fold models are pooled per seed; the BN posterior is nearly binary (few distinct values), so its own ROC
cannot trade recall for fewer false alarms; recall resolution is 1/|pool| (1/9 on verified M); CIs cover subsampling variance only.
Raw per-seed results: reports/cjsj_20_fair_lc.csv."""
from cjsj_common import ensure_omp
ensure_omp()
import time
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from cjsj_common import REPORTS, TAG_CONFOUNDED, write_section
import cjsj_eval as E
import cjsj_lcs as S

POOLS = {"verified M (9)": [2, 3, 4, 6, 9], "all 24": [2, 3, 4, 6, 10, 20]}
WHICH = ["BN", "RF", "RFb", "XGBu", "XGB"]
NAME = {"RF": "RF unweighted", "RFb": "RF balanced", "XGBu": "XGB spw=1", "XGB": "XGB spw=neg/pos"}
FS = S.FEATSETS["all features (baseline)"]


def task(df, pool, k, seed):
    r = S.protocol_scores(df, pool, FS, WHICH, n_sub=k, seed=1000 * k + seed)
    fa_bn = int((r["neg"]["BN"] >= .5).sum()); rows = []
    for m in WHICH:
        n, p = r["neg"][m], r["pos"][m]
        row = dict(k=k, seed=seed, model=m, auc=S.auc(n, p), fa_bn=fa_bn, rec_fa0=S.recall_at_fa(n, p, 0), rec_matched=S.recall_at_fa(n, p, fa_bn))
        fa5, rc5 = S.at_thr(n, p, .5, .5); row.update(fa_05=fa5, rec_05=rc5)
        fap, rcp = float((n >= r["neg_pi"]).sum()), float((p >= r["pos_pi"]).mean()); row.update(fa_pi=fap, rec_pi=rcp)
        rows.append(row)
    return rows


def bm(v, B=2000, seed=0):
    v = np.asarray(v, float); rng = np.random.default_rng(seed); b = [rng.choice(v, len(v)).mean() for _ in range(B)]
    return v.mean(), *np.percentile(b, [2.5, 97.5])


def bdiff(a, b, B=2000, seed=0):
    d = np.asarray(a, float) - np.asarray(b, float); rng = np.random.default_rng(seed); bs = [rng.choice(d, len(d)).mean() for _ in range(B)]
    return d.mean(), *np.percentile(bs, [2.5, 97.5])


def main():
    t0 = time.time(); base = E.load_base(); sets = E.positive_sets(base); rows = []
    import os
    csv = REPORTS / "cjsj_20_fair_lc.csv"
    for pname, ks in ({} if (os.environ.get("CJSJ_FROM_CSV") and csv.exists()) else POOLS).items():
        pool = sets["verified M (9)"] if pname.startswith("verified") else sets["all 24 (audit baseline)"]; df = E.subset(base, pool)
        res = Parallel(n_jobs=8)(delayed(task)(df, pool, k, s) for k in ks for s in range(30))
        for rr in res:
            for r in rr: rows.append(dict(pool=pname, **r))
        print(pname, "done", f"{time.time() - t0:.0f}s", flush=True)
    R = pd.read_csv(csv) if (os.environ.get("CJSJ_FROM_CSV") and csv.exists()) else pd.DataFrame(rows)
    R.to_csv(csv, index=False)
    L = []; Q = L.append; f2 = lambda t: f"{t[0]:.2f} [{t[1]:.2f}, {t[2]:.2f}]"; fd = lambda t: f"{t[0]:+.2f} [{t[1]:+.2f}, {t[2]:+.2f}]"
    Q("Protocol: `cjsj_lcs.py`, all-feature models (as in item 12), 30 seeds. 'Matched FA' = each model's threshold moved so it admits the same number of false alarms as the BN did in that seed (BN at .5).")
    Q("")
    surv = {}
    for pname, ks in POOLS.items():
        Q(f"#### 20a. Recall at matched false alarms, pool = {pname}"); Q("")
        Q("| k | BN FA (mean) | BN recall (own .5) | " + " | ".join(f"{NAME[m]}: recall at matched FA [CI]" for m in NAME) + " |"); Q("|---|---|---|" + "---|" * len(NAME))
        for k in ks:
            b = R[(R.pool == pname) & (R.k == k) & (R.model == "BN")].sort_values("seed")
            cells = []
            for m in NAME:
                d = R[(R.pool == pname) & (R.k == k) & (R.model == m)].sort_values("seed"); cells.append(f2(bm(d.rec_matched)))
            Q(f"| {k} | {b.fa_bn.mean():.1f} | {f2(bm(b.rec_05))} | " + " | ".join(cells) + " |")
        Q("")
        Q(f"#### 20b. Paired difference, BN recall (.5) minus model recall at matched FA (positive = BN advantage survives), pool = {pname}"); Q("")
        Q("| k | " + " | ".join(NAME[m] for m in NAME) + " |"); Q("|---|" + "---|" * len(NAME))
        for k in ks:
            b = R[(R.pool == pname) & (R.k == k) & (R.model == "BN")].sort_values("seed"); cells = []
            for m in NAME:
                d = R[(R.pool == pname) & (R.k == k) & (R.model == m)].sort_values("seed"); t = bdiff(b.rec_05.values, d.rec_matched.values)
                deg = d.auc.mean() < 0.5; surv[(pname, k, m)] = t + (deg,)
                cells.append("n/a (degenerate model)" if deg else fd(t) + (" *" if t[1] > 0 else ""))
            Q(f"| {k} | " + " | ".join(cells) + " |")
        Q("")
        Q("`*` = 95% CI excludes 0 in the BN's favour. 'degenerate' = the model's out-of-fold AUC is below 0.5 (XGB with unweighted loss and 2 training positives outputs a near-constant score whose base rate differs between the folds that score negatives and positives, so pooled scores rank positives below negatives; the cell carries no information).")
        Q("")
        Q(f"#### 20c. Native operating points and AUC, pool = {pname} (false alarms of 138 / recall; AUC of the out-of-fold scores)"); Q("")
        Q("| k | model | AUC | at .5: FA / recall | at training prevalence: FA / recall | recall at 0 FA |"); Q("|---|---|---|---|---|---|")
        for k in ks:
            for m in WHICH:
                d = R[(R.pool == pname) & (R.k == k) & (R.model == m)]
                Q(f"| {k} | {NAME.get(m, 'BN')} | {d.auc.mean():.3f} | {d.fa_05.mean():.1f} / {d.rec_05.mean():.2f} | {d.fa_pi.mean():.1f} / {d.rec_pi.mean():.2f} | {d.rec_fa0.mean():.2f} |")
        Q("")
    # verdict
    Q("#### 20d. Verdict (computed)"); Q("")
    for pname, ks in POOLS.items():
        small = [k for k in ks if 2 <= k <= 4]
        for m in NAME:
            ok = [k for k in small if (not surv[(pname, k, m)][3]) and surv[(pname, k, m)][1] > 0]; dg = [k for k in small if surv[(pname, k, m)][3]]
            gain = ", ".join(f"k={k}: {surv[(pname, k, m)][0]:+.2f}" for k in small if not surv[(pname, k, m)][3])
            Q(f"- {pname}, {NAME[m]}: BN advantage at matched FA has CI>0 at k in {ok if ok else 'none'} of {small} (mean differences {gain}{'; degenerate at k=' + str(dg) if dg else ''}); at k={ks[-1]} {surv[(pname, ks[-1], m)][0]:+.2f}.")
    Q("")
    for pname, ks in POOLS.items():
        f0 = {m: R[(R.pool == pname) & (R.k.isin([k for k in ks if k <= 4])) & (R.model == m)].rec_fa0.mean() for m in WHICH}
        fp = {m: R[(R.pool == pname) & (R.k.isin([k for k in ks if k <= 4])) & (R.model == m)].fa_pi.mean() for m in WHICH}
        Q(f"- {pname}, k<=4 averaged: recall at ZERO false alarms: " + ", ".join(f"{NAME.get(m, 'BN')} {f0[m]:.2f}" for m in WHICH) + f" (the BN cannot go below its ~2-4 false alarms by thresholding: its own recall at 0 FA is {f0['BN']:.2f}). "
          f"False alarms at the training-prevalence threshold (of 138): " + ", ".join(f"{NAME.get(m, 'BN')} {fp[m]:.1f}" for m in WHICH) + ".")
    Q("")
    Q(f"(runtime {time.time() - t0:.0f}s; cjsj_20_fair_lc.py)")
    body = "\n".join(L); print(body)
    write_section("cjsj_20_fair_lc.py", "20", "Fairness check on the learning curve: matched-false-alarm recall", TAG_CONFOUNDED + " (verified-M pool rows: verified labels, negatives unchanged)", body)


if __name__ == "__main__":
    main()
