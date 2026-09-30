"""CJSJ item 26: cost-sensitive analysis with dollar losses of the 24 attacks.
Losses: DeFiHackLabs README `### Lost:` strings (matched to our attacks by date +-4 days and name similarity, reports/defihacklabs_index.csv) or the PoC header
`@KeyInfo - Total Lost`; ETH/WETH amounts are converted at the Chainlink ETH/USD answer at the attack block (eth_call latestAnswer, archive read). Five older attacks have
no figure in either place and use the amounts reported by the retrieved sources (marked 'source override'). Where a PoC/README states a per-pool figure inside a
multi-pool campaign (Ajna, BalancerV1BPool, SecuredFi) the per-pool/per-tx figure is used, since the dataset row is that transaction.
Decision cost (in units of one false halt): cost = FH + R * w_i * [attack i missed] where R = ratio (1:10, 1:100, 1:1000 = a missed attack costs R false halts on
average), and w_i = L_i / mean(L) (dollar-weighted) or 1 (count-based). Expected cost per 1000 anomalies at prevalence pi: 1000 * ((1-pi) * FPR + pi * R * mean_i(w_i * miss_i)).
Operating point: threshold .5 (as deployed). Evaluations: LOOCV predictions (cjsj_loocv_preds.csv, 24 attacks / 138 volatility) and forward-time 2024-01 (13 attacks / 70).
Also an optimistic best-threshold sweep (threshold chosen in-sample to minimize cost; shown separately). P(cheapest) = share of 2000 stratified bootstrap resamples in which
the model has the lowest expected cost. Baselines: flag nothing, flag everything. Figure: reports/figures/fig_cost_curves.png."""
from cjsj_common import ensure_omp
ensure_omp()
import re, difflib
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from cjsj_common import REPORTS, ROOT, TAG_CONFOUNDED, rpc, write_section
import cjsj_eval as E
from cjsj_fwd import forward_all

DHL = ROOT.parent  # placeholder, replaced below
import os
from pathlib import Path
DHL = Path(os.environ.get("DEFIHACKLABS_DIR", "/private/tmp/claude-501/-Users-sanjayjillellamudi/d1383b8d-c9c6-4c1d-900f-92574fa52ea4/scratchpad/DeFiHackLabs"))
OVERRIDE = {  # incident: (USD, source)
    "Harvest Finance": (24e6, "CoinDesk 2020-10-26: ~$24M drained"), "Cream Finance": (130e6, "The Register 2021-10-28: ~$130M"),
    "Indexed Finance": (16e6, "PeckShield via BeInCrypto: ~$16M"), "Inverse Finance": (5.83e6, "BlockSec: net protocol loss $5.83M (attacker gain $1.2M)"),
    "MonoX Finance": (31e6, "SlowMist/MonoX post-mortem: ~$31M"),
}
POC_FILE = {"MEVBOTa47b": "2022-10/MEVa47b_exp.sol", "BalancerBoostedPool2023": "2023-08/Balancer_exp.sol", "TOPBPool": "2026-06/TOPBPool_exp.sol", "EFLeverVault": "2022-10/EFLeverVault_exp.sol"}
NAMES = {"UwU Lend": "UwULend"}


def parse_amount(s):
    s = str(s); m = re.search(r"(~?\$)?\s*([\d,]+(?:\.\d+)?)\s*([KkMmBb])?\s*(USDC|USD|US\$|WETH|ETH|WBTC|BTC)?", s)
    if not m: return None
    num = float(m.group(2).replace(",", "")); mult = {"k": 1e3, "m": 1e6, "b": 1e9}.get((m.group(3) or "").lower(), 1.0); unit = (m.group(4) or ("USD" if m.group(1) else "USD")).upper()
    if unit in ("WBTC", "BTC"):
        d = re.search(r"\$\s*([\d,]+(?:\.\d+)?)\s*([KkMm])", s); return (float(d.group(1).replace(",", "")) * {"k": 1e3, "m": 1e6}[d.group(2).lower()], "USD") if d else None
    return num * mult, ("ETH" if unit in ("ETH", "WETH") else "USD")


def eth_usd(block):
    r = rpc("eth_call", [{"to": "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", "data": "0x50d25bcd"}, hex(int(block))]); return int(r, 16) / 1e8


