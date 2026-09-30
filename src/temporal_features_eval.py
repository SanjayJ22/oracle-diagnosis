"""Evaluate adding the 4 new temporal features (src/compute_temporal_features.py)
to the classifier as real model inputs, on top of the existing 7 static features,
keeping the hand-drawn structure and class-conditional discretization (the current
defaults) unchanged -- only the FEATURE SET is being tested here.

Reuses fit_cpds/predict unchanged from src/structure_learning.py (already generic
to an arbitrary edge list and discretized training frame), and _fit_gaussian_nb/
naive_bayes_posterior unchanged from models.py (already generic to an arbitrary
feature_cols list) -- no production code modified to run this evaluation.
"""

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from models import (
    BN_EDGES,
    BN_RAW_TO_DISCRETE,
    BN_STATE_NAMES,
    FEATURE_COLS,
    LABELS,
    RESERVE_SKEW_CLIP,
    _bn_clean,
    _class_conditional_threshold,
    _fit_gaussian_nb,
    load_data,
    naive_bayes_posterior,
)
from structure_learning import fit_cpds, predict, _entropy

TEMPORAL_COLS = ["temporal_deviation_persistence", "temporal_slope",
                  "temporal_step_change_count", "temporal_gap_trend"]

TEMPORAL_PREFIXES = {
    "temporal_deviation_persistence": "tdp",
    "temporal_slope": "tsl",
    "temporal_step_change_count": "tsc",
    "temporal_gap_trend": "tgt",
}


def build_extended(temporal_cols_to_include):
    """Returns (feature_cols, raw_to_discrete, state_names, edges) for NB/BN,
    with `temporal_cols_to_include` (a subset of TEMPORAL_COLS) added on top of
    the original 7 static features -- used both for the full-11-feature run and
    for the leave-one-out ablation."""
    feature_cols = FEATURE_COLS + temporal_cols_to_include
    raw_to_discrete = dict(BN_RAW_TO_DISCRETE)
    state_names = dict(BN_STATE_NAMES)
    edges = list(BN_EDGES)
    for col in temporal_cols_to_include:
        prefix = TEMPORAL_PREFIXES[col]
        disc_col = f"{col}_d"
        raw_to_discrete[col] = (disc_col, prefix)
        state_names[disc_col] = [f"{prefix}_low", f"{prefix}_high"]
        edges.append(("label_d", disc_col))
    return feature_cols, raw_to_discrete, state_names, edges


def _discretize(train_df, raw_to_discrete, missing_as_category=False):
    work = train_df.copy()
    work["label_d"] = work["label"]
    thresholds = {}
    for raw_col, (disc_col, prefix) in raw_to_discrete.items():
        cleaned = work[raw_col].apply(lambda v, c=raw_col: _bn_clean(c, v))
        magnitude = cleaned.abs()
        t = _class_conditional_threshold(work, raw_col, magnitude)
        if t is None:
            t = magnitude.dropna().median()
        thresholds[raw_col] = t
        if missing_as_category:
            work[disc_col] = magnitude.apply(
                lambda m, tt=t, p=prefix: (f"{p}_missing" if pd.isna(m) else (f"{p}_high" if m > tt else f"{p}_low")))
        else:
            work[disc_col] = magnitude.apply(
                lambda m, tt=t, p=prefix: np.nan if pd.isna(m) else (f"{p}_high" if m > tt else f"{p}_low"))
    disc_cols = ["label_d"] + [v[0] for v in raw_to_discrete.values()]
    return work[disc_cols], thresholds


def _discretize_row(row, raw_to_discrete, thresholds):
    evidence = {}
    for raw_col, (disc_col, prefix) in raw_to_discrete.items():
        x = _bn_clean(raw_col, row[raw_col])
        if pd.isna(x):
            continue
        evidence[disc_col] = f"{prefix}_high" if abs(x) > thresholds[raw_col] else f"{prefix}_low"
    return evidence


def loocv_bn_extended(df, raw_to_discrete, state_names, edges):
    # temporarily patch BN_STATE_NAMES so fit_cpds (imported from
    # structure_learning, which references models.BN_STATE_NAMES globally via
    # its own import) can resolve the new temporal_*_d state name lists too.
    import models as _models
    original_state_names = dict(_models.BN_STATE_NAMES)
    _models.BN_STATE_NAMES.update(state_names)
    try:
        rows = []
        for i in range(len(df)):
            held_out = df.iloc[i]
            train = df.drop(df.index[i])
            train_disc, thresholds = _discretize(train, raw_to_discrete, missing_as_category=False)
            model = fit_cpds(edges, train_disc)
            if model is None:
                rows.append({"incident": held_out["incident"], "label": held_out["label"], "pred": None,
                             "p_manipulation": np.nan, "p_malfunction": np.nan, "p_volatility": np.nan,
                             "confidence": np.nan, "entropy": np.nan, "correct": False, "note": "fit failed"})
                continue
            evidence = _discretize_row(held_out, raw_to_discrete, thresholds)
            post = predict(model, evidence)
            pred = max(post, key=post.get)
            rows.append({"incident": held_out["incident"], "label": held_out["label"], "pred": pred,
                         "p_manipulation": post["manipulation"], "p_malfunction": post["malfunction"],
                         "p_volatility": post["large volatility event"],
                         "confidence": post[pred], "entropy": _entropy(post), "correct": pred == held_out["label"], "note": ""})
        return pd.DataFrame(rows)
    finally:
        _models.BN_STATE_NAMES.clear()
        _models.BN_STATE_NAMES.update(original_state_names)


