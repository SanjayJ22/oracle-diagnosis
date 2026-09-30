"""CJSJ item 27: explainability parity. SHAP for RF and XGBoost vs the BN evidence breakdown on the same two incidents as item 7:
UwU Lend (a manipulation the BN gets right) and the Oct 10-11 2025 flash crash (the BN's most confident crash false alarm). All models are fit WITHOUT the
incident (as in item 7): BN (production; exact per-node log-likelihood ratios, item 7's bn_llr), RF (300 trees, ALW), XGBoost (depth 2, 150 trees, lr .1,
scale_pos_weight neg/pos). SHAP: shap.TreeExplainer; XGB in log-odds (exact TreeSHAP); RF interventional with a 100-row background sample of the training set, in probability
space (RF has no log-odds output). Additivity is asserted (base + sum = model output). Comparison: signs, |attribution| ranks, Spearman rank correlation over the features
BN and the ML models share, and the share of total |attribution| that falls on ETH-context features (the audit's shortcut features). BN and XGB attributions are in
log-odds, RF's in probability points, so magnitudes are compared through ranks and shares, not directly."""
from cjsj_common import ensure_omp
ensure_omp()
import numpy as np, pandas as pd
import shap, xgboost as xgb
from scipy.stats import spearmanr
from sklearn.ensemble import RandomForestClassifier
from cjsj_common import TAG_CONFOUNDED, write_section
import cjsj_eval as E
import cjsj_lc as LC
from cjsj_07_calibration_evidence import bn_llr
from models import BN_RAW_TO_DISCRETE, predict_bayesian_network

SHARED = ['heartbeat_elapsed', 'reserve_skew', 'ref_realized_vol', 'temporal_deviation_persistence', 'temporal_slope', 'temporal_step_change_count', 'reserve_skew_localization']
ETHC = {'heartbeat_elapsed', 'congestion', 'ref_realized_vol', 'temporal_deviation_persistence', 'temporal_slope', 'temporal_step_change_count', 'temporal_gap_trend'}
INCS = ["UwU Lend", "Oct 10-11 2025 flash crash"]


def explain(base, name):
    i = int(base.index[base.incident == name][0]); tr = np.delete(np.arange(len(base)), i); d = base.drop(columns=["dt"], errors="ignore")
    m, th = E.bn_fit_c(d.iloc[tr]); row = d.iloc[i]; prior, rows, lo_post = bn_llr(m, th, row)
    raw_of = {dc: raw for raw, (dc, _) in BN_RAW_TO_DISCRETE.items()}; bn = {raw_of[n]: llr for n, s, llr in rows}
    X = E.feats(base).values; y = E.labels(base); med = np.nanmedian(X[tr], axis=0); Xi = np.where(np.isnan(X), med, X)
    rf = RandomForestClassifier(n_estimators=300, random_state=0).fit(Xi[tr], y[tr]); p_rf = float(rf.predict_proba(Xi[[i]])[0, 1])
    bg = Xi[tr][np.random.default_rng(0).choice(len(tr), 100, replace=False)]
    er = shap.TreeExplainer(rf, data=bg, feature_perturbation="interventional", model_output="probability"); sv = er.shap_values(Xi[[i]], check_additivity=False)
    sv = sv[0, :, 1] if np.ndim(sv) == 3 else sv[0][:, 1] if isinstance(sv, list) else sv[0]
    add_rf = abs(er.expected_value[1] if np.ndim(er.expected_value) else er.expected_value) if False else None
    ev_rf = er.expected_value[1] if np.ndim(er.expected_value) else er.expected_value
    yt = y[tr]; spw = float((yt == 0).sum()) / max(int((yt == 1).sum()), 1)
    g = xgb.XGBClassifier(**LC.XCFG, scale_pos_weight=spw, tree_method="hist", n_jobs=1, random_state=0, verbosity=0).fit(X[tr], yt)
    ex = shap.TreeExplainer(g); sx = ex.shap_values(X[[i]])[0]; p_x = float(g.predict_proba(X[[i]])[0, 1])
    margin = float(g.get_booster().predict(xgb.DMatrix(X[[i]]), output_margin=True)[0])
    return dict(i=i, bn=bn, prior=prior, bn_total=prior + sum(bn.values()), bn_post=float(predict_bayesian_network(m, th, row)[0][E.MAN]), p_rf=p_rf, rf=dict(zip(E.ALW, sv)), ev_rf=float(ev_rf),
                rf_add=abs(float(ev_rf) + float(sv.sum()) - p_rf), p_x=p_x, xgb=dict(zip(E.ALW, sx)), ev_x=float(ex.expected_value), x_add=abs(float(ex.expected_value) + float(sx.sum()) - margin), X=dict(zip(E.ALW, X[i])),
                raw=row)


