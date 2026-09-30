"""CJSJ item 43: 95% intervals (Wilson and bootstrap) on precision (PPV) at 1% prevalence for the BN and RF, matching section 4's method (cjsj_04_ppv.py):
PPV(pi) = pi*TPR / (pi*TPR + (1-pi)*FPR), TPR/FPR at threshold .5; LOOCV predictions (reports/cjsj_loocv_preds.csv; 24 attacks / 138 volatility) and the forward split train<2024-01
(13 attacks / 70 volatility; BN and RF with 300 trees in the audit's row order, as section 4). Bootstrap = stratified (attacks and volatility resampled separately), 5000 replicates, seed 0,
percentile interval (section 4's). Wilson interval for PPV: Wilson 95% intervals for TPR and FPR propagated through the PPV formula: lower = PPV(TPR_lower, FPR_upper), upper = PPV(TPR_upper, FPR_lower)
(the pairing is monotone, so this is a conservative joint interval, wider than a 95% interval for the ratio alone; section 4's 'conservative' column is its lower end). Extra rows at 5% and 15% prevalence."""
from cjsj_common import ensure_omp
ensure_omp()
import numpy as np, pandas as pd
from cjsj_common import REPORTS, TAG_CONFOUNDED, write_section
import cjsj_eval as E
import cjsj_04_ppv as P4

PREV = (0.01, 0.05, 0.15)


def wil_ppv(tp, npos, fp, nneg, pi):
    tlo, thi = E.wilson(tp, npos); flo, fhi = E.wilson(fp, nneg)
    return P4.ppv(tlo, fhi, pi), P4.ppv(thi, flo, pi), (tlo, thi), (flo, fhi)


def main():
    pr = pd.read_csv(REPORTS / "cjsj_loocv_preds.csv"); base = E.load_base(); y = pr.y.values.astype(int); n = len(y)
    (tr, te), = E.forward_split(base, "2024-01-01")
    pb = np.full(n, np.nan); pr_ = np.full(n, np.nan); pb[te] = E.bn_proba(base, tr, te); pr_[te] = E.rf_proba(base, tr, te, n_est=300)
    evals = {"LOOCV (24 attacks / 138 volatility)": {"BN": pr.p_bn.values, "RF": pr.p_rf.values}, "Forward-time, train < 2024-01 (13 attacks / 70 volatility)": {"BN": pb, "RF": pr_}}
    L = []; Q = L.append; store = {}
    Q("PPV at threshold .5. 'Wilson interval' propagates Wilson intervals for TPR and FPR; 'bootstrap' is section 4's stratified percentile interval (5000, seed 0).")
    Q("")
    for ename, P in evals.items():
        Q(f"#### {ename}"); Q("")
        Q("| Model | prevalence | TPR (caught) [Wilson] | FPR (false alarms) [Wilson] | PPV | Wilson interval for PPV | bootstrap 95% interval |"); Q("|---|---|---|---|---|---|---|")
        for m in ("BN", "RF"):
            p = P[m]; ok = ~np.isnan(p); pred = (p[ok] >= .5).astype(int); yy = y[ok]; pos = pred[yy == 1]; neg = pred[yy == 0]; tp, fp, npos, nneg = int(pos.sum()), int(neg.sum()), len(pos), len(neg)
            boot = P4.boot_ppv(pos, neg)
            for pi in PREV:
                v = P4.ppv(tp / npos, fp / nneg, pi); lo, hi, tc, fc = wil_ppv(tp, npos, fp, nneg, pi); store[(ename, m, pi)] = (v, lo, hi, boot[pi])
                Q(f"| {m} | {pi:.0%} | {tp}/{npos} = {tp / npos:.3f} [{tc[0]:.3f}, {tc[1]:.3f}] | {fp}/{nneg} = {fp / nneg:.3f} [{fc[0]:.3f}, {fc[1]:.3f}] | {v:.3f} | [{lo:.3f}, {hi:.3f}] | [{boot[pi][0]:.3f}, {boot[pi][1]:.3f}] |")
        Q("")
    Q("Reading (computed, 1% prevalence, LOOCV): " + "; ".join(f"{m} PPV {store[('LOOCV (24 attacks / 138 volatility)', m, .01)][0]:.3f}, Wilson interval [{store[('LOOCV (24 attacks / 138 volatility)', m, .01)][1]:.3f}, {store[('LOOCV (24 attacks / 138 volatility)', m, .01)][2]:.3f}], bootstrap [{store[('LOOCV (24 attacks / 138 volatility)', m, .01)][3][0]:.3f}, {store[('LOOCV (24 attacks / 138 volatility)', m, .01)][3][1]:.3f}]" for m in ("BN", "RF")) +
      ". The paper's 'BN 0.23; RF conservative bound 0.19' are the point estimate (0.225) and the lower end of the Wilson interval (0.193). With 0 observed false alarms the RF's bootstrap interval is degenerate at [1, 1] and its Wilson upper end is 1, so its PPV is bounded only from below; the BN's interval is wide on both sides because 24 attacks and 4 false alarms leave TPR and FPR uncertain.")
    Q("")
    body = "\n".join(L); print(body)
    write_section("cjsj_43_ppv_ci.py", "43", "Precision at 1% prevalence: Wilson and bootstrap intervals for the BN and RF", TAG_CONFOUNDED, body)


if __name__ == "__main__":
    main()
