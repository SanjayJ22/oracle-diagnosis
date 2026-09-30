"""CJSJ item 45: method-agnostic attribution by permutation importance, directly comparable (same quantity: share of a model's attribution that falls on market-context features) with section 29.
Protocol (per label set: all 24 + 138 volatility = 162 rows, verified 9 + 138 = 147 rows): LOOCV. For each held-out row i the model is fit on the other rows; its baseline prediction p0[i] is the LOOCV prediction.
Permuted prediction: in row i the feature GROUP is replaced JOINTLY (all of the group's columns or nodes together, so within-group structure is kept) by the values of a donor row j != i drawn from the data, and the same
fold model predicts. 200 random donor assignments (each a permutation of rows without fixed points, same assignments for every model and group), giving 200 permuted LOOCV prediction vectors per model and group.
Drop = change in metric versus the unpermuted LOOCV predictions, averaged over the 200 permutations: AUC drop = AUC(p0) - mean AUC(permuted); log-loss drop = mean log-loss(permuted) - log-loss(p0)
(probabilities clipped to [0.001, 0.999] before the log). Missing values travel with the donor (a donor row with missing values leaves the recipient missing; RF/LR-style median imputation is applied inside the model as at training).
Groups: market-context = the features of section 29's ETH-context set that each model has: RF/XGBoost ALW features heartbeat_elapsed, ref_realized_vol, temporal_deviation_persistence, temporal_slope, temporal_step_change_count,
temporal_gap_trend (6; congestion is not an ALW feature); BN nodes heartbeat_elapsed, congestion, ref_realized_vol, temporal_deviation_persistence, temporal_slope, temporal_step_change_count (6). Venue = reserve_skew and
reserve_skew_localization (RF/XGB/BN). Price = price_dev, cross_venue_spread, dex_oracle_spread (BN only; RF/XGBoost do not use them in the ALW set, as in section 29).
Share = drop(market) / (drop(market) + drop(venue) [+ drop(price) for the BN]) with negative drops set to 0. The BN is the closed-form count model of section 42 (validated there against pgmpy); RF = 150 trees, random_state 0,
median imputation; XGBoost = fixed config, scale_pos_weight neg/pos. CI = stratified bootstrap over the LOOCV rows (1000 replicates, same resample for all models and groups), recomputing the drops and shares on the resample
from the stored permuted predictions (the models are not refit, so the CI reflects sampling of the evaluation rows only). Baseline values differ slightly from earlier tables that use nested-tuned XGBoost or 300-tree RF."""
from cjsj_common import ensure_omp
ensure_omp()
import time
import numpy as np, pandas as pd
import xgboost as xgb
from joblib import Parallel, delayed
from scipy.stats import rankdata
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score
from cjsj_common import REPORTS, TAG_VERIFIED, write_section
import cjsj_eval as E
import cjsj_lc as LC
import cjsj_42_bn_below_chance as C42
from models import BN_RAW_TO_DISCRETE

R = 200; B = 1000; EPS = 1e-3
ML_GROUPS = {"market": ["heartbeat_elapsed", "ref_realized_vol", "temporal_deviation_persistence", "temporal_slope", "temporal_step_change_count", "temporal_gap_trend"], "venue": ["reserve_skew", "reserve_skew_localization"]}
BN_GROUPS = {"market": ["heartbeat_elapsed", "congestion", "ref_realized_vol", "temporal_deviation_persistence", "temporal_slope", "temporal_step_change_count"], "venue": ["reserve_skew", "reserve_skew_localization"],
             "price": ["price_dev", "cross_venue_spread", "dex_oracle_spread"]}
ALLN = list(BN_RAW_TO_DISCRETE)


def donors_matrix(n, seed=0):
    rng = np.random.default_rng(seed); D = np.empty((R, n), int)
    for r in range(R):
        p = rng.permutation(n)
        while True:
            fx = np.where(p == np.arange(n))[0]
            if len(fx) == 0: break
            for f in fx: j = (f + 1) % n; p[f], p[j] = p[j], p[f]
        D[r] = p
    return D


