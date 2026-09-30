"""CJSJ item 3 (B10): XGBoost and simple deviation-threshold heuristics, nested-CV tuned, in LOOCV and forward-time
splits, with exact McNemar vs the production BN (and vs RF). Positive class = all 24 manipulations (within-benchmark).

Nested CV: for every OUTER split, every hyperparameter / heuristic choice is made using only that split's TRAIN rows
via an INNER stratified K-fold (K=min(5, minority count)); the outer test rows are never seen during tuning.
  XGB grid (24): max_depth {2,3,4} x n_estimators {50,150} x learning_rate {0.1,0.3} x scale_pos_weight {1, neg/pos};
                 choose by inner mean log-loss.  Features = ALW (8), NaN handled natively.
  Heuristics (flag = manipulation), threshold tau fitted on train rows by balanced accuracy (ties -> larger tau):
    H1 price-deviation guard : max(|price_dev|, |cross_venue_spread|, |dex_oracle_spread|) > tau   (missing ignored)
    H2 TWAP guard            : |dex_twap_spread| > tau                                             (missing ignored)
    H3 reserve-skew guard    : |reserve_skew| > tau     (audit C2: measures the loss itself, post-exploit)
    H4 localization guard    : reserve_skew_localization > tau
    H5 decision stump        : best single ALW feature by inner-CV balanced accuracy (tau refit inside each inner fold)
    H-best                   : among H1..H5, the one with best inner-CV balanced accuracy
Forward-time uses the audit's skip rule (train positives >= 3 and test positives >= 2). Saves LOOCV predictions to
reports/cjsj_loocv_preds.csv for items 4 and 7.
"""
from cjsj_common import ensure_omp
ensure_omp()
import itertools, time
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from scipy import stats
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import roc_auc_score
import xgboost as xgb
from cjsj_common import REPORTS, TAG_CONFOUNDED, write_section
import cjsj_eval as E

GRID = [dict(max_depth=d, n_estimators=n, learning_rate=lr, spw=s)
        for d, n, lr, s in itertools.product((2, 3, 4), (50, 150), (0.1, 0.3), ("one", "balanced"))]


def _xgb(cfg, X, y):
    spw = 1.0 if cfg["spw"] == "one" else float((y == 0).sum()) / max(int((y == 1).sum()), 1)
    return xgb.XGBClassifier(max_depth=cfg["max_depth"], n_estimators=cfg["n_estimators"], learning_rate=cfg["learning_rate"],
                             scale_pos_weight=spw, tree_method="hist", n_jobs=1, random_state=0, verbosity=0,
                             eval_metric="logloss").fit(X, y)


def inner_folds(y, seed=0):
    k = int(min(5, (y == 1).sum(), (y == 0).sum()))
    return list(StratifiedKFold(k, shuffle=True, random_state=seed).split(np.zeros(len(y)), y)) if k >= 2 else []


def xgb_nested(df, tr, te):
    X = E.feats(df).values; y = E.labels(df)
    Xtr, ytr = X[tr], y[tr]; folds = inner_folds(ytr)
    best, best_ll = None, np.inf
    for cfg in GRID:
        ll = []
        for a, b in folds:
            if ytr[a].sum() == 0: continue
            p = np.clip(_xgb(cfg, Xtr[a], ytr[a]).predict_proba(Xtr[b])[:, 1], 1e-6, 1 - 1e-6)
            ll.append(-np.mean(ytr[b] * np.log(p) + (1 - ytr[b]) * np.log(1 - p)))
        m = np.mean(ll) if ll else np.inf
        if m < best_ll - 1e-12: best, best_ll = cfg, m
    best = best or GRID[0]
    return _xgb(best, Xtr, ytr).predict_proba(X[te])[:, 1], best


# ---------------- heuristics ----------------
def h_scores(df):
    d = df.replace([np.inf, -np.inf], E.RESERVE_SKEW_CLIP)
    ab = lambda c: d[c].abs()
    S = {"H1": pd.concat([ab("price_dev"), ab("cross_venue_spread"), ab("dex_oracle_spread")], axis=1).max(axis=1, skipna=True),
         "H2": ab("dex_twap_spread"), "H3": ab("reserve_skew"), "H4": d["reserve_skew_localization"].astype(float)}
    S = {k: v.astype(float).fillna(0.0).values for k, v in S.items()}
    for c in E.ALW:                                          # H5 stump candidates: magnitude of each ALW feature
        S["S:" + c] = d[c].abs().astype(float).fillna(0.0).values
    return S


def fit_tau(s, y):
    u = np.unique(s); cand = np.unique(np.quantile(u, np.linspace(0, 1, 61))) if len(u) > 60 else u
    cand = np.concatenate([[u.min() - 1e-9], (cand[:-1] + cand[1:]) / 2 if len(cand) > 1 else cand, [u.max() + 1e-9]])
    best, bs = cand[-1], -1
    for t in cand:
        pr = s > t
        tpr = pr[y == 1].mean() if (y == 1).any() else 0; tnr = (~pr)[y == 0].mean() if (y == 0).any() else 0
        bacc = (tpr + tnr) / 2
        if bacc > bs + 1e-12 or (abs(bacc - bs) <= 1e-12 and t > best): best, bs = t, bacc
    return best


