"""CJSJ item 37: why does AUC drop when heartbeat_elapsed is dropped on verified M (item 36: RF 0.961 -> 0.907, XGB 0.976 -> 0.895) while accuracy at .5 is unchanged?
Same models/protocol as item 36: LOOCV, verified M (9 positives) + 138 volatility negatives; RF 150 trees seed 0 and XGBoost fixed config on ALW (8 features) vs ALW minus heartbeat_elapsed.
Reports: (a) AUC as a function of where each positive ranks: per positive, number of negatives scoring above it with / without heartbeat (AUC = 1 - mean over positives of that count / 138), so the
drop decomposes exactly into per-positive contributions; (b) rank position (1 = highest of 147) of every positive and the negatives that move most; (c) leave-one-positive-out two ways:
(i) delete positive i from the AUC computation using the same LOOCV scores, (ii) remove positive i from the data and rerun the whole LOOCV (8 positives) for both variants; (d) paired stratified
bootstrap (2000) CI of AUC(without) - AUC(with) for verified M, the strict-7 set and all 24 (scores fixed, refit variance ignored); (e) score ties and heartbeat values."""
from cjsj_common import ensure_omp
ensure_omp()
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from sklearn.metrics import roc_auc_score
from cjsj_common import REPORTS, TAG_VERIFIED, write_section
import cjsj_eval as E
import cjsj_lcs as S

NOHB = [c for c in E.ALW if c != "heartbeat_elapsed"]
FS = {"with": dict(ml=E.ALW, bn=None), "without": dict(ml=NOHB, bn=None)}


def one(d, i, v, m):
    return S.predict_models(d, np.delete(np.arange(len(d)), i), np.array([i]), FS[v], [m])[m][0]


def loocv(d):
    n = len(d); out = {}
    for m in ("RF", "XGB"):
        for v in FS: out[(m, v)] = np.array(Parallel(n_jobs=8)(delayed(one)(d, i, v, m) for i in range(n)))
    return out


def auc_ties(pos, neg):
    x = pos[:, None]; y = neg[None, :]; return float(((x > y).sum() + 0.5 * (x == y).sum()) / (len(pos) * len(neg)))


def n_above(s, neg): return float((neg > s).sum() + 0.5 * (neg == s).sum())


def boot_diff(y, a, b, B=2000, seed=0):
    rng = np.random.default_rng(seed); pos = np.where(y == 1)[0]; neg = np.where(y == 0)[0]; v = []
    for _ in range(B):
        s = np.concatenate([rng.choice(pos, len(pos)), rng.choice(neg, len(neg))]); v.append(roc_auc_score(y[s], b[s]) - roc_auc_score(y[s], a[s]))
    return np.percentile(v, [2.5, 97.5]), float((np.array(v) < 0).mean())


