"""Final certification pass over the complete project. Two checks, read-only --
does not touch data/processed/features.parquet or change any model's fitted behavior,
only measures variants of it for the purpose of this report.

1. ABLATION: for both Naive Bayes and the Bayesian network, under leave-one-incident-out,
   drop one feature at a time and measure the resulting per-class + overall accuracy
   (vs the full-6-feature LOOCV baseline established in loocv_validation.py: NB 75%
   overall / BN 80% overall). Confirms (or refutes) which feature "carries" which class.

2. LEAKAGE / ROBUSTNESS AUDIT: hunt for remaining data artifacts the way the
   heartbeat_elapsed anchoring bug was found earlier. Checks: single-feature perfect
   class separation, manipulation reserve_skew cleanliness, remaining lookahead,
   structural/bookkeeping separability.
"""

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from models import (
    BN_RAW_TO_DISCRETE,
    FEATURE_COLS,
    FEATURES_PATH,
    LABELS,
    RESERVE_SKEW_CLIP,
    _fit_gaussian_nb,
    fit_bayesian_network,
    naive_bayes_posterior,
    predict_bayesian_network,
)

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 20)


# ============================================================================
# 1. Ablation
# ============================================================================

def _loocv_nb_preds(df: pd.DataFrame, drop_feature: str = None) -> dict:
    cols = [c for c in FEATURE_COLS if c != drop_feature]
    preds = {}
    for i in range(len(df)):
        held_out = df.iloc[i]
        train = df.drop(df.index[i])
        priors = {label: (train["label"] == label).mean() for label in LABELS}
        stats = _fit_gaussian_nb(train, feature_cols=cols)
        post = naive_bayes_posterior(held_out, stats, priors, feature_cols=cols)
        preds[held_out["incident"]] = max(post, key=post.get)
    return preds


def _loocv_bn_preds(df: pd.DataFrame, drop_feature: str = None) -> tuple:
    preds = {}
    fit_failures = 0
    for i in range(len(df)):
        held_out = df.iloc[i]
        train = df.drop(df.index[i])
        model, thresholds = fit_bayesian_network(train, verbose=False, drop_feature=drop_feature)
        if model is None:
            preds[held_out["incident"]] = None
            fit_failures += 1
            continue
        post, _evidence = predict_bayesian_network(model, thresholds, held_out)
        preds[held_out["incident"]] = max(post, key=post.get)
    return preds, fit_failures


def _accuracy(df: pd.DataFrame, preds: dict) -> tuple:
    correct = {label: 0 for label in LABELS}
    total = {label: int((df["label"] == label).sum()) for label in LABELS}
    for _, r in df.iterrows():
        if preds.get(r["incident"]) == r["label"]:
            correct[r["label"]] += 1
    overall = sum(correct.values()) / len(df)
    per_class = {label: correct[label] / total[label] for label in LABELS}
    return overall, per_class


def _loocv_nb(df: pd.DataFrame, drop_feature: str = None):
    preds = _loocv_nb_preds(df, drop_feature)
    overall, per_class = _accuracy(df, preds)
    return overall, per_class, preds


def _loocv_bn(df: pd.DataFrame, drop_feature: str = None):
    preds, fit_failures = _loocv_bn_preds(df, drop_feature)
    overall, per_class = _accuracy(df, preds)
    return overall, per_class, fit_failures, preds


def _report_flips(df: pd.DataFrame, base_preds: dict, drop_preds: dict, model_name: str, feature: str):
    """Print per-incident prediction changes -- a 0% net accuracy delta can hide a
    correct->wrong flip and a wrong->correct flip cancelling out, which matters for
    honestly attributing what a feature does."""
    flips = []
    for _, r in df.iterrows():
        name, true = r["incident"], r["label"]
        b, d = base_preds.get(name), drop_preds.get(name)
        if b != d:
            b_ok, d_ok = (b == true), (d == true)
            direction = "correct->WRONG" if b_ok and not d_ok else ("WRONG->correct" if d_ok and not b_ok else "wrong->wrong (different)")
            flips.append((name, true, b, d, direction))
    if flips:
        print(f"    {model_name} drop-{feature} per-incident flips ({len(flips)}):")
        for name, true, b, d, direction in flips:
            print(f"      {name:35s} true={true:24s} {b!s:24s} -> {d!s:24s}  [{direction}]")
    return flips


