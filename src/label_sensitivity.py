"""Label-definition sensitivity. Drops incidents whose OWN reference_note describes a
non-oracle mechanism (rounding/precision, share accounting, redemption curve, MEV-bot
exploit). Categorization is from the project's notes, pending post-mortem confirmation."""
import warnings, numpy as np, pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score
from models import load_data, RESERVE_SKEW_CLIP, predict_bayesian_network
from n162_experiments import bn_fit, MAN, CL
warnings.filterwarnings("ignore")
NON_ORACLE = ["BalancerV2","BalancerV1BPool","BalancerBoostedPool2023","WiseLending",
              "ThetanutsIndexVault","USM","MEVBOTa47b"]
ALW=['heartbeat_elapsed','reserve_skew','ref_realized_vol','temporal_deviation_persistence','temporal_slope','temporal_step_change_count','temporal_gap_trend','reserve_skew_localization']
ETH=["heartbeat_elapsed","congestion","ref_realized_vol","temporal_deviation_persistence","temporal_slope","temporal_step_change_count","temporal_gap_trend"]
base=load_data(); base=base[base.label.isin(CL)].reset_index(drop=True)
def run(df,cols,tag):
    y=(df.label==MAN).astype(int).values; X=df[cols].replace([np.inf,-np.inf],RESERVE_SKEW_CLIP).astype(float)
    prf=np.zeros(len(df)); pbn=np.zeros(len(df))
    for i in range(len(df)):
        tr=[j for j in range(len(df)) if j!=i]; med=X.iloc[tr].median()
        c=RandomForestClassifier(n_estimators=150,random_state=0).fit(X.iloc[tr].fillna(med).values,y[tr])
        prf[i]=c.predict_proba(X.iloc[[i]].fillna(med).values)[0][list(c.classes_).index(1)]
        if cols is ALW:
            m,th=bn_fit(df.iloc[tr]); pbn[i]=predict_bayesian_network(m,th,df.iloc[i])[0][MAN]
    for name,p in ([("RF",prf),("BN",pbn)] if cols is ALW else [("RF-ETHctx",prf)]):
        pr=(p>=.5).astype(int)
        print(f"  {tag:34s} {name:9s} n_manip={y.sum():2d} acc={(pr==y).mean():.3f} AUC={roc_auc_score(y,p):.3f} manip={int(((pr==1)&(y==1)).sum())}/{y.sum()} FA={int(((pr==1)&(y==0)).sum())}")
strict=base[~base.incident.isin(NON_ORACLE)].reset_index(drop=True)
for df,tag in [(base,"all 24 manipulations"),(strict,"oracle-only (17 manipulations)")]:
    run(df,ALW,tag); run(df,ETH,tag)