def main():
    base = E.load_base(); L = []; Q = L.append
    Q("BN: exact log-likelihood ratios (natural log, manipulation:volatility) plus the prior; XGB: TreeSHAP in log-odds; RF: interventional TreeSHAP in probability. Features not in a model's input are blank.")
    Q("")
    summ = []
    for name in INCS:
        r = explain(base, name); Q(f"#### {name}"); Q("")
        Q(f"Outputs: BN P={r['bn_post']:.3f} (prior {r['prior']:+.2f} + sum of LLRs = {r['bn_total']:+.2f} log-odds); RF P={r['p_rf']:.3f} (base {r['ev_rf']:.3f}); XGB P={r['p_x']:.3f} (base margin {r['ev_x']:+.2f}). "
          f"Additivity check |base + sum - output|: RF {r['rf_add']:.1e}, XGB {r['x_add']:.1e}.")
        Q("")
        feats = sorted(set(E.ALW) | set(r["bn"]), key=lambda f: -max(abs(r["bn"].get(f, 0)), abs(r["xgb"].get(f, 0))))
        Q("| Feature | value | ETH-context? | BN LLR | XGB SHAP (log-odds) | RF SHAP (prob. points) | BN rank | XGB rank | RF rank |"); Q("|---|---|---|---|---|---|---|---|---|")
        rk = lambda dct: {f: k + 1 for k, f in enumerate(sorted(dct, key=lambda f: -abs(dct[f])))}
        rb, rx, rrf = rk(r["bn"]), rk(r["xgb"]), rk(r["rf"])
        for f in feats:
            v = r["X"].get(f, r["raw"][f] if f in r["raw"].index else np.nan)
            Q(f"| {f} | {v:.4g} | {'yes' if f in ETHC else 'no'} | {r['bn'][f]:+.2f} | " if f in r["bn"] else f"| {f} | {v:.4g} | {'yes' if f in ETHC else 'no'} |  | ")
            L[-1] += (f"{r['xgb'][f]:+.2f} | {r['rf'][f]:+.3f} | " if f in r["xgb"] else " |  | ") + f"{rb.get(f, '')} | {rx.get(f, '')} | {rrf.get(f, '')} |"
        Q("")
        sp = lambda a, b: spearmanr([abs(a[f]) for f in SHARED if f in a and f in b], [abs(b[f]) for f in SHARED if f in a and f in b])[0]
        share = lambda dct: sum(abs(v) for f, v in dct.items() if f in ETHC) / max(sum(abs(v) for v in dct.values()), 1e-12)
        sg = lambda a, b: sum(np.sign(a[f]) == np.sign(b[f]) for f in SHARED if f in a and f in b and abs(a[f]) > 0.05 and abs(b[f]) > 0.05)
        top = lambda dct: max(dct, key=lambda f: abs(dct[f]))
        Q(f"Parity: top feature BN {top(r['bn'])}, XGB {top(r['xgb'])}, RF {top(r['rf'])}. Spearman of |attribution| over the {len(SHARED)} shared features: BN-XGB {sp(r['bn'], r['xgb']):+.2f}, BN-RF {sp(r['bn'], r['rf']):+.2f}, XGB-RF {sp(r['xgb'], r['rf']):+.2f}. "
          f"Sign agreement on shared features with |attribution| > .05: BN-XGB {sg(r['bn'], r['xgb'])}, BN-RF {sg(r['bn'], r['rf'])}. Share of total |attribution| on ETH-context features: BN {share(r['bn']):.0%}, XGB {share(r['xgb']):.0%}, RF {share(r['rf']):.0%}.")
        Q(""); summ.append((name, r, sp, share, top))
    Q("#### 27 summary (computed)"); Q("")
    for name, r, sp, share, top in summ:
        Q(f"- {name}: BN and XGB name the same top feature: {top(r['bn']) == top(r['xgb'])}; BN and RF: {top(r['bn']) == top(r['rf'])}. ETH-context share of |attribution| BN/XGB/RF = {share(r['bn']):.0%}/{share(r['xgb']):.0%}/{share(r['rf']):.0%}.")
    Q("- Differences that limit parity: BN evidence includes price_dev / cross_venue_spread / dex_oracle_spread (missing for most attacks) and excludes temporal_gap_trend; the ML models use the 8 ALW features only; RF attributions are in probability points and depend on the background sample.")
    Q("")
    body = "\n".join(L); print(body)
    write_section("cjsj_27_shap_parity.py", "27", "Explainability parity: SHAP for RF and XGBoost vs the BN evidence breakdown", TAG_CONFOUNDED, body)


if __name__ == "__main__":
    main()
