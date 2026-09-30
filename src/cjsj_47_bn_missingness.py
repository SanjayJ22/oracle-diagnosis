"""CJSJ item 47: how much of the BN's LOOCV AUC depends on missing evidence?
The production BN (11 nodes: price_dev, cross_venue_spread, dex_oracle_spread, reserve_skew, ref_realized_vol, heartbeat_elapsed, congestion, temporal_deviation_persistence, temporal_slope,
temporal_step_change_count, reserve_skew_localization; fixed thresholds; BDeu ESS 2; congestion -> heartbeat edge) omits a node whose value is missing (evidence = observed features only) and estimates each
CPT from the rows where that node is observed. Variants (LOOCV, AUC with stratified bootstrap 95% CI, 2000 reps, seed 0):
  baseline        : production BN, missing evidence omitted (as in the paper)
  (a) drop price  : the three price-feature nodes (price_dev, cross_venue_spread, dex_oracle_spread) removed from the network
  (b) impute      : every missing BN feature value (price_dev 20/24 attacks, cross_venue_spread 23/24, dex_oracle_spread 23/24 missing; congestion 1/24 attacks, 3/138 volatility) replaced by the
                    median absolute value among the VOLATILITY rows of the training fold, in training rows and in the held-out row, then discretised at the fixed threshold
  (b2) impute price only: as (b) for the three price features only (congestion left omitted)
  price nodes only: the BN restricted to the three price nodes, omitted (baseline treatment) or imputed
The BN is a closed-form count model (same implementation as section 42, cjsj_42_bn_below_chance.py), validated against pgmpy's LOOCV scores on the baseline and on (a) before use.
Leave-one-out AUC is biased below 0.5 for near-uninformative discrete features (section 42)."""
from cjsj_common import ensure_omp
ensure_omp()
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from scipy.special import expit
from sklearn.metrics import roc_auc_score
from cjsj_common import REPORTS, TAG_VERIFIED, write_section
import cjsj_eval as E
import cjsj_lcs as S
import cjsj_35_shortcut_models as C35
import cjsj_42_bn_below_chance as C42
from models import BN_RAW_TO_DISCRETE, FIXED_THRESHOLDS as THR

ALL = list(BN_RAW_TO_DISCRETE); PRICE = ["price_dev", "cross_venue_spread", "dex_oracle_spread"]; CG = "congestion"


def loocv_bn(d, y, nodes, impute=()):
    n = len(y); st = C42.states(d, nodes); raw = {nd: d[nd].astype(float).values for nd in nodes}; out = np.zeros(n); idx = np.arange(n)
    for i in range(n):
        tr = np.delete(idx, i); s2 = {nd: st[nd].copy() for nd in nodes}
        for nd in nodes:
            if nd in impute:
                m = tr[(y[tr] == 0) & ~np.isnan(raw[nd][tr])]; vm = np.median(np.abs(raw[nd][m])); s2[nd] = np.where(s2[nd] < 0, int(vm > THR[nd]), s2[nd])
        T = C42.tables(s2, y, tr, nodes); ll = C42.llr_nodes(T, {nd: s2[nd][i] for nd in nodes}, nodes); n1 = y[tr].sum()
        out[i] = expit(np.log((n1 + 1) / ((len(tr) - n1) + 1)) + sum(ll.values()))
    return out


