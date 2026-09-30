"""Score-returning held-out protocol for items 20-21 (extends cjsj_lc.py): returns out-of-fold SCORES so operating points can be moved.

Protocol (as cjsj_lc.protocol): every negative held out once (10 random folds), every pool positive held out once (leave-one-out),
optional random subsample of n_sub training positives, optional label flips / extra training positives.
Models (`which`): BN | RF (unweighted, 150 trees) | RFb (class_weight='balanced') | XGBu (scale_pos_weight=1) | XGB (scale_pos_weight=neg/pos).
XGB config fixed: max_depth 2, 150 trees, lr .1. Feature sets (`fs`): ML models use fs['ml'] columns; BN keeps only the nodes for fs['bn'] raw columns
(None = full production BN). Each returned score comes with `pi`, the training prevalence of its fold (for prevalence-threshold operating points).
"""
from cjsj_common import ensure_omp
ensure_omp()
import numpy as np, pandas as pd
import xgboost as xgb
from sklearn.ensemble import RandomForestClassifier
import cjsj_eval as E
import cjsj_lc as LC
from models import (BN_EDGES, BN_RAW_TO_DISCRETE, BN_STATE_NAMES, FIXED_THRESHOLDS, _bn_clean, predict_bayesian_network)

ETH6 = ["heartbeat_elapsed", "congestion", "ref_realized_vol", "temporal_deviation_persistence", "temporal_slope", "temporal_step_change_count"]
FEATSETS = {
    "all features (baseline)": dict(ml=E.ALW, bn=None),
    "no ETH-context, venue only (reserve_skew, localization)": dict(ml=["reserve_skew", "reserve_skew_localization"], bn=["reserve_skew", "reserve_skew_localization"]),
    "no ETH-context, extended (+price_dev, cross_venue_spread, dex_oracle_spread)": dict(ml=["price_dev", "cross_venue_spread", "dex_oracle_spread", "reserve_skew", "reserve_skew_localization"],
                                                                                        bn=["price_dev", "cross_venue_spread", "dex_oracle_spread", "reserve_skew", "reserve_skew_localization"]),
    "ETH-context only (6 BN-compatible features)": dict(ml=ETH6, bn=ETH6),
}


def bn_fit_keep(tr, keep, thr=None, ess=2):
    from pgmpy.estimators import BayesianEstimator
    from pgmpy.models import DiscreteBayesianNetwork
    thr = thr or FIXED_THRESHOLDS
    raw2d = {k: v for k, v in BN_RAW_TO_DISCRETE.items() if keep is None or k in keep}
    disc = {v[0] for v in raw2d.values()}
    edges = [(a, b) for a, b in BN_EDGES if (a == "label_d" or a in disc) and b in disc]
    sn = {**BN_STATE_NAMES, "label_d": E.CL}
    w = tr.copy(); w["label_d"] = w["label"]; th = {}
    for raw, (dc, p) in raw2d.items():
        m = w[raw].apply(lambda v, c=raw: _bn_clean(c, v)).abs(); t = thr[raw]; th[raw] = t
        w[dc] = m.apply(lambda x, tt=t, pp=p: np.nan if pd.isna(x) else (f"{pp}_high" if x > tt else f"{pp}_low"))
    model = DiscreteBayesianNetwork(edges); cpds = []
    for node in model.nodes():
        cols = [node] + list(model.get_parents(node)); comp = w.dropna(subset=cols)
        if len(comp) == 0: return None, th
        cpds.append(BayesianEstimator(model, comp, state_names={c: sn[c] for c in cols}).estimate_cpd(node, prior_type="BDeu", equivalent_sample_size=ess))
    model.add_cpds(*cpds)
    return (model if model.check_model() else None), th


def bn_scores(d, tr, te, keep):
    dd = d.drop(columns=["dt"], errors="ignore"); m, th = bn_fit_keep(dd.iloc[tr], keep)
    if m is None: return np.zeros(len(te))
    return np.array([predict_bayesian_network(m, th, dd.iloc[j])[0][E.MAN] for j in te])


