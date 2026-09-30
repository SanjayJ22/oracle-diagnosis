"""Shared forward-time runner for cjsj_08 / cjsj_10: BN, RF(300 trees), nested-tuned XGBoost per cutoff (cjsj_03 settings).
Audit skip rule: evaluable only if train positives >= 3 and test positives >= 2."""
from cjsj_common import ensure_omp
ensure_omp()
import numpy as np
import cjsj_eval as E
import cjsj_03_xgb_heuristics as X3


def forward_all(df, cutoffs=E.CUTOFFS, min_tr=3, min_te=2):
    y = E.labels(df); n = len(df); out = []
    for c in cutoffs:
        (tr, te), = E.forward_split(df, c)
        ntr, ptr, nte, pte = len(tr), int(y[tr].sum()), len(te), int(y[te].sum())
        rec = dict(cut=c, tr=tr, te=te, ntr=ntr, ptr=ptr, nte=nte, pte=pte, ok=(ptr >= min_tr and pte >= min_te))
        if rec["ok"]:
            P = {m: np.full(n, np.nan) for m in ("BN", "RF", "XGB")}
            P["BN"][te] = E.bn_proba(df, tr, te); P["RF"][te] = E.rf_proba(df, tr, te, n_est=300)
            px, cfg = X3.xgb_nested(df, tr, te); P["XGB"][te] = px; rec["cfg"] = cfg
            rec["P"] = P
        out.append(rec)
    return out


def cell(y, p, te):
    m = np.zeros(len(y), bool); m[te] = True
    s = E.summ(y, p, mask=m)
    return s