def losses():
    sh = pd.read_csv(REPORTS / "a2_label_sheet.csv"); idx = pd.read_csv(REPORTS / "defihacklabs_index.csv"); idx["d"] = pd.to_datetime(idx.date.astype(str), format="%Y%m%d")
    ft = pd.read_parquet(ROOT / "data/processed/features.parquet").set_index("incident"); rows = []
    for r in sh.itertuples():
        inc = r.incident_id; d0 = pd.Timestamp(ft.date[inc]); raw = src = None
        if inc in OVERRIDE: usd, src = OVERRIDE[inc]; raw = "(no figure in README/PoC)"
        else:
            near = idx[(idx.d - d0).abs() <= pd.Timedelta(days=4)]
            if len(near):
                sc = near["name"].map(lambda n: difflib.SequenceMatcher(None, re.sub(r"[^a-z0-9]", "", n.lower()), re.sub(r"[^a-z0-9]", "", inc.lower())).ratio()); best = near.loc[sc.idxmax()]
                raw = best.lost if isinstance(best.lost, str) else None; src = f"README ({best['name']}, {best.date})"
            if raw is None and inc in POC_FILE:
                t = (DHL / "src/test" / POC_FILE[inc]).read_text(errors="ignore"); m = re.search(r"Total Lost\s*:\s*(.*)", t); raw = m.group(1).strip() if m else None; src = f"PoC header ({POC_FILE[inc]})"
            pa = parse_amount(raw) if raw else None
            if pa is None: raise SystemExit(f"no parsable loss for {inc}: {raw!r}")
            usd = pa[0] if pa[1] == "USD" else pa[0] * eth_usd(r.T_block)
        rows.append(dict(incident=inc, category=r.category, verified_M=bool(r.verified_M), raw=raw, usd=float(usd), source=src, T_block=int(r.T_block)))
    return pd.DataFrame(rows)


def cost(pred_neg, pred_pos, w, R, pi):
    fpr = np.mean(pred_neg); miss = np.mean(w * (1 - pred_pos)); return 1000 * ((1 - pi) * fpr + pi * R * miss)


