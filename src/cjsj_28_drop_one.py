"""CJSJ item 28: which ETH-context feature drives the forward-time false-alarm bursts? Drop ONE ETH-context feature at a time and rerun forward-time false alarms
for RF (150 trees, mean of 5 seeds) and XGBoost (fixed config, deterministic). ETH-context features: heartbeat_elapsed, congestion, ref_realized_vol, temporal_deviation_persistence,
temporal_slope, temporal_step_change_count, temporal_gap_trend. NOTE: the audit's 8-feature set (ALW) does not contain `congestion`, so the drop-one experiment starts from
ALW + congestion (9 features) and ALW itself is shown for reference. Also 'venue + ONE ETH feature only' (sufficiency) and grouped drops.
Forward protocol (audit): train on incidents before each of the 7 cutoffs, test on incidents at/after; evaluable if train positives >= 3 and test positives >= 2; two training positive sets:
all 24 attacks (where RF/XGB bursts are largest) and verified M (9). Reported: false alarms on volatility test incidents summed over cutoffs, manipulations caught, share of the
full-feature false alarms removed. Drift of each ETH-context feature within the volatility class (pre- vs post-2024, Mann-Whitney) is included to test the expectation that the drifting
feature (heartbeat_elapsed, p=8e-7 in the audit) carries the bursts. Raw results: reports/cjsj_28_drop_one.csv."""
from cjsj_common import ensure_omp
ensure_omp()
import time
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from scipy.stats import mannwhitneyu
from cjsj_common import REPORTS, TAG_CONFOUNDED, write_section
import cjsj_eval as E
import cjsj_lcs as S

ETH7 = ["heartbeat_elapsed", "congestion", "ref_realized_vol", "temporal_deviation_persistence", "temporal_slope", "temporal_step_change_count", "temporal_gap_trend"]
VEN = ["reserve_skew", "reserve_skew_localization"]; BASE9 = VEN + ETH7; TEMP4 = [c for c in ETH7 if c.startswith("temporal_")]
CONFIGS = {"ALW (audit 8 features, no congestion)": E.ALW, "all 9 (ALW + congestion)": BASE9}
for f in ETH7: CONFIGS[f"drop {f}"] = [c for c in BASE9 if c != f]
CONFIGS["drop all 4 temporal_*"] = [c for c in BASE9 if c not in TEMP4]
CONFIGS["drop heartbeat + congestion + ref_realized_vol"] = [c for c in BASE9 if c not in ("heartbeat_elapsed", "congestion", "ref_realized_vol")]
for f in ETH7: CONFIGS[f"venue + {f} only"] = VEN + [f]
CONFIGS["venue only (no ETH-context)"] = VEN
SEEDS = range(5)


def run(base, pos_inc, name):
    cols = CONFIGS[name]; out = []
    for c in E.CUTOFFS:
        cc = pd.Timestamp(c); ptr = int(base.incident.isin(pos_inc)[(base.dt < cc)].sum()); pte = int((base.incident.isin(pos_inc) & (base.dt >= cc)).sum())
        if ptr < 3 or pte < 2: continue
        neg = np.where((base.dt < cc) & (base.label == E.VOL))[0]; pos = np.where((base.dt < cc) & base.incident.isin(pos_inc))[0]
        te = np.where(base.dt >= cc)[0]; tr = np.concatenate([neg, pos])
        isneg = base.label.values[te] == E.VOL; ismp = (~isneg) & base.incident.isin(pos_inc).values[te]
        rf = [E.rf_proba(base, tr, te, cols=cols, n_est=150, seed=s) for s in SEEDS]
        xg = S.xgb_scores(base, tr, te, cols, True)
        out.append(dict(cut=c, rf_fa=np.mean([(p[isneg] >= .5).sum() for p in rf]), rf_caught=np.mean([(p[ismp] >= .5).sum() for p in rf]),
                        xgb_fa=int((xg[isneg] >= .5).sum()), xgb_caught=int((xg[ismp] >= .5).sum()), n_pos_test=int(ismp.sum()), n_neg_test=int(isneg.sum())))
    return name, out


