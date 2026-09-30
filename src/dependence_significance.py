import warnings, numpy as np, pandas as pd
from scipy.stats import binomtest
from sklearn.ensemble import RandomForestClassifier
from models import load_data, RESERVE_SKEW_CLIP, predict_bayesian_network
from n162_experiments import bn_fit, MAN, VOL, CL
warnings.filterwarnings("ignore")
ALW=['heartbeat_elapsed','reserve_skew','ref_realized_vol','temporal_deviation_persistence','temporal_slope','temporal_step_change_count','temporal_gap_trend','reserve_skew_localization']
df=load_data(); df=df[df.label.isin(CL)].reset_index(drop=True)
df["dt"]=pd.to_datetime(df["date"])
y=(df.label==MAN).astype(int).values
X=df[ALW].replace([np.inf,-np.inf],RESERVE_SKEW_CLIP).astype(float)

# ---- event clusters: incidents within 3 days of each other (single-linkage) ----
order=df.sort_values("dt").index; grp=np.zeros(len(df),int); g=0; prev=None
for i in order:
    if prev is not None and (df.dt[i]-df.dt[prev]).days>3: g+=1
    grp[i]=g; prev=i
df["grp"]=grp
sizes=df.groupby("grp").size()
print(f"TASK3 dependence: {len(df)} incidents fall into {len(sizes)} date-clusters (<=3 days apart); "
      f"{(sizes>1).sum()} clusters have >1 incident, largest={sizes.max()}")
print("  exact same-date duplicates:", int(df.duplicated('date',keep=False).sum()), "incidents share a date with another")
multi=df[df.grp.isin(sizes[sizes>1].index)].groupby("grp").agg(n=("incident","size"),labels=("label",lambda s:",".join(sorted(set(x[:5] for x in s)))),first=("date","min")).sort_values("n",ascending=False).head(8)
print(multi.to_string())

def rf_pred(tr_idx, te_idx):
    med=X.iloc[tr_idx].median()
    c=RandomForestClassifier(n_estimators=150,random_state=0).fit(X.iloc[tr_idx].fillna(med).values,y[tr_idx])
    return c.predict_proba(X.iloc[te_idx].fillna(med).values)[:,list(c.classes_).index(1)]
def bn_pred(tr_idx, te_idx):
    m,th=bn_fit(df.iloc[tr_idx].drop(columns=["dt","grp"],errors="ignore")); return np.array([predict_bayesian_network(m,th,df.drop(columns=["dt","grp"],errors="ignore").iloc[j])[0][MAN] for j in te_idx])
def evaluate(splitter,name):
    out={}
    for mname,fn in [("RF",rf_pred),("BN",bn_pred)]:
        p=np.full(len(df),np.nan)
        for tr,te in splitter(): p[te]=fn(tr,te)
        m=~np.isnan(p); pr=(p[m]>=.5).astype(int); yy=y[m]
        out[mname]=p
        print(f"  {name:28s} {mname}: n={m.sum()} acc={(pr==yy).mean():.3f} manip={int(((pr==1)&(yy==1)).sum())}/{int(yy.sum())} falseAlarms={int(((pr==1)&(yy==0)).sum())}/{int((yy==0).sum())}")
    return out
idx=np.arange(len(df))
print("\nLOOCV vs grouped-by-event CV vs forward-in-time:")
loo=evaluate(lambda:[(np.delete(idx,i),[i]) for i in idx],"plain LOOCV")
evaluate(lambda:[(idx[df.grp!=g],idx[df.grp==g]) for g in sizes.index],"leave-one-event-cluster-out")
cut=pd.Timestamp("2024-01-01")
evaluate(lambda:[(idx[df.dt<cut],idx[df.dt>=cut])],f"train<2024, test>=2024")

# ---- TASK4 significance: BN vs RF on plain LOOCV ----
pb=(loo["BN"]>=.5).astype(int); pr=(loo["RF"]>=.5).astype(int)
bw=int(((pb!=y)&(pr==y)).sum()); rw=int(((pr!=y)&(pb==y)).sum())
p=binomtest(bw,bw+rw,0.5).pvalue if bw+rw>0 else 1.0
print(f"\nTASK4 McNemar BN vs RF: BN-only errors={bw}, RF-only errors={rw}, exact p={p:.3f}")
rng=np.random.default_rng(0); B=5000
bb=2*(loo["BN"]-y)**2; br=2*(loo["RF"]-y)**2; d=[]
for _ in range(B):
    s=rng.integers(0,len(y),len(y)); d.append(bb[s].mean()-br[s].mean())
print(f"  Brier BN={bb.mean():.3f} RF={br.mean():.3f}; diff 95% CI [{np.percentile(d,2.5):.3f}, {np.percentile(d,97.5):.3f}]")
man=y==1
print(f"  manipulation recall BN={(pb[man]==1).mean():.3f} RF={(pr[man]==1).mean():.3f} (identical sets: {bool(((pb==1)&man).tolist()==((pr==1)&man).tolist())})")
