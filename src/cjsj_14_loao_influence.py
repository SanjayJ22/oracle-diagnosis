"""CJSJ item 14: leave-one-attack-out (LOAO) influence on RF and XGBoost false alarms, generalizing item 8 to all 24 attacks.

14a forward-time: for each cutoff (the 7 audit cutoffs plus 2025-10, 2026-03, 2026-07 so that late attacks enter a training set), train on all
    pre-cutoff volatility incidents + all pre-cutoff attacks, test on volatility incidents at/after the cutoff (false alarms only). Then drop each
    training attack in turn. RF: 300 trees, mean of 5 seeds. XGB: nested-tuned (cjsj_03) - deterministic. Influence = change in false alarms after
    dropping the attack (negative = the attack was causing false alarms). Test negatives shrink at late cutoffs (2025-10: 22, 2026-03: 9,
    2026-07: 3), so late-cutoff changes are noisy and are shown but weighted equally only in the mean.
14b static (covers attacks that are only ever test attacks in 14a): 10-fold over the 138 negatives, all other 23 attacks + training negatives,
    RF 150 trees (5 seeds of fold assignment) and XGB fixed config (cjsj_lc.py); false alarms out of 138, drop one attack at a time.
Ranking: mean forward ΔFA (RF and XGB), most negative first; attacks never in a forward training set are marked n/a in 14a.
Raw per-(cutoff, attack) results: reports/cjsj_14_loao_forward.csv."""
from cjsj_common import ensure_omp
ensure_omp()
import time
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from cjsj_common import REPORTS, TAG_CONFOUNDED, write_section
import cjsj_eval as E
import cjsj_lc as LC
import cjsj_03_xgb_heuristics as X3

CUTS = E.CUTOFFS + ["2025-10-01", "2026-03-01", "2026-07-01"]
SEEDS = range(5)


def fa_pair(base, pos, cut):
    c = pd.Timestamp(cut)
    tr = np.where((base.dt < c) & ((base.label == E.VOL) | base.incident.isin(pos)))[0]
    te = np.where((base.dt >= c) & (base.label == E.VOL))[0]
    rf = np.mean([(E.rf_proba(base, tr, te, n_est=300, seed=s) >= .5).sum() for s in SEEDS])
    xg = int((X3.xgb_nested(base, tr, te)[0] >= .5).sum())
    return float(rf), xg, len(te)


def fwd_job(base, allpos, cut, drop):
    pos = [p for p in allpos if p != drop]
    rf, xg, nte = fa_pair(base, pos, cut); return cut, drop, rf, xg, nte


def static_job(base, pos, drop, seed):
    d = E.subset(base, [p for p in pos if p != drop]).reset_index(drop=True)
    rng = np.random.default_rng(seed); neg = np.where(d.label.values == E.VOL)[0]; ps = np.where(d.label.values == E.MAN)[0]
    rf = xg = 0
    for fold in np.array_split(rng.permutation(neg), 10):
        tr = np.concatenate([np.setdiff1d(neg, fold), ps])
        rf += int((E.rf_proba(d, tr, fold, n_est=150) >= .5).sum()); xg += int((LC.xgb_fixed(d, tr, fold) >= .5).sum())
    return drop, seed, rf, xg


