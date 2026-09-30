"""Reviewer-hardening analyses for the CJSJ paper (evaluation only; imports the
production pipeline read-only, changes no model or feature).

Produces:
  #1 manipulation-vs-volatility two-class LOOCV (n=162, malfunction dropped)
  #2 strong baselines: multinomial logistic regression + random forest
  #3 confusion matrices, per-class P/R/F1, macro-F1, bootstrap 95% CIs
  #4 risk-coverage (selective prediction) curve, BN vs NB
"""
import warnings, json
from pathlib import Path
REPORTS = Path(__file__).resolve().parent.parent / "reports"
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import f1_score, confusion_matrix
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from models import (
    load_data, LABELS, FEATURE_COLS, RESERVE_SKEW_CLIP,
    BN_EDGES, BN_RAW_TO_DISCRETE, BN_STATE_NAMES, FIXED_THRESHOLDS, _bn_clean,
    predict_bayesian_network,
)
from loocv_validation import loocv_naive_bayes, loocv_bayesian_network
from two_class_analysis import (
    loocv_naive_bayes_2class, _fit_gaussian_nb_2class, _naive_bayes_posterior_2class,
)

warnings.filterwarnings("ignore")
rng = np.random.default_rng(0)
VOL = "large volatility event"

# ----------------------------------------------------------------------------
# generic metric helpers (work for any class list + posterior matrix)
# ----------------------------------------------------------------------------
def brier(y_true, P, classes):
    idx = {c: k for k, c in enumerate(classes)}
    s = 0.0
    for yt, p in zip(y_true, P):
        oh = np.zeros(len(classes)); oh[idx[yt]] = 1.0
        s += ((p - oh) ** 2).sum()
    return s / len(y_true)

def logloss(y_true, P, classes):
    idx = {c: k for k, c in enumerate(classes)}
    e = 1e-15; s = 0.0
    for yt, p in zip(y_true, P):
        pt = min(max(p[idx[yt]], e), 1 - e); s += -np.log(pt)
    return s / len(y_true)

ECE_BINS = [(0.9, 1.01), (0.7, 0.9), (0.5, 0.7), (0.0, 0.5)]
def ece(y_true, y_pred, conf):
    n = len(y_true); tot = 0.0
    for lo, hi in ECE_BINS:
        m = (conf >= lo) & (conf < hi)
        if m.sum() == 0: continue
        acc = np.mean(np.array(y_true)[m] == np.array(y_pred)[m])
        tot += (m.sum() / n) * abs(conf[m].mean() - acc)
    return tot

def macro_f1(y_true, y_pred, classes):
    return f1_score(y_true, y_pred, labels=classes, average="macro", zero_division=0)

def per_class(y_true, y_pred, classes):
    out = {}
    yt = np.array(y_true); yp = np.array(y_pred)
    for c in classes:
        tp = int(((yp == c) & (yt == c)).sum())
        pp = int((yp == c).sum()); ap = int((yt == c).sum())
        prec = tp / pp if pp else float("nan")
        rec = tp / ap if ap else float("nan")
        f1 = 2 * prec * rec / (prec + rec) if (pp and ap and prec + rec > 0) else float("nan")
        out[c] = dict(precision=prec, recall=rec, f1=f1, support=ap)
    return out

def boot_ci(y_true, y_pred, fn, B=2000):
    yt = np.array(y_true); yp = np.array(y_pred); n = len(yt); vals = []
    for _ in range(B):
        ix = rng.integers(0, n, n)
        vals.append(fn(yt[ix], yp[ix]))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))

# ----------------------------------------------------------------------------
# sklearn baselines under LOOCV (median impute + missingness indicators)
# ----------------------------------------------------------------------------
def make_X(df, cols):
    X = df[cols].replace([np.inf, -np.inf], RESERVE_SKEW_CLIP).astype(float)
    miss = X.isna().astype(float)
    miss.columns = [c + "_miss" for c in cols]
    med = X.median()
    Xi = X.fillna(med)
    return pd.concat([Xi, miss], axis=1).values, med

