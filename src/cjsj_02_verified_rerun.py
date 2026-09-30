"""CJSJ item 2: rerun label_sensitivity.py, forward_time.py, dependence_significance.py with positives restricted to
A2-verified M (reports/a2_label_sheet.csv). Negatives are the same 138 volatility incidents (audit C1-C3 still apply).
Baseline (all 24) is rerun in the same code path so numbers are comparable; models/settings copied from the audit scripts:
  label_sensitivity : LOOCV, RF(150 trees) + BN on ALW features, RF on ETH-context features
  forward_time      : 7 cutoffs, RF(300), BN, NB; audit rule: skip cutoff if train positives < 3 or test positives < 2
  dependence        : date clusters (<=3 days), LOOCV vs leave-cluster-out vs train<2024/test>=2024, McNemar + Brier CI
"""
import time
import numpy as np, pandas as pd
from scipy import stats
from cjsj_common import TAG_VERIFIED, write_section
import cjsj_eval as E
from n162_experiments import nb_fit_pred


def nb_proba(df, tr, te):
    d = df.drop(columns=["dt"], errors="ignore")
    return np.array([nb_fit_pred(d.iloc[tr], d.iloc[j]) for j in te])


def run_set(name, df):
    out = []; P = out.append
    y = E.labels(df); n = len(df)
    P(f"#### {name}: n={n}, positives={y.sum()}, negatives={(y == 0).sum()}")
    P("")
    t0 = time.time()
    lo = E.loocv_splits(n)
    p_rf = E.cv_predict(df, E.rf_proba, lo, n_est=150)
    p_bn = E.cv_predict(df, E.bn_proba, lo)
    p_eth = E.cv_predict(df, E.rf_proba, lo, cols=E.ETH, n_est=150)
    P("**A. label_sensitivity analog (LOOCV, threshold .5)** [cjsj_02_verified_rerun.py]")
    P("")
    P("| Model | Result |"); P("|---|---|")
    for lab, p in [("RF (ALW 8 features)", p_rf), ("BN (production)", p_bn), ("RF, ETH-market-context features only (7)", p_eth)]:
        P(f"| {lab} | {E.fmt(E.summ(y, p))} |")
    n1, n2, pv = E.mcnemar(y, p_bn, p_rf)
    P(""); P(f"BN vs RF McNemar (exact): BN-only errors {n1}, RF-only errors {n2}, p={pv:.3f}")
    P(""); P("**B. forward_time analog** (train < cutoff, test >= cutoff; skipped = train positives < 3 or test positives < 2)")
    P("")
    P("| Cutoff | train n (pos) | test n (pos) | RF acc / manip / FA | BN acc / manip / FA | NB acc / FA | McNemar p (BN vs RF) |")
    P("|---|---|---|---|---|---|---|")
    dt = df.dt
    for cut in E.CUTOFFS:
        (tr, te), = E.forward_split(df, cut)
        ntr, ptr, nte, pte = len(tr), int(y[tr].sum()), len(te), int(y[te].sum())
        if ptr < 3 or pte < 2:
            P(f"| {cut[:7]} | {ntr} ({ptr}) | {nte} ({pte}) | skipped | skipped | skipped | skipped |"); continue
        prf = np.full(n, np.nan); pbn = np.full(n, np.nan); pnb = np.full(n, np.nan)
        prf[te] = E.rf_proba(df, tr, te, n_est=300); pbn[te] = E.bn_proba(df, tr, te); pnb[te] = nb_proba(df, tr, te)
        f = lambda s: f"{s['acc']:.3f} / {s['tp']}/{s['npos']} / {s['fp']}/{s['nneg']}"
        sr, sb, sn = E.summ(y, prf), E.summ(y, pbn), E.summ(y, pnb)
        _, _, pv = E.mcnemar(y, pbn, prf)
        P(f"| {cut[:7]} | {ntr} ({ptr}) | {nte} ({pte}) | {f(sr)} | {f(sb)} | {sn['acc']:.3f} / {sn['fp']}/{sn['nneg']} | {pv:.4f} |")
    P("")
    grp = E.event_groups(df); sizes = pd.Series(grp).value_counts()
    P(f"**C. dependence_significance analog**: {n} incidents form {len(sizes)} date clusters (<=3 days); "
      f"{int((sizes > 1).sum())} have >1 incident; largest={int(sizes.max())}.")
    P("")
    p_rf_g = E.cv_predict(df, E.rf_proba, E.group_splits(df), n_est=150)
    p_bn_g = E.cv_predict(df, E.bn_proba, E.group_splits(df))
    P("| Split | RF | BN |"); P("|---|---|---|")
    P(f"| plain LOOCV | {E.fmt(E.summ(y, p_rf))} | {E.fmt(E.summ(y, p_bn))} |")
    P(f"| leave-one-event-cluster-out | {E.fmt(E.summ(y, p_rf_g))} | {E.fmt(E.summ(y, p_bn_g))} |")
    (tr, te), = E.forward_split(df, "2024-01-01")
    if y[tr].sum() >= 1 and y[te].sum() >= 1:
        pf_rf = np.full(n, np.nan); pf_bn = np.full(n, np.nan)
        pf_rf[te] = E.rf_proba(df, tr, te, n_est=150); pf_bn[te] = E.bn_proba(df, tr, te)
        P(f"| train<2024, test>=2024 (train pos {int(y[tr].sum())}, test pos {int(y[te].sum())}) | {E.fmt(E.summ(y, pf_rf))} | {E.fmt(E.summ(y, pf_bn))} |")
    else:
        P(f"| train<2024, test>=2024 | not evaluable (train pos {int(y[tr].sum())}, test pos {int(y[te].sum())}) | |")
    P("")
    bb = 2 * (p_bn - y) ** 2; br = 2 * (p_rf - y) ** 2
    rng = np.random.default_rng(0); d = [(bb[s].mean() - br[s].mean()) for s in (rng.integers(0, n, n) for _ in range(5000))]
    man = y == 1; pb = (p_bn >= .5).astype(int); pr = (p_rf >= .5).astype(int)
    P(f"Brier (2-class, sum-of-both-classes convention of the audit) BN={bb.mean():.3f} RF={br.mean():.3f}; diff 95% bootstrap CI [{np.percentile(d, 2.5):.3f}, {np.percentile(d, 97.5):.3f}]. "
      f"Manipulation recall BN={(pb[man] == 1).mean():.3f} RF={(pr[man] == 1).mean():.3f}; identical caught sets: {bool(np.array_equal(pb[man], pr[man]))}.")
    P(f"(set runtime {time.time() - t0:.0f}s)")
    return "\n".join(out)


def main():
    base = E.load_base(); sets = E.positive_sets(base)
    chunks = []
    for name in ["all 24 (audit baseline)", "verified M (9)", "verified M strict, no math_enabled (7)"]:
        df = E.subset(base, sets[name]); txt = run_set(name, df); print(txt); print(); chunks.append(txt)
    intro = ("Positives restricted to A2 **verified M** (category M and 2-source; `reports/a2_label_sheet.csv`). The 138 volatility negatives are unchanged, "
             "so audit flaws C1-C3 still apply to the negative class and to every feature. With 9 (or 7) positives, per-cutoff forward tests are "
             "mostly not evaluable under the audit's own skip rule (train pos >= 3, test pos >= 2), and every recall interval is wide.\n")
    write_section("cjsj_02_verified_rerun.py", "2", "Verified-M rerun of label_sensitivity / forward_time / dependence_significance",
                  TAG_VERIFIED, intro + "\n" + "\n\n".join(chunks))


if __name__ == "__main__":
    main()
