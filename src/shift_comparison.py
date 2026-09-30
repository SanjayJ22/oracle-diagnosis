"""Distribution-shift robustness across ALL models (not just discretization schemes).
Applies the same fold-level training perturbations from discretization_robustness.py
to NB, BN(fixed), RandomForest(no-miss), LogisticRegression(no-miss), and measures
how much each degrades. Held-out evaluation incident is never perturbed."""
import warnings, numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import f1_score
from models import (LABELS, FEATURE_COLS, RESERVE_SKEW_CLIP, load_data,
                    _fit_gaussian_nb, naive_bayes_posterior,
                    fit_bayesian_network, predict_bayesian_network)
from discretization_robustness import no_perturb, oversample_calm_volatility, combined_perturb
warnings.filterwarnings("ignore")
VOL = "large volatility event"

PERTS = {
    "baseline": no_perturb,
    "oversample_calm_vol_3x": oversample_calm_volatility,
    "combined_shift": combined_perturb,
}

def metrics(yt, yp):
    yt=np.array(yt); yp=np.array(yp)
    acc=np.mean(yt==yp)
    mrec=np.sum((yp=="manipulation")&(yt=="manipulation"))/max(1,np.sum(yt=="manipulation"))
    mf1=f1_score(yt,yp,labels=LABELS,average="macro",zero_division=0)
    return acc,mrec,mf1

def loocv_nb(df, pfn):
    yp=[]
    for i in range(len(df)):
        te=df.iloc[i]; tr=pfn(df.drop(df.index[i]))
        priors={l:(tr["label"]==l).mean() for l in LABELS}
        stats=_fit_gaussian_nb(tr)
        post=naive_bayes_posterior(te,stats,priors)
        yp.append(max(post,key=post.get))
    return df["label"].values, yp

def loocv_bn(df, pfn):
    yp=[]
    for i in range(len(df)):
        te=df.iloc[i]; tr=pfn(df.drop(df.index[i]))
        model,th=fit_bayesian_network(tr,verbose=False,discretization="fixed")
        if model is None: yp.append(None); continue
        post,_=predict_bayesian_network(model,th,te); yp.append(max(post,key=post.get))
    return df["label"].values, yp

def loocv_sk(df, pfn, kind):
    yp=[]
    for i in range(len(df)):
        te=df.iloc[[i]]; tr=pfn(df.drop(df.index[i]))
        Xtr=tr[FEATURE_COLS].replace([np.inf,-np.inf],RESERVE_SKEW_CLIP).astype(float)
        med=Xtr.median()
        Xtr_=Xtr.fillna(med).values
        Xte_=te[FEATURE_COLS].replace([np.inf,-np.inf],RESERVE_SKEW_CLIP).astype(float).fillna(med).values
        ytr=tr["label"].values
        if kind=="logreg":
            sc=StandardScaler().fit(Xtr_); clf=LogisticRegression(max_iter=2000)
            clf.fit(sc.transform(Xtr_),ytr); yp.append(clf.predict(sc.transform(Xte_))[0])
        else:
            clf=RandomForestClassifier(n_estimators=150,random_state=0); clf.fit(Xtr_,ytr); yp.append(clf.predict(Xte_)[0])
    return df["label"].values, yp

MODELS={"NB":lambda d,p:loocv_nb(d,p),
        "BN(fixed)":lambda d,p:loocv_bn(d,p),
        "RF(no-miss)":lambda d,p:loocv_sk(d,p,"rf"),
        "LogReg(no-miss)":lambda d,p:loocv_sk(d,p,"logreg")}

def main():
    df=load_data().reset_index(drop=True)
    res={}
    for mname,fn in MODELS.items():
        for pname,pfn in PERTS.items():
            yt,yp=fn(df,pfn)
            yp=[x if x is not None else "large volatility event" for x in yp]
            acc,mrec,mf1=metrics(yt,yp)
            res[(mname,pname)]=(acc,mrec,mf1)
            print(f"{mname:16s} {pname:22s} acc={acc:.3f} manip_recall={mrec:.3f} macroF1={mf1:.3f}",flush=True)
    print("\n"+"="*74)
    print("DEGRADATION baseline -> combined_shift (accuracy / manipulation recall):")
    for mname in MODELS:
        a0,r0,_=res[(mname,"baseline")]; a1,r1,_=res[(mname,"combined_shift")]
        print(f"  {mname:16s} acc {a0:.3f} -> {a1:.3f} (drop {a0-a1:+.3f})   "
              f"manip_recall {r0:.3f} -> {r1:.3f} (drop {r0-r1:+.3f})")

if __name__=="__main__":
    main()