def loocv_sklearn(df, classes, cols, kind):
    y = df["label"].values
    preds, confs, P = [], [], []
    for i in range(len(df)):
        tr = df.drop(df.index[i]); te = df.iloc[[i]]
        Xtr = df[cols].replace([np.inf, -np.inf], RESERVE_SKEW_CLIP).astype(float)
        med = Xtr.iloc[[j for j in range(len(df)) if j != i]].median()
        def build(rows):
            Xv = df.loc[rows, cols].replace([np.inf, -np.inf], RESERVE_SKEW_CLIP).astype(float)
            missv = Xv.isna().astype(float)
            return np.hstack([Xv.fillna(med).values, missv.values])
        Xtr_ = build(tr.index); Xte_ = build(te.index)
        ytr = tr["label"].values
        if kind == "logreg":
            sc = StandardScaler().fit(Xtr_)
            clf = LogisticRegression(max_iter=2000, C=1.0)
            clf.fit(sc.transform(Xtr_), ytr)
            proba = clf.predict_proba(sc.transform(Xte_))[0]
        else:
            clf = RandomForestClassifier(n_estimators=150, random_state=0)
            clf.fit(Xtr_, ytr); proba = clf.predict_proba(Xte_)[0]
        pmap = {c: 0.0 for c in classes}
        for c, p in zip(clf.classes_, proba): pmap[c] = p
        vec = np.array([pmap[c] for c in classes])
        pred = classes[int(vec.argmax())]
        preds.append(pred); confs.append(vec.max()); P.append(vec)
    return np.array(preds), np.array(confs), np.array(P)

# ----------------------------------------------------------------------------
# BN fit generic over label states (for manip-vs-vol 2-class)
# ----------------------------------------------------------------------------
def fit_bn_generic(df, label_states):
    from pgmpy.estimators import BayesianEstimator
    from pgmpy.models import DiscreteBayesianNetwork
    state_names = {**BN_STATE_NAMES, "label_d": label_states}
    work = df.copy(); work["label_d"] = work["label"]; thresholds = {}
    for raw_col, (disc_col, prefix) in BN_RAW_TO_DISCRETE.items():
        cleaned = work[raw_col].apply(lambda v, c=raw_col: _bn_clean(c, v))
        mag = cleaned.abs(); t = FIXED_THRESHOLDS[raw_col]; thresholds[raw_col] = t
        work[disc_col] = mag.apply(lambda m, tt=t, p=prefix: np.nan if pd.isna(m) else (f"{p}_high" if m > tt else f"{p}_low"))
    model = DiscreteBayesianNetwork(BN_EDGES); cpds = []
    for node in model.nodes():
        parents = list(model.get_parents(node)); cols = [node] + parents
        comp = work.dropna(subset=cols)
        if len(comp) == 0: return None, thresholds
        est = BayesianEstimator(model, comp, state_names={c: state_names[c] for c in cols})
        cpds.append(est.estimate_cpd(node, prior_type="BDeu", equivalent_sample_size=2))
    model.add_cpds(*cpds)
    if not model.check_model(): return None, thresholds
    return model, thresholds

def loocv_bn_generic(df, label_states):
    preds, confs, P = [], [], []
    for i in range(len(df)):
        te = df.iloc[i]; tr = df.drop(df.index[i])
        model, th = fit_bn_generic(tr, label_states)
        if model is None:
            preds.append(None); confs.append(np.nan); P.append(np.array([np.nan]*len(label_states))); continue
        post, _ = predict_bayesian_network(model, th, te)
        vec = np.array([post[c] for c in label_states])
        preds.append(label_states[int(vec.argmax())]); confs.append(vec.max()); P.append(vec)
    return np.array(preds), np.array(confs), np.array(P)

# ----------------------------------------------------------------------------
def summarize(name, y_true, y_pred, conf, P, classes):
    acc = np.mean(np.array(y_true) == np.array(y_pred))
    mf1 = macro_f1(y_true, y_pred, classes)
    return dict(name=name, acc=acc, macro_f1=mf1,
                brier=brier(y_true, P, classes), ece=ece(y_true, y_pred, conf),
                logloss=logloss(y_true, P, classes),
                per_class=per_class(y_true, y_pred, classes))

def fmt(m):
    return f"{m['name']:34s} acc={m['acc']:.3f} macroF1={m['macro_f1']:.3f} Brier={m['brier']:.3f} ECE={m['ece']:.3f} logloss={m['logloss']:.3f}"