def bacc(pr, y):
    return ((pr[y == 1].mean() if (y == 1).any() else 0) + ((~pr)[y == 0].mean() if (y == 0).any() else 0)) / 2


def heur_nested(df, tr, te):
    S = h_scores(df); y = E.labels(df); ytr = y[tr]; folds = inner_folds(ytr)
    def inner(key):
        v = []
        for a, b in folds:
            t = fit_tau(S[key][tr][a], ytr[a]); v.append(bacc(S[key][tr][b] > t, ytr[b]))
        return float(np.mean(v)) if v else -1
    stump_keys = [k for k in S if k.startswith("S:")]
    stump = max(stump_keys, key=inner)
    out = {}
    for name, key in [("H1", "H1"), ("H2", "H2"), ("H3", "H3"), ("H4", "H4"), ("H5", stump)]:
        t = fit_tau(S[key][tr], ytr); out[name] = ((S[key][te] > t).astype(float), S[key][te], key, t)
    best_name = max(["H1", "H2", "H3", "H4", "H5"], key=lambda n: inner(out[n][2]))
    out["Hbest"] = (*out[best_name][:2], best_name + ":" + out[best_name][2], out[best_name][3])
    return out


def run_outer(df, splits):
    def job(tr, te):
        px, cfg = xgb_nested(df, tr, te); h = heur_nested(df, tr, te)
        return te, px, cfg, h
    res = Parallel(n_jobs=-1)(delayed(job)(tr, te) for tr, te in splits)
    n = len(df); P = {"XGB": np.full(n, np.nan)}
    for k in ("H1", "H2", "H3", "H4", "H5", "Hbest"):
        P[k] = np.full(n, np.nan); P[k + "_score"] = np.full(n, np.nan)
    chosen = {"XGB": [], "H5": [], "Hbest": [], "tau": {k: [] for k in ("H1", "H2", "H3", "H4", "H5", "Hbest")}}
    for te, px, cfg, h in res:
        P["XGB"][te] = px; chosen["XGB"].append(tuple(sorted(cfg.items())))
        for k in ("H1", "H2", "H3", "H4", "H5", "Hbest"):
            P[k][te] = h[k][0]; P[k + "_score"][te] = h[k][1]; chosen["tau"][k].append(h[k][3])
        chosen["H5"].append(h["H5"][2]); chosen["Hbest"].append(h["Hbest"][2])
    return P, chosen


def holm(pvals):
    order = np.argsort(pvals); m = len(pvals); adj = np.empty(m); run = 0
    for r, i in enumerate(order):
        run = max(run, (m - r) * pvals[i]); adj[i] = min(1, run)
    return adj


MODELS = ["BN", "RF", "XGB", "H1", "H2", "H3", "H4", "H5", "Hbest"]
DESC = {"BN": "BN (production)", "RF": "RF (150 trees)", "XGB": "XGBoost (nested-tuned)", "H1": "H1 price-deviation guard",
        "H2": "H2 TWAP guard", "H3": "H3 reserve-skew guard", "H4": "H4 localization guard", "H5": "H5 best stump",
        "Hbest": "H-best (inner-CV pick of H1-H5)"}


def score_of(P, m, y):
    return P.get(m + "_score", P[m])


def table(y, P, mask=None):
    rows = []; pv = []
    for m in MODELS:
        s = E.summ(y, P[m], mask=mask)
        if m in ("BN", "RF", "XGB"): auc = s["auc"]
        else:
            sc = P[m + "_score"]; mm = ~np.isnan(sc) if mask is None else mask & ~np.isnan(sc)
            auc = roc_auc_score(y[mm], sc[mm]) if 0 < y[mm].sum() < mm.sum() else np.nan
        rows.append((m, s, auc))
        pv.append(E.mcnemar(y, P[m], P["BN"], mask=mask)[2] if m != "BN" else np.nan)
    others = [i for i, m in enumerate(MODELS) if m != "BN"]
    adj = holm(np.array([pv[i] for i in others])); ai = dict(zip(others, adj))
    lines = ["| Model | acc | AUC | manip caught (Wilson 95%) | false alarms | McNemar vs BN (BN-only/model-only errors; p; Holm p) | vs RF p |", "|---|---|---|---|---|---|---|"]
    for i, (m, s, auc) in enumerate(rows):
        lo, hi = E.wilson(s["tp"], s["npos"])
        if m == "BN": mc = "-"
        else:
            n1, n2, p = E.mcnemar(y, P["BN"], P[m], mask=mask); mc = f"{n1}/{n2}; {p:.3f}; {ai[i]:.3f}"
        vr = "-" if m == "RF" else f"{E.mcnemar(y, P['RF'], P[m], mask=mask)[2]:.3f}"
        lines.append(f"| {DESC[m]} | {s['acc']:.3f} | {auc:.3f} | {s['tp']}/{s['npos']} ({lo:.2f}-{hi:.2f}) | {s['fp']}/{s['nneg']} | {mc} | {vr} |")
    return "\n".join(lines)


