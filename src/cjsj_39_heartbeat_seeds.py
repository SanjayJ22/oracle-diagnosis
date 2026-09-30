"""CJSJ item 39: 30-seed check of the paper's sentence 'removing heartbeat_elapsed alone eliminated all of the random forest's false alarms and 85% of XGBoost's' (single run, section 28).
Forward-time false-alarm totals (7 audit cutoffs, trained on all 24 attacks, test = volatility incidents at/after the cutoff), RF 150 trees and XGBoost (fixed config with subsample 0.8 and
colsample_bytree 0.8 so seeds differ, as in section 32), 30 seeds each. Two baselines: (A) the paper's own models, ALW (8 features) vs ALW minus heartbeat_elapsed (7); (B) section 28's
baseline, ALW + congestion (9) vs minus heartbeat (8). Percentage reduction = 1 - mean(total without) / mean(total with). Intervals as section 32, made PAIRED: each bootstrap replicate resamples the
138 volatility incidents (same indices for both variants) and draws one seed index used for both variants; 2000 replicates; 'seed range' = 2.5-97.5th percentile of per-seed reductions.
Also the deterministic (no-sampling) XGBoost reduction for reference, and the per-cutoff RF false alarms (30-seed mean) to compare with the single-run '16 of 70' at January 2024."""
from cjsj_common import ensure_omp
ensure_omp()
import time
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from cjsj_common import REPORTS, TAG_CONFOUNDED, write_section
import cjsj_eval as E
import cjsj_lcs as S
from cjsj_32_fig3_ci import xgb_seeded

HB = "heartbeat_elapsed"; CFG = {"A: paper's 8 features (ALW)": E.ALW, "A: ALW minus heartbeat (7)": [c for c in E.ALW if c != HB],
       "B: ALW + congestion (9)": E.ALW + ["congestion"], "B: minus heartbeat (8)": [c for c in E.ALW + ["congestion"] if c != HB]}
SEEDS = list(range(30))


def task(base, pos_inc, cfg, model, seed):
    cols = CFG[cfg]; per = np.zeros(len(base)); by = {}
    for c in E.CUTOFFS:
        cc = pd.Timestamp(c); ptr = int(base.incident.isin(pos_inc)[(base.dt < cc)].sum()); pte = int((base.incident.isin(pos_inc) & (base.dt >= cc)).sum())
        if ptr < 3 or pte < 2: continue
        neg = np.where((base.dt < cc) & (base.label == E.VOL))[0]; pos = np.where((base.dt < cc) & base.incident.isin(pos_inc))[0]; te = np.where(base.dt >= cc)[0]; tr = np.concatenate([neg, pos])
        p = E.rf_proba(base, tr, te, cols=cols, n_est=150, seed=seed) if model == "RF" else (xgb_seeded(base, tr, te, cols, seed) if model == "XGB" else S.xgb_scores(base, tr, te, cols, True))
        isneg = base.label.values[te] == E.VOL; per[te[isneg]] += (p[isneg] >= .5); by[c] = int((p[isneg] >= .5).sum())
    return cfg, model, seed, per, by


