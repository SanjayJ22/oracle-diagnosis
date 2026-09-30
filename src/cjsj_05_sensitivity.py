"""CJSJ item 5 (B11): sensitivity of the forward-time BN-vs-RF result to BN thresholds (+-50%) and BDeu ESS (1, 2, 5, 10).

Reference result (audit, reproduced in cjsj_02): forward-time McNemar BN vs RF, train<cutoff/test>=cutoff, 7 cutoffs, all 24
positives; the significant cutoff is 2024-01 (p=0.0044; only one surviving Holm across cutoffs). RF is unchanged across BN
configs (it has no thresholds/ESS): RF(300 trees, seed 0), ALW features, audit skip rule (train pos>=3, test pos>=2).
BN configs:
  baseline           : FIXED_THRESHOLDS, ESS=2
  thresholds x0.5/x1.5 applied to ALL 11 BN thresholds at once (heartbeat 3600s -> 1800/5400, congestion .5 -> .25/.75,
                       step-change count 1 -> .5/1.5, the rest .05 -> .025/.075 etc.)
  one-at-a-time x0.5/x1.5 for each of the 11 thresholds
  ESS 1, 2, 5, 10 with baseline thresholds
Summary per config: BN errors vs RF errors summed over evaluable cutoffs, BN better/worse/tied count, McNemar p at 2024-01,
number of cutoffs with p<0.05, and Holm-adjusted min p across the 7 cutoffs.
"""
import time
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from cjsj_common import TAG_CONFOUNDED, write_section
import cjsj_eval as E
from models import FIXED_THRESHOLDS


def holm(p):
    p = np.asarray(p); o = np.argsort(p); m = len(p); adj = np.empty(m); run = 0
    for r, i in enumerate(o):
        run = max(run, (m - r) * p[i]); adj[i] = min(1, run)
    return adj


def configs():
    C = [("baseline (thr x1, ESS 2)", dict(thr=dict(FIXED_THRESHOLDS), ess=2))]
    for f in (0.5, 1.5):
        C.append((f"ALL thresholds x{f}", dict(thr={k: v * f for k, v in FIXED_THRESHOLDS.items()}, ess=2)))
    for ess in (1, 5, 10):
        C.append((f"ESS {ess}", dict(thr=dict(FIXED_THRESHOLDS), ess=ess)))
    from models import BN_RAW_TO_DISCRETE
    for k in BN_RAW_TO_DISCRETE:
        for f in (0.5, 1.5):
            t = dict(FIXED_THRESHOLDS); t[k] = FIXED_THRESHOLDS[k] * f
            C.append((f"{k} x{f}", dict(thr=t, ess=2)))
    return C


