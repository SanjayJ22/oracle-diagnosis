"""Primary robustness experiments on the paper's headline task:
manipulation vs large volatility event, n=162 (malfunction excluded, case study only).

Fairness fixes vs shift_comparison.py:
  - sklearn models get the UNION feature set (NB features + reserve_skew_localization)
  - no missingness-indicator columns (known near-label leak)
  - adds class_weight="balanced" RandomForest and LogisticRegression
  - simulated shift repeated over many seeds (manip downsample draw + RF seed)
  - REAL shift: train on original_20/phase1/phase2, test on phase3 (calmer volatility)
"""
import os, sys, time, json, warnings
from pathlib import Path
REPORTS = Path(__file__).resolve().parent.parent / "reports"
import numpy as np, pandas as pd
from multiprocessing import Pool
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import f1_score
from models import (load_data, FEATURE_COLS, RESERVE_SKEW_CLIP, BN_EDGES, BN_RAW_TO_DISCRETE,
                    BN_STATE_NAMES, FIXED_THRESHOLDS, _bn_clean, predict_bayesian_network)
from two_class_analysis import _fit_gaussian_nb_2class, _naive_bayes_posterior_2class
from discretization_robustness import oversample_calm_volatility
warnings.filterwarnings("ignore")

VOL = "large volatility event"; MAN = "manipulation"; CL = [MAN, VOL]
SK_COLS = FEATURE_COLS + ["reserve_skew_localization"]

# ---------------- perturbation (seeded) ----------------
def combined_shift(train, seed):
    t = oversample_calm_volatility(train, multiplier=3)
    man = t[t.label == MAN]; rest = t[t.label != MAN]
    return pd.concat([rest, man.sample(frac=0.5, random_state=seed)], ignore_index=True)

# ---------------- model fit/predict: return P(manipulation) ----------------
def nb_fit_pred(tr, te):
    pri = {l: (tr.label == l).mean() for l in CL}
    st = _fit_gaussian_nb_2class(tr, CL)
    return _naive_bayes_posterior_2class(te, st, pri, CL)[MAN]

def bn_fit(tr):
    from pgmpy.estimators import BayesianEstimator
    from pgmpy.models import DiscreteBayesianNetwork
    sn = {**BN_STATE_NAMES, "label_d": CL}
    w = tr.copy(); w["label_d"] = w["label"]; th = {}
    for raw, (dc, p) in BN_RAW_TO_DISCRETE.items():
        m = w[raw].apply(lambda v, c=raw: _bn_clean(c, v)).abs(); t = FIXED_THRESHOLDS[raw]; th[raw] = t
        w[dc] = m.apply(lambda x, tt=t, pp=p: np.nan if pd.isna(x) else (f"{pp}_high" if x > tt else f"{pp}_low"))
    model = DiscreteBayesianNetwork(BN_EDGES); cpds = []
    for node in model.nodes():
        cols = [node] + list(model.get_parents(node)); comp = w.dropna(subset=cols)
        if len(comp) == 0: return None, th
        cpds.append(BayesianEstimator(model, comp, state_names={c: sn[c] for c in cols})
                    .estimate_cpd(node, prior_type="BDeu", equivalent_sample_size=2))
    model.add_cpds(*cpds)
    return (model if model.check_model() else None), th

def bn_fit_pred(tr, te):
    model, th = bn_fit(tr)
    if model is None: return 0.0
    post, _ = predict_bayesian_network(model, th, te)
    return float(post[MAN])

def sk_mats(tr, te_rows):
    Xtr = tr[SK_COLS].replace([np.inf, -np.inf], RESERVE_SKEW_CLIP).astype(float)
    med = Xtr.median()
    Xte = te_rows[SK_COLS].replace([np.inf, -np.inf], RESERVE_SKEW_CLIP).astype(float).fillna(med)
    return Xtr.fillna(med).values, Xte.values

def sk_fit_pred_many(tr, te_rows, kind, seed=0):
    Xtr, Xte = sk_mats(tr, te_rows); y = tr["label"].values
    if kind.startswith("logreg"):
        sc = StandardScaler().fit(Xtr)
        clf = LogisticRegression(max_iter=3000, class_weight=("balanced" if "bal" in kind else None))
        clf.fit(sc.transform(Xtr), y); P = clf.predict_proba(sc.transform(Xte))
    else:
        clf = RandomForestClassifier(n_estimators=150, random_state=seed, n_jobs=1,
                                     class_weight=("balanced" if "bal" in kind else None))
        clf.fit(Xtr, y); P = clf.predict_proba(Xte)
    return P[:, list(clf.classes_).index(MAN)]

