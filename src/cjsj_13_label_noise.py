"""CJSJ item 13: label-noise injection. Question: is the MEVBOTa47b effect (item 8) a general label-noise sensitivity?

Base = verified M (9 positives held out one at a time) + 138 volatility negatives; protocol and models as in cjsj_lc.py (10-fold over negatives,
leave-one-out over positives; XGB fixed config). Conditions, 30 seeds each:
  clean            : no injection
  random flips k=1,2,3 : k random TRAINING negatives relabeled 'manipulation' (fresh draw in every fold). All 138 negatives share the venue
                    (WETH_USDC_V3, audit C1), so a random negative is already 'same venue'.
  targeted flips k=1,2,3 : the k training negatives nearest (standardized ALW feature space, median-imputed) to MEVBOTa47b's feature vector,
                    i.e. the volatility incidents that look most like the MEV-bot exploit on the same pool.
  + MEVBOTa47b     : the real K-category attack added as an extra training positive (never scored) - the item 8 effect in this protocol.
  + each other non-verified attack : one at a time as an extra training positive (5 seeds) - shows how special MEVBOTa47b is.
13d forward-time repeat (where the item 8 effect lives): cutoffs 2023-01, 2023-07, 2024-01; train on verified-M attacks + volatility incidents before the
cutoff, test false alarms on volatility incidents at/after it. Conditions: clean, random flips k=1..3 (30 seeds), targeted flips k=1..3 (deterministic),
+ MEVBOTa47b as an extra positive. BN, RF (300 trees), XGB (fixed config).
Metric: false alarms (of 138 held-out negatives) and recall on the 9 verified positives; 95% bootstrap CI over seeds (fold randomness only).
Raw: reports/cjsj_13_label_noise.csv."""
from cjsj_common import ensure_omp
ensure_omp()
import time
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from cjsj_common import REPORTS, TAG_VERIFIED, write_section
import cjsj_eval as E
import cjsj_lc as LC

MEV = "MEVBOTa47b"


def task(df, pool, extra, mode, k, seed, target, cond):
    r, nn, npool = LC.protocol(df, pool, extra_pos=extra, flip_mode=mode, k_flip=k, seed=seed, target_row=target)
    return cond, seed, r


def fwd_task(base, ver, cut, mode, k, seed, target, extra):
    c = pd.Timestamp(cut); rng = np.random.default_rng(seed)
    neg = np.where((base.dt < c) & (base.label == E.VOL))[0]
    pos = np.where((base.dt < c) & base.incident.isin(list(ver) + list(extra)))[0]
    te = np.where((base.dt >= c) & (base.label == E.VOL))[0]
    d = base
    if k:
        fl = rng.choice(neg, k, replace=False) if mode == "random" else LC.nn_order(base, target, neg)[:k]
        d = base.copy(); d.loc[fl, "label"] = E.MAN
    tr = np.concatenate([neg, pos])
    return {"BN": int((E.bn_proba(d, tr, te) >= .5).sum()), "RF": int((E.rf_proba(d, tr, te, n_est=300) >= .5).sum()),
            "XGB": int((LC.xgb_fixed(d, tr, te) >= .5).sum())}, len(te)