def main():
    df = load_data().reset_index(drop=True)
    classes3 = LABELS
    print("="*90); print("DATA:", dict(df["label"].value_counts())); print("="*90)

    # ---- 3-class LOOCV: NB, BN (from production code) ----
    nb3 = loocv_naive_bayes(df); bn3 = loocv_bayesian_network(df)
    def to_PC(res):
        cols = {"manipulation":"p_manipulation","malfunction":"p_malfunction",VOL:"p_volatility"}
        P = res[[cols[c] for c in classes3]].values
        return res["label"].values, res["pred"].values, res["confidence"].values, P
    yt, yp_nb, cf_nb, P_nb = to_PC(nb3)
    _,  yp_bn, cf_bn, P_bn = to_PC(bn3)
    m_nb3 = summarize("NB 3-class", yt, yp_nb, cf_nb, P_nb, classes3)
    m_bn3 = summarize("BN 3-class", yt, yp_bn, cf_bn, P_bn, classes3)

    # sklearn baselines 3-class
    results3 = [m_nb3, m_bn3]
    for kind, lab in [("logreg","LogReg 3-class"),("rf","RandomForest 3-class")]:
        yp, cf, P = loocv_sklearn(df, classes3, FEATURE_COLS, kind)
        results3.append(summarize(lab, df["label"].values, yp, cf, P, classes3))

    print("\n#2 BASELINE COMPARISON — three-class LOOCV (n=165)")
    for m in results3: print("  ", fmt(m))

    # ---- #3 confusion + per-class + bootstrap CI for BN 3-class ----
    print("\n#3 BN three-class — confusion (rows=true, cols=pred):")
    cm = confusion_matrix(yt, yp_bn, labels=classes3)
    print("   ", " ".join(f"{c[:11]:>12s}" for c in classes3))
    for r, c in zip(cm, classes3): print(f"   {c[:11]:>12s} " + " ".join(f"{v:12d}" for v in r))
    print("   per-class:")
    for c, d in m_bn3["per_class"].items():
        print(f"     {c:24s} P={d['precision']:.3f} R={d['recall']:.3f} F1={d['f1']:.3f} n={d['support']}")
    acc_ci = boot_ci(yt, yp_bn, lambda a,b: np.mean(a==b))
    mf1_ci = boot_ci(yt, yp_bn, lambda a,b: macro_f1(a,b,classes3))
    mrec_ci = boot_ci(yt, yp_bn, lambda a,b: (np.sum((b=='manipulation')&(a=='manipulation'))/max(1,np.sum(a=='manipulation'))))
    print(f"   bootstrap 95% CI: acc={m_bn3['acc']:.3f} {tuple(round(x,3) for x in acc_ci)}"
          f"  macroF1={m_bn3['macro_f1']:.3f} {tuple(round(x,3) for x in mf1_ci)}"
          f"  manip_recall {tuple(round(x,3) for x in mrec_ci)}")

    # ---- #1 manipulation-vs-volatility two-class (n=162) ----
    df2 = df[df["label"].isin(["manipulation", VOL])].reset_index(drop=True)
    classes2 = ["manipulation", VOL]
    print("\n#1 MANIPULATION vs VOLATILITY two-class (n=%d): %s" % (len(df2), dict(df2["label"].value_counts())))
    # NB 2-class (reuse generalized funcs)
    def loocv_nb2(dd):
        preds,confs,P=[],[],[]
        for i in range(len(dd)):
            te=dd.iloc[i]; tr=dd.drop(dd.index[i])
            priors={l:(tr["label"]==l).mean() for l in classes2}
            stats=_fit_gaussian_nb_2class(tr, classes2)
            post=_naive_bayes_posterior_2class(te, stats, priors, classes2)
            vec=np.array([post[c] for c in classes2])
            preds.append(classes2[int(vec.argmax())]); confs.append(vec.max()); P.append(vec)
        return np.array(preds),np.array(confs),np.array(P)
    yp_nb2,cf_nb2,P_nb2 = loocv_nb2(df2)
    yp_bn2,cf_bn2,P_bn2 = loocv_bn_generic(df2, classes2)
    yt2 = df2["label"].values
    res2 = [summarize("NB 2-class", yt2,yp_nb2,cf_nb2,P_nb2,classes2),
            summarize("BN 2-class", yt2,yp_bn2,cf_bn2,P_bn2,classes2)]
    for kind,lab in [("logreg","LogReg 2-class"),("rf","RandomForest 2-class")]:
        yp,cf,P = loocv_sklearn(df2, classes2, FEATURE_COLS, kind)
        res2.append(summarize(lab, yt2, yp, cf, P, classes2))
    for m in res2: print("  ", fmt(m))
    print("   BN 2-class confusion (rows=true, cols=pred):")
    cm2 = confusion_matrix(yt2, yp_bn2, labels=classes2)
    print("   ", " ".join(f"{c[:11]:>12s}" for c in classes2))
    for r,c in zip(cm2, classes2): print(f"   {c[:11]:>12s} " + " ".join(f"{v:12d}" for v in r))
    for c,d in res2[1]["per_class"].items():
        print(f"     {c:24s} P={d['precision']:.3f} R={d['recall']:.3f} F1={d['f1']:.3f} n={d['support']}")
    acc2_ci = boot_ci(yt2, yp_bn2, lambda a,b: np.mean(a==b))
    mrec2_ci = boot_ci(yt2, yp_bn2, lambda a,b:(np.sum((b=='manipulation')&(a=='manipulation'))/max(1,np.sum(a=='manipulation'))))
    print(f"   bootstrap 95% CI: acc={res2[1]['acc']:.3f} {tuple(round(x,3) for x in acc2_ci)}"
          f"  manip_recall {tuple(round(x,3) for x in mrec2_ci)}")

    # malfunction as case study: run production 3-class BN, report its calls on the 3 malfunction incidents
    mal = bn3[bn3["label"]=="malfunction"][["incident","pred","confidence"]]
    print("\n   malfunction case study (production 3-class BN calls on the 3 incidents):")
    print(mal.to_string(index=False))

    # ---- #4 risk-coverage (selective prediction), 3-class BN vs NB ----
    def risk_cov(conf, correct):
        xs, ys = [], []
        for tau in np.linspace(0.34, 1.0, 34):
            m = conf >= tau
            if m.sum()==0: continue
            xs.append(m.mean()); ys.append(np.mean(np.array(correct)[m]))
        return xs, ys
    corr_bn = (yp_bn==yt); corr_nb=(yp_nb==yt)
    xb,yb = risk_cov(cf_bn, corr_bn); xn,yn = risk_cov(cf_nb, corr_nb)
    plt.figure(figsize=(6.2,4.2))
    plt.plot(xb,yb,"-o",ms=3,label="Bayesian network",color="#1f4e79")
    plt.plot(xn,yn,"-s",ms=3,label="Naive Bayes",color="#c0392b")
    plt.xlabel("Coverage (fraction of incidents auto-decided)")
    plt.ylabel("Selective accuracy (on auto-decided)")
    plt.title("Risk-coverage: calibrated deferral (3-class LOOCV)")
    plt.grid(alpha=.3); plt.legend(); plt.tight_layout()
    plt.savefig(REPORTS / "risk_coverage.png", dpi=200)
    # concrete operating points
    print("\n#4 risk-coverage operating points (3-class):")
    for tau in [0.7,0.8,0.9]:
        for nm,cf,corr in [("BN",cf_bn,corr_bn),("NB",cf_nb,corr_nb)]:
            m=cf>=tau
            print(f"   tau={tau} {nm}: coverage={m.mean():.2f} selective_acc={(np.mean(corr[m]) if m.sum() else float('nan')):.3f} deferred={1-m.mean():.2f}")

    # dump machine-readable summary
    out = dict(three_class=[{k:v for k,v in m.items() if k!='per_class'} for m in results3],
               two_class=[{k:v for k,v in m.items() if k!='per_class'} for m in res2],
               bn3_per_class=m_bn3["per_class"], bn2_per_class=res2[1]["per_class"],
               ci=dict(acc3=acc_ci,mf13=mf1_ci,mrec3=mrec_ci,acc2=acc2_ci,mrec2=mrec2_ci))
    open(REPORTS / "extras_summary.json","w").write(json.dumps(out,indent=2,default=float))
    print("\nSaved risk_coverage.png and extras_summary.json")

if __name__ == "__main__":
    main()