def main():
    LS = losses(); LS.to_csv(REPORTS / "cjsj_26_losses.csv", index=False)
    pr = pd.read_csv(REPORTS / "cjsj_loocv_preds.csv"); base = E.load_base(); lmap = LS.set_index("incident").usd; y = pr.y.values.astype(int)
    fw = forward_all(base, ["2024-01-01"])[0]; te = fw["te"]
    ev = {"LOOCV (24 attacks / 138 volatility)": dict(score={"BN": pr.p_bn.values, "RF": pr.p_rf.values, "XGB": pr.p_xgb.values}, mask=np.ones(len(y), bool)),
          "forward 2024-01 (13 attacks / 70 volatility)": dict(score={m: fw["P"][m] for m in ("BN", "RF", "XGB")}, mask=np.isin(np.arange(len(y)), te))}
    RATIOS = [10, 100, 1000]; PIS = [0.01, 0.05, 0.148]; L = []; Q = L.append
    Q("#### 26a. Dollar losses used (`reports/cjsj_26_losses.csv`)"); Q("")
    Q("| Attack | A2 cat | verified M | loss (USD) | source | raw string |"); Q("|---|---|---|---|---|---|")
    for r in LS.sort_values("usd", ascending=False).itertuples(): Q(f"| {r.incident} | {r.category} | {'yes' if r.verified_M else 'no'} | {r.usd:,.0f} | {r.source} | {str(r.raw)[:70]} |")
    Q(""); Q(f"Total {LS.usd.sum():,.0f} USD; median {LS.usd.median():,.0f}; largest two (Cream, BalancerV2) = {LS.usd.nlargest(2).sum() / LS.usd.sum():.0%} of the total, so dollar-weighted cost is dominated by whether those two are caught. ETH conversions at Chainlink ETH/USD at the attack block: " +
      ", ".join(f"{r.incident} {r.usd / (parse_amount(r.raw)[0]):.0f}" for r in LS.itertuples() if isinstance(r.raw, str) and parse_amount(r.raw) and parse_amount(r.raw)[1] == 'ETH') + " USD/ETH.")
    Q("")
    wins = {}
    for ename, e in ev.items():
        m = e["mask"]; yy = y[m]; inc = pr.incident.values[m]; att = yy == 1
        Lm = np.array([lmap.get(i, np.nan) for i in inc[att]]); wd = Lm / np.nanmean(Lm); wc = np.ones(att.sum())
        Q(f"#### 26b. Expected cost per 1000 anomalies, in false-halt units, {ename} (threshold .5)"); Q("")
        Q("| Weighting | Ratio 1:R | prevalence | BN | RF | XGB | flag nothing | flag everything | cheapest [P(cheapest) over bootstrap] |"); Q("|---|---|---|---|---|---|---|---|---|")
        rng = np.random.default_rng(0); P = {mm: (e["score"][mm][m] >= .5).astype(int) for mm in ("BN", "RF", "XGB")}
        neg_i = np.where(~att)[0]; pos_i = np.where(att)[0]
        for wname, w in [("dollar-weighted", wd), ("count-based", wc)]:
            for R in RATIOS:
                for pi in PIS:
                    c = {mm: cost(P[mm][~att], P[mm][att], w, R, pi) for mm in P}; none = 1000 * pi * R * np.mean(w); allf = 1000 * (1 - pi)
                    wins_b = {mm: 0 for mm in P}
                    for _ in range(1000):
                        sn = rng.choice(np.arange(len(neg_i)), len(neg_i)); sp = rng.choice(np.arange(len(pos_i)), len(pos_i))
                        cc = {mm: cost(P[mm][~att][sn], P[mm][att][sp], w[sp], R, pi) for mm in P}; mn = min(cc.values()); ws = [k for k, v in cc.items() if abs(v - mn) < 1e-9]
                        for k in ws: wins_b[k] += 1 / len(ws)
                    best = min(c, key=c.get); wins[(ename, wname, R, pi)] = (best, c, wins_b)
                    Q(f"| {wname} | 1:{R} | {pi:.1%} | {c['BN']:.0f} | {c['RF']:.0f} | {c['XGB']:.0f} | {none:.0f} | {allf:.0f} | **{best}** [BN {wins_b['BN'] / 1000:.2f}, RF {wins_b['RF'] / 1000:.2f}, XGB {wins_b['XGB'] / 1000:.2f}] |")
        Q("")
    # optimistic best-threshold sweep
    Q("#### 26c. Optimistic best-threshold sweep (threshold picked in-sample to minimize cost; upper bound on what threshold tuning could give)"); Q("")
    Q("| Evaluation | Weighting | Ratio | prevalence | BN (thr) | RF (thr) | XGB (thr) |"); Q("|---|---|---|---|---|---|---|")
    for ename, e in ev.items():
        m = e["mask"]; yy = y[m]; att = yy == 1; inc = pr.incident.values[m]; Lm = np.array([lmap.get(i, np.nan) for i in inc[att]]); wd = Lm / np.nanmean(Lm)
        for wname, w in [("dollar-weighted", wd)]:
            for R in RATIOS:
                for pi in [0.01, 0.05]:
                    cells = []
                    for mm in ("BN", "RF", "XGB"):
                        s = e["score"][mm][m]; best = (np.inf, None)
                        for t in np.unique(np.concatenate([s, [0.0, 1.0001]])):
                            c = cost((s[~att] >= t).astype(int), (s[att] >= t).astype(int), w, R, pi)
                            if c < best[0] - 1e-9: best = (c, t)
                        cells.append(f"{best[0]:.0f} ({best[1]:.3f})")
                    Q(f"| {ename.split(' (')[0]} | {wname} | 1:{R} | {pi:.0%} | " + " | ".join(cells) + " |")
    Q("")
    Q("#### 26d. Winners at the requested ratios (threshold .5)"); Q("")
    Q("| Evaluation | Weighting | prevalence | 1:10 | 1:100 | 1:1000 |"); Q("|---|---|---|---|---|---|")
    for ename in ev:
        for wname in ["dollar-weighted", "count-based"]:
            for pi in PIS: Q(f"| {ename.split(' (')[0]} | {wname} | {pi:.1%} | " + " | ".join(wins[(ename, wname, R, pi)][0] for R in RATIOS) + " |")
    Q("")
    # figure: LOOCV, dollar-weighted, pi=5%
    Rg = np.logspace(0, 4, 60); fig, ax = plt.subplots(1, 2, figsize=(11.2, 4.2), sharey=True); col = {"BN": "#2a78d6", "RF": "#eb6834", "XGB": "#1baf7a"}
    for a, (ename, e) in zip(ax, ev.items()):
        m = e["mask"]; yy = y[m]; att = yy == 1; inc = pr.incident.values[m]; Lm = np.array([lmap.get(i, np.nan) for i in inc[att]]); w = Lm / np.nanmean(Lm)
        for mm, mk in zip(("BN", "RF", "XGB"), "osv"):
            p = (e["score"][mm][m] >= .5).astype(int); a.plot(Rg, [cost(p[~att], p[att], w, R, 0.05) for R in Rg], color=col[mm], lw=2, label=mm)
        a.plot(Rg, [1000 * 0.05 * R * np.mean(w) for R in Rg], color="#9a9994", ls="--", label="flag nothing"); a.axhline(1000 * .95, color="#c0c0bb", ls=":", label="flag everything")
        a.set_xscale("log"); a.set_yscale("log"); a.set_title(ename.split(" (")[0], loc="left", fontsize=10); a.set_xlabel("cost ratio R (missed attack : false halt)"); a.grid(color="#e6e5e1", lw=.6)
        for R in RATIOS: a.axvline(R, color="#e6e5e1", lw=1)
    ax[0].set_ylabel("expected cost per 1000 anomalies\n(false-halt units), prevalence 5%, dollar-weighted"); ax[0].legend(frameon=False, fontsize=8.5)
    fig.suptitle("Expected-cost curves at threshold .5 (within-benchmark, confounded data)", fontsize=10, x=0.01, ha="left"); fig.tight_layout(rect=[0, 0, 1, 0.93])
    (REPORTS / "figures").mkdir(exist_ok=True); fig.savefig(REPORTS / "figures" / "fig_cost_curves.png", dpi=160); plt.close(fig)
    Q("Figure: `reports/figures/fig_cost_curves.png` (prevalence 5%, dollar-weighted).")
    body = "\n".join(L); print(body)
    write_section("cjsj_26_cost.py", "26", "Cost-sensitive analysis with DeFiHackLabs dollar losses", TAG_CONFOUNDED, body)


if __name__ == "__main__":
    main()
