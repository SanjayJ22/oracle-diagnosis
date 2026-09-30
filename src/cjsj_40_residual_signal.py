"""CJSJ item 40: residual signal. LOOCV AUC (RF 150 trees, XGBoost fixed config, logistic regression, BN; stratified bootstrap 95% CI, 2000 reps) on all 24 and verified 9 using ONLY features that are none of:
market-context, missingness indicators, or reserve_skew. Feature inventory (columns of features.parquet) and what is excluded and why is printed below; the remaining set is fixed in the script (REMAINING).
Judgment calls, stated: reserve_skew_localization and skew_vol_ratio are functions of reserve_skew (skew_vol_ratio also of ref_realized_vol) so they are excluded; market_basket_skew describes the ETH reference basket
(market context) and is excluded; n_basket_pools is none of the three excluded kinds (it is a construction artifact: the volatility pool is left out of its own basket) so it stays in the primary set and is
dropped in a sensitivity run. The four price-deviation features (price_dev, cross_venue_spread, dex_oracle_spread, dex_twap_spread) have values for almost every volatility incident and few attacks, so a model that sees
them without explicit indicators can still recover missingness implicitly (median imputation; XGBoost's native NaN handling); the BN omits missing evidence and cannot. BN nodes exist only for price_dev,
cross_venue_spread, dex_oracle_spread. Variants: remaining features; remaining + explicit missingness indicators (is-missing flags of the four deviation features); indicators only."""
from cjsj_common import ensure_omp
ensure_omp()
import numpy as np, pandas as pd
from cjsj_common import ROOT, TAG_VERIFIED, write_section
import cjsj_eval as E
import cjsj_09_shortcuts as C9
from cjsj_35_shortcut_models import loocv

DEV4 = ["price_dev", "cross_venue_spread", "dex_oracle_spread", "dex_twap_spread"]; REMAINING = DEV4 + ["n_basket_pools"]; BN_KEEP = ["price_dev", "cross_venue_spread", "dex_oracle_spread"]
EXCL = {"heartbeat_elapsed": "market-context", "congestion": "market-context", "ref_realized_vol": "market-context", "temporal_n_rounds": "market-context (oracle 24 h trajectory)", "temporal_deviation_persistence": "market-context",
        "temporal_slope": "market-context", "temporal_step_change_count": "market-context", "temporal_gap_trend": "market-context", "market_basket_skew": "market-context (ETH reference basket)",
        "reserve_skew": "reserve_skew (excluded by the brief)", "reserve_skew_localization": "function of reserve_skew", "skew_vol_ratio": "function of reserve_skew and ref_realized_vol"}