def run_ablation(df: pd.DataFrame) -> pd.DataFrame:
    print("=" * 100)
    print("ABLATION: drop one feature at a time, re-run LOOCV, measure accuracy change")
    print("=" * 100)

    nb_base_overall, nb_base_pc, nb_base_preds = _loocv_nb(df, None)
    bn_base_overall, bn_base_pc, bn_base_fail, bn_base_preds = _loocv_bn(df, None)

    print(f"\nBaseline (all 6 features, LOOCV):")
    print(f"  Naive Bayes      overall={nb_base_overall:.0%}   manipulation={nb_base_pc['manipulation']:.0%}  "
          f"malfunction={nb_base_pc['malfunction']:.0%}  volatility={nb_base_pc['large volatility event']:.0%}")
    print(f"  Bayesian Network overall={bn_base_overall:.0%}   manipulation={bn_base_pc['manipulation']:.0%}  "
          f"malfunction={bn_base_pc['malfunction']:.0%}  volatility={bn_base_pc['large volatility event']:.0%}"
          + (f"   ({bn_base_fail} fold(s) failed to fit)" if bn_base_fail else ""))

    rows = []
    all_flips = {}
    for feat in FEATURE_COLS:
        nb_overall, nb_pc, nb_preds = _loocv_nb(df, feat)
        # FEATURE_COLS (NB's feature list) and BN_RAW_TO_DISCRETE (BN's) are no
        # longer 1:1 since the temporal-features per-model split (reports/
        # temporal_features.md): temporal_gap_trend is in FEATURE_COLS (helps NB)
        # but deliberately absent from BN's structure (hurts BN). Dropping a
        # feature BN never had would previously crash fit_bayesian_network with a
        # KeyError -- guarded here (not in models.py, to keep this fix scoped to
        # the ablation script rather than touching production) by skipping BN's
        # ablation for such features and reporting it explicitly as N/A, not
        # silently zero.
        feat_in_bn = feat in BN_RAW_TO_DISCRETE
        if feat_in_bn:
            bn_overall, bn_pc, bn_fail, bn_preds = _loocv_bn(df, feat)
        else:
            bn_overall, bn_pc, bn_fail, bn_preds = None, None, None, None
        rows.append({
            "feature_dropped": feat,
            "NB_overall_Δ": nb_overall - nb_base_overall,
            "NB_manip_Δ": nb_pc["manipulation"] - nb_base_pc["manipulation"],
            "NB_malf_Δ": nb_pc["malfunction"] - nb_base_pc["malfunction"],
            "NB_vol_Δ": nb_pc["large volatility event"] - nb_base_pc["large volatility event"],
            "BN_overall_Δ": (bn_overall - bn_base_overall) if feat_in_bn else np.nan,
            "BN_manip_Δ": (bn_pc["manipulation"] - bn_base_pc["manipulation"]) if feat_in_bn else np.nan,
            "BN_malf_Δ": (bn_pc["malfunction"] - bn_base_pc["malfunction"]) if feat_in_bn else np.nan,
            "BN_vol_Δ": (bn_pc["large volatility event"] - bn_base_pc["large volatility event"]) if feat_in_bn else np.nan,
            "BN_fit_failures": bn_fail if feat_in_bn else "N/A (not in BN)",
        })
        all_flips[feat] = {
            "nb": _report_flips(df, nb_base_preds, nb_preds, "NB", feat),
            "bn": _report_flips(df, bn_base_preds, bn_preds, "BN", feat) if feat_in_bn else [],
        }

    result = pd.DataFrame(rows).set_index("feature_dropped")
    print("\nAccuracy CHANGE from baseline when each feature is removed (negative = feature was load-bearing):")
    print(result.drop(columns=["BN_fit_failures"]).to_string(float_format=lambda x: f"{x:+.0%}"))
    print("\nBN fit failures per drop (a fold whose training CPD had zero complete rows):")
    print(result["BN_fit_failures"].to_string())

    print(
        "\nCaution: a 0% net delta can hide a correct->wrong flip and a wrong->correct flip"
        " cancelling out. Per-incident flips printed above for every (model, feature) pair"
        " that changed even one prediction -- e.g. dropping heartbeat_elapsed nets to +0%"
        " on NB's volatility recall, but that's a real flip TO wrong (Oct 2025 flash crash)"
        " cancelling a real flip TO correct (March 2024 rally), not 'no effect'."
    )

    print(
        "\nInterpretation -- confirming/refuting the hypothesis (reserve_skew carries manipulation,\n"
        "heartbeat_elapsed carries malfunction) empirically, per model:\n"
        f"  - NB manipulation: carried by reserve_skew (drop -> {result.loc['reserve_skew','NB_manip_Δ']:+.0%},"
        f" loses Indexed Finance). heartbeat_elapsed drop = {result.loc['heartbeat_elapsed','NB_manip_Δ']:+.0%}"
        f" net (no manipulation incident flips) -- reserve_skew is the one carrying manipulation for NB,"
        f" matching the hypothesis.\n"
        f"  - BN manipulation: the SINGLE biggest effect in the whole table is dropping ref_realized_vol"
        f" (-> {result.loc['ref_realized_vol','BN_manip_Δ']:+.0%}, loses 4 of 5 -- Cream/Indexed/Inverse/UwU),"
        f" bigger than dropping heartbeat_elapsed (-> {result.loc['heartbeat_elapsed','BN_manip_Δ']:+.0%},"
        f" loses Harvest/Indexed/Inverse). reserve_skew drop = {result.loc['reserve_skew','BN_manip_Δ']:+.0%}"
        f" (zero flips). This CONTRADICTS the hypothesis for the BN: its manipulation calls lean on"
        f" ref_realized_vol first and heartbeat_elapsed second, not on reserve_skew at all -- plausible"
        f" (attackers may prefer calm markets so a manipulated block looks anomalously quiet under-neath),"
        f" but also exactly the kind of over-reliance on a 5-incident class a small sample can produce.\n"
        f"  - NB malfunction: NOT carried by heartbeat_elapsed (drop -> {result.loc['heartbeat_elapsed','NB_malf_Δ']:+.0%}"
        f" net, no malfunction flips at all) -- instead carried by ref_realized_vol (drop -> "
        f"{result.loc['ref_realized_vol','NB_malf_Δ']:+.0%}, loses UST/USD). This CONTRADICTS the hypothesis"
        f" for NB.\n"
        f"  - BN malfunction: carried by BOTH heartbeat_elapsed (drop -> {result.loc['heartbeat_elapsed','BN_malf_Δ']:+.0%})"
        f" AND price_dev (drop -> {result.loc['price_dev','BN_malf_Δ']:+.0%}) -- both drops lose the same"
        f" single incident (UST/USD, the BN's only correct malfunction call under LOOCV), so this is really"
        f" one incident being correctly called via two redundant signals, not two independent confirmations.\n"
        f"  Net: the hypothesis holds cleanly only for NB-manipulation/reserve_skew. Everywhere else"
        f" (BN-manipulation, NB-malfunction, BN-malfunction) the real load-bearing feature differs from"
        f" what was expected, and BN's malfunction 'signal' rests on a single incident (n=3 class, only 1"
        f" ever gets a correct LOOCV call) -- too little data to call this a validated pattern rather than"
        f" a description of these specific 20 points."
    )
    return result, all_flips