def main():
    t0 = time.time(); base = E.load_base(); y = E.labels(base); n = len(base)
    out = []; Q = out.append
    Q("Positives = all 24 manipulations, negatives = 138 volatility incidents (the audit benchmark). Nested CV: hyperparameters / heuristic choice are picked on outer-TRAIN rows only by inner stratified K-fold.")
    Q("")
    # ---- LOOCV ----
    lo = E.loocv_splits(n)
    P = {"BN": E.cv_predict(base, E.bn_proba, lo), "RF": E.cv_predict(base, E.rf_proba, lo, n_est=150)}
    Px, ch = run_outer(base, lo); P.update(Px)
    Q(f"### 3a. LOOCV (n={n}, {int(y.sum())} positives; threshold .5 for BN/RF/XGB; heuristics are hard flags, AUC uses the raw score)")
    Q(""); Q(table(y, P)); Q("")
    cx = pd.Series([str(c) for c in ch["XGB"]]).value_counts()
    Q("XGB configs chosen across the 162 outer folds (top 3): " + "; ".join(f"{dict(eval(k))} x{v}" for k, v in cx.head(3).items()))
    Q("H5 stump feature chosen: " + ", ".join(f"{k[2:]} x{v}" for k, v in pd.Series(ch["H5"]).value_counts().items()))
    Q("H-best chosen: " + ", ".join(f"{k} x{v}" for k, v in pd.Series(ch["Hbest"]).value_counts().items()))
    Q("Median fitted tau (across outer folds): " + ", ".join(f"{k} {np.median(v):.4g}" for k, v in ch["tau"].items()))
    Q("")
    pd.DataFrame({"incident": base.incident, "label": base.label, "y": y, "p_bn": P["BN"], "p_rf": P["RF"], "p_xgb": P["XGB"],
                  **{f"flag_{k}": P[k] for k in ("H1", "H2", "H3", "H4", "H5", "Hbest")}}).to_csv(REPORTS / "cjsj_loocv_preds.csv", index=False)
    # ---- forward-time ----
    Q("### 3b. Forward-time splits (train < cutoff, test >= cutoff; audit skip rule train pos >= 3 and test pos >= 2)")
    Q("")
    fw_rows = []; fw_p = {m: [] for m in MODELS if m != "BN"}
    for cut in E.CUTOFFS:
        (tr, te), = E.forward_split(base, cut)
        if y[tr].sum() < 3 or y[te].sum() < 2:
            Q(f"- {cut[:7]}: skipped (train pos {int(y[tr].sum())}, test pos {int(y[te].sum())})"); continue
        Pf = {"BN": np.full(n, np.nan), "RF": np.full(n, np.nan)}
        Pf["BN"][te] = E.bn_proba(base, tr, te); Pf["RF"][te] = E.rf_proba(base, tr, te, n_est=300)
        Px, chf = run_outer(base, [(tr, te)]); Pf.update(Px)
        mask = np.zeros(n, bool); mask[te] = True
        Q(f"#### cutoff {cut[:7]}: train {len(tr)} ({int(y[tr].sum())} pos), test {len(te)} ({int(y[te].sum())} pos)")
        Q(""); Q(table(y, Pf, mask)); Q("")
        Q(f"Nested choices at this cutoff: XGB {dict(chf['XGB'][0])}; H5 stump feature {chf['H5'][0][2:]} (tau {chf['tau']['H5'][0]:.4g}); H-best {chf['Hbest'][0]}.")
        Q("")
        for m in fw_p: fw_p[m].append(E.mcnemar(y, Pf["BN"], Pf[m], mask=mask)[2])
    Q("#### Holm correction across the evaluable forward cutoffs (per model, McNemar p vs BN)")
    Q("")
    Q("| Model | raw p by cutoff | Holm-adjusted p | min adjusted |"); Q("|---|---|---|---|")
    for m, ps in fw_p.items():
        if ps:
            a = holm(np.array(ps)); Q(f"| {DESC[m]} | {', '.join(f'{p:.3f}' for p in ps)} | {', '.join(f'{p:.3f}' for p in a)} | {a.min():.3f} |")
    Q(""); Q(f"(runtime {time.time() - t0:.0f}s; script cjsj_03_xgb_heuristics.py)")
    body = "\n".join(out); print(body)
    write_section("cjsj_03_xgb_heuristics.py", "3", "B10 XGBoost and deviation-threshold heuristics (nested CV) vs BN", TAG_CONFOUNDED, body)


if __name__ == "__main__":
    main()