def xgb_scores(d, tr, te, cols, balanced):
    X = E.feats(d, cols).values; y = E.labels(d); yt = y[tr]
    spw = float((yt == 0).sum()) / max(int((yt == 1).sum()), 1) if balanced else 1.0
    g = xgb.XGBClassifier(**LC.XCFG, scale_pos_weight=spw, tree_method="hist", n_jobs=1, random_state=0, verbosity=0).fit(X[tr], yt)
    return g.predict_proba(X[te])[:, 1]


def predict_models(d, tr, te, fs, which):
    tr = np.asarray(tr); te = np.asarray(te); out = {}
    for m in which:
        if m == "BN": out[m] = bn_scores(d, tr, te, fs["bn"])
        elif m == "RF": out[m] = E.rf_proba(d, tr, te, cols=fs["ml"], n_est=150)
        elif m == "RFb": out[m] = E.rf_proba(d, tr, te, cols=fs["ml"], n_est=150, class_weight="balanced")
        elif m == "XGBu": out[m] = xgb_scores(d, tr, te, fs["ml"], False)
        elif m == "XGB": out[m] = xgb_scores(d, tr, te, fs["ml"], True)
    return out


def protocol_scores(df, pool_pos, fs, which, n_sub=None, flip_mode=None, k_flip=0, seed=0, extra_pos=(), target_row=None, nfold=10):
    rng = np.random.default_rng(seed); df = df.reset_index(drop=True)
    neg = np.where(df.label.values == E.VOL)[0]
    pool = df.index[df.incident.isin(pool_pos)].values; extra = df.index[df.incident.isin(list(extra_pos))].values
    order = rng.permutation(neg); folds = np.array_split(order, nfold)
    neg_s = {m: np.zeros(len(neg)) for m in which}; neg_pi = np.zeros(len(neg)); pos_s = {m: np.zeros(len(pool)) for m in which}; pos_pi = np.zeros(len(pool))
    where_neg = {v: i for i, v in enumerate(neg)}

    def flipped(train_neg):
        if not k_flip: return df
        fl = rng.choice(train_neg, k_flip, replace=False) if flip_mode == "random" else LC.nn_order(df, target_row, train_neg)[:k_flip]
        d = df.copy(); d.loc[fl, "label"] = E.MAN; return d

    for fold in folds:
        trn = np.setdiff1d(neg, fold)
        S = pool if n_sub is None else rng.choice(pool, min(n_sub, len(pool)), replace=False)
        d = flipped(trn); tr = np.concatenate([trn, S, extra]); P = predict_models(d, tr, fold, fs, which)
        pi = float((d.label.values[tr] == E.MAN).mean())
        for m in which:
            for j, v in zip(fold, P[m]): neg_s[m][where_neg[j]] = v
        for j in fold: neg_pi[where_neg[j]] = pi
    for a, i in enumerate(pool):
        rest = pool[pool != i]; S = rest if n_sub is None else rng.choice(rest, min(n_sub, len(rest)), replace=False)
        d = flipped(neg); tr = np.concatenate([neg, S, extra]); P = predict_models(d, tr, [i], fs, which)
        for m in which: pos_s[m][a] = P[m][0]
        pos_pi[a] = float((d.label.values[tr] == E.MAN).mean())
    return dict(neg=neg_s, pos=pos_s, neg_pi=neg_pi, pos_pi=pos_pi)


# ---------------- operating points ----------------
def recall_at_fa(neg, pos, f):
    """Expected recall when the threshold admits exactly f false alarms (ties between negatives and positives split proportionally)."""
    N = len(neg)
    if f >= N: return 1.0
    ns = np.sort(neg)[::-1]; s = ns[f]                      # first negative that must be excluded
    a = int((neg > s).sum()); g = int((neg == s).sum())
    return float(((pos > s).sum() + (pos == s).sum() * (f - a) / g) / len(pos))


def auc(neg, pos):
    x = np.asarray(pos)[:, None]; y = np.asarray(neg)[None, :]
    return float(((x > y).sum() + 0.5 * (x == y).sum()) / (len(neg) * len(pos)))


def at_thr(neg, pos, thr_neg, thr_pos):
    return int((neg >= thr_neg).sum()), float((pos >= thr_pos).mean())