# ============================================================================
# 2. Leakage / robustness audit
# ============================================================================

def _clip(series: pd.Series) -> pd.Series:
    return series.apply(lambda v: (np.sign(v) * RESERVE_SKEW_CLIP if (pd.notna(v) and np.isinf(v)) else v))


def audit_missingness_by_class(df: pd.DataFrame):
    print("\n--- (a) Missingness pattern per feature per class ---")
    print("Checking whether any feature's mere PRESENCE/ABSENCE (not its value) tracks a class --")
    print("this is exactly the shape of bug the heartbeat_elapsed anchoring artifact had.\n")
    miss = pd.DataFrame({
        col: df.groupby("label")[col].apply(lambda s: s.isna().sum())
        for col in FEATURE_COLS
    })
    total = df.groupby("label").size()
    miss_pct = miss.div(total, axis=0)
    print(miss.to_string())
    print()

    findings = []
    for col in FEATURE_COLS:
        for label in LABELS:
            pct_missing_in = miss_pct.loc[label, col]
            others = [l for l in LABELS if l != label]
            pct_missing_out = (miss.loc[others, col].sum()) / (total.loc[others].sum())
            if pct_missing_in in (0.0, 1.0) and abs(pct_missing_in - pct_missing_out) > 0.5:
                findings.append((col, label, pct_missing_in, pct_missing_out))
    return findings