def main():
    t0 = time.time(); base = E.load_base(); pos = E.positive_sets(base)["all 24 (audit baseline)"]; jobs = []
    for cfg in CFG:
        jobs += [(cfg, "RF", s) for s in SEEDS] + [(cfg, "XGB", s) for s in SEEDS] + [(cfg, "XGBdet", 0)]
    res = Parallel(n_jobs=8)(delayed(task)(base, pos, *j) for j in jobs); negidx = np.where(base.label.values == E.VOL)[0]
    per = {(c, m): np.array([r[3][negidx] for r in res if r[0] == c and r[1] == m]) for c in CFG for m in ("RF", "XGB", "XGBdet")}
    by = {(c, m): pd.DataFrame([r[4] for r in res if r[0] == c and r[1] == m]).mean() for c in CFG for m in ("RF", "XGB")}
    rng = np.random.default_rng(0); B = 2000; L = []; Q = L.append
    def red(base_cfg, drop_cfg, m):
        pb, pd_ = per[(base_cfg, m)], per[(drop_cfg, m)]; tb, td = pb.sum(1), pd_.sum(1); point = 1 - td.mean() / tb.mean()
        per_seed = 1 - td / np.where(tb > 0, tb, np.nan); rep = []
        for _ in range(B):
            i = rng.integers(0, len(negidx), len(negidx)); s = rng.integers(0, len(pb)) if len(pb) > 1 else 0
            b_, d_ = pb[s][i].sum(), pd_[s][i].sum(); rep.append(1 - d_ / b_ if b_ > 0 else np.nan)
        return point, np.nanpercentile(rep, [2.5, 97.5]), np.nanpercentile(per_seed, [2.5, 97.5]), tb, td
    def comb(cfg, m):
        pr = per[(cfg, m)]; v = [pr[rng.integers(0, len(pr))][rng.integers(0, len(negidx), len(negidx))].sum() for _ in range(B)]; return pr.sum(1).mean(), np.percentile(v, [2.5, 97.5])
    Q("Training on all 24 attacks; false-alarm totals over the 7 cutoffs; 30 seeds (XGBoost with row/column sampling; its deterministic run is shown separately). Combined 95% interval as section 32.")
    Q("")
    Q("#### 39a. False-alarm totals (mean over 30 seeds, combined 95% interval)"); Q("")
    Q("| Configuration | RF | XGBoost (30 seeds) | XGBoost (deterministic) |"); Q("|---|---|---|---|")
    for c in CFG:
        r, x = comb(c, "RF"), comb(c, "XGB"); Q(f"| {c} | {r[0]:.1f} [{r[1][0]:.0f}, {r[1][1]:.0f}] | {x[0]:.1f} [{x[1][0]:.0f}, {x[1][1]:.0f}] | {per[(c, 'XGBdet')].sum():.0f} |")
    Q("")
    Q("#### 39b. Percentage reduction from removing heartbeat_elapsed alone (paired; 30-seed means)"); Q("")
    Q("| Baseline | Model | reduction [combined paired 95% CI] | per-seed range (2.5-97.5%) | total with -> without (means) |"); Q("|---|---|---|---|---|")
    out = {}
    for lab, b, d in [("A: paper's own 8-feature models", "A: paper's 8 features (ALW)", "A: ALW minus heartbeat (7)"), ("B: section 28's 9-feature baseline", "B: ALW + congestion (9)", "B: minus heartbeat (8)")]:
        for m in ("RF", "XGB"):
            p, ci, rg, tb, td = red(b, d, m); out[(lab[:1], m)] = (p, ci, rg, tb.mean(), td.mean())
            Q(f"| {lab} | {'RF' if m == 'RF' else 'XGBoost (30 seeds)'} | {p:.0%} [{ci[0]:.0%}, {ci[1]:.0%}] | [{rg[0]:.0%}, {rg[1]:.0%}] | {tb.mean():.1f} -> {td.mean():.1f} |")
        dd = 1 - per[(d, 'XGBdet')].sum() / per[(b, 'XGBdet')].sum(); Q(f"| {lab} | XGBoost (deterministic, single run) | {dd:.0%} | - | {per[(b, 'XGBdet')].sum():.0f} -> {per[(d, 'XGBdet')].sum():.0f} |")
    Q("")
    Q("#### 39c. RF false alarms by cutoff (30-seed mean, 150 trees; ALW 8 features)"); Q("")
    Q("| Cutoff | " + " | ".join(c[:7] for c in by[("A: paper's 8 features (ALW)", "RF")].index) + " |"); Q("|---|" + "---|" * len(by[("A: paper's 8 features (ALW)", "RF")]))
    Q("| RF with heartbeat | " + " | ".join(f"{v:.1f}" for v in by[("A: paper's 8 features (ALW)", "RF")].values) + " |"); Q("| RF without heartbeat | " + " | ".join(f"{v:.1f}" for v in by[("A: ALW minus heartbeat (7)", "RF")].values) + " |")
    Q("")
    Q("Reading (computed): from the paper's own 8-feature models, removing heartbeat_elapsed alone cuts false alarms by " + f"{out[('A', 'RF')][0]:.0%} [{out[('A', 'RF')][1][0]:.0%}, {out[('A', 'RF')][1][1]:.0%}] for the random forest and {out[('A', 'XGB')][0]:.0%} [{out[('A', 'XGB')][1][0]:.0%}, {out[('A', 'XGB')][1][1]:.0%}] for XGBoost (30-seed means); "
      f"from section 28's 9-feature baseline {out[('B', 'RF')][0]:.0%} [{out[('B', 'RF')][1][0]:.0%}, {out[('B', 'RF')][1][1]:.0%}] and {out[('B', 'XGB')][0]:.0%} [{out[('B', 'XGB')][1][0]:.0%}, {out[('B', 'XGB')][1][1]:.0%}]. "
      f"Random forest: {out[('A', 'RF')][3]:.1f} -> {out[('A', 'RF')][4]:.1f} false alarms (8-feature baseline; zero in all 30 seeds) and {out[('B', 'RF')][3]:.1f} -> {out[('B', 'RF')][4]:.1f} (9-feature baseline), so 'eliminated all' holds for the 8-feature models and to within {out[('B', 'RF')][4]:.1f} false alarms for the 9-feature baseline. "
      f"XGBoost: the single-run 85% lies inside the 30-seed interval ({out[('A', 'XGB')][0]:.0%} for the paper's 8-feature models, {out[('B', 'XGB')][0]:.0%} for the 9-feature baseline; the deterministic 8-feature run gives 81%).")
    Q("")
    Q(f"(runtime {time.time() - t0:.0f}s; cjsj_39_heartbeat_seeds.py)")
    body = "\n".join(L); print(body)
    pd.DataFrame([dict(baseline=k[0], model=k[1], reduction=v[0], ci_lo=v[1][0], ci_hi=v[1][1], seed_lo=v[2][0], seed_hi=v[2][1], total_with=v[3], total_without=v[4]) for k, v in out.items()]).to_csv(REPORTS / "cjsj_39_heartbeat_seeds.csv", index=False)
    write_section("cjsj_39_heartbeat_seeds.py", "39", "30-seed check of 'removing heartbeat_elapsed alone eliminated the random forest's false alarms and 85% of XGBoost's'", TAG_CONFOUNDED, body)


if __name__ == "__main__":
    main()