def main():
    t0 = time.time(); base = E.load_base(); y = E.labels(base); n = len(base)
    cuts = []
    for c in E.CUTOFFS:
        (tr, te), = E.forward_split(base, c)
        if y[tr].sum() >= 3 and y[te].sum() >= 2: cuts.append((c, tr, te))
    rf = {c: E.rf_proba(base, tr, te, n_est=300) for c, tr, te in cuts}
    C = configs()
    def job(ci, cj):
        name, kw = C[ci]; c, tr, te = cuts[cj]
        return ci, cj, E.bn_proba(base, tr, te, thr=kw["thr"], ess=kw["ess"])
    res = Parallel(n_jobs=-1)(delayed(job)(i, j) for i in range(len(C)) for j in range(len(cuts)))
    bn = {(i, j): p for i, j, p in res}
    rows = []; detail = []
    for i, (name, kw) in enumerate(C):
        fa, rec, bnerr, rferr, better, worse, ps = [], [], 0, 0, 0, 0, []
        for j, (c, tr, te) in enumerate(cuts):
            pb = np.full(n, np.nan); pr = np.full(n, np.nan); pb[te] = bn[(i, j)]; pr[te] = rf[c]
            sb, sr = E.summ(y, pb), E.summ(y, pr); n1, n2, p = E.mcnemar(y, pb, pr)
            bnerr += (sb["fp"] + sb["npos"] - sb["tp"]); rferr += (sr["fp"] + sr["npos"] - sr["tp"])
            better += n1 < n2; worse += n1 > n2; ps.append(p); fa.append(sb["fp"]); rec.append(sb["tp"])
            detail.append((name, c[:7], sb["tp"], sb["npos"], sb["fp"], sb["nneg"], sr["tp"], sr["fp"], p))
        # note: mcnemar returns (BN-wrong-only, RF-wrong-only): fewer BN-only errors => BN better
        rows.append(dict(cfg=name, bn_err=bnerr, rf_err=rferr, bn_better=int(better), bn_worse=int(worse),
                         p2024=ps[[c for c, _, _ in cuts].index("2024-01-01")], n_sig=int(sum(p < .05 for p in ps)),
                         holm_min=holm(ps).min(), fa=fa, rec=rec))
    # mcnemar returns (only first wrong, only second wrong); first=BN. better means BN has FEWER unique errors:
    R = pd.DataFrame(rows)
    out = []; Q = out.append
    Q(f"Evaluable forward cutoffs (train pos >= 3, test pos >= 2): {', '.join(c[:7] for c, _, _ in cuts)}. RF errors summed over these cutoffs (fixed across BN configs): {int(R.rf_err.iloc[0])}.")
    Q("")
    Q("| BN config | BN errors (sum) | BN-better cutoffs | BN-worse cutoffs | p at 2024-01 | cutoffs with p<.05 | Holm min p (7 cutoffs) | BN false alarms by cutoff | BN manip caught by cutoff |")
    Q("|---|---|---|---|---|---|---|---|---|")
    for _, r in R.iterrows():
        Q(f"| {r.cfg} | {r.bn_err} | {r.bn_better} | {r.bn_worse} | {r.p2024:.4f} | {r.n_sig} | {r.holm_min:.3f} | {', '.join(map(str, r.fa))} | {', '.join(map(str, r.rec))} |")
    Q("")
    b = R.iloc[0]
    Q(f"Baseline reproduces the audit: p at 2024-01 = {b.p2024:.4f}, BN false alarms by cutoff {b.fa} (audit: 2, 3, 3, 2, 2, 1, 1).")
    thr_rows = R[R.cfg.str.contains(r" x0\.5| x1\.5")]
    Q(f"Across the {len(thr_rows)} threshold-perturbed configs: p at 2024-01 ranges {thr_rows.p2024.min():.4f} to {thr_rows.p2024.max():.4f}; "
      f"{int((thr_rows.p2024 < .05).sum())} of {len(thr_rows)} keep p<.05 at 2024-01; {int((thr_rows.holm_min < .05).sum())} of {len(thr_rows)} keep a Holm-significant cutoff.")
    ess_rows = R[R.cfg.str.startswith("ESS") | R.cfg.str.startswith("baseline")]
    Q(f"Across ESS 1/2/5/10: p at 2024-01 ranges {ess_rows.p2024.min():.4f} to {ess_rows.p2024.max():.4f}; BN false alarms (sum over cutoffs) {', '.join(f'{r.cfg}: {sum(r.fa)}' for _, r in ess_rows.iterrows())}.")
    Q("")
    Q("Per-cutoff detail is in `reports/cjsj_05_detail.csv` (config, cutoff, BN caught/pos, BN FA/neg, RF caught, RF FA, McNemar p).")
    pd.DataFrame(detail, columns=["cfg", "cutoff", "bn_tp", "npos", "bn_fp", "nneg", "rf_tp", "rf_fp", "p"]).to_csv(E.REPORTS / "cjsj_05_detail.csv", index=False)
    Q(f"(runtime {time.time() - t0:.0f}s; script cjsj_05_sensitivity.py)")
    body = "\n".join(out); print(body)
    write_section("cjsj_05_sensitivity.py", "5", "B11 forward-time BN-vs-RF sensitivity to thresholds and BDeu ESS", TAG_CONFOUNDED, body)


if __name__ == "__main__":
    main()