def main():
    base = E.load_base(); sets = E.positive_sets(base); L = []; Q = L.append
    d = E.subset(base, sets["verified M (9)"]); y = E.labels(d); S_ = loocv(d); pos_i = np.where(y == 1)[0]; neg_i = np.where(y == 0)[0]
    Q("Verified M (9 positives) + 138 negatives; LOOCV scores; RF = 150 trees seed 0, XGB = fixed config; 'with' = ALW (8 features), 'without' = ALW minus heartbeat_elapsed.")
    Q("")
    Q("#### 37a. Reproduction and paired bootstrap CI of the AUC difference (without minus with)"); Q("")
    Q("| Label set | Model | AUC with | AUC without | difference [95% paired bootstrap CI] | share of resamples with a drop |"); Q("|---|---|---|---|---|---|")
    summ = {}
    for sname in ["verified M (9)", "verified M strict, no math_enabled (7)", "all 24 (audit baseline)"]:
        dd = d if sname == "verified M (9)" else E.subset(base, sets[sname]); yy = E.labels(dd); SS = S_ if sname == "verified M (9)" else loocv(dd)
        for m in ("RF", "XGB"):
            a, b = SS[(m, "with")], SS[(m, "without")]; ci, pdrop = boot_diff(yy, a, b); summ[(sname, m)] = (roc_auc_score(yy, a), roc_auc_score(yy, b), ci)
            Q(f"| {sname} | {m} | {roc_auc_score(yy, a):.3f} | {roc_auc_score(yy, b):.3f} | {roc_auc_score(yy, b) - roc_auc_score(yy, a):+.3f} [{ci[0]:+.3f}, {ci[1]:+.3f}] | {pdrop:.1%} |")
    Q("")
    inc = d.incident.values; hb = d.heartbeat_elapsed.values
    contrib = {}
    Q("#### 37b. Per-positive decomposition of the drop (negatives scoring above the positive, of 138; AUC = 1 - mean(count)/138)"); Q("")
    for m in ("RF", "XGB"):
        Q(f"**{m}**"); Q("")
        Q("| Positive | heartbeat_elapsed | score with | score without | negatives above, with | negatives above, without | contribution to AUC drop | rank of 147, with -> without |"); Q("|---|---|---|---|---|---|---|---|")
        a, b = S_[(m, "with")], S_[(m, "without")]; ra = (-a).argsort().argsort() + 1; rb = (-b).argsort().argsort() + 1; tot = 0; cc = []
        for i in pos_i:
            na, nb = n_above(a[i], a[neg_i]), n_above(b[i], b[neg_i]); c = (nb - na) / (138 * len(pos_i)); cc.append((inc[i], c)); tot += c
            Q(f"| {inc[i]} | {hb[i]:.0f} | {a[i]:.3f} | {b[i]:.3f} | {na:.1f} | {nb:.1f} | {-c:+.3f} | {ra[i]} -> {rb[i]} |")
        Q(f"| **sum** | | | | | | **{-tot:+.3f}** (= AUC without minus with) | |"); Q("")
        contrib[m] = sorted(cc, key=lambda t: -t[1])
    Q("#### 37c. Negatives that move most (rank of 147 by score; 1 = most manipulation-like)"); Q("")
    for m in ("RF", "XGB"):
        a, b = S_[(m, "with")], S_[(m, "without")]; ra = (-a).argsort().argsort() + 1; rb = (-b).argsort().argsort() + 1
        Q(f"**{m}**: negatives with the largest gain in score after dropping heartbeat (they then outrank more positives)"); Q("")
        Q("| Volatility incident | date | heartbeat_elapsed | score with | score without | rank with -> without | positives it outranks, with -> without |"); Q("|---|---|---|---|---|---|---|")
        gain = sorted(neg_i, key=lambda j: -(b[j] - a[j]))[:8]
        for j in gain: Q(f"| {inc[j]} | {d.date.values[j]} | {hb[j]:.0f} | {a[j]:.3f} | {b[j]:.3f} | {ra[j]} -> {rb[j]} | {int((a[pos_i] < a[j]).sum())} -> {int((b[pos_i] < b[j]).sum())} |")
        Q("")
    Q("#### 37d. Leave-one-positive-out"); Q("")
    Q("(i) = delete positive i from the AUC calculation, same LOOCV scores; (ii) = remove positive i from the data and rerun the whole LOOCV (8 positives) for both variants. Entries are AUC without minus AUC with.")
    Q("")
    lopo = {}
    for m in ("RF", "XGB"):
        a, b = S_[(m, "with")], S_[(m, "without")]; Q(f"**{m}** (all 9: {roc_auc_score(y, b) - roc_auc_score(y, a):+.3f})"); Q("")
        Q("| Positive left out | (i) AUC with / without / diff | (ii) refit: AUC with / without / diff |"); Q("|---|---|---|")
        for i in pos_i:
            keep = np.array([k for k in range(len(d)) if k != i]); dd = d.iloc[keep].reset_index(drop=True); yy = E.labels(dd)
            i1 = (roc_auc_score(y[keep], a[keep]), roc_auc_score(y[keep], b[keep]))
            lopo[(m, inc[i])] = None
            SS = {}
            for v in FS: SS[v] = np.array(Parallel(n_jobs=8)(delayed(one)(dd, k, v, m) for k in range(len(dd))))
            i2 = (roc_auc_score(yy, SS["with"]), roc_auc_score(yy, SS["without"])); lopo[(m, inc[i])] = (i1[1] - i1[0], i2[1] - i2[0])
            Q(f"| {inc[i]} | {i1[0]:.3f} / {i1[1]:.3f} / {i1[1] - i1[0]:+.3f} | {i2[0]:.3f} / {i2[1]:.3f} / {i2[1] - i2[0]:+.3f} |")
        Q("")
    Q("#### 37e. Ties, resolution and heartbeat values"); Q("")
    for m in ("RF", "XGB"):
        for v in FS:
            s = S_[(m, v)]; Q(f"- {m} {v}: {len(np.unique(np.round(s, 6)))} distinct scores over 147 incidents; positives' scores {np.round(np.sort(s[pos_i])[::-1], 3).tolist()}; 10 highest negative scores {np.round(np.sort(s[neg_i])[::-1][:10], 3).tolist()}.")
    Q(f"- heartbeat_elapsed: positives {sorted(hb[pos_i].tolist())} (median {np.median(hb[pos_i]):.0f}); negatives median {np.median(hb[neg_i]):.0f}, p10-p90 {np.percentile(hb[neg_i], 10):.0f}-{np.percentile(hb[neg_i], 90):.0f}.")
    cl = d.index[d.incident == "CurveLlamaLend"][0]; negs = d[d.label == E.VOL]
    Q("CurveLlamaLend's ALW features vs the 138 negatives (value; percentile of negatives at or below it): " + "; ".join(f"{c} {d.loc[cl, c]:.4g} ({100 * (negs[c].astype(float) <= d.loc[cl, c]).mean():.0f}th)" for c in E.ALW) + ". The A2 sheet records it as an atomic donation attack whose block-close snapshot understates the manipulation (reserve_skew -0.016).")
    Q("")
    Q("#### 37f. Reading (computed)"); Q("")
    for m in ("RF", "XGB"):
        c = contrib[m]; tot = sum(x[1] for x in c); top = [x for x in c if abs(x[1]) > 1e-9][:2]; ls = [(k[1], v) for k, v in lopo.items() if k[0] == m]
        Q(f"- {m}: AUC drop {-tot:+.3f} = sum of per-positive contributions. Positives whose number of higher-scoring negatives changes: " + ", ".join(f"{n} ({-x:+.3f}, {x / tot:.0%} of the drop)" for n, x in top) + f"; the other {9 - len(top)} positives have {0} or an unchanged number of negatives above them, so their rank shuffles among the positives (e.g. XGB Cream 1 -> 6) do not enter the AUC. "
          f"Leave-one-positive-out range of the difference: (i) {min(v[0] for _, v in ls):+.3f} to {max(v[0] for _, v in ls):+.3f}; (ii) refit {min(v[1] for _, v in ls):+.3f} to {max(v[1] for _, v in ls):+.3f}. Paired bootstrap CI for all 9: [{summ[('verified M (9)', m)][2][0]:+.3f}, {summ[('verified M (9)', m)][2][1]:+.3f}] ({'excludes 0' if summ[('verified M (9)', m)][2][1] < 0 else 'includes 0'}).")
    Q("")
    body = "\n".join(L); print(body)
    write_section("cjsj_37_heartbeat_auc.py", "37", "Why AUC falls when heartbeat_elapsed is dropped on verified M (item 36 follow-up)", TAG_VERIFIED + "; all-24 row in 37a is within-benchmark (confounded data, see research_audit.md)", body)


if __name__ == "__main__":
    main()
