import warnings, numpy as np, pandas as pd
from sklearn.ensemble import RandomForestClassifier
from models import load_data, RESERVE_SKEW_CLIP
from n162_experiments import bn_fit, CL, MAN, VOL
from models import predict_bayesian_network
warnings.filterwarnings("ignore")
ALW=['heartbeat_elapsed','reserve_skew','ref_realized_vol','temporal_deviation_persistence','temporal_slope','temporal_step_change_count','temporal_gap_trend','reserve_skew_localization']
df=load_data(); df=df[df.label.isin(CL)].reset_index(drop=True)
X=df[ALW].replace([np.inf,-np.inf],RESERVE_SKEW_CLIP).astype(float)
bn,rf,bnp,rfp=[],[],[],[]
for i in range(len(df)):
    tr=df.drop(df.index[i]); te=df.iloc[i]
    m,th=bn_fit(tr); p=float(predict_bayesian_network(m,th,te)[0][MAN]); bnp.append(p); bn.append(MAN if p>=.5 else VOL)
    idx=[j for j in range(len(df)) if j!=i]
    c=RandomForestClassifier(n_estimators=150,random_state=0).fit(X.iloc[idx].values,df.label.values[idx])
    q=c.predict_proba(X.iloc[[i]].values)[0][list(c.classes_).index(MAN)]; rfp.append(q); rf.append(MAN if q>=.5 else VOL)
df["bn"],df["rf"],df["p_bn"],df["p_rf"]=bn,rf,bnp,rfp
err=df[(df.bn!=df.label)|(df.rf!=df.label)][["incident","label","bn","p_bn","rf","p_rf","reserve_skew","reserve_skew_localization"]]
pd.set_option("display.width",220); print(err.to_string(index=False,float_format=lambda v:f"{v:.3g}"))
print("\nBN errors:",int((df.bn!=df.label).sum()),"RF errors:",int((df.rf!=df.label).sum()))
