"""Shared protocol for cjsj_12 (learning curve) and cjsj_13 (label noise).

Held-out scoring ("LOOCV-style"): every negative is held out once per seed (10 random folds over the 138 volatility incidents; training
uses the other negatives), and every pool positive is held out once (leave-one-out; training uses the other positives). False alarms =
held-out negatives with P(manipulation) >= .5, recall = held-out pool positives with P >= .5. Full leave-one-negative-out would need
~138 refits per (seed, k, model); 10 folds keeps the 30-seed design tractable. Models (all thresholded at .5):
  BN  : production BN (models.py; fixed thresholds, BDeu ESS 2)         RF : 150 trees, ALW features, median imputation
  XGB : FIXED config max_depth 2, 150 trees, lr .1, scale_pos_weight = neg/pos (the config chosen most often in cjsj_03); not re-tuned per fold.
"""
from cjsj_common import ensure_omp
ensure_omp()
import numpy as np, pandas as pd
import xgboost as xgb
import cjsj_eval as E

XCFG = dict(max_depth=2, n_estimators=150, learning_rate=0.1)
MODELS = ("BN", "RF", "XGB")


def xgb_fixed(d, tr, te):
    X = E.feats(d).values; y = E.labels(d); yt = y[tr]
    spw = float((yt == 0).sum()) / max(int((yt == 1).sum()), 1)
    g = xgb.XGBClassifier(**XCFG, scale_pos_weight=spw, tree_method="hist", n_jobs=1, random_state=0, verbosity=0).fit(X[tr], yt)
    return g.predict_proba(X[te])[:, 1]


def fit_predict_all(d, tr, te):
    tr = np.asarray(tr); te = np.asarray(te)
    return {"BN": E.bn_proba(d, tr, te), "RF": E.rf_proba(d, tr, te, n_est=150), "XGB": xgb_fixed(d, tr, te)}


def nn_order(df, target_row, cand):
    """Candidate indices sorted by standardized ALW-feature distance to target_row (median-imputed)."""
    X = E.feats(df); med = X.median(); sd = X.std().replace(0, 1)
    Z = ((X.fillna(med) - med) / sd).values; t = ((pd.Series(target_row).fillna(med) - med) / sd).values
    dist = np.sqrt(((Z[cand] - t) ** 2).sum(1)); return cand[np.argsort(dist)]


def protocol(df, pool_pos, extra_pos=(), n_sub=None, flip_mode=None, k_flip=0, seed=0, target_row=None, nfold=10):
    """df: rows = negatives + pool positives + extra positives (positional index == df.index).
    pool_pos: incidents held out one at a time (recall) and eligible for subsampling; extra_pos: always in training when not held out."""
    rng = np.random.default_rng(seed); df = df.reset_index(drop=True)
    neg = np.where(df.label.values == E.VOL)[0]
    pool = df.index[df.incident.isin(pool_pos)].values; extra = df.index[df.incident.isin(list(extra_pos))].values
    folds = np.array_split(rng.permutation(neg), nfold)
    fa = {m: 0 for m in MODELS}; caught = {m: 0 for m in MODELS}

    def flipped(train_neg):
        if not k_flip: return df
        if flip_mode == "random": fl = rng.choice(train_neg, k_flip, replace=False)
        else: fl = nn_order(df, target_row, train_neg)[:k_flip]
        d = df.copy(); d.loc[fl, "label"] = E.MAN; return d

    for fold in folds:
        trn = np.setdiff1d(neg, fold)
        S = pool if n_sub is None else rng.choice(pool, min(n_sub, len(pool)), replace=False)
        P = fit_predict_all(flipped(trn), np.concatenate([trn, S, extra]), fold)
        for m in MODELS: fa[m] += int((P[m] >= .5).sum())
    for i in pool:
        rest = pool[pool != i]
        S = rest if n_sub is None else rng.choice(rest, min(n_sub, len(rest)), replace=False)
        P = fit_predict_all(flipped(neg), np.concatenate([neg, S, extra]), [i])
        for m in MODELS: caught[m] += int(P[m][0] >= .5)
    return {m: (fa[m], caught[m] / len(pool)) for m in MODELS}, len(neg), len(pool)


def boot_mean(v, B=2000, seed=0):
    v = np.asarray(v, float); rng = np.random.default_rng(seed)
    bm = [rng.choice(v, len(v)).mean() for _ in range(B)]
    return v.mean(), *np.percentile(bm, [2.5, 97.5])