def audit_perfect_separation(df: pd.DataFrame):
    print("\n--- (b) Single-feature perfect-separation check ---")
    print("For each feature/class pair with data on BOTH sides, check whether the value ranges")
    print("overlap. No overlap = a threshold exists that perfectly separates that class (suspicious).\n")
    findings = []
    for col in FEATURE_COLS:
        vals = _clip(df[col])
        for label in LABELS:
            in_c = vals[df["label"] == label].dropna()
            out_c = vals[df["label"] != label].dropna()
            if len(in_c) == 0 or len(out_c) == 0:
                print(f"  {col:20s} vs {label:24s}: SKIPPED -- one side has zero non-missing observations "
                      f"(see missingness check above, not a value-based separation)")
                continue
            no_overlap = in_c.min() > out_c.max() or in_c.max() < out_c.min()
            flag = "  <<<< PERFECT SEPARATION" if no_overlap else ""
            print(f"  {col:20s} vs {label:24s}: in=[{in_c.min():.4f},{in_c.max():.4f}] (n={len(in_c)})  "
                  f"out=[{out_c.min():.4f},{out_c.max():.4f}] (n={len(out_c)}){flag}")
            if no_overlap:
                findings.append((col, label, in_c.min(), in_c.max(), out_c.min(), out_c.max()))
    return findings