def loocv_nb_extended(df, feature_cols):
    rows = []
    for i in range(len(df)):
        held_out = df.iloc[i]
        train = df.drop(df.index[i])
        priors = {label: (train["label"] == label).mean() for label in LABELS}
        stats = _fit_gaussian_nb(train, feature_cols=feature_cols)
        post = naive_bayes_posterior(held_out, stats, priors, feature_cols=feature_cols)
        pred = max(post, key=post.get)
        rows.append({"incident": held_out["incident"], "label": held_out["label"], "pred": pred,
                     "p_manipulation": post["manipulation"], "p_malfunction": post["malfunction"],
                     "p_volatility": post["large volatility event"],
                     "confidence": post[pred], "entropy": _entropy(post), "correct": pred == held_out["label"]})
    return pd.DataFrame(rows)


def summarize(name, result_df):
    from calibration_metrics import brier_score, expected_calibration_error, multiclass_log_loss
    overall = result_df["correct"].mean()
    print(f"\n--- {name} ---")
    print(f"Overall accuracy: {result_df['correct'].sum()}/{len(result_df)} = {overall:.1%}")
    for label in LABELS:
        sub = result_df[result_df.label == label]
        print(f"  {label:28s}: {sub['correct'].sum()}/{len(sub)} = {sub['correct'].mean():.1%}")
    brier = brier_score(result_df)
    ece, _ = expected_calibration_error(result_df)
    ll = multiclass_log_loss(result_df)
    print(f"Brier={brier:.3f}  ECE={ece:.3f}  log-loss={ll:.3f}")
    return {"accuracy": overall, "brier": brier, "ece": ece, "log_loss": ll,
            "manip_recall": result_df[result_df.label == "manipulation"]["correct"].mean(),
            "malf_recall": result_df[result_df.label == "malfunction"]["correct"].mean(),
            "vol_recall": result_df[result_df.label == "large volatility event"]["correct"].mean()}


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    df = load_data()
    print(f"n = {len(df)}")

    print("\n" + "=" * 78)
    print("FULL: all 7 static + all 4 temporal features")
    print("=" * 78)
    feat_cols, r2d, sn, edges = build_extended(TEMPORAL_COLS)
    bn_full = loocv_bn_extended(df, r2d, sn, edges)
    nb_full = loocv_nb_extended(df, feat_cols)
    bn_full_summary = summarize("BN (11 features)", bn_full)
    nb_full_summary = summarize("NB (11 features)", nb_full)
    bn_full.to_csv("/tmp/temporal_bn_full.csv", index=False)
    nb_full.to_csv("/tmp/temporal_nb_full.csv", index=False)

    print("\n" + "=" * 78)
    print("LEAVE-ONE-TEMPORAL-FEATURE-OUT ABLATION (BN)")
    print("=" * 78)
    ablation_results = {}
    for drop_col in TEMPORAL_COLS:
        kept = [c for c in TEMPORAL_COLS if c != drop_col]
        feat_cols_a, r2d_a, sn_a, edges_a = build_extended(kept)
        bn_a = loocv_bn_extended(df, r2d_a, sn_a, edges_a)
        s = summarize(f"BN, drop {drop_col}", bn_a)
        ablation_results[drop_col] = s
        bn_a.to_csv(f"/tmp/temporal_bn_drop_{drop_col}.csv", index=False)

    print("\n" + "=" * 78)
    print("BASELINE: 0 temporal features (for reference, should match discretization_v2.md)")
    print("=" * 78)
    feat_cols_0, r2d_0, sn_0, edges_0 = build_extended([])
    bn_0 = loocv_bn_extended(df, r2d_0, sn_0, edges_0)
    summarize("BN (0 temporal features, sanity check)", bn_0)
    bn_0.to_csv("/tmp/temporal_bn_baseline.csv", index=False)

    print("\n" + "=" * 78)
    print("5 PREVIOUSLY-MISSED MANIPULATION INCIDENTS: recovered?")
    print("=" * 78)
    watch = ["Cream Finance", "MonoX Finance", "MEVBOTa47b", "CurveLlamaLend", "ResupplyFi"]
    print(bn_full[bn_full.incident.isin(watch)][["incident", "pred", "confidence"]].to_string(index=False))

    print("\nDONE")