def main():
    base = E.load_base(); sets = E.positive_sets(base); L = []; Q = L.append
    ft = pd.read_parquet(ROOT / "data/processed/features.parquet"); num = [c for c in ft.columns if c not in ("incident", "date", "block", "label", "chain", "cohort", "reference_note")]
    sub = ft[ft.label.isin(E.CL)]
    Q("#### 40a. Feature inventory: what remains"); Q("")
    Q("| Feature | status | missing in attacks / volatility (of 24 / 138) |"); Q("|---|---|---|"); att = sub[sub.label == E.MAN]; vol = sub[sub.label == E.VOL]
    for c in num:
        st = "**REMAINS**" if c in REMAINING else "excluded: " + EXCL.get(c, "?")
        Q(f"| {c} | {st} | {int(att[c].isna().sum())} / {int(vol[c].isna().sum())} |")
    Q("")
    Q(f"Remaining features (exactly): **{', '.join(REMAINING)}**. BN nodes available among them: {', '.join(BN_KEEP)}. Sensitivity set without n_basket_pools: {', '.join(DEV4)}. n_basket_pools values: attacks {att.n_basket_pools.value_counts().sort_index().to_dict()}, volatility {vol.n_basket_pools.value_counts().sort_index().to_dict()}.")
    Q("")
    f = lambda t: f"{t[0]:.3f} [{t[1]:.3f}, {t[2]:.3f}]"; res = {}
    Q("#### 40b. LOOCV AUC [stratified bootstrap 95% CI]"); Q("")
    Q("| Label set | Features | RF | XGBoost | Logistic regression | BN |"); Q("|---|---|---|---|---|---|")
    for sname in ["all 24 (audit baseline)", "verified M (9)"]:
        d = E.subset(base, sets[sname]).copy(); y = E.labels(d)
        for c in DEV4: d["miss_" + c] = d[c].isna().astype(float)
        MISS = ["miss_" + c for c in DEV4]
        variants = [("remaining (5)", REMAINING, BN_KEEP, True), ("remaining + missingness indicators", REMAINING + MISS, None, False), ("missingness indicators only", MISS, None, False), ("sensitivity: without n_basket_pools (4)", DEV4, BN_KEEP, True)]
        for lab, cols, keep, bn_ok in variants:
            cells = []
            for m in ["RF", "XGB", "LR", "BN"]:
                if m == "BN" and not bn_ok: cells.append("n/a (no indicator nodes)"); continue
                p = loocv(d, m, cols, keep); res[(sname, lab, m)] = C9.boot(y, [p], lambda yy, pp: C9.auc(yy, pp)); cells.append(f(res[(sname, lab, m)]))
            Q(f"| {sname} | {lab} | " + " | ".join(cells) + " |")
    Q("")
    Q("#### 40c. Reading (computed)"); Q("")
    a24, a9 = "all 24 (audit baseline)", "verified M (9)"
    for s in (a24, a9):
        r0 = {m: res[(s, "remaining (5)", m)] for m in ("RF", "XGB", "LR", "BN")}; ri = {m: res[(s, "remaining + missingness indicators", m)] for m in ("RF", "XGB", "LR")}; r4 = {m: res[(s, "sensitivity: without n_basket_pools (4)", m)] for m in ("RF", "XGB", "LR", "BN")}
        ro = {m: res[(s, "missingness indicators only", m)] for m in ("RF", "XGB", "LR")}
        Q(f"- {s.split(' (')[0]}: remaining features RF {r0['RF'][0]:.3f}, XGB {r0['XGB'][0]:.3f}, LR {r0['LR'][0]:.3f}, BN {r0['BN'][0]:.3f}; adding explicit indicators changes RF by {ri['RF'][0] - r0['RF'][0]:+.3f}, XGB {ri['XGB'][0] - r0['XGB'][0]:+.3f}, LR {ri['LR'][0] - r0['LR'][0]:+.3f}; indicators alone give RF {ro['RF'][0]:.3f}, XGB {ro['XGB'][0]:.3f}, LR {ro['LR'][0]:.3f}; without n_basket_pools: RF {r4['RF'][0]:.3f}, XGB {r4['XGB'][0]:.3f}, LR {r4['LR'][0]:.3f}, BN {r4['BN'][0]:.3f}.")
    above = [f"{m} ({s.split(' (')[0]})" for s in (a24, a9) for m in ("RF", "XGB", "LR", "BN") if res[(s, 'remaining (5)', m)][1] > .5]
    Q(f"- CI lower bound above 0.5 for the remaining features: {', '.join(above) or 'none'}.")
    Q("- Caveat (important): the remaining set is not clean of missingness. price_dev, cross_venue_spread, dex_oracle_spread and dex_twap_spread are missing for 20, 23, 23, 23 of 24 attacks and for 0, 0, 0, 2 of 138 volatility incidents, so in every model a missing value is itself the class signal; the indicators-only rows (4 binary flags) already reach the same AUC. The BN omits missing evidence but is not blind to it: a row with no evidence keeps the prior while every volatility row carries evidence, so its AUC also reflects missingness. n_basket_pools is a construction artifact (attacks 22/24 have 3, volatility 137/138 have 2), and dropping it makes LR fall below 0.5 (leave-one-out artifact, section 42). The non-missingness signal in this set is therefore not separately identified: at most 4 attacks (price_dev) have an observed deviation value, so no valid inference about it is possible from this data.")
    Q("")
    body = "\n".join(L); print(body)
    write_section("cjsj_40_residual_signal.py", "40", "Residual signal: features that are not market-context, not missingness indicators and not reserve_skew", TAG_VERIFIED + "; all-24 rows are within-benchmark (confounded data, see research_audit.md)", body)


if __name__ == "__main__":
    main()
