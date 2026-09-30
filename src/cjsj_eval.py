"""Shared evaluation harness for cjsj_02..07 (task: manipulation vs large volatility, malfunction excluded).

Model behaviour is copied from the existing audit scripts so numbers stay comparable:
  RF   : RandomForest, ALW features (8), median imputation from training rows, inf -> RESERVE_SKEW_CLIP
  BN   : project production BN (models.BN_EDGES / BN_RAW_TO_DISCRETE), fixed thresholds, BDeu ESS=2 (defaults)
  XGB  : xgboost (see cjsj_03) on the same 8 features, NaN handled natively
`bn_fit_c` differs from n162_experiments.bn_fit only by exposing `thr` (dict of thresholds) and `ess`.
"""
import warnings
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from scipy import stats
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score
from models import (load_data, RESERVE_SKEW_CLIP, BN_EDGES, BN_RAW_TO_DISCRETE, BN_STATE_NAMES,
                    FIXED_THRESHOLDS, _bn_clean, predict_bayesian_network)
from cjsj_common import REPORTS

warnings.filterwarnings("ignore")
MAN = "manipulation"; VOL = "large volatility event"; CL = [MAN, VOL]
ALW = ['heartbeat_elapsed', 'reserve_skew', 'ref_realized_vol', 'temporal_deviation_persistence', 'temporal_slope',
       'temporal_step_change_count', 'temporal_gap_trend', 'reserve_skew_localization']
ETH = ["heartbeat_elapsed", "congestion", "ref_realized_vol", "temporal_deviation_persistence", "temporal_slope",
       "temporal_step_change_count", "temporal_gap_trend"]


# ---------------- data ----------------
def load_base():
    df = load_data(); df = df[df.label.isin(CL)].reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["date"])
    return df


def label_sheet():
    return pd.read_csv(REPORTS / "a2_label_sheet.csv")


def subset(df, positives):
    """Keep all volatility rows and only the listed manipulation incidents."""
    keep = (df.label != MAN) | df.incident.isin(positives)
    return df[keep].reset_index(drop=True)


def positive_sets(df):
    sh = label_sheet()
    return {
        "all 24 (audit baseline)": list(df[df.label == MAN].incident),
        "A2 M, any tier (12)": list(sh[sh.category == "M"].incident_id),
        "verified M (9)": list(sh[sh.verified_M].incident_id),
        "verified M strict, no math_enabled (7)": list(sh[sh.verified_M_strict].incident_id),
    }


def feats(df, cols=ALW):
    return df[cols].replace([np.inf, -np.inf], RESERVE_SKEW_CLIP).astype(float)


def labels(df):
    return (df.label == MAN).astype(int).values


# ---------------- models: each returns P(manipulation) for te rows ----------------
def rf_proba(df, tr, te, cols=ALW, n_est=150, seed=0, **kw):
    X = feats(df, cols); y = labels(df); med = X.iloc[tr].median()
    c = RandomForestClassifier(n_estimators=n_est, random_state=seed, n_jobs=1, **kw).fit(X.iloc[tr].fillna(med).values, y[tr])
    return c.predict_proba(X.iloc[te].fillna(med).values)[:, list(c.classes_).index(1)]


def bn_fit_c(tr, thr=None, ess=2):
    from pgmpy.estimators import BayesianEstimator
    from pgmpy.models import DiscreteBayesianNetwork
    thr = thr or FIXED_THRESHOLDS
    sn = {**BN_STATE_NAMES, "label_d": CL}
    w = tr.copy(); w["label_d"] = w["label"]; th = {}
    for raw, (dc, p) in BN_RAW_TO_DISCRETE.items():
        m = w[raw].apply(lambda v, c=raw: _bn_clean(c, v)).abs(); t = thr[raw]; th[raw] = t
        w[dc] = m.apply(lambda x, tt=t, pp=p: np.nan if pd.isna(x) else (f"{pp}_high" if x > tt else f"{pp}_low"))
    model = DiscreteBayesianNetwork(BN_EDGES); cpds = []
    for node in model.nodes():
        cols = [node] + list(model.get_parents(node)); comp = w.dropna(subset=cols)
        if len(comp) == 0:
            return None, th
        cpds.append(BayesianEstimator(model, comp, state_names={c: sn[c] for c in cols})
                    .estimate_cpd(node, prior_type="BDeu", equivalent_sample_size=ess))
    model.add_cpds(*cpds)
    return (model if model.check_model() else None), th


