"""CJSJ item 36: does dropping heartbeat_elapsed cost static accuracy? LOOCV accuracy, manipulation recall (Wilson 95%), false alarms (of 138) and AUC for BN, RF (150 trees) and XGBoost
(fixed config) with all features vs without heartbeat_elapsed (RF/XGB: ALW minus heartbeat, 7 features; BN: all nodes minus the heartbeat node, which also removes the congestion->heartbeat edge).
Sets: all 24 and verified M (9), 138 volatility negatives. Paired comparison with vs without: exact McNemar on correctness (errors only with / only without) and a stratified bootstrap
95% CI (2000 reps) for the accuracy difference (without minus with)."""
from cjsj_common import ensure_omp
ensure_omp()
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from scipy.stats import binomtest
from sklearn.metrics import roc_auc_score
from cjsj_common import TAG_VERIFIED, write_section
import cjsj_eval as E
import cjsj_lcs as S
from models import BN_RAW_TO_DISCRETE

ALW_NOHB = [c for c in E.ALW if c != "heartbeat_elapsed"]; BN_ALL = list(BN_RAW_TO_DISCRETE); BN_NOHB = [c for c in BN_ALL if c != "heartbeat_elapsed"]
FS = {"with heartbeat_elapsed": dict(ml=E.ALW, bn=None), "without heartbeat_elapsed": dict(ml=ALW_NOHB, bn=BN_NOHB)}


def one(d, i, fsname, m):
    idx = np.delete(np.arange(len(d)), i); return S.predict_models(d, idx, np.array([i]), FS[fsname], [m])[m][0]


def main():
    base = E.load_base(); sets = E.positive_sets(base); L = []; Q = L.append; rng = np.random.default_rng(0); out = {}; aucs = {}
    for sname in ["all 24 (audit baseline)", "verified M (9)"]:
        d = E.subset(base, sets[sname]); y = E.labels(d); n = len(d)
        P = {}
        for m in ["BN", "RF", "XGB"]:
            for fsn in FS: P[(m, fsn)] = np.array(Parallel(n_jobs=8)(delayed(one)(d, i, fsn, m) for i in range(n)))
        Q(f"#### {sname}: n={n}, positives={int(y.sum())}"); Q("")
        Q("| Model | Features | accuracy | manipulation recall [Wilson] | false alarms (of 138) | AUC | errors only with / only without (McNemar p) | accuracy change, without minus with [95% CI] |"); Q("|---|---|---|---|---|---|---|---|")
        for m in ["BN", "RF", "XGB"]:
            a, b = P[(m, "with heartbeat_elapsed")], P[(m, "without heartbeat_elapsed")]; wa, wb = (a >= .5).astype(int) != y, (b >= .5).astype(int) != y
            n1, n2 = int((wa & ~wb).sum()), int((wb & ~wa).sum()); pv = 1.0 if n1 + n2 == 0 else binomtest(min(n1, n2), n1 + n2, .5).pvalue
            pos_i = np.where(y == 1)[0]; neg_i = np.where(y == 0)[0]; dd = []
            for _ in range(2000):
                s = np.concatenate([rng.choice(pos_i, len(pos_i)), rng.choice(neg_i, len(neg_i))]); dd.append(((~wb[s]).mean() - (~wa[s]).mean()))
            for fsn, p in [("with heartbeat_elapsed", a), ("without heartbeat_elapsed", b)]:
                pr = (p >= .5).astype(int); tp = int(((pr == 1) & (y == 1)).sum()); lo, hi = E.wilson(tp, int(y.sum()))
                extra = f"{n1} / {n2} (p={pv:.3f}) | {(~wb).mean() - (~wa).mean():+.3f} [{np.percentile(dd, 2.5):+.3f}, {np.percentile(dd, 97.5):+.3f}]" if fsn.startswith("without") else " | "
                Q(f"| {m} | {fsn} | {(pr == y).mean():.3f} | {tp}/{int(y.sum())} [{lo:.2f}, {hi:.2f}] | {int(((pr == 1) & (y == 0)).sum())} | {roc_auc_score(y, p):.3f} | {extra} |")
            out[(sname, m)] = ((~wb).mean() - (~wa).mean(), np.percentile(dd, 2.5), np.percentile(dd, 97.5), pv); aucs[(sname, m)] = (roc_auc_score(y, a), roc_auc_score(y, b))
        Q("")
    Q("Reading (computed): accuracy change when heartbeat_elapsed is dropped (all 24): " + "; ".join(f"{m} {out[('all 24 (audit baseline)', m)][0]:+.3f} [{out[('all 24 (audit baseline)', m)][1]:+.3f}, {out[('all 24 (audit baseline)', m)][2]:+.3f}]" for m in ["BN", "RF", "XGB"]) +
      "; verified M: " + "; ".join(f"{m} {out[('verified M (9)', m)][0]:+.3f} [{out[('verified M (9)', m)][1]:+.3f}, {out[('verified M (9)', m)][2]:+.3f}]" for m in ["BN", "RF", "XGB"]) + ".")
    Q("")
    Q("AUC with -> without heartbeat_elapsed: " + "; ".join(f"{s.split(' (')[0]} {m} {aucs[(s, m)][0]:.3f} -> {aucs[(s, m)][1]:.3f}" for s in ["all 24 (audit baseline)", "verified M (9)"] for m in ["BN", "RF", "XGB"]) + ". Threshold-.5 accuracy is unchanged but rank quality (AUC) falls for RF and XGBoost on the verified-M set (the reason was not investigated), so 'no static cost' holds for accuracy and not for AUC there; n_pos = 9.")
    Q("")
    body = "\n".join(L); print(body)
    write_section("cjsj_36_heartbeat_static.py", "36", "Static cost of dropping heartbeat_elapsed (LOOCV)", TAG_VERIFIED + "; all-24 rows are within-benchmark (confounded data, see research_audit.md)", body)


if __name__ == "__main__":
    main()