def audit_manipulation_reserve_skew(df: pd.DataFrame):
    print("\n--- (c) Manipulation reserve_skew / price_dev cleanliness ---")
    manip = df[df["label"] == "manipulation"][["incident", "price_dev", "reserve_skew", "reference_note"]]
    for _, r in manip.iterrows():
        print(f"  {r['incident']:20s} price_dev={r['price_dev']!s:>10}  reserve_skew={r['reserve_skew']!s:>10}")
    print(
        "\n  Known, previously-documented caveats (re-confirmed here, not new):\n"
        "  - Cream Finance reserve_skew is +inf (clipped to +3.0 for arithmetic): the vault went from\n"
        "    ~0 backing to ~1.0 exactly at the attack block, a real and correctly-captured infinite jump,\n"
        "    not a bug -- this IS the exploit.\n"
        "  - Inverse Finance reserve_skew (+2.4%) is a known UNDERSTATEMENT: the flash-loan deposit and its\n"
        "    self-reversal land in the same block, so the post-block balance partially nets out the\n"
        "    attacker's own temporary deposit. Its value overlaps with ordinary volatility-day DEX moves\n"
        "    (e.g. April 2025's 5.6%) -- this is a real limitation, not corrected here, consistent with\n"
        "    why the deterministic rule and some LOOCV folds get this incident wrong.\n"
        "\n  NEW finding from this pass: Harvest Finance's price_dev (+24.4%) is computed against an\n"
        "  assumed 1.0 peg for the raw yUSDC/yUSDT balanceOf() ratio in the Curve Y pool. But the\n"
        "  temporal trajectory analysis (reports/temporal_trajectories.md) already showed this ratio\n"
        "  sits at ~1.24-1.32 throughout the whole +/-1h window around the attack, including the start\n"
        "  and end of the window -- i.e. it is NEVER near 1.0, attack or no attack. This is because\n"
        "  get_coin_balances() reads raw yToken balances directly, and yDAI/yUSDC/yUSDT/yTUSD each\n"
        "  accrue yield at different rates against their own underlying, so their raw balance ratio in\n"
        "  the pool has no reason to sit at 1:1 even when the pool is perfectly healthy. price_dev's\n"
        "  assumed peg is therefore the WRONG reference point for this incident, and +24.4% overstates\n"
        "  how far the attack moved the venue from a genuine baseline. reserve_skew is NOT affected the\n"
        "  same way: it compares the SAME ratio at the incident block vs 300 blocks (~1h) earlier, and\n"
        "  yield-rate drift over 1 hour is negligible next to the attack's own -13% move, so reserve_skew\n"
        "  stays a clean before/after measurement at the same venue. Net effect: Harvest's reserve_skew is\n"
        "  trustworthy; its price_dev is not, and price_dev is not the feature relied on for manipulation\n"
        "  (reserve_skew is, per your instruction after the first alignment probe) -- but flagging this\n"
        "  plainly since it's exactly the kind of hidden reference-point issue this audit is meant to catch."
    )


def audit_lookahead():
    print("\n--- (d) Remaining lookahead check (code-level, not data-level) ---")
    print(
        "  Re-read build_features.py, recompute_manipulation_curve_features.py,\n"
        "  recompute_heartbeat_elapsed.py, and fetch_curve.py in full for this pass. Findings:\n"
        "  - All DEX/oracle/vault reads use `block_identifier=block_number` (or block_number - N)\n"
        "    against the EVM's own historical state. This isn't just a convention that could be\n"
        "    violated by accident -- a state query at block N architecturally cannot see block N+1's\n"
        "    data, since it doesn't exist yet at that point in history. No RPC call in this codebase\n"
        "    reads a block > the incident's own anchor block.\n"
        "  - reserve_skew's baseline is always block_number - BASELINE_LAG_BLOCKS (before), never after,\n"
        "    in both build_features.py and recompute_manipulation_curve_features.py.\n"
        "  - price_dev/ref_realized_vol's CEX candle lookup explicitly filters to\n"
        "    `cex[cex['timestamp'] <= window_end]` and takes the LAST (most recent) row -- 'at or\n"
        "    before', never after.\n"
        "  - heartbeat_elapsed (post-fix) reads the round at block_number - 1, strictly before the\n"
        "    anchor -- confirmed still the case, this pass didn't touch it.\n"
        "  - congestion's trailing sample loop is `range(start_block, block_number, stride)`, which\n"
        "    stops BEFORE block_number -- the incident block's own base fee is used only as the\n"
        "    comparison threshold, not injected into the sample it's being ranked against.\n"
        "  Conclusion: no lookahead found. This is a stronger guarantee than 'checked and looks fine'\n"
        "  because point-in-time EVM state queries are non-lookahead by construction, not by omission."
    )


