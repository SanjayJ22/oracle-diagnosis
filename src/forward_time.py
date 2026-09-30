import warnings, numpy as np, pandas as pd
from scipy.stats import binomtest, mannwhitneyu
from sklearn.ensemble import RandomForestClassifier
from models import load_data, RESERVE_SKEW_CLIP, predict_bayesian_network
from n162_experiments import bn_fit, nb_fit_pred, MAN, CL
warnings.filterwarnings("ignore")
ALW=['heartbeat_elapsed','reserve_skew','ref_realized_vol','temporal_deviation_persistence','temporal_slope','temporal_step_change_count','temporal_gap_trend','reserve_skew_localization']
df=load_data(); df=df[df.label.isin(CL)].reset_index(drop=True); dt=pd.to_datetime(df.date)
y=(df.label==MAN).astype(int).values
X=df[ALW].replace([np.inf,-np.inf],RESERVE_SKEW_CLIP).astype(float)
print("cutoff      n_tr(m) n_te(m) | RF acc  manip  FA      | BN acc  manip  FA     | NB acc  FA     | McNemar p (BN vs RF)")
for cut in ["2022-07-01","2023-01-01","2023-07-01","2024-01-01","2024-07-01","2025-01-01","2025-07-01"]:
    c=pd.Timestamp(cut); tr=np.where(dt<c)[0]; te=np.where(dt>=c)[0]
    if y[tr].sum()<3 or y[te].sum()<2: continue
    med=X.iloc[tr].median()
    rf=RandomForestClassifier(n_estimators=300,random_state=0).fit(X.iloc[tr].fillna(med).values,y[tr])
    pr=(rf.predict_proba(X.iloc[te].fillna(med).values)[:,1]>=.5).astype(int)
    m,th=bn_fit(df.iloc[tr]); pb=np.array([predict_bayesian_network(m,th,df.iloc[j])[0][MAN]>=.5 for j in te]).astype(int)
    pn=np.array([nb_fit_pred(df.iloc[tr],df.iloc[j])>=.5 for j in te]).astype(int)
    yt=y[te]
    f=lambda p:(f"{(p==yt).mean():.3f} {int(((p==1)&(yt==1)).sum()):2d}/{int(yt.sum()):<2d} {int(((p==1)&(yt==0)).sum()):2d}/{int((yt==0).sum()):<3d}")
    bw=int(((pb!=yt)&(pr==yt)).sum()); rw=int(((pr!=yt)&(pb==yt)).sum())
    pv=binomtest(min(bw,rw),bw+rw,0.5).pvalue if bw+rw else 1.0
    print(f"{cut}  {len(tr):3d}({y[tr].sum():2d})  {len(te):3d}({yt.sum():2d}) | {f(pr)} | {f(pb)} | {(pn==yt).mean():.3f} {int(((pn==1)&(yt==0)).sum()):2d} | {pv:.4f}")
print("\nDRIFT in volatility-class features, pre-2024 vs 2024+ (Mann-Whitney p):")
v=df.label!=MAN
for col in ALW:
    a=X.loc[v&(dt<"2024-01-01"),col].dropna(); b=X.loc[v&(dt>="2024-01-01"),col].dropna()
    print(f"  {col:32s} median {a.median():>10.4g} -> {b.median():>10.4g}   p={mannwhitneyu(a,b).pvalue:.2g}")
