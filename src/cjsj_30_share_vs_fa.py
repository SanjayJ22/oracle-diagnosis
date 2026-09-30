"""CJSJ item 30: does reliance on ETH-context features (attribution share) go with failure under shift (forward-time false alarms) across configurations?
One point = (model, feature set, training positives):
  Group A: BN / RF / XGB x the 4 feature sets of item 21 (baseline, venue only, extended, ETH-context only) x training positives {all 24, verified M}  = 24 points
  Group B: RF and XGB x the 19 feature configurations of item 28 (drop-one, venue+one, grouped drops) x 2 training sets (duplicates of Group A column sets removed)
Attribution share: fit on all training rows (negatives + that training set's attacks), explain the training attacks, mean over them of the share of total |attribution|
on ETH-context features (cjsj_attr.py; in-sample, describes what the fitted model uses). Forward-time false alarms: train before each of the 7 audit cutoffs, false alarms on volatility
incidents at/after it, summed over the evaluable cutoffs (Group A: computed here, RF 150 trees seed 0; Group B: from reports/cjsj_28_drop_one.csv, RF mean of 5 seeds).
Statistic: Spearman rank correlation; CI = 95% percentile of 2000 bootstrap resamples of configurations; permutation p from 5000 shuffles. Points are NOT independent (same incidents, same cutoffs,
overlapping feature sets), so the CI and p describe this set of configurations, not a population of independent studies. The ETH-context-only points have share = 1 by construction
and are shown with and without. Raw: reports/cjsj_30_configs.csv."""
from cjsj_common import ensure_omp
ensure_omp()
import time
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from scipy.stats import spearmanr
from cjsj_common import REPORTS, TAG_CONFOUNDED, write_section
import cjsj_eval as E
import cjsj_lcs as S
import cjsj_attr as A
import cjsj_28_drop_one as D28

TRAIN = {"all 24": "all 24 (audit baseline)", "verified M (9)": "verified M (9)"}
SHORT = {"all features (baseline)": "baseline", "no ETH-context, venue only (reserve_skew, localization)": "venue only", "no ETH-context, extended (+price_dev, cross_venue_spread, dex_oracle_spread)": "extended (no ETH)",
         "ETH-context only (6 BN-compatible features)": "ETH-context only"}


def fwd_fa(base, pos_inc, model, fs):
    fa = caught = 0
    for c in E.CUTOFFS:
        cc = pd.Timestamp(c); ptr = int(base.incident.isin(pos_inc)[(base.dt < cc)].sum()); pte = int((base.incident.isin(pos_inc) & (base.dt >= cc)).sum())
        if ptr < 3 or pte < 2: continue
        neg = np.where((base.dt < cc) & (base.label == E.VOL))[0]; pos = np.where((base.dt < cc) & base.incident.isin(pos_inc))[0]; te = np.where(base.dt >= cc)[0]
        P = S.predict_models(base, np.concatenate([neg, pos]), te, fs, [model])[model]
        isneg = base.label.values[te] == E.VOL; ismp = (~isneg) & base.incident.isin(pos_inc).values[te]
        fa += int((P[isneg] >= .5).sum()); caught += int((P[ismp] >= .5).sum())
    return fa, caught


def point(base, pos_inc, model, cols, bn_keep, label, group, tn, fa=None, caught=None, fs=None):
    tr = base[base.label.eq(E.VOL) | base.incident.isin(pos_inc)].reset_index(drop=True); ex = tr[tr.label == E.MAN]
    sh = float(np.nanmean(A.shares(tr, ex, model, cols, bn_keep)))
    if fa is None: fa, caught = fwd_fa(base, pos_inc, model, fs)
    return dict(group=group, training=tn, model=model, config=label, n_features=len(cols), eth_share=sh, fa=fa, caught=caught)


def sp_ci(x, y, B=2000, seed=0):
    x, y = np.asarray(x, float), np.asarray(y, float); r = spearmanr(x, y)[0]; rng = np.random.default_rng(seed); bs = []
    for _ in range(B):
        i = rng.integers(0, len(x), len(x)); v = spearmanr(x[i], y[i])[0]
        if not np.isnan(v): bs.append(v)
    null = [spearmanr(x, rng.permutation(y))[0] for _ in range(5000)]; p = (1 + sum(abs(n) >= abs(r) for n in null)) / 5001
    return r, *np.percentile(bs, [2.5, 97.5]), p