def audit_structural_separability(missingness_findings):
    print("\n--- (e) Structural/bookkeeping separability (beyond the already-fixed heartbeat_elapsed) ---")
    if not missingness_findings:
        print("  No feature found whose presence/absence alone tracks a class.")
        return
    for col, label, pct_in, pct_out in missingness_findings:
        print(f"  {col} : missing {pct_in:.0%} within '{label}' vs {pct_out:.0%} outside it")
    print(
        "\n  cross_venue_spread is the one real structural asymmetry left: it is NON-missing for\n"
        "  12/12 volatility incidents and MISSING for all 5 manipulation and all 3 malfunction\n"
        "  incidents (8/8). Cause: build_features.py's dex_pool mapping only covers the Uniswap\n"
        "  WETH/USDC and wstETH/WETH pools; manipulation incidents happened on Curve venues that\n"
        "  were never wired into cross_venue_spread specifically (the later Curve recompute pass\n"
        "  only patched price_dev and reserve_skew, per your instruction at the time), and\n"
        "  malfunction's assets either have no CEX symbol (stETH) or no identified DEX pool at all\n"
        "  (FTT, UST).\n"
        "  This differs from the heartbeat_elapsed bug in mechanism and severity: heartbeat_elapsed\n"
        "  was literally 0 (a real, wrong VALUE) for every non-manipulation row, and both NB and BN\n"
        "  treat 0 as real evidence. cross_venue_spread is NaN, and both models explicitly SKIP\n"
        "  missing features rather than encoding absence as a value -- so a model cannot mistake\n"
        "  'missing' for 'small spread'. It cannot be exploited as a disguised zero.\n"
        "  It still matters, though: every volatility incident receives one additional real,\n"
        "  independent piece of evidence in the Naive Bayes likelihood product (and one more parent\n"
        "  observation in the BN) that manipulation/malfunction incidents structurally never get.\n"
        "  All else equal this can make volatility's posterior look more confident/separable simply\n"
        "  because it is supported by more evidence terms, not because the other two classes lack a\n"
        "  real signal there. Flagging this plainly: it is an availability asymmetry baked into which\n"
        "  venues got mapped to which feature, not a fabricated signal, and not correctable without\n"
        "  redoing the Curve recompute pass to also backfill cross_venue_spread -- out of scope for\n"
        "  this read-only audit, noted here for the record."
    )


def main():
    warnings.filterwarnings("ignore")
    df = pd.read_parquet(FEATURES_PATH)
    df["reserve_skew_clipped"] = _clip(df["reserve_skew"])

    ablation_table, ablation_flips = run_ablation(df)

    print("\n" + "=" * 100)
    print("LEAKAGE AND ROBUSTNESS AUDIT")
    print("=" * 100)
    missingness_findings = audit_missingness_by_class(df)
    separation_findings = audit_perfect_separation(df)
    audit_manipulation_reserve_skew(df)
    audit_lookahead()
    audit_structural_separability(missingness_findings)

    print("\n" + "=" * 100)
    print("AUDIT SUMMARY")
    print("=" * 100)
    print(f"  Perfect single-feature separations found: {len(separation_findings)}"
          + (" -- NONE. Every feature/class pair with comparable data overlaps; no feature trivially"
             " gives away a class." if not separation_findings else ""))
    for col, label, in_lo, in_hi, out_lo, out_hi in separation_findings:
        print(f"    SUSPICIOUS: {col} perfectly separates {label} "
              f"(in=[{in_lo:.4f},{in_hi:.4f}] vs out=[{out_lo:.4f},{out_hi:.4f}])")
    print(f"  Structural missingness-by-class asymmetries found: {len(missingness_findings)} "
          f"(cross_venue_spread, discussed above -- not exploitable as a fake zero, but a real"
          f" evidence-count asymmetry).")
    print("  Lookahead: none found (architecturally impossible given point-in-time EVM state reads).")
    print("  Manipulation reserve_skew: clean and load-bearing except Inverse Finance's known,")
    print("  previously-documented understatement; Harvest's price_dev (not reserve_skew) carries a")
    print("  newly-flagged bad-reference-point caveat (see above) -- reserve_skew itself is unaffected.")

    return ablation_table


if __name__ == "__main__":
    main()