def main():
    t0 = time.time(); base = E.load_base(); sets = E.positive_sets(base); ver = sets["verified M (9)"]
    sh = E.label_sheet(); others = [i for i in sh.incident_id if i not in ver and i != MEV]
    target = E.feats(base).loc[base.incident == MEV].iloc[0]
    jobs = []
    dv = E.subset(base, ver)
    for s in range(30):
        jobs.append((dv, ver, (), None, 0, 1000 + s, None, "clean"))
        for k in (1, 2, 3):
            jobs.append((dv, ver, (), "random", k, 2000 + 100 * k + s, None, f"random flips k={k}"))
            jobs.append((dv, ver, (), "nn", k, 3000 + 100 * k + s, target, f"targeted flips k={k}"))
    dm = E.subset(base, ver + [MEV])
    for s in range(30): jobs.append((dm, ver, (MEV,), None, 0, 4000 + s, None, "+ MEVBOTa47b (K)"))
    for o in others:
        do = E.subset(base, ver + [o])
        for s in range(5): jobs.append((do, ver, (o,), None, 0, 5000 + s, None, f"+ {o} [{sh.set_index('incident_id').category[o]}]"))
    res = Parallel(n_jobs=8)(delayed(task)(*j) for j in jobs)
    rows = [dict(cond=c, seed=s, model=m, fa=fa, recall=rec) for c, s, r in res for m, (fa, rec) in r.items()]
    R = pd.DataFrame(rows); R.to_csv(REPORTS / "cjsj_13_label_noise.csv", index=False)
    L = []; Q = L.append
    Q("Protocol: `cjsj_lc.py`. False alarms are out of 138 held-out negatives; recall over the 9 verified positives. CI = 95% bootstrap over seeds (fold randomness only). Positives are never flipped; only training negatives are.")
    Q("")
    order = ["clean"] + [f"random flips k={k}" for k in (1, 2, 3)] + [f"targeted flips k={k}" for k in (1, 2, 3)] + ["+ MEVBOTa47b (K)"]
    f = lambda t, p=1: f"{t[0]:.{p}f} [{t[1]:.{p}f}, {t[2]:.{p}f}]"
    Q("#### 13a. Injection conditions"); Q("")
    Q("| Condition | BN FA [CI] | RF FA [CI] | XGB FA [CI] | BN recall | RF recall | XGB recall |"); Q("|---|---|---|---|---|---|---|")
    S = {}
    for c in order:
        cells = {m: (LC.boot_mean(R[(R.cond == c) & (R.model == m)].fa), LC.boot_mean(R[(R.cond == c) & (R.model == m)].recall)) for m in LC.MODELS}
        S[c] = cells
        Q(f"| {c} | " + " | ".join(f(cells[m][0]) for m in LC.MODELS) + " | " + " | ".join(f"{cells[m][1][0]:.2f}" for m in LC.MODELS) + " |")
    Q("")
    Q("#### 13b. Each non-verified attack added alone as an extra training positive (5 seeds; mean false alarms of 138)"); Q("")
    Q("| Added attack [A2 category] | BN FA | RF FA | XGB FA | BN recall | RF recall | XGB recall |"); Q("|---|---|---|---|---|---|---|")
    oc = sorted({c for c in R.cond.unique() if c.startswith("+ ") and "MEVBOT" not in c})
    ofa = {}
    for c in oc + ["+ MEVBOTa47b (K)"]:
        d = {m: R[(R.cond == c) & (R.model == m)] for m in LC.MODELS}
        ofa[c] = {m: d[m].fa.mean() for m in LC.MODELS}
        Q(f"| {c[2:]} | " + " | ".join(f"{d[m].fa.mean():.1f}" for m in LC.MODELS) + " | " + " | ".join(f"{d[m].recall.mean():.2f}" for m in LC.MODELS) + " |")
    Q("")
    FC = ["2023-01-01", "2023-07-01", "2024-01-01"]
    fj = []
    for c in FC:
        fj.append((base, ver, c, None, 0, 0, None, (), "clean")); fj.append((base, ver, c, None, 0, 0, None, (MEV,), "+ MEVBOTa47b (K)"))
        for k in (1, 2, 3):
            fj.append((base, ver, c, "nn", k, 0, target, (), f"targeted flips k={k}"))
            for sd in range(30): fj.append((base, ver, c, "random", k, 7000 + 100 * k + sd, None, (), f"random flips k={k}"))
    fr = Parallel(n_jobs=8)(delayed(lambda j: (j[2], j[-1], *fwd_task(*j[:-1])))(j) for j in fj)
    FR = pd.DataFrame([dict(cut=c, cond=cond, model=m, fa=v, n_test=nt) for c, cond, r, nt in fr for m, v in r.items()])
    FR.to_csv(REPORTS / "cjsj_13_label_noise_forward.csv", index=False)
    Q("#### 13d. Forward-time label noise (false alarms on volatility incidents at/after the cutoff; mean [95% CI over seeds] for random flips, single value otherwise)"); Q("")
    Q("| Cutoff (test volatility n) | Condition | BN FA | RF FA | XGB FA |"); Q("|---|---|---|---|---|")
    fs = {}
    for c in FC:
        for cond in ["clean"] + [f"random flips k={k}" for k in (1, 2, 3)] + [f"targeted flips k={k}" for k in (1, 2, 3)] + ["+ MEVBOTa47b (K)"]:
            d = FR[(FR.cut == c) & (FR.cond == cond)]; nt = int(d.n_test.iloc[0]); cells = []
            for m in LC.MODELS:
                v = d[d.model == m].fa.values; fs[(c, cond, m)] = v.mean()
                cells.append(f"{v.mean():.1f} [{LC.boot_mean(v)[1]:.1f}, {LC.boot_mean(v)[2]:.1f}]" if len(v) > 1 else f"{v[0]}")
            Q(f"| {c[:7]} ({nt}) | {cond} | " + " | ".join(cells) + " |")
    Q("")
    Q("#### 13c. Answer (computed)"); Q("")
    for m in LC.MODELS:
        cl = S["clean"][m][0][0]; r1 = S["random flips k=1"][m][0][0]; r3 = S["random flips k=3"][m][0][0]
        t1 = S["targeted flips k=1"][m][0][0]; t3 = S["targeted flips k=3"][m][0][0]; mv = S["+ MEVBOTa47b (K)"][m][0][0]
        oth = np.array([ofa[c][m] for c in oc]); rank = int((oth >= ofa["+ MEVBOTa47b (K)"][m]).sum()) + 1
        Q(f"- {m}: FA clean {cl:.1f}; random flips k=1 {r1:.1f}, k=3 {r3:.1f}; targeted flips k=1 {t1:.1f}, k=3 {t3:.1f}; + MEVBOTa47b {mv:.1f}; the other {len(oc)} non-verified attacks added alone give {oth.min():.1f} to {oth.max():.1f} (median {np.median(oth):.1f}); MEVBOTa47b ranks {rank} of {len(oc) + 1}.")
    Q("")
    Q("Forward-time (13d), RF false alarms, random flips k=3 / targeted flips k=3 / + MEVBOTa47b, by cutoff: " + "; ".join(
        f"{c[:7]}: {fs[(c, 'random flips k=3', 'RF')]:.1f} / {fs[(c, 'targeted flips k=3', 'RF')]:.1f} / {fs[(c, '+ MEVBOTa47b (K)', 'RF')]:.1f} (clean {fs[(c, 'clean', 'RF')]:.1f})" for c in FC) + ".")
    Q("XGB, same order: " + "; ".join(
        f"{c[:7]}: {fs[(c, 'random flips k=3', 'XGB')]:.1f} / {fs[(c, 'targeted flips k=3', 'XGB')]:.1f} / {fs[(c, '+ MEVBOTa47b (K)', 'XGB')]:.1f} (clean {fs[(c, 'clean', 'XGB')]:.1f})" for c in FC) + ".")
    Q("BN, same order: " + "; ".join(
        f"{c[:7]}: {fs[(c, 'random flips k=3', 'BN')]:.1f} / {fs[(c, 'targeted flips k=3', 'BN')]:.1f} / {fs[(c, '+ MEVBOTa47b (K)', 'BN')]:.1f} (clean {fs[(c, 'clean', 'BN')]:.1f})" for c in FC) + ".")
    Q("")
    g = lambda c, cond, m: fs[(c, cond, m)]
    Q("**Answer.** The MEVBOTa47b effect is one instance of a general, forward-time label-noise sensitivity of RF and XGBoost, not a static one and not specific to that attack.")
    Q("")
    Q(f"1. Static held-out (13a/13b): it does not appear at all: adding MEVBOTa47b gives RF {S['+ MEVBOTa47b (K)']['RF'][0][0][0]:.1f} and XGB {S['+ MEVBOTa47b (K)']['XGB'][0][0][0]:.1f} false alarms, as do the 14 other non-verified attacks; RF is unmoved by 3 random or targeted flips ({S['random flips k=3']['RF'][0][0][0]:.1f} / {S['targeted flips k=3']['RF'][0][0][0]:.1f}); XGB is sensitive ({S['clean']['XGB'][0][0][0]:.1f} -> {S['random flips k=3']['XGB'][0][0][0]:.1f} random, {S['targeted flips k=3']['XGB'][0][0][0]:.1f} targeted at k=3); BN is unchanged at {S['clean']['BN'][0][0][0]:.1f}.")
    Q(f"2. Forward-time (13d): at 2023-01 RF false alarms are {g('2023-01-01', '+ MEVBOTa47b (K)', 'RF'):.0f} with MEVBOTa47b, {g('2023-01-01', 'random flips k=3', 'RF'):.1f} with 3 random flips and {g('2023-01-01', 'targeted flips k=3', 'RF'):.0f} with 3 targeted flips (clean {g('2023-01-01', 'clean', 'RF'):.0f}), so the real attack sits inside the range that a few mislabeled volatility incidents produce, and targeted flips (negatives most like the MEV-bot exploit) are worse. At 2023-07 and 2024-01 MEVBOTa47b gives {g('2023-07-01', '+ MEVBOTa47b (K)', 'RF'):.0f} and {g('2024-01-01', '+ MEVBOTa47b (K)', 'RF'):.0f} (seed 0; item 8's 5-seed means with the K group were 1.4 and 2.0), against {g('2023-07-01', 'random flips k=3', 'RF'):.1f} and {g('2024-01-01', 'random flips k=3', 'RF'):.1f} for 3 random flips. XGB is affected too (e.g. 2024-01: clean {g('2024-01-01', 'clean', 'XGB'):.0f} -> {g('2024-01-01', 'random flips k=3', 'XGB'):.1f} random, {g('2024-01-01', 'targeted flips k=3', 'XGB'):.0f} targeted). BN moves by at most +1 false alarm.")
    Q("3. So the item 8 diagnosis stands but its reading changes: the false alarms are driven by forward-time sensitivity to a handful of training rows whose features look like volatility incidents; a mislabeled volatility incident and a real K-category attack do the same kind of damage. It needs distribution shift to show up (absent in the static protocol). Not tested: whether the sensitivity is specific to the heartbeat drift found in the audit; single seed for MEVBOTa47b and targeted rows in 13d; CIs cover flip/fold randomness only.")
    Q("")
    Q(f"(runtime {time.time() - t0:.0f}s; cjsj_13_label_noise.py)")
    body = "\n".join(L); print(body)
    write_section("cjsj_13_label_noise.py", "13", "Label-noise injection: false alarms vs flipped training labels (BN, RF, XGBoost)", TAG_VERIFIED, body)


if __name__ == "__main__":
    main()