def main():
    base = E.load_base(); sets = E.positive_sets(base); L = []; Q = L.append; res = {}; val = {}
    nodes_a = [x for x in ALL if x not in PRICE]
    variants = [("baseline: production BN, missing omitted", ALL, ()), ("(a) price nodes dropped", nodes_a, ()), ("(b) all missing values imputed (volatility median)", ALL, tuple(PRICE + [CG])),
                ("(b2) price features imputed, congestion omitted", ALL, tuple(PRICE)), ("price nodes only, missing omitted", PRICE, ()), ("price nodes only, imputed", PRICE, tuple(PRICE))]
    for sname in ["all 24 (audit baseline)", "verified M (9)"]:
        d = E.subset(base, sets[sname]); y = E.labels(d); n = len(d)
        for lab, nodes, imp in variants:
            p = loocv_bn(d, y, nodes, imp); res[(sname, lab)] = (C35.boot(y, p), p)
        for lab, nodes, keep in [("baseline", ALL, None), ("(a)", nodes_a, nodes_a)]:
            pg = np.array(Parallel(n_jobs=8)(delayed(S.bn_scores)(d, np.delete(np.arange(n), i), np.array([i]), keep) for i in range(n))).ravel()
            cf = res[(sname, variants[0][0] if lab == "baseline" else variants[1][0])][1]; val[(sname, lab)] = (float(np.abs(pg - cf).max()), roc_auc_score(y, pg), roc_auc_score(y, cf))
    Q("#### 47a. Validation of the closed-form BN against pgmpy (LOOCV scores)"); Q("")
    Q("| Label set | variant | max abs score difference | AUC pgmpy | AUC closed form |"); Q("|---|---|---|---|---|")
    for (s, l), (mx, a1, a2) in val.items(): Q(f"| {s} | {l} | {mx:.2e} | {a1:.3f} | {a2:.3f} |")
    Q("")
    Q("#### 47b. BN LOOCV AUC [stratified bootstrap 95% CI]"); Q("")
    Q("| Variant | all 24 | verified 9 |"); Q("|---|---|---|")
    f = lambda t: f"{t[0]:.3f} [{t[1]:.3f}, {t[2]:.3f}]"
    for lab, _, _ in variants: Q(f"| {lab} | {f(res[('all 24 (audit baseline)', lab)][0])} | {f(res[('verified M (9)', lab)][0])} |")
    Q("")
    Q("#### 47c. How much of the BN's AUC depends on missing evidence")
    Q("")
    Q("| Quantity | all 24 | verified 9 |"); Q("|---|---|---|")
    A = lambda s, l: res[(s, l)][0][0]; s1, s2 = "all 24 (audit baseline)", "verified M (9)"
    rows = [("baseline - (a) drop price nodes", variants[0][0], variants[1][0]), ("baseline - (b) impute all missing", variants[0][0], variants[2][0]), ("baseline - (b2) impute price only", variants[0][0], variants[3][0])]
    for lab, a, b in rows: Q(f"| {lab} (AUC points) | {A(s1, a) - A(s1, b):+.3f} | {A(s2, a) - A(s2, b):+.3f} |")
    Q(f"| share of the baseline's margin over 0.5 lost by (b) | {(A(s1, variants[0][0]) - A(s1, variants[2][0])) / (A(s1, variants[0][0]) - .5):.0%} | {(A(s2, variants[0][0]) - A(s2, variants[2][0])) / (A(s2, variants[0][0]) - .5):.0%} |")
    Q(f"| share of the baseline's margin over 0.5 lost by (a) | {(A(s1, variants[0][0]) - A(s1, variants[1][0])) / (A(s1, variants[0][0]) - .5):.0%} | {(A(s2, variants[0][0]) - A(s2, variants[1][0])) / (A(s2, variants[0][0]) - .5):.0%} |")
    Q("")
    Q("Missingness counts among the BN's price features (attacks / volatility): " + "; ".join(f"{c}: {int(E.subset(base, sets[s1])[E.subset(base, sets[s1]).label == E.MAN][c].isna().sum())} / {int(base[base.label == E.VOL][c].isna().sum())}" for c in PRICE + [CG]) + f" (all 24; verified 9: " + "; ".join(f"{c}: {int(E.subset(base, sets[s2])[E.subset(base, sets[s2]).label == E.MAN][c].isna().sum())}" for c in PRICE + [CG]) + " attacks missing).")
    Q("")
    vb = base[base.label == E.VOL]; ab = base[base.label == E.MAN]
    Q("Observed values (all 24 attacks / 138 volatility): " + "; ".join(f"{c}: observed {int(ab[c].notna().sum())} / {int(vb[c].notna().sum())}, above the fixed threshold {int((ab[c].abs() > THR[c]).sum())} / {int((vb[c].abs() > THR[c]).sum())}, volatility-class median |x| {vb[c].abs().median():.4f} (threshold {THR[c]})" for c in PRICE) + ".")
    Q("")
    Q("Reading (computed): all 24: baseline " + f"{A(s1, variants[0][0]):.3f}, price nodes dropped {A(s1, variants[1][0]):.3f}, all missing imputed {A(s1, variants[2][0]):.3f}; verified 9: baseline {A(s2, variants[0][0]):.3f}, price dropped {A(s2, variants[1][0]):.3f}, imputed {A(s2, variants[2][0]):.3f}. "
      "The volatility median of every price feature lies below its threshold, so imputation makes every missing value a 'low' state, i.e. it erases the missingness signal; the imputed network then equals the network without price nodes up to a class-constant shift (hence identical AUC in (a), (b), (b2)). "
      "The price nodes alone score high only through missingness: with imputation their AUC falls to " + f"{A(s1, variants[5][0]):.3f} (all 24) and {A(s2, variants[5][0]):.3f} (verified 9), which is the leave-one-out artifact of a near-constant node (section 42), because only 2 attacks have an observed price_dev above the threshold.")
    Q("")
    body = "\n".join(L); print(body)
    write_section("cjsj_47_bn_missingness.py", "47", "BN missingness reliance: dropping price nodes and imputing missing values", TAG_VERIFIED + "; all-24 rows are within-benchmark (confounded data, see research_audit.md)", body)


if __name__ == "__main__":
    main()
