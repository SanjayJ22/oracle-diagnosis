"""Does the baseline dominance come from real signal or from the missingness
indicators (which are near-label proxies per structure_learning.md)?
Run LogReg/RF with and without the _miss columns."""
import warnings, numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import f1_score
from models import load_data, LABELS, FEATURE_COLS, RESERVE_SKEW_CLIP
warnings.filterwarnings("ignore")
VOL="large volatility event"

def loocv(df, classes, cols, kind, use_miss):
    yt=df["label"].values; preds=[]
    for i in range(len(df)):
        idx=[j for j in range(len(df)) if j!=i]
        Xall=df[cols].replace([np.inf,-np.inf],RESERVE_SKEW_CLIP).astype(float)
        med=Xall.iloc[idx].median()
        def build(rows):
            Xv=df.loc[rows,cols].replace([np.inf,-np.inf],RESERVE_SKEW_CLIP).astype(float)
            base=Xv.fillna(med).values
            if use_miss:
                return np.hstack([base, Xv.isna().astype(float).values])
            return base
        Xtr=build(df.index[idx]); Xte=build([df.index[i]]); ytr=df["label"].values[idx]
        if kind=="logreg":
            sc=StandardScaler().fit(Xtr); clf=LogisticRegression(max_iter=2000)
            clf.fit(sc.transform(Xtr),ytr); p=clf.predict_proba(sc.transform(Xte))[0]
        else:
            clf=RandomForestClassifier(n_estimators=150,random_state=0); clf.fit(Xtr,ytr); p=clf.predict_proba(Xte)[0]
        pmap={c:0.0 for c in classes}
        for c,pp in zip(clf.classes_,p): pmap[c]=pp
        preds.append(classes[int(np.argmax([pmap[c] for c in classes]))])
    preds=np.array(preds)
    acc=np.mean(preds==yt); mf1=f1_score(yt,preds,labels=classes,average="macro",zero_division=0)
    mrec=np.sum((preds=="manipulation")&(yt=="manipulation"))/max(1,np.sum(yt=="manipulation"))
    return acc,mf1,mrec

df=load_data().reset_index(drop=True)
df2=df[df["label"].isin(["manipulation",VOL])].reset_index(drop=True)
for tag,dd,classes in [("3-class",df,LABELS),("2-class manip/vol",df2,["manipulation",VOL])]:
    print(f"\n=== {tag} ===")
    for kind in ["logreg","rf"]:
        for use_miss in [True,False]:
            a,f,r=loocv(dd,classes,FEATURE_COLS,kind,use_miss)
            print(f"  {kind:7s} miss={use_miss!s:5s} acc={a:.3f} macroF1={f:.3f} manip_recall={r:.3f}")
