"""Pilot models (NOT models.py): ETH-context control + price-path model on data/processed/pilot.parquet.

Everything printed/returned is labeled "pilot, underpowered per A10". LOOCV predictions -> AUC; uncertainty from
(a) Hanley-McNeil normal approximation, (b) stratified bootstrap of the LOOCV predictions, (c) label-permutation null
of the LOOCV-AUC (logistic). With n_pos this small every interval is close to uninformative; they are reported anyway.
"""
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from a10_power_analysis import auc_mde, hanley_mcneil_se, se_null

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
PILOT = ROOT / "data" / "processed" / "pilot.parquet"
PATH = ["P2", "P3", "D1", "D5"]                                   # S price path only (no reference price)
FULL = ["P1", "P2", "P3", "D1", "D2", "D3", "D5"]
ETH = ["eth_ret_300", "eth_vol_300", "eth_gas_util_300", "eth_gas_util_T", "eth_absret_T", "eth_absret_50", "eth_cl_stale_a"]
LABEL = "pilot, underpowered per A10"
RNG = np.random.default_rng(20260930)


def mk(kind):
    if kind == "logit":
        return make_pipeline(StandardScaler(), LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000))
    return RandomForestClassifier(n_estimators=300, min_samples_leaf=1, class_weight="balanced_subsample", random_state=0, n_jobs=1)


def loocv_scores(X, y, kind):
    n = len(y)
    s = np.zeros(n)
    for i in range(n):
        tr = np.arange(n) != i
        if len(set(y[tr])) < 2:
            s[i] = 0.5
            continue
        m = mk(kind).fit(X[tr], y[tr])
        s[i] = m.predict_proba(X[i:i + 1])[0, 1]
    return s


def auc_report(y, s, n_boot=2000):
    npos, nneg = int(y.sum()), int((1 - y).sum())
    auc = roc_auc_score(y, s)
    se = hanley_mcneil_se(min(max(auc, 0.02), 0.98), npos, nneg)
    boots = []
    pi, ni = np.where(y == 1)[0], np.where(y == 0)[0]
    for _ in range(n_boot):
        idx = np.concatenate([RNG.choice(pi, len(pi)), RNG.choice(ni, len(ni))])
        boots.append(roc_auc_score(y[idx], s[idx]))
    return dict(auc=float(auc), n_pos=npos, n_neg=nneg,
                hm_ci95=[float(max(0, auc - 1.96 * se)), float(min(1, auc + 1.96 * se))],
                boot_ci95=[float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
                hm_upper_one_sided95=float(min(1.0, auc + 1.645 * se)),
                boot_upper_one_sided95=float(np.percentile(boots, 95)),
                se_null=float(se_null(npos, nneg)),
                mde_auc_at_this_n=float(auc_mde(npos, nneg)) if npos >= 2 else None,
                label=LABEL)


def perm_null(X, y, kind="logit", n=300):
    """Null distribution of LOOCV-AUC under label permutation (keeps class counts)."""
    out = []
    for _ in range(n):
        yp = RNG.permutation(y)
        out.append(roc_auc_score(yp, loocv_scores(X, yp, kind)))
    return np.array(out)


def run(df):
    a = df[df.in_analysis == True].copy()                        # noqa: E712
    y = (a.cls == "attack").astype(int).values
    res = {"n_rows_in_analysis": int(len(a)), "n_pos": int(y.sum()), "n_neg": int((1 - y).sum()), "label": LABEL, "models": {}}
    if y.sum() < 1 or y.sum() == len(y):
        return res
    groups = {"eth_context_control": ETH, "price_path_model(P2,P3,D1,D5)": PATH, "full_pilot_features(P1-3,D1,D2,D3,D5)": FULL,
              "price_path_no_D5(P2,P3,D1)": ["P2", "P3", "D1"]}
    for gname, cols in groups.items():
        X = a[cols].astype(float).values
        for kind in ("logit", "rf"):
            s = loocv_scores(X, y, kind)
            r = auc_report(y, s)
            r["features"] = cols
            if kind == "logit" and gname == "eth_context_control":
                nullc = perm_null(X, y, "logit")
                r["perm_null_auc_mean"] = float(nullc.mean())
                r["perm_null_auc_p95"] = float(np.percentile(nullc, 95))
                r["perm_p_one_sided"] = float((1 + (nullc >= r["auc"]).sum()) / (1 + len(nullc)))
            res["models"][f"{gname}|{kind}"] = r
    # S_type-only control (venue-identity style)
    Xt = pd.get_dummies(a["S_type"]).astype(float).values
    res["models"]["S_type_only_control|logit"] = dict(auc_report(y, loocv_scores(Xt, y, "logit")), features=["S_type onehot"])
    return res


if __name__ == "__main__":
    df = pd.read_parquet(PILOT)
    res = run(df)
    (ROOT / "reports" / "pilot_model_results.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: (v if k != "models" else {m: {kk: vv for kk, vv in r.items() if kk in ("auc", "boot_ci95", "hm_upper_one_sided95")}
                                                     for m, r in v.items()}) for k, v in res.items()}, indent=1))