MODELS = ["NB", "BN(fixed)", "RF", "RF(balanced)", "LogReg(balanced)"]

def predict_one(model, tr, te_row, seed):
    if model == "NB": return nb_fit_pred(tr, te_row)
    if model == "BN(fixed)": return bn_fit_pred(tr, te_row)
    kind = {"RF": "rf", "RF(balanced)": "rf_bal", "LogReg(balanced)": "logreg_bal"}[model]
    return float(sk_fit_pred_many(tr, te_row.to_frame().T, kind, seed)[0])

# ---------------- metrics from P(manip) ----------------
def score(y, pman):
    y = np.array(y); p = np.clip(np.array(pman, float), 1e-15, 1 - 1e-15)
    pred = np.where(p >= 0.5, MAN, VOL)
    acc = float(np.mean(pred == y))
    mrec = float(np.sum((pred == MAN) & (y == MAN)) / max(1, np.sum(y == MAN)))
    vrec = float(np.sum((pred == VOL) & (y == VOL)) / max(1, np.sum(y == VOL)))
    mf1 = float(f1_score(y, pred, labels=CL, average="macro", zero_division=0))
    yb = (y == MAN).astype(float)
    brier = float(np.mean(2 * (p - yb) ** 2))           # 2-class multiclass-Brier convention
    ll = float(-np.mean(yb * np.log(p) + (1 - yb) * np.log(1 - p)))
    return dict(acc=acc, manip_recall=mrec, vol_recall=vrec, macro_f1=mf1, brier=brier, logloss=ll,
                manip_hit=int(np.sum((pred == MAN) & (y == MAN))), manip_n=int(np.sum(y == MAN)))

# ---------------- LOOCV job (one model, one condition) ----------------
def loocv_job(args):
    model, cond, seed = args
    df = load_data(); df = df[df.label.isin(CL)].reset_index(drop=True)
    ys, ps = [], []
    for i in range(len(df)):
        te = df.iloc[i]; tr = df.drop(df.index[i])
        if cond == "shift": tr = combined_shift(tr, seed)
        ps.append(predict_one(model, tr, te, seed)); ys.append(te["label"])
    return (model, cond, seed, score(ys, ps))

def cohort_job(model):
    df = load_data(); df = df[df.label.isin(CL)].reset_index(drop=True)
    tr = df[df.cohort != "phase3"].reset_index(drop=True); te = df[df.cohort == "phase3"].reset_index(drop=True)
    if model == "BN(fixed)":
        m, th = bn_fit(tr)
        ps = [float(predict_bayesian_network(m, th, te.iloc[i])[0][MAN]) for i in range(len(te))]
    elif model == "NB":
        ps = [nb_fit_pred(tr, te.iloc[i]) for i in range(len(te))]
    else:
        kind = {"RF": "rf", "RF(balanced)": "rf_bal", "LogReg(balanced)": "logreg_bal"}[model]
        ps = list(sk_fit_pred_many(tr, te, kind, 0))
    return (model, score(te["label"].values, ps))

if __name__ == "__main__":
    SEEDS = list(range(int(sys.argv[1]) if len(sys.argv) > 1 else 10))
    t0 = time.time(); out = {}
    jobs = [(m, "baseline", 0) for m in MODELS] + [(m, "shift", s) for m in MODELS for s in SEEDS]
    with Pool(os.cpu_count()) as pool:
        for model, cond, seed, sc in pool.imap_unordered(loocv_job, jobs):
            out.setdefault(model, {}).setdefault(cond, []).append(sc)
            print(f"[{time.time()-t0:6.0f}s] {model:17s} {cond:8s} seed={seed:2d} "
                  f"acc={sc['acc']:.3f} manip={sc['manip_hit']}/{sc['manip_n']} brier={sc['brier']:.3f}", flush=True)
        cohort = dict(pool.map(cohort_job, MODELS))
    json.dump(dict(loocv=out, cohort=cohort, seeds=SEEDS),
              open(REPORTS / "n162_results.json", "w"), indent=1)
    print(f"DONE in {time.time()-t0:.0f}s")