def fold_ml(kind, X, y, i, D, cols_of):
    n = len(y); tr = np.delete(np.arange(n), i)
    if kind == "RF":
        med = np.nanmedian(X[tr], axis=0); fill = lambda M: np.where(np.isnan(M), med, M)
        m = RandomForestClassifier(n_estimators=150, random_state=0, n_jobs=1).fit(fill(X[tr]), y[tr]); pr = lambda M: m.predict_proba(fill(M))[:, list(m.classes_).index(1)]
    else:
        spw = float((y[tr] == 0).sum()) / max(int((y[tr] == 1).sum()), 1)
        m = xgb.XGBClassifier(**LC.XCFG, scale_pos_weight=spw, tree_method="hist", n_jobs=1, random_state=0, verbosity=0).fit(X[tr], y[tr]); pr = lambda M: m.predict_proba(M)[:, 1]
    out = {"p0": float(pr(X[i:i + 1])[0])}
    for g, cidx in cols_of.items():
        Xp = np.repeat(X[i:i + 1], R, axis=0); Xp[:, cidx] = X[D[:, i]][:, cidx]; out[g] = pr(Xp)
    return out


def fold_bn(st, y, i, D):
    n = len(y); tr = np.delete(np.arange(n), i); T = C42.tables(st, y, tr, ALLN); n1 = y[tr].sum(); lp = np.log((n1 + 1) / ((len(tr) - n1) + 1))
    sc = lambda row: float(1.0 / (1.0 + np.exp(-(lp + sum(C42.llr_nodes(T, row, ALLN).values())))))
    row0 = {nd: st[nd][i] for nd in ALLN}; out = {"p0": sc(row0)}
    for g, nodes in BN_GROUPS.items():
        v = np.zeros(R)
        for r in range(R):
            row = dict(row0)
            for nd in nodes: row[nd] = st[nd][D[r, i]]
            v[r] = sc(row)
        out[g] = v
    return out


def ll_mat(y, P):
    P = np.clip(P, EPS, 1 - EPS); return -(y * np.log(P) + (1 - y) * np.log(1 - P)).mean(-1)


def auc_mat(y, P):
    P = np.atleast_2d(P); rk = rankdata(P, axis=1); npos = int(y.sum()); nneg = len(y) - npos
    return (rk[:, y == 1].sum(1) - npos * (npos + 1) / 2) / (npos * nneg)


def drops(y, p0, Pg):
    """{group: (AUC drop, logloss drop)}"""
    a0 = auc_mat(y, p0)[0]; l0 = ll_mat(y, p0)
    return {g: (a0 - auc_mat(y, P).mean(), ll_mat(y, P).mean() - l0) for g, P in Pg.items()}


def share(dr, k, groups):
    v = {g: max(dr[g][k], 0.0) for g in groups}; t = sum(v.values()); return v["market"] / t if t > 1e-12 else np.nan


