"""Shared attribution helpers for items 29-31: per-incident share of total |attribution| that falls on ETH-context features.
  RF  : shap.TreeExplainer, interventional, 100-row background from the TRAINING rows, probability space (RF 150 trees, median imputation)
  XGB : shap.TreeExplainer (exact TreeSHAP, log-odds), fixed config (cjsj_lc.XCFG, scale_pos_weight neg/pos)
  BN  : exact per-node log-likelihood ratios (as cjsj_07.bn_llr), generalized to BN variants with fewer nodes (cjsj_lcs.bn_fit_keep); the prior is not an attribution
share = sum over ETH-context features of |attribution| / sum over all features of |attribution| (congestion counts as ETH-context; the BN's congestion node carries no label evidence)."""
from cjsj_common import ensure_omp
ensure_omp()
import itertools
import numpy as np, pandas as pd
import shap, xgboost as xgb
from sklearn.ensemble import RandomForestClassifier
import cjsj_eval as E
import cjsj_lc as LC
import cjsj_lcs as S
from models import BN_RAW_TO_DISCRETE, _bn_clean

ETHC = {"heartbeat_elapsed", "congestion", "ref_realized_vol", "temporal_deviation_persistence", "temporal_slope", "temporal_step_change_count", "temporal_gap_trend"}


def _share(attr):
    tot = sum(abs(v) for v in attr.values()); return (sum(abs(v) for f, v in attr.items() if f in ETHC) / tot) if tot > 1e-12 else np.nan


def bn_llr_row(model, thr, row):
    cpds = {c.variable: c for c in model.get_cpds()}; raw_of = {dc: raw for raw, (dc, _) in BN_RAW_TO_DISCRETE.items()}; ev = {}
    for raw, (dc, pref) in BN_RAW_TO_DISCRETE.items():
        if dc not in cpds: continue
        x = _bn_clean(raw, row[raw])
        if pd.notna(x): ev[dc] = f"{pref}_high" if abs(x) > thr[raw] else f"{pref}_low"
    out = {}
    for node, state in ev.items():
        c = cpds[node]; parents = [v for v in c.variables if v != node]
        if "label_d" not in parents: continue
        names = c.state_names
        def p_given(label):
            others = [v for v in parents if v != "label_d" and v not in ev]; tot = 0.0
            for combo in itertools.product(*[range(len(names[o])) for o in others] or [[None]]):
                idx = [names[node].index(state)]
                for var in parents:
                    idx.append(names[var].index(label) if var == "label_d" else (combo[others.index(var)] if var in others else names[var].index(ev[var])))
                w = 1.0
                for o, ci in zip(others, combo): w *= cpds[o].values[ci] if cpds[o].values.ndim == 1 else 1.0
                tot += w * c.values[tuple(idx)]
            return tot
        out[raw_of[node]] = float(np.log(p_given(E.MAN) / p_given(E.VOL)))
    return out


def shares(train, explain, model, cols, bn_keep=None, n_bg=100, seed=0):
    """Per-row ETH-context attribution share for rows of `explain`, models fit on `train` (both DataFrames with the project columns)."""
    y = (train.label == E.MAN).astype(int).values
    if model == "BN":
        m, th = S.bn_fit_keep(train.drop(columns=["dt"], errors="ignore"), bn_keep)
        if m is None: return np.full(len(explain), np.nan)
        return np.array([_share(bn_llr_row(m, th, explain.iloc[i])) for i in range(len(explain))])
    X = E.feats(train, cols).values; Xe = E.feats(explain, cols).values; med = np.nanmedian(X, axis=0)
    Xi = np.where(np.isnan(X), med, X); Xei = np.where(np.isnan(Xe), med, Xe)
    if model == "RF":
        rf = RandomForestClassifier(n_estimators=150, random_state=0).fit(Xi, y)
        bg = Xi[np.random.default_rng(seed).choice(len(Xi), min(n_bg, len(Xi)), replace=False)]
        er = shap.TreeExplainer(rf, data=bg, feature_perturbation="interventional", model_output="probability"); sv = er.shap_values(Xei, check_additivity=False)
        sv = sv[:, :, 1] if np.ndim(sv) == 3 else (sv[1] if isinstance(sv, list) else sv)
    else:
        spw = float((y == 0).sum()) / max(int((y == 1).sum()), 1)
        g = xgb.XGBClassifier(**LC.XCFG, scale_pos_weight=spw, tree_method="hist", n_jobs=1, random_state=0, verbosity=0).fit(X, y)
        sv = shap.TreeExplainer(g).shap_values(Xe)
    return np.array([_share(dict(zip(cols, sv[i]))) for i in range(len(sv))])