def bn_proba(df, tr, te, thr=None, ess=2):
    d = df.drop(columns=["dt"], errors="ignore")
    m, th = bn_fit_c(d.iloc[tr], thr, ess)
    if m is None:
        return np.zeros(len(te))
    return np.array([predict_bayesian_network(m, th, d.iloc[j])[0][MAN] for j in te])


def _one(fn, df, tr, te, kw):
    return te, fn(df, tr, te, **kw)


def cv_predict(df, fn, splits, n_jobs=-1, **kw):
    """Run fn(df, tr, te, **kw) over (tr, te) index splits; return P(man) array (NaN where never tested)."""
    p = np.full(len(df), np.nan)
    for te, pr in Parallel(n_jobs=n_jobs)(delayed(_one)(fn, df, tr, te, kw) for tr, te in splits):
        p[np.asarray(te)] = pr
    return p


# ---------------- splitters ----------------
def loocv_splits(n):
    idx = np.arange(n); return [(np.delete(idx, i), np.array([i])) for i in idx]


def event_groups(df, days=3):
    order = df.sort_values("dt").index; grp = np.zeros(len(df), int); g = 0; prev = None
    for i in order:
        if prev is not None and (df.dt[i] - df.dt[prev]).days > days:
            g += 1
        grp[i] = g; prev = i
    return grp


def group_splits(df):
    grp = event_groups(df); idx = np.arange(len(df))
    return [(idx[grp != g], idx[grp == g]) for g in np.unique(grp)]


def forward_split(df, cutoff):
    c = pd.Timestamp(cutoff); idx = np.arange(len(df))
    return [(idx[df.dt < c], idx[df.dt >= c])]


CUTOFFS = ["2022-07-01", "2023-01-01", "2023-07-01", "2024-01-01", "2024-07-01", "2025-01-01", "2025-07-01"]


# ---------------- metrics ----------------
def wilson(k, n, conf=0.95):
    if n == 0: return (np.nan, np.nan)
    z = stats.norm.ppf(1 - (1 - conf) / 2); p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def summ(y, p, thr=0.5, mask=None):
    m = ~np.isnan(p) if mask is None else mask & ~np.isnan(p)
    yy, pp = y[m], p[m]; pr = (pp >= thr).astype(int)
    tp = int(((pr == 1) & (yy == 1)).sum()); fp = int(((pr == 1) & (yy == 0)).sum())
    auc = roc_auc_score(yy, pp) if 0 < yy.sum() < len(yy) else np.nan
    return dict(n=int(m.sum()), npos=int(yy.sum()), acc=float((pr == yy).mean()), auc=float(auc), tp=tp, fp=fp,
                nneg=int((yy == 0).sum()), brier=float(np.mean((pp - yy) ** 2)), recall=tp / max(int(yy.sum()), 1))


def fmt(s):
    lo, hi = wilson(s["tp"], s["npos"])
    return (f"acc {s['acc']:.3f}; AUC {s['auc']:.3f}; manip {s['tp']}/{s['npos']} (Wilson {lo:.2f}-{hi:.2f}); "
            f"FA {s['fp']}/{s['nneg']}; Brier {s['brier']:.3f}")


def mcnemar(y, p1, p2, thr=0.5, mask=None):
    """Exact McNemar on correctness of two probability predictors. Returns (only1_wrong, only2_wrong, p)."""
    m = ~np.isnan(p1) & ~np.isnan(p2)
    if mask is not None: m &= mask
    a = (p1[m] >= thr).astype(int) != y[m]; b = (p2[m] >= thr).astype(int) != y[m]
    n1 = int((a & ~b).sum()); n2 = int((b & ~a).sum())
    p = 1.0 if n1 + n2 == 0 else float(stats.binomtest(min(n1, n2), n1 + n2, 0.5).pvalue)
    return n1, n2, p


def boot_ci(fn, y, B=2000, seed=0, *arrs):
    rng = np.random.default_rng(seed); n = len(y); v = []
    for _ in range(B):
        s = rng.integers(0, n, n); v.append(fn(*(a[s] for a in (y,) + arrs)))
    return np.nanpercentile(v, [2.5, 97.5])