def main():
    t0 = time.time(); base = E.load_base(); sh = E.label_sheet().set_index("incident_id"); allpos = list(sh.index)
    ver = set(sh.index[sh.verified_M]); dts = base.set_index("incident").dt
    jobs = []
    for c in CUTS:
        cp = [p for p in allpos if dts[p] < pd.Timestamp(c)]
        jobs.append((base, cp, c, None)); jobs += [(base, cp, c, a) for a in cp]
    res = Parallel(n_jobs=8)(delayed(fwd_job)(*j) for j in jobs)
    F = pd.DataFrame(res, columns=["cut", "drop", "rf_fa", "xgb_fa", "n_test_neg"])
    basef = F[F["drop"].isna()].set_index("cut"); D = F[F["drop"].notna()].copy()
    D["d_rf"] = D.apply(lambda r: r.rf_fa - basef.rf_fa[r.cut], axis=1); D["d_xgb"] = D.apply(lambda r: r.xgb_fa - basef.xgb_fa[r.cut], axis=1)
    D.to_csv(REPORTS / "cjsj_14_loao_forward.csv", index=False)
    sres = Parallel(n_jobs=8)(delayed(static_job)(base, allpos, a, s) for a in [None] + allpos for s in SEEDS)
    S = pd.DataFrame(sres, columns=["drop", "seed", "rf", "xgb"]); S["drop"] = S["drop"].fillna("(none)")
    sm = S.groupby("drop")[["rf", "xgb"]].mean(); sb = sm.loc["(none)"]
    L = []; Q = L.append
    Q("#### 14a. Baseline false alarms by cutoff (all attacks in training) and number of test volatility incidents"); Q("")
    Q("| Cutoff | train attacks | test volatility n | RF FA (5-seed mean) | XGB FA (nested) |"); Q("|---|---|---|---|---|")
    for c in CUTS:
        ntr = sum(dts[p] < pd.Timestamp(c) for p in allpos); b = basef.loc[c]
        Q(f"| {c[:7]} | {ntr} | {int(b.n_test_neg)} | {b.rf_fa:.1f} | {int(b.xgb_fa)} |")
    Q("")
    rows = []
    for a in allpos:
        d = D[D["drop"] == a]
        rows.append(dict(attack=a, a2cat=sh.category[a], ver="yes" if a in ver else "no", ncut=len(d),
                         rf_mean=d.d_rf.mean() if len(d) else np.nan, rf_min=d.d_rf.min() if len(d) else np.nan, xgb_mean=d.d_xgb.mean() if len(d) else np.nan,
                         xgb_min=d.d_xgb.min() if len(d) else np.nan, s_rf=sm.rf[a] - sb.rf, s_xgb=sm.xgb[a] - sb.xgb))
    T = pd.DataFrame(rows)
    T["rank_rf"] = T.rf_mean.rank(method="min"); T["rank_xgb"] = T.xgb_mean.rank(method="min"); T["rank_comb"] = ((T.rank_rf + T.rank_xgb) / 2).rank(method="min")
    T = T.sort_values(["rank_comb", "attack"])
    Q("#### 14b. Influence ranking (dropping the attack changes false alarms by ΔFA; negative = the attack was causing false alarms)"); Q("")
    Q("Forward columns average ΔFA over the cutoffs where the attack is in the training set (n cutoffs shown) and give the most negative single-cutoff change; static columns are ΔFA of 10-fold held-out negatives (out of 138) relative to the no-drop baseline "
      f"(RF {sb.rf:.1f}, XGB {sb.xgb:.1f} false alarms).")
    Q("")
    Q("| Rank | Attack | A2 cat | verified M | n cutoffs | RF mean ΔFA (min) | XGB mean ΔFA (min) | static RF ΔFA | static XGB ΔFA |"); Q("|---|---|---|---|---|---|---|---|---|")
    for _, r in T.iterrows():
        fr = lambda m, mn: "n/a" if r.ncut == 0 else f"{m:+.2f} ({mn:+.1f})"
        Q(f"| {'n/a' if np.isnan(r.rank_comb) else int(r.rank_comb)} | {r.attack} | {r.a2cat} | {r.ver} | {r.ncut} | {fr(r.rf_mean, r.rf_min)} | {fr(r.xgb_mean, r.xgb_min)} | {r.s_rf:+.2f} | {r.s_xgb:+.2f} |")
    Q("")
    top = T[T.ncut > 0].sort_values("rf_mean").head(5)
    Q("Computed summary:")
    Q("")
    Q("- Most false-alarm-inducing attacks by forward RF ΔFA: " + "; ".join(f"{r.attack} [{r.a2cat}{', verified M' if r.ver == 'yes' else ''}] {r.rf_mean:+.2f}" for _, r in top.iterrows()) + ".")
    topx = T[T.ncut > 0].sort_values("xgb_mean").head(5)
    Q("- By forward XGB ΔFA: " + "; ".join(f"{r.attack} [{r.a2cat}{', verified M' if r.ver == 'yes' else ''}] {r.xgb_mean:+.2f}" for _, r in topx.iterrows()) + ".")
    ev = T[T.ncut > 0]
    Q(f"- Attacks with mean forward ΔFA <= -1 (RF): {int((ev.rf_mean <= -1).sum())} of {len(ev)} evaluable; (XGB): {int((ev.xgb_mean <= -1).sum())}; of the RF ones, verified M: {int(((ev.rf_mean <= -1) & (ev.ver == 'yes')).sum())}, non-verified: {int(((ev.rf_mean <= -1) & (ev.ver == 'no')).sum())}.")
    Q(f"- Not evaluable in the forward design (never in a training set at cutoffs up to 2026-07): {', '.join(T[T.ncut == 0].attack)}. Static influence, all 24: max |ΔFA| RF {T.s_rf.abs().max():.2f}, XGB {T.s_xgb.abs().max():.2f} of 138.")
    Q("")
    Q(f"(runtime {time.time() - t0:.0f}s; cjsj_14_loao_influence.py)")
    body = "\n".join(L); print(body)
    write_section("cjsj_14_loao_influence.py", "14", "Leave-one-attack-out influence on forward-time RF/XGBoost false alarms (all 24 attacks)", TAG_CONFOUNDED, body)


if __name__ == "__main__":
    main()