def main():
    t0 = time.time(); base = E.load_base(); sets = E.positive_sets(base); L = []; Q = L.append; rows = []; stash = {}
    s29 = pd.read_csv(REPORTS / "cjsj_29_share_ci.csv"); pl = pd.read_csv(REPORTS / "cjsj_loocv_preds.csv")
    for sname in ["all 24 (audit baseline)", "verified M (9)"]:
        d = E.subset(base, sets[sname]); y = E.labels(d); n = len(d); D = donors_matrix(n); rng = np.random.default_rng(0)
        Xml = E.feats(d, E.ALW).values; cols_of = {g: [E.ALW.index(c) for c in cs if c in E.ALW] for g, cs in ML_GROUPS.items()}
        # the ML groups above name columns; RF/XGB use the ALW matrix (8 columns): market columns present in ALW
        cols_of = {g: [E.ALW.index(c) for c in cs] for g, cs in ML_GROUPS.items()}
        st = C42.states(d, ALLN)
        preds = {}
        for kind in ["BN", "RF", "XGBoost"]:
            if kind == "BN": res = Parallel(n_jobs=8)(delayed(fold_bn)(st, y, i, D) for i in range(n))
            else: res = Parallel(n_jobs=8)(delayed(fold_ml)("RF" if kind == "RF" else "XGB", Xml, y, i, D, cols_of) for i in range(n))
            groups = list(BN_GROUPS) if kind == "BN" else list(ML_GROUPS)
            p0 = np.array([r["p0"] for r in res]); Pg = {g: np.stack([r[g] for r in res], axis=1) for g in groups}; preds[kind] = (p0, Pg, groups)
        # stratified bootstrap, same resample for all models/groups
        pos = np.where(y == 1)[0]; neg = np.where(y == 0)[0]; bs = [np.concatenate([rng.choice(pos, len(pos)), rng.choice(neg, len(neg))]) for _ in range(B)]
        for kind, (p0, Pg, groups) in preds.items():
            pt = drops(y, p0, Pg); sh = {k: share(pt, k, groups) for k in (0, 1)}; sh_np = {k: share(pt, k, ["market", "venue"]) for k in (0, 1)} if kind == "BN" else None
            bt = {0: [], 1: []}; bnp = {0: [], 1: []}; bd = {g: {0: [], 1: []} for g in groups}
            for s in bs:
                dr = drops(y[s], p0[s], {g: P[:, s] for g, P in Pg.items()})
                for k in (0, 1):
                    bt[k].append(share(dr, k, groups))
                    if kind == "BN": bnp[k].append(share(dr, k, ["market", "venue"]))
                    for g in groups: bd[g][k].append(dr[g][k])
            ci = lambda v: tuple(np.nanpercentile(v, [2.5, 97.5])) if np.isfinite(v).any() else (np.nan, np.nan)
            rows.append(dict(label_set=sname, model=kind, auc0=roc_auc_score(y, p0), ll0=float(ll_mat(y, p0)), drops=pt, share_auc=sh[0], ci_auc=ci(bt[0]), share_ll=sh[1], ci_ll=ci(bt[1]),
                             nan_auc=int(np.isnan(bt[0]).sum()), nan_ll=int(np.isnan(bt[1]).sum()), gci={g: (ci(bd[g][0]), ci(bd[g][1])) for g in groups},
                             sh_np=sh_np, ci_np=(ci(bnp[0]), ci(bnp[1])) if kind == "BN" else None, groups=groups))
    Q(f"Permutation importance on LOOCV predictions, {R} joint group permutations, {B} stratified bootstrap replicates for the CIs. Groups and definitions in the script docstring (cjsj_45_perm_importance.py).")
    Q("")
    Q("#### 45a. Baseline LOOCV performance of the models used here (fixed-config XGBoost, 150-tree RF, closed-form BN)"); Q("")
    Q("| Label set | Model | LOOCV AUC | LOOCV log-loss (clipped 0.001) |"); Q("|---|---|---|---|")
    for r in rows: Q(f"| {r['label_set']} | {r['model']} | {r['auc0']:.3f} | {r['ll0']:.3f} |")
    a = pl; Q(""); Q(f"For reference, saved LOOCV predictions (cjsj_03, n=162; nested-tuned XGBoost, production pgmpy BN, RF 300 trees): AUC BN {roc_auc_score(a.y, a.p_bn):.3f}, RF {roc_auc_score(a.y, a.p_rf):.3f}, XGBoost {roc_auc_score(a.y, a.p_xgb):.3f}.")
    Q("")
    Q("#### 45b. Metric drop when a feature group is jointly permuted (mean over 200 permutations; bootstrap 95% CI in brackets)"); Q("")
    Q("| Label set | Model | group | AUC drop | log-loss increase |"); Q("|---|---|---|---|---|")
    for r in rows:
        for g in r["groups"]: Q(f"| {r['label_set']} | {r['model']} | {g} | {r['drops'][g][0]:+.3f} [{r['gci'][g][0][0]:+.3f}, {r['gci'][g][0][1]:+.3f}] | {r['drops'][g][1]:+.3f} [{r['gci'][g][1][0]:+.3f}, {r['gci'][g][1][1]:+.3f}] |")
    Q("")
    Q("#### 45c. Market-context share of the permutation importance (share of total positive drop)"); Q("")
    Q("| Label set | Model | share by AUC drop [95% CI] | share by log-loss increase [95% CI] | replicates with zero total drop (AUC / log-loss, excluded from CI) |"); Q("|---|---|---|---|---|")
    f = lambda v: "n/a" if np.isnan(v) else f"{v:.0%}"
    for r in rows: Q(f"| {r['label_set']} | {r['model']} | {f(r['share_auc'])} [{f(r['ci_auc'][0])}, {f(r['ci_auc'][1])}] | {f(r['share_ll'])} [{f(r['ci_ll'][0])}, {f(r['ci_ll'][1])}] | {r['nan_auc']} / {r['nan_ll']} |")
    Q("")
    for r in rows:
        if r["model"] == "BN": Q(f"- BN sensitivity ({r['label_set']}), market / (market + venue) excluding the price nodes: AUC-drop share {f(r['sh_np'][0])} [{f(r['ci_np'][0][0])}, {f(r['ci_np'][0][1])}], log-loss share {f(r['sh_np'][1])} [{f(r['ci_np'][1][0])}, {f(r['ci_np'][1][1])}].")
    Q("")
    Q("#### 45d. Comparison with section 29 (SHAP / evidence shares, mean over out-of-bag attacks; 200 bootstrap refits; cjsj_29_share_ci.csv)"); Q("")
    Q("| Model | section 29 share, attacks | section 29 share, volatility | permutation share (all 24), AUC | permutation share (all 24), log-loss |"); Q("|---|---|---|---|---|")
    for kind in ["BN", "RF", "XGB"]:
        r = [x for x in rows if x["label_set"].startswith("all 24") and x["model"] == (kind if kind != "XGB" else "XGBoost")][0]
        Q(f"| {kind} | {s29[f'{kind}_att'].mean():.0%} | {s29[f'{kind}_vol'].mean():.0%} | {f(r['share_auc'])} | {f(r['share_ll'])} |")
    Q("")
    Q("Comparability note: section 29 measures the share of each model's per-incident attribution (SHAP / evidence) on market-context features, while this table measures how much predictive performance is lost when the group is scrambled; the two need not agree. Under permutation the BN loses essentially nothing from market context (its market nodes are nearly constant, sections 35 and 42), whereas RF and XGBoost lose 21-28% of their total group-wise drop (all 24); venue features carry most of every model's permutation importance. The BN's section 29 share (8%) is also low, so the ordering BN << RF < XGBoost agrees, but the ML shares are lower here (21-28%) than in section 29 (32-36% on attacks, 44% on volatility incidents).")
    Q("")
    r = {x["model"]: x for x in rows if x["label_set"].startswith("all 24")}
    Q("Reading (computed): all 24, market-context share by AUC drop: " + ", ".join(f"{m} {f(r[m]['share_auc'])} [{f(r[m]['ci_auc'][0])}, {f(r[m]['ci_auc'][1])}]" for m in r) + "; by log-loss: " + ", ".join(f"{m} {f(r[m]['share_ll'])} [{f(r[m]['ci_ll'][0])}, {f(r[m]['ci_ll'][1])}]" for m in r) + ".")
    Q("")
    Q(f"(runtime {time.time() - t0:.0f}s; cjsj_45_perm_importance.py)")
    body = "\n".join(L); print(body)
    write_section("cjsj_45_perm_importance.py", "45", "Method-agnostic attribution: permutation importance of market-context vs venue features (BN, RF, XGBoost)", TAG_VERIFIED + "; all-24 rows are within-benchmark (confounded data, see research_audit.md)", body)


if __name__ == "__main__":
    main()
