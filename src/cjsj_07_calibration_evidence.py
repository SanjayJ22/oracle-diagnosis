"""CJSJ item 7: B2 reliability diagrams with bootstrap CIs (BN, RF, XGB, LOOCV) and B5 evidence breakdown.

B2: LOOCV probabilities from cjsj_03 (reports/cjsj_loocv_preds.csv), 6 fixed bins [0,.1,.3,.5,.7,.9,1]. Observed frequency CI and
    ECE / Brier / log-loss / calibration slope+intercept CIs come from a 2000-rep bootstrap over incidents (percentile).
    Figure: reports/cjsj_07_reliability.png (palette slots 1-3 of the reference dataviz palette, validated).
B5: For UwU Lend (a manipulation the BN gets right), the BN's most confident crash false alarm, and a correctly classified crash, the
    BN is refit WITHOUT that incident (LOOCV-style) and the posterior is decomposed exactly: log-odds(man:vol) = prior
    + sum_i LLR_i, LLR_i = ln P(e_i | man, .) / P(e_i | vol, .) from the fitted CPDs (asserted equal to the variable-elimination
    posterior). Compared with RF (one probability) and XGBoost (native per-feature log-odds contributions, pred_contribs).
"""
from cjsj_common import ensure_omp
ensure_omp()
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import xgboost as xgb
from sklearn.linear_model import LogisticRegression
from cjsj_common import REPORTS, TAG_CONFOUNDED, write_section
import cjsj_eval as E
from models import BN_RAW_TO_DISCRETE, BN_STATE_NAMES, FIXED_THRESHOLDS, _bn_clean, predict_bayesian_network

EDGES = np.array([0, .1, .3, .5, .7, .9, 1.0000001]); B = 2000
COL = {"BN": "#2a78d6", "RF": "#eb6834", "XGB": "#1baf7a"}; NAME = {"BN": "BN (production)", "RF": "RF", "XGB": "XGBoost (nested-tuned)"}


def bins(p, y):
    idx = np.digitize(p, EDGES) - 1
    return [(int((idx == b).sum()), p[idx == b].mean() if (idx == b).any() else np.nan, y[idx == b].mean() if (idx == b).any() else np.nan) for b in range(len(EDGES) - 1)]


def ece(p, y):
    b = bins(p, y); n = len(p)
    return sum(c / n * abs(o - m) for c, m, o in b if c)


def logloss(p, y):
    q = np.clip(p, 1e-6, 1 - 1e-6); return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))


def slope_int(p, y):
    z = np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4))).reshape(-1, 1)
    try:
        m = LogisticRegression(penalty=None, max_iter=2000).fit(z, y); return float(m.coef_[0, 0]), float(m.intercept_[0])
    except Exception:
        return np.nan, np.nan


def reliability(y, P):
    rng = np.random.default_rng(0); n = len(y); out = {}; lines = []
    for m, p in P.items():
        obs_ci = [[] for _ in range(len(EDGES) - 1)]; st = {k: [] for k in ("ece", "brier", "ll", "slope", "icpt")}
        for _ in range(B):
            s = rng.integers(0, n, n); ps, ys = p[s], y[s]
            for b, (c, mp, o) in enumerate(bins(ps, ys)):
                if c: obs_ci[b].append(o)
            st["ece"].append(ece(ps, ys)); st["brier"].append(np.mean((ps - ys) ** 2)); st["ll"].append(logloss(ps, ys))
            sl, ic = slope_int(ps, ys); st["slope"].append(sl); st["icpt"].append(ic)
        bt = bins(p, y)
        out[m] = [(c, mp, o, *(np.percentile(obs_ci[b], [2.5, 97.5]) if obs_ci[b] else (np.nan, np.nan))) for b, (c, mp, o) in enumerate(bt)]
        sl0, ic0 = slope_int(p, y)
        ci = lambda k, v: f"{v:.3f} [{np.nanpercentile(st[k], 2.5):.3f}, {np.nanpercentile(st[k], 97.5):.3f}]"
        lines.append(f"| {NAME[m]} | {ci('ece', ece(p, y))} | {ci('brier', float(np.mean((p - y) ** 2)))} | {ci('ll', logloss(p, y))} | {ci('slope', sl0)} | {ci('icpt', ic0)} |")
    return out, lines


