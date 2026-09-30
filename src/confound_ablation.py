"""Construct/selection confound test. Volatility incidents were SELECTED as large
ETH/USD moves and all their features are measured on ETH instruments; for 23/24
manipulations, heartbeat/ref_vol/temporal features are ETH/USD 'fallback' context,
not the attacked asset. If ETH-context features alone predict the label, the
classifier can succeed by detecting 'was ETH moving' = the volatility selection rule."""
import warnings, numpy as np, pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score
from models import load_data, RESERVE_SKEW_CLIP
warnings.filterwarnings("ignore")
MAN,VOL="manipulation","large volatility event"
df=load_data(); df=df[df.label.isin([MAN,VOL])].reset_index(drop=True)
y=(df.label==MAN).astype(int).values
GROUPS={
 "ETH-market context only (heartbeat, congestion, ref_vol, 4 temporal)":
   ["heartbeat_elapsed","congestion","ref_realized_vol","temporal_deviation_persistence","temporal_slope","temporal_step_change_count","temporal_gap_trend"],
 "heartbeat_elapsed alone":["heartbeat_elapsed"],
 "temporal features alone":["temporal_deviation_persistence","temporal_slope","temporal_step_change_count","temporal_gap_trend"],
 "venue signal only (reserve_skew)":["reserve_skew"],
 "localization only":["reserve_skew_localization"],
 "venue + localization":["reserve_skew","reserve_skew_localization"],
}
def loocv(cols):
    X=df[cols].replace([np.inf,-np.inf],RESERVE_SKEW_CLIP).astype(float)
    p=np.zeros(len(df))
    for i in range(len(df)):
        tr=[j for j in range(len(df)) if j!=i]; med=X.iloc[tr].median()
        c=RandomForestClassifier(n_estimators=150,random_state=0).fit(X.iloc[tr].fillna(med).values,y[tr])
        p[i]=c.predict_proba(X.iloc[[i]].fillna(med).values)[0][list(c.classes_).index(1)]
    pred=(p>=.5).astype(int)
    return (pred==y).mean(), int(((pred==1)&(y==1)).sum()), int(((pred==1)&(y==0)).sum()), roc_auc_score(y,p)
print(f"majority-class baseline acc = {1-y.mean():.3f}\n")
for name,cols in GROUPS.items():
    a,h,fp,auc=loocv(cols)
    print(f"{name:72s} acc={a:.3f} AUC={auc:.3f} manip={h}/24 falseAlarms={fp}/138")
