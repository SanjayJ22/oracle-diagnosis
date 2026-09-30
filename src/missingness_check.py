import warnings, numpy as np, pandas as pd
from sklearn.ensemble import RandomForestClassifier
from models import load_data, FEATURE_COLS, RESERVE_SKEW_CLIP
warnings.filterwarnings("ignore")
MAN,VOL="manipulation","large volatility event"
COLS=FEATURE_COLS+["reserve_skew_localization"]
df=load_data(); df=df[df.label.isin([MAN,VOL])].reset_index(drop=True)
X=df[COLS].replace([np.inf,-np.inf],RESERVE_SKEW_CLIP).astype(float)
print("MISSING RATE BY CLASS (n=162)")
print((X.isna().groupby(df.label).mean()*100).T.round(0).astype(int).to_string())
def run(cols, mode):
    hits=0; correct=0; rng=np.random.default_rng(0)
    Xa=df[cols].replace([np.inf,-np.inf],RESERVE_SKEW_CLIP).astype(float)
    for i in range(len(df)):
        tr=[j for j in range(len(df)) if j!=i]
        Xtr=Xa.iloc[tr].copy(); Xte=Xa.iloc[[i]].copy()
        if mode=="median":
            med=Xtr.median(); Xtr=Xtr.fillna(med); Xte=Xte.fillna(med)
        else:  # random draw from observed training values: breaks the constant-value signature
            for c in cols:
                obs=Xtr[c].dropna().values
                for M in (Xtr,Xte):
                    m=M[c].isna()
                    if m.any(): M.loc[m,c]=rng.choice(obs,m.sum())
        clf=RandomForestClassifier(n_estimators=150,random_state=0).fit(Xtr.values,df.label.values[tr])
        p=clf.predict(Xte.values)[0]; y=df.label.values[i]
        correct+=(p==y); hits+=(p==MAN and y==MAN)
    return correct/len(df), hits
always=[c for c in COLS if X[c].isna().sum()==0]
print("\nalways-observed features:", always)
for name,cols,mode in [("RF median-impute (current)",COLS,"median"),
                       ("RF random-draw impute",COLS,"random"),
                       ("RF always-observed features only",always,"median")]:
    a,h=run(cols,mode); print(f"{name:34s} acc={a:.3f} manip={h}/24")