def plot(out, y):
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "font.family": "sans-serif"})
    fig, ax = plt.subplots(2, 3, figsize=(11, 5.6), gridspec_kw={"height_ratios": [3.2, 1]}, sharex="col")
    for j, m in enumerate(out):
        a, h = ax[0, j], ax[1, j]
        a.plot([0, 1], [0, 1], color="#9a9994", lw=1, ls="--", zorder=1)
        pts = [(mp, o, lo, hi, c) for c, mp, o, lo, hi in out[m] if c]
        x = np.array([p[0] for p in pts]); yv = np.array([p[1] for p in pts]); lo = np.array([p[2] for p in pts]); hi = np.array([p[3] for p in pts])
        a.errorbar(x, yv, yerr=[np.clip(yv - lo, 0, None), np.clip(hi - yv, 0, None)], fmt="none", ecolor=COL[m], elinewidth=1.4, capsize=3, zorder=2)
        a.plot(x, yv, "o-", color=COL[m], lw=2, ms=8, mec="#fcfcfb", mew=1.5, zorder=3)
        for xi, yi, p in zip(x, yv, pts): a.annotate(f"n={p[4]}", (xi, yi), textcoords="offset points", xytext=(5, 7), fontsize=8, color="#52514e")
        a.set_xlim(-0.03, 1.03); a.set_ylim(-0.05, 1.05); a.set_title(NAME[m], color="#0b0b0b", fontsize=11, loc="left")
        a.set_ylabel("observed manipulation rate" if j == 0 else ""); a.grid(color="#e6e5e1", lw=.6); a.set_axisbelow(True)
        h.hist(np.clip(P_ALL[m], 0, 0.999999), bins=EDGES[:-1].tolist() + [1.0], color=COL[m], edgecolor="#fcfcfb", linewidth=2)
        h.set_yscale("log"); h.set_xlabel("predicted P(manipulation), LOOCV"); h.set_ylabel("count (log)" if j == 0 else "")
    fig.suptitle("Reliability, LOOCV, n=162 (24 manipulations). Bars: 95% bootstrap CI of observed rate per bin. Within-benchmark, confounded data.", fontsize=10, x=0.01, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.95]); fig.savefig(REPORTS / "cjsj_07_reliability.png", dpi=160, facecolor="#fcfcfb"); plt.close(fig)


# ---------------- B5 ----------------
def bn_llr(model, thr, row):
    """Exact per-node log-likelihood ratios (manipulation vs volatility) for the evidence in `row`."""
    cpds = {c.variable: c for c in model.get_cpds()}
    ev = {}
    for raw, (dc, pref) in BN_RAW_TO_DISCRETE.items():
        x = _bn_clean(raw, row[raw])
        if pd.notna(x): ev[dc] = f"{pref}_high" if abs(x) > thr[raw] else f"{pref}_low"
    lab = cpds["label_d"]; sn = lab.state_names["label_d"]
    prior = np.log(lab.values[sn.index(E.MAN)] / lab.values[sn.index(E.VOL)])
    rows = []
    for node, state in ev.items():
        c = cpds[node]; parents = [v for v in c.variables if v != node]
        def p_given(label):
            v = c.values; names = c.state_names
            # index: [node, *parents] in c.variables order
            ax = {var: names[var].index(label if var == "label_d" else ev.get(var)) if (var == "label_d" or var in ev) else None for var in parents}
            tot = 0.0
            others = [var for var in parents if var != "label_d" and ax[var] is None]
            import itertools
            grids = [range(len(names[o])) for o in others] or [[None]]
            for combo in itertools.product(*grids):
                idx = [names[node].index(state)]
                for var in parents:
                    if var in others: idx.append(combo[others.index(var)])
                    else: idx.append(ax[var])
                w = 1.0
                for o, ci in zip(others, combo):   # marginalise unobserved parent with its own marginal P(o)
                    w *= cpds[o].values[ci] if cpds[o].values.ndim == 1 else 1.0
                tot += w * v[tuple(idx)]
            return tot
        if "label_d" not in parents: continue
        rows.append((node, state, float(np.log(p_given(E.MAN) / p_given(E.VOL)))))
    post, _ = predict_bayesian_network(model, thr, row)
    lo_post = float(np.log(post[E.MAN] / post[E.VOL]))
    return float(prior), rows, lo_post


