"""CJSJ item 46: forward-time false alarms when the models are trained on the 9 verified-M attacks only (new Figure 3 condition). Same protocol as section 32 (cjsj_32_fig3_ci.task, same 7 cutoffs, the same
evaluability rule: train positives >= 3 and test positives >= 2, now counted among the 9 verified attacks; all earlier volatility incidents are in training; the 15 unverified attacks are in neither training
nor the evaluability count; false alarms are counted on volatility test incidents only), same feature sets, same intervals (cjsj_44.summarize = section 32 definitions and rng stream). BN deterministic, RF
(150 trees) and XGBoost (subsample/colsample 0.8) 30 seeds, XGB deterministic alongside. Fewer cutoffs are evaluable than in section 32, so totals are NOT comparable with section 32's; the all-24 totals
restricted to the same cutoffs are given for comparison. The paired RF-BN / XGB-BN difference (section 44 method) is added."""
from cjsj_common import ensure_omp
ensure_omp()
import time
import numpy as np, pandas as pd
from cjsj_common import REPORTS, TAG_VERIFIED, write_section
import cjsj_eval as E
import cjsj_32_fig3_ci as F
import cjsj_44_paired_fa as P44


def evaluable(base, pos_inc):
    out = []
    for c in E.CUTOFFS:
        cc = pd.Timestamp(c); ptr = int(base.incident.isin(pos_inc)[(base.dt < cc)].sum()); pte = int((base.incident.isin(pos_inc) & (base.dt >= cc)).sum())
        nv = int(((base.dt >= cc) & (base.label == E.VOL)).sum())
        out.append((c, ptr, pte, nv, ptr >= 3 and pte >= 2))
    return out


def main():
    t0 = time.time(); base = E.load_base(); sets = E.positive_sets(base); ver = sets["verified M (9)"]; L = []; Q = L.append
    ev = evaluable(base, ver)
    Q("#### 46a. Cutoffs (evaluability counted among the 9 verified attacks)"); Q("")
    Q("| Cutoff | verified attacks in training | verified attacks in test | volatility test incidents | evaluable |"); Q("|---|---|---|---|---|")
    for c, a, b, nv, ok in ev: Q(f"| {c} | {a} | {b} | {nv} | {'yes' if ok else 'no'} |")
    Q("")
    okc = [e for e in ev if e[4]]; Q(f"Evaluable cutoffs: {len(okc)} ({', '.join(e[0] for e in okc)}); volatility test incidents counted across them: {sum(e[3] for e in okc)}. Attacks in the test sets are the verified ones only for the evaluability rule; unverified attacks that fall in test periods are ignored.")
    Q("")
    per = P44.fa_arrays(base, ver); store = P44.summarize(per)
    Q("#### 46b. Section 32 layout: false-alarm totals, trained on verified M (9)"); Q("")
    Q("| Feature set | Model | mean total false alarms | seed range (2.5-97.5%) | incident-bootstrap 95% CI | combined 95% CI |"); Q("|---|---|---|---|---|---|")
    rows = []
    for (sn, m), st in store.items():
        Q(f"| {sn} | {m} | {st['mean']:.1f} | [{st['seed_lo']:.0f}, {st['seed_hi']:.0f}] | [{st['boot_lo']:.1f}, {st['boot_hi']:.1f}] | [{st['comb_lo']:.1f}, {st['comb_hi']:.1f}] |")
        rows.append(dict(feature_set=sn, model=m, **st))
    pd.DataFrame(rows).to_csv(REPORTS / "cjsj_46_fwd_verified.csv", index=False)
    Q("")
    Q("#### 46c. Paired difference vs BN (section 44 method), trained on verified M (9)"); Q("")
    Q("| Feature set | Comparison | BN total | mean difference | paired 95% CI | excludes 0? |"); Q("|---|---|---|---|---|---|")
    for sn in F.SETS:
        bn = per[(sn, "BN")][0]
        for m in ["RF", "XGB (30 seeds)", "XGB (deterministic)"]:
            A = per[(sn, m)]; d = P44.paired(A, bn); lo, hi = np.percentile(d, [2.5, 97.5])
            Q(f"| {sn} | {m} - BN | {bn.sum():.0f} | {A.sum(1).mean() - bn.sum():+.1f} | [{lo:+.1f}, {hi:+.1f}] | {'yes' if (lo > 0 or hi < 0) else 'no'} |")
    Q("")
    # same cutoffs, all 24 attacks in training (for comparison)
    allp = sets["all 24 (audit baseline)"]; okset = {e[0] for e in okc}
    Q("#### 46d. Comparison: all-24 training restricted to the same evaluable cutoffs"); Q("")
    cuts_all = [c for c in E.CUTOFFS if c in okset]
    Q(f"Cutoffs used: {', '.join(cuts_all)}. Means over 30 seeds (BN / XGB deterministic single run).")
    Q("")
    Q("| Feature set | BN: verified-9 | BN: all-24 | RF: verified-9 | RF: all-24 | XGB (30 seeds): verified-9 | XGB (30 seeds): all-24 |"); Q("|---|---|---|---|---|---|---|")
    per24 = P44.fa_arrays(base, allp, cuts=cuts_all)
    for sn in F.SETS:
        Q(f"| {sn} | " + " | ".join(f"{per[(sn, m)].sum(1).mean():.1f} | {per24[(sn, m)].sum(1).mean():.1f}" for m in ["BN", "RF", "XGB (30 seeds)"]) + " |")
    Q("")
    Q("Reading (computed): " + "; ".join(f"{sn}: BN {store[(sn, 'BN')]['mean']:.0f}, RF {store[(sn, 'RF')]['mean']:.1f} [{store[(sn, 'RF')]['comb_lo']:.0f}, {store[(sn, 'RF')]['comb_hi']:.0f}], XGB {store[(sn, 'XGB (30 seeds)')]['mean']:.1f} [{store[(sn, 'XGB (30 seeds)')]['comb_lo']:.0f}, {store[(sn, 'XGB (30 seeds)')]['comb_hi']:.0f}]" for sn in F.SETS) + ".")
    Q("")
    Q(f"(runtime {time.time() - t0:.0f}s; cjsj_46_fwd_verified.py; raw CSV reports/cjsj_46_fwd_verified.csv)")
    body = "\n".join(L); print(body)
    write_section("cjsj_46_fwd_verified.py", "46", "Forward-time false alarms trained on verified M only (9): BN, RF (30 seeds), XGBoost (30 seeds)", TAG_VERIFIED + " (verified-label rerun)", body)


if __name__ == "__main__":
    main()