def main():
    t0 = time.time(); base = E.load_base(); sets = E.positive_sets(base); rows = []
    trainings = {"all 24": sets["all 24 (audit baseline)"], "verified M (9)": sets["verified M (9)"]}
    res = Parallel(n_jobs=8)(delayed(run)(base, pos, n) for tn, pos in trainings.items() for n in CONFIGS)
    it = iter(res)
    for tn in trainings:
        for n in CONFIGS:
            name, out = next(it)
            for o in out: rows.append(dict(training=tn, config=name, **o))
    R = pd.DataFrame(rows); R.to_csv(REPORTS / "cjsj_28_drop_one.csv", index=False)
    L = []; Q = L.append
    # drift table
    Q("#### 28a. Drift of each ETH-context feature within the volatility class (before vs from 2024-01; Mann-Whitney)"); Q("")
    v = base[base.label == E.VOL]; a = v[v.dt < "2024-01-01"]; b = v[v.dt >= "2024-01-01"]
    Q("| Feature | median before 2024 | median from 2024 | Mann-Whitney p | n before / after |"); Q("|---|---|---|---|---|")
    drift = {}
    for f in ETH7:
        x, y = a[f].dropna(), b[f].dropna(); p = mannwhitneyu(x, y).pvalue if len(x) and len(y) else np.nan; drift[f] = p
        Q(f"| {f} | {x.median():.4g} | {y.median():.4g} | {p:.2g} | {len(x)} / {len(y)} |")
    Q("")
    cfg_order = list(CONFIGS); summ = {}
    for tn in trainings:
        Q(f"#### 28b. Forward-time false alarms summed over the evaluable cutoffs, training positives: {tn}"); Q("")
        Q("| Configuration | n features | RF false alarms (mean of 5 seeds) | RF caught | XGB false alarms | XGB caught | RF: share of full-feature FA removed | XGB: share removed |"); Q("|---|---|---|---|---|---|---|---|")
        ref = R[(R.training == tn) & (R.config == "all 9 (ALW + congestion)")]; rf0, xg0 = ref.rf_fa.sum(), ref.xgb_fa.sum()
        for n in cfg_order:
            d = R[(R.training == tn) & (R.config == n)]
            summ[(tn, n)] = (d.rf_fa.sum(), d.xgb_fa.sum(), d.rf_caught.sum(), d.xgb_caught.sum())
            Q(f"| {n} | {len(CONFIGS[n])} | {d.rf_fa.sum():.1f} | {d.rf_caught.sum():.1f}/{d.n_pos_test.sum()} | {d.xgb_fa.sum()} | {d.xgb_caught.sum()}/{d.n_pos_test.sum()} | "
              f"{(rf0 - d.rf_fa.sum()) / rf0 if rf0 else float('nan'):+.0%} | {(xg0 - d.xgb_fa.sum()) / xg0 if xg0 else float('nan'):+.0%} |")
        Q("")
    # verdict
    Q("#### 28c. Verdict (computed)"); Q("")
    drops = [f"drop {f}" for f in ETH7]; only = [f"venue + {f} only" for f in ETH7]; top_cnt = 0; cells = 0
    for tn in trainings:
        for mi, mname in [(0, "RF"), (1, "XGB")]:
            base_fa = summ[(tn, "all 9 (ALW + congestion)")][mi]
            if base_fa < 5: Q(f"- {tn}, {mname}: full-feature false alarms are only {base_fa:.1f}; no burst to attribute."); continue
            rem = {n: (base_fa - summ[(tn, n)][mi]) / base_fa for n in drops}; best = max(rem, key=rem.get); cells += 1; top_cnt += best == "drop heartbeat_elapsed"
            suf = {n: summ[(tn, n)][mi] for n in only}; bests = min(suf, key=suf.get); worsts = max(suf, key=suf.get)
            Q(f"- {tn}, {mname}: full-feature false alarms {base_fa:.1f}. Single drop removing most: **{best[5:]}** ({rem[best]:+.0%}); heartbeat_elapsed drop {rem['drop heartbeat_elapsed']:+.0%}, ref_realized_vol {rem['drop ref_realized_vol']:+.0%}, congestion {rem['drop congestion']:+.0%}, temporal (each) "
              f"{', '.join(f'{f[9:]} {rem[f'drop {f}']:+.0%}' for f in TEMP4)}. Venue + ONE ETH feature (false alarms): " + ", ".join(f"{f[8:-5]} {suf[f]:.1f}" for f in only) + f"; venue only {summ[(tn, 'venue only (no ETH-context)')][mi]:.1f}. Drop all 4 temporal {(base_fa - summ[(tn, 'drop all 4 temporal_*')][mi]) / base_fa:+.0%}; drop heartbeat+congestion+ref_vol {(base_fa - summ[(tn, 'drop heartbeat + congestion + ref_realized_vol')][mi]) / base_fa:+.0%}.")
    Q("")
    Q(f"heartbeat_elapsed is the single most effective drop in {top_cnt} of {cells} model x training cells that have a burst. Drift p-values: " + ", ".join(f"{f} {drift[f]:.2g}" for f in ETH7) + ".")
    Q("")
    Q(f"(runtime {time.time() - t0:.0f}s; cjsj_28_drop_one.py)")
    body = "\n".join(L); print(body)
    write_section("cjsj_28_drop_one.py", "28", "Which ETH-context feature drives the forward-time false-alarm bursts (drop one at a time)", TAG_CONFOUNDED + " (verified-M training rows: verified labels, negatives unchanged)", body)


if __name__ == "__main__":
    main()