def b5(base, name, pxgb_cfg=dict(max_depth=2, n_estimators=150, learning_rate=0.1)):
    i = int(base.index[base.incident == name][0]); tr = np.delete(np.arange(len(base)), i)
    d = base.drop(columns=["dt"], errors="ignore")
    m, th = E.bn_fit_c(d.iloc[tr]); row = d.iloc[i]
    prior, rows, lo_post = bn_llr(m, th, row)
    tot = prior + sum(r[2] for r in rows)
    ok = abs(tot - lo_post) < 1e-6
    p_rf = float(E.rf_proba(base, tr, np.array([i]), n_est=300)[0])
    X = E.feats(base).values; y = E.labels(base)
    yt = y[tr]; spw = float((yt == 0).sum()) / max(int((yt == 1).sum()), 1)
    g = xgb.XGBClassifier(**pxgb_cfg, scale_pos_weight=spw, tree_method="hist", n_jobs=1, random_state=0, verbosity=0).fit(X[tr], yt)
    contrib = g.get_booster().predict(xgb.DMatrix(X[[i]]), pred_contribs=True)[0]
    p_x = float(g.predict_proba(X[[i]])[0, 1])
    L = [f"#### {name} ({base.label[i]}, {base.date[i]}); BN refit without this incident", ""]
    L.append(f"BN P(manipulation) = {predict_bayesian_network(m, th, row)[0][E.MAN]:.3f}; RF = {p_rf:.3f}; XGBoost = {p_x:.3f}. Decomposition check (prior + sum of LLRs equals VE log-odds): {'OK' if ok else f'MISMATCH ({tot:.4f} vs {lo_post:.4f})'}.")
    L += ["", "| BN evidence (discretized node = observed state) | raw value | LLR manip:vol (natural log) | direction |", "|---|---|---|---|"]
    raw_of = {dc: raw for raw, (dc, _) in BN_RAW_TO_DISCRETE.items()}
    L.append(f"| prior (training class frequencies) | - | {prior:+.2f} | {'manip' if prior > 0 else 'vol'} |")
    for node, state, llr in sorted(rows, key=lambda r: -abs(r[2])):
        rv = row[raw_of[node]]
        L.append(f"| {node} = {state} | {rv:.4g} | {llr:+.2f} | {'manip' if llr > 0 else 'vol'} |")
    miss = [raw for raw, (dc, _) in BN_RAW_TO_DISCRETE.items() if pd.isna(_bn_clean(raw, row[raw]))]
    L.append(f"| **total log-odds** | | **{tot:+.2f}** | P={1 / (1 + np.exp(-tot)):.3f} |")
    L.append(""); L.append(f"Missing evidence (omitted by the BN, so it contributes nothing): {', '.join(miss) if miss else 'none'}.")
    L += ["", "XGBoost native per-feature contributions (log-odds, same held-out incident; features are the 8 ALW features):", "", "| feature | value | contribution |", "|---|---|---|"]
    fn = E.ALW
    for k in np.argsort(-np.abs(contrib[:-1])):
        L.append(f"| {fn[k]} | {X[i][k]:.4g} | {contrib[k]:+.2f} |")
    L.append(f"| (bias) | | {contrib[-1]:+.2f} |"); L.append("")
    return "\n".join(L)


P_ALL = {}


def main():
    pr = pd.read_csv(REPORTS / "cjsj_loocv_preds.csv"); base = E.load_base(); assert list(base.incident) == list(pr.incident)
    y = pr.y.values.astype(int)
    P_ALL.update({"BN": pr.p_bn.values, "RF": pr.p_rf.values, "XGB": pr.p_xgb.values})
    out, lines = reliability(y, P_ALL); plot(out, y)
    O = []; Q = O.append
    Q("### 7a. B2 reliability, LOOCV (n=162, 24 positives), 2000-rep bootstrap over incidents, 95% percentile CIs")
    Q(""); Q("![reliability](cjsj_07_reliability.png)  (`reports/cjsj_07_reliability.png`)"); Q("")
    Q("| Model | ECE (6 bins) | Brier (per-class, mean (p-y)^2) | log-loss | calibration slope | calibration intercept |"); Q("|---|---|---|---|---|---|")
    for l in lines: Q(l)
    Q(""); Q("Slope 1 / intercept 0 = perfect calibration; slope > 1 means under-confident, < 1 over-confident. Per-bin values (n, mean predicted, observed rate, 95% CI):"); Q("")
    Q("| Model | bin | n | mean predicted | observed | 95% CI |"); Q("|---|---|---|---|---|---|")
    for m, bl in out.items():
        for b, (c, mp, o, lo, hi) in enumerate(bl):
            if c: Q(f"| {NAME[m]} | [{EDGES[b]:.1f}, {min(EDGES[b + 1], 1):.1f}) | {c} | {mp:.3f} | {o:.3f} | [{lo:.3f}, {hi:.3f}] |")
    Q(""); Q("Bins with few incidents (see n) have wide intervals; with 24 positives the upper bins are thin for every model.")
    Q("")
    bnp = pr.set_index("incident").p_bn
    crash_fa = base[(base.label == E.VOL)].incident[lambda s: bnp[s.values].values >= .5].tolist()
    crash_fa = sorted(crash_fa, key=lambda n: -bnp[n])
    crash_ok = [n for n in base[base.label == E.VOL].incident if bnp[n] < .02][:1]
    Q("### 7b. B5 evidence breakdown (BN exact log-likelihood-ratio contributions vs RF single score vs XGBoost contributions)")
    Q("")
    Q(f"Incidents: manipulation = UwU Lend; crash false alarm = {crash_fa[0]} (BN P={bnp[crash_fa[0]]:.3f}); correctly classified crash = {crash_ok[0]} (BN P={bnp[crash_ok[0]]:.3f}). Crash names are volatility-class incidents from `features.parquet`.")
    Q("")
    for nm in ["UwU Lend", crash_fa[0], crash_ok[0]]:
        Q(b5(base, nm))
    body = "\n".join(O); print(body)
    write_section("cjsj_07_calibration_evidence.py", "7", "B2 reliability diagrams with bootstrap CIs; B5 evidence breakdown", TAG_CONFOUNDED, body)


if __name__ == "__main__":
    main()
