"""CJSJ item 9: rerun confound_ablation.py and baseline_leakcheck.py on verified M (9) and A2 M-all (12), with the audit's 24 as reference.
Same models/settings as the audit scripts (RF 150 trees seed 0, median imputation from training rows, LOOCV; LogReg = StandardScaler + LR(max_iter 2000)).
Negatives = the same 138 volatility incidents; leakcheck 3-class also keeps the 3 malfunction incidents.
CIs: 2000-rep stratified bootstrap (positives and negatives resampled separately) of the LOOCV predictions, percentile 95%. This ignores
variance from re-fitting, so CIs are if anything too narrow. Paired differences use the same resamples.
Audit reference values (research_audit.md): ETH-context-only acc .907 AUC .906 11/24 FA 2/138; temporal-only .907/.851, 13/24, 4;
venue+localization .963/.901, 18/24, 0; LogReg 2-class with missingness flags 99.4% vs 88.9% without (manip recall .958 -> .375).
"""
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import f1_score, roc_auc_score
from cjsj_common import TAG_VERIFIED, write_section
import cjsj_eval as E
from models import load_data, LABELS, FEATURE_COLS, RESERVE_SKEW_CLIP

B = 2000
GROUPS = {
    "ETH-market context only (7)": ["heartbeat_elapsed", "congestion", "ref_realized_vol", "temporal_deviation_persistence", "temporal_slope", "temporal_step_change_count", "temporal_gap_trend"],
    "heartbeat_elapsed alone": ["heartbeat_elapsed"],
    "temporal features alone (4)": ["temporal_deviation_persistence", "temporal_slope", "temporal_step_change_count", "temporal_gap_trend"],
    "venue signal only (reserve_skew)": ["reserve_skew"],
    "localization only": ["reserve_skew_localization"],
    "venue + localization": ["reserve_skew", "reserve_skew_localization"],
}
SETS = ["all 24 (audit baseline)", "A2 M, any tier (12)", "verified M (9)"]


def auc(y, p):
    return roc_auc_score(y, p) if 0 < y.sum() < len(y) else np.nan


def strat_idx(y, rng):
    pos = np.where(y == 1)[0]; neg = np.where(y == 0)[0]
    return np.concatenate([rng.choice(pos, len(pos)), rng.choice(neg, len(neg))])


def boot(y, preds, fn, seed=0):
    """fn(y, *preds) evaluated on B stratified resamples; returns (point, lo, hi)."""
    rng = np.random.default_rng(seed); v = []
    for _ in range(B):
        s = strat_idx(y, rng); v.append(fn(y[s], *[p[s] for p in preds]))
    return fn(y, *preds), *np.nanpercentile(v, [2.5, 97.5])


def rf_loocv_one(df, cols, i):
    X = df[cols].replace([np.inf, -np.inf], RESERVE_SKEW_CLIP).astype(float); y = (df.label == E.MAN).astype(int).values
    tr = [j for j in range(len(df)) if j != i]; med = X.iloc[tr].median()
    c = RandomForestClassifier(n_estimators=150, random_state=0).fit(X.iloc[tr].fillna(med).values, y[tr])
    return c.predict_proba(X.iloc[[i]].fillna(med).values)[0][list(c.classes_).index(1)]


def rf_loocv(df, cols):
    return np.array(Parallel(n_jobs=-1)(delayed(rf_loocv_one)(df, cols, i) for i in range(len(df))))


def fmt_ci(t): return f"{t[0]:.3f} [{t[1]:.3f}, {t[2]:.3f}]"


# ---------------- leakcheck (3-class / 2-class, multiclass LOOCV as in the audit script) ----------------
def leak_one(df, classes, cols, kind, use_miss, i):
    idx = [j for j in range(len(df)) if j != i]
    Xall = df[cols].replace([np.inf, -np.inf], RESERVE_SKEW_CLIP).astype(float); med = Xall.iloc[idx].median()
    def build(rows):
        Xv = df.loc[rows, cols].replace([np.inf, -np.inf], RESERVE_SKEW_CLIP).astype(float); base = Xv.fillna(med).values
        return np.hstack([base, Xv.isna().astype(float).values]) if use_miss else base
    Xtr = build(df.index[idx]); Xte = build([df.index[i]]); ytr = df["label"].values[idx]
    if kind == "logreg":
        sc = StandardScaler().fit(Xtr); clf = LogisticRegression(max_iter=2000).fit(sc.transform(Xtr), ytr); p = clf.predict_proba(sc.transform(Xte))[0]
    else:
        clf = RandomForestClassifier(n_estimators=150, random_state=0).fit(Xtr, ytr); p = clf.predict_proba(Xte)[0]
    pm = {c: 0.0 for c in classes}
    for c, pp in zip(clf.classes_, p): pm[c] = pp
    return [pm[c] for c in classes]