def main():
    t0 = time.time(); base = E.load_base(); sets = E.positive_sets(base); jobs = []; seen = set()
    for tn, key in TRAIN.items():
        pos = sets[key]
        for m in ["BN", "RF", "XGB"]:
            for fsn, fs in S.FEATSETS.items():
                cols = fs["ml"] if m != "BN" else fs["ml"]; jobs.append(("A", base, pos, m, cols, fs["bn"], f"{SHORT[fsn]}", tn, fs))
                seen.add((m, tuple(sorted(fs["ml"])), tn))
    R28 = pd.read_csv(REPORTS / "cjsj_28_drop_one.csv")
    for tn, key in TRAIN.items():
        pos = sets[key]
        for name, cols in D28.CONFIGS.items():
            for m in ["RF", "XGB"]:
                if (m, tuple(sorted(cols)), tn) in seen: continue
                d = R28[(R28.training == ("all 24" if tn == "all 24" else "verified M (9)")) & (R28.config == name)]
                fa = float(d.rf_fa.sum() if m == "RF" else d.xgb_fa.sum()); cg = float(d.rf_caught.sum() if m == "RF" else d.xgb_caught.sum())
                jobs.append(("B", base, pos, m, cols, None, name, tn, None, fa, cg)); seen.add((m, tuple(sorted(cols)), tn))
    def run(j):
        g, b, pos, m, cols, keep, label, tn, fs, *rest = j
        return point(b, pos, m, cols, keep, label, g, tn, *(rest if rest else (None, None)), fs=fs)
    res = Parallel(n_jobs=8)(delayed(run)(j) for j in jobs); P = pd.DataFrame(res); P.to_csv(REPORTS / "cjsj_30_configs.csv", index=False)
    L = []; Q = L.append
    Q(f"{len(P)} configurations ({(P.group == 'A').sum()} in group A, {(P.group == 'B').sum()} in group B). Attribution share and forward-time false alarms as defined in the script docstring.")
    Q("")
    Q("#### 30a. Group A: model x feature set x training positives"); Q("")
    Q("| Training | Model | Feature set | ETH-context share | forward false alarms (sum over cutoffs) | attacks caught |"); Q("|---|---|---|---|---|---|")
    for r in P[P.group == "A"].sort_values(["training", "model", "eth_share"]).itertuples(): Q(f"| {r.training} | {r.model} | {r.config} | {r.eth_share:.0%} | {r.fa:.0f} | {r.caught:.0f} |")
    Q("")
    Q("#### 30b. Spearman correlation between ETH-context share and forward-time false alarms"); Q("")
    Q("| Subset | n configs | Spearman rho [95% CI over configs] | permutation p |"); Q("|---|---|---|---|")
    subs = {"all configurations": P, "excluding ETH-context-only sets (share = 1 by construction)": P[P.config != "ETH-context only"], "RF and XGB only (excl. ETH-only)": P[(P.model != "BN") & (P.config != "ETH-context only")],
            "training: all 24 (excl. ETH-only)": P[(P.training == "all 24") & (P.config != "ETH-context only")], "training: verified M (excl. ETH-only)": P[(P.training == "verified M (9)") & (P.config != "ETH-context only")],
            "RF only (excl. ETH-only)": P[(P.model == "RF") & (P.config != "ETH-context only")], "XGB only (excl. ETH-only)": P[(P.model == "XGB") & (P.config != "ETH-context only")], "group A only": P[P.group == "A"], "group B only": P[P.group == "B"]}
    out = {}
    for k, d in subs.items():
        r, lo, hi, p = sp_ci(d.eth_share, d.fa); out[k] = (r, lo, hi, p, len(d)); Q(f"| {k} | {len(d)} | {r:+.2f} [{lo:+.2f}, {hi:+.2f}] | {p:.4f} |")
    Q("")
    hb = P[P.config.str.contains("heartbeat") & P.config.str.contains("venue \\+")]
    Q("Caveats (computed/structural): (1) the ETH-context-only points (BN share 100% with 0 false alarms because the BN is inert on those features) are the main outliers, hence the with/without rows; (2) share is computed in-sample on the training attacks; (3) within a training set the forward cutoffs and test incidents are identical for every configuration, but configurations share data and feature sets, so the interval understates uncertainty; (4) item 28 showed one feature, heartbeat_elapsed, produces nearly all the false alarms, so the correlation is partly a proxy for whether that one feature is in the model, not an effect of ETH-context reliance in general.")
    Q("")
    Q(f"Headline (excluding ETH-context-only sets): Spearman rho = {out['excluding ETH-context-only sets (share = 1 by construction)'][0]:+.2f} [{out['excluding ETH-context-only sets (share = 1 by construction)'][1]:+.2f}, {out['excluding ETH-context-only sets (share = 1 by construction)'][2]:+.2f}] over {out['excluding ETH-context-only sets (share = 1 by construction)'][4]} configurations; including them rho = {out['all configurations'][0]:+.2f} [{out['all configurations'][1]:+.2f}, {out['all configurations'][2]:+.2f}].")
    Q("")
    Q(f"(runtime {time.time() - t0:.0f}s; cjsj_30_share_vs_fa.py)")
    body = "\n".join(L); print(body)
    write_section("cjsj_30_share_vs_fa.py", "30", "ETH-context attribution share vs forward-time false alarms across configurations", TAG_CONFOUNDED + " (verified-M training points: verified labels, negatives unchanged)", body)


if __name__ == "__main__":
    main()