def leak(df, classes, kind, use_miss):
    return np.array(Parallel(n_jobs=-1)(delayed(leak_one)(df, classes, FEATURE_COLS, kind, use_miss, i) for i in range(len(df))))


def subset_full(full, positives):
    return full[(full.label != E.MAN) | full.incident.isin(positives)].reset_index(drop=True)


def main():
    base = E.load_base(); sets = E.positive_sets(base); full = load_data().reset_index(drop=True)
    L = []; Q = L.append; concl = {}
    Q(f"Bootstrap: {B} stratified resamples of the LOOCV predictions. Negatives = 138 volatility incidents in every set.")
    Q("")
    # ---------- 9a confound ablation ----------
    Q("### 9a. confound_ablation.py rerun (RF LOOCV; threshold .5; AUC with 95% bootstrap CI)"); Q("")
    aucs = {}
    for sname in SETS:
        df = E.subset(base, sets[sname]); y = E.labels(df); npos = int(y.sum())
        Q(f"#### {sname}: n={len(df)}, positives={npos}; majority-class accuracy = {1 - y.mean():.3f}"); Q("")
        Q("| Features | acc | AUC [95% CI] | manip caught | false alarms |"); Q("|---|---|---|---|---|")
        P = {}
        for g, cols in GROUPS.items():
            p = rf_loocv(df, cols); P[g] = p; pr = (p >= .5).astype(int)
            a = boot(y, [p], lambda yy, pp: auc(yy, pp))
            Q(f"| {g} | {(pr == y).mean():.3f} | {fmt_ci(a)} | {int(((pr == 1) & (y == 1)).sum())}/{npos} | {int(((pr == 1) & (y == 0)).sum())}/{int((y == 0).sum())} |")
        aucs[sname] = (y, P); Q("")
    Q("#### Paired AUC differences (same resamples; a CI containing 0 means the two feature sets are not distinguishable at this n)"); Q("")
    Q("| Set | Comparison | difference [95% CI] |"); Q("|---|---|---|")
    for sname in SETS:
        y, P = aucs[sname]
        for a_, b_ in [("ETH-market context only (7)", "venue + localization"), ("ETH-market context only (7)", "venue signal only (reserve_skew)"),
                       ("heartbeat_elapsed alone", "venue + localization"), ("temporal features alone (4)", "venue + localization")]:
            d = boot(y, [P[a_], P[b_]], lambda yy, p1, p2: auc(yy, p1) - auc(yy, p2))
            Q(f"| {sname} | AUC({a_}) - AUC({b_}) | {d[0]:+.3f} [{d[1]:+.3f}, {d[2]:+.3f}] |")
            if a_.startswith("ETH") and b_ == "venue + localization": concl[(sname, "eth_vs_venue")] = d
        e = boot(y, [P["ETH-market context only (7)"]], lambda yy, pp: auc(yy, pp) - 0.5)
        Q(f"| {sname} | AUC(ETH-market context only) - 0.5 | {e[0]:+.3f} [{e[1]:+.3f}, {e[2]:+.3f}] |")
        concl[(sname, "eth_vs_half")] = e
    Q("")
    # ---------- 9b leakcheck ----------
    Q("### 9b. baseline_leakcheck.py rerun (all 10 raw features + temporal; LOOCV; with vs without missingness-indicator columns)"); Q("")
    for tag, classes, keep_mal in [("2-class manip/vol (the paper task)", [E.MAN, E.VOL], False), ("3-class (adds the 3 malfunction incidents)", LABELS, True)]:
        Q(f"#### {tag}"); Q("")
        Q("| Set | Model | missingness flags | acc [Wilson] | macro-F1 | manip recall [Wilson] | false alarms (vol called manip) | AUC(manip vs rest) [95% CI] |"); Q("|---|---|---|---|---|---|---|---|")
        for sname in SETS:
            df = subset_full(full, sets[sname]); 
            if not keep_mal: df = df[df.label.isin([E.MAN, E.VOL])].reset_index(drop=True)
            yl = df.label.values; ym = (yl == E.MAN).astype(int); pmiss = {}
            for kind in ("logreg", "rf"):
                for use in (True, False):
                    Pm = leak(df, classes, kind, use); pred = np.array(classes)[Pm.argmax(1)]
                    pman = Pm[:, classes.index(E.MAN)]; acc = (pred == yl).mean(); k = int((pred == yl).sum())
                    tp = int(((pred == E.MAN) & (yl == E.MAN)).sum()); fp = int(((pred == E.MAN) & (yl == E.VOL)).sum())
                    mf1 = f1_score(yl, pred, labels=classes, average="macro", zero_division=0)
                    lo, hi = E.wilson(k, len(yl)); rlo, rhi = E.wilson(tp, int(ym.sum()))
                    a = boot(ym, [pman], lambda yy, pp: auc(yy, pp))
                    Q(f"| {sname} | {kind} | {'yes' if use else 'no'} | {acc:.3f} [{lo:.3f}, {hi:.3f}] | {mf1:.3f} | {tp}/{int(ym.sum())} = {tp / ym.sum():.3f} [{rlo:.2f}, {rhi:.2f}] | {fp}/138 | {fmt_ci(a)} |")
                    pmiss[(kind, use)] = (pman, acc, tp / ym.sum())
            if not keep_mal:
                for kind in ("logreg", "rf"):
                    d = boot(ym, [pmiss[(kind, True)][0], pmiss[(kind, False)][0]], lambda yy, p1, p2: auc(yy, p1) - auc(yy, p2))
                    concl[(sname, kind, "miss_auc")] = d; concl[(sname, kind, "acc")] = (pmiss[(kind, True)][1], pmiss[(kind, False)][1]); concl[(sname, kind, "rec")] = (pmiss[(kind, True)][2], pmiss[(kind, False)][2])
        Q("")
        if not keep_mal:
            Q("Paired AUC difference, with flags minus without flags (2-class):"); Q("")
            Q("| Set | Model | difference [95% CI] |"); Q("|---|---|---|")
            for sname in SETS:
                for kind in ("logreg", "rf"):
                    d = concl[(sname, kind, "miss_auc")]; Q(f"| {sname} | {kind} | {d[0]:+.3f} [{d[1]:+.3f}, {d[2]:+.3f}] |")
            Q("")
    # ---------- 9c verdict ----------
    Q("### 9c. Do the shortcut findings hold on verified labels? (computed)"); Q("")
    for sname in SETS:
        e = concl[(sname, "eth_vs_half")]; d = concl[(sname, "eth_vs_venue")]
        ls, lr = concl[(sname, "logreg", "acc")], concl[(sname, "logreg", "rec")]; lm = concl[(sname, "logreg", "miss_auc")]
        Q(f"- {sname}: (i) ETH-context-only AUC above chance? AUC-0.5 = {e[0]:+.3f} [{e[1]:+.3f}, {e[2]:+.3f}] -> {'yes (CI excludes 0)' if e[1] > 0 else 'not shown (CI includes 0)'}. "
          f"(ii) ETH-context vs venue+localization: {d[0]:+.3f} [{d[1]:+.3f}, {d[2]:+.3f}] -> {'not distinguishable' if d[1] <= 0 <= d[2] else ('ETH context better' if d[1] > 0 else 'venue+localization better')}. "
          f"(iii) LogReg with vs without missingness flags: accuracy {ls[0]:.3f} vs {ls[1]:.3f}, manip recall {lr[0]:.3f} vs {lr[1]:.3f}, paired AUC {lm[0]:+.3f} [{lm[1]:+.3f}, {lm[2]:+.3f}].")
    Q("")
    return "\n".join(L)


if __name__ == "__main__":
    body = main(); print(body)
    write_section("cjsj_09_shortcuts.py", "9", "confound_ablation and baseline_leakcheck rerun on verified-M (9) and M-all (12)", TAG_VERIFIED, body)
