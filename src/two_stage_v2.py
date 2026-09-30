"""Re-test the two-stage hierarchical BN (Stage 1: oracle-failure vs volatility;
Stage 2: manipulation vs malfunction, for Stage-1-positive incidents only) on the
CURRENT production model: 165 incidents, "fixed" discretization (the current
default as of reports/production_baseline_fixed.md -- this script originally
shipped hardcoded to "class_conditional", the default AT THE TIME it was first
written; updated here as part of reports/refresh_summary.md's staleness pass,
not a new experiment), hand-drawn star structure, temporal features per the
current production split (BN's BN_RAW_TO_DISCRETE/BN_EDGES -- 3 of the 4
temporal features, excluding temporal_gap_trend, which an ablation showed hurts
BN specifically -- see reports/temporal_features.md).

This was tested once before (src/two_stage_analysis.py, ~45 incidents) and lost:
Stage 2 was starved of data (malfunction n=3 split across an already-tiny
oracle-failure subset) and discretization was still the original sign-based
scheme. Both have since changed materially (165 incidents, fixed discretization)
-- this re-tests whether the verdict changes, using a FRESH implementation
rather than reusing the old script, because the old script keeps its own
separate, unmodified sign-based discretization copy (out of scope to touch) and
does not have the current feature set (temporal features didn't exist when it
was written).

Reuses fit_cpds/predict unchanged from src/structure_learning.py, and
_class_conditional_threshold/_bn_clean/FIXED_THRESHOLDS from models.py -- the
former was extended with an optional `labels` parameter (backward-compatible
default preserves every existing caller's behavior unchanged) specifically so a
relabeled 2-class Stage 1/Stage 2 frame can compute its OWN class-conditional
thresholds using this same function, rather than a parallel copy, when that
scheme is selected via `discretization=`. Both "fixed" (default, matching
production) and "class_conditional" (kept for comparison) remain available.

COHERENT CHAIN-RULE POSTERIOR, not hard-zeroing: Stage 2's posterior is ALWAYS
computed for every held-out incident, regardless of what Stage 1's hard decision
was -- this is the exact fix already applied in the original two_stage_analysis.py
after hard-zeroing was found to manufacture log(0) penalties for near-coin-flip
Stage 1 calls. Final 3-class posterior:
    P(volatility)    = P(volatility | Stage 1 evidence)
    P(manipulation)  = P(oracle_failure | Stage 1 evidence) * P(manipulation | oracle_failure, Stage 2 evidence)
    P(malfunction)   = P(oracle_failure | Stage 1 evidence) * P(malfunction  | oracle_failure, Stage 2 evidence)
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
    FIXED_THRESHOLDS,
    LABELS,
    _bn_clean,
    _class_conditional_threshold,
    load_data,
)
from structure_learning import fit_cpds, predict

STAGE1_LABELS = ["oracle_failure", "large volatility event"]
STAGE2_LABELS = ["manipulation", "malfunction"]
MAX_ENTROPY_3CLASS = np.log(3)


def _stage1_label(true_label: str) -> str:
    return "large volatility event" if true_label == "large volatility event" else "oracle_failure"


def _discretize(train_df: pd.DataFrame, stage_col: str, stage_labels: list,
                 discretization: str = "fixed") -> tuple[pd.DataFrame, dict]:
    """Discretization matching whichever scheme `discretization` names -- "fixed"
    (default, matching current production) reads a constant straight from
    FIXED_THRESHOLDS, unaffected by `stage_labels`; "class_conditional" (kept for
    comparison) conditions the threshold on `stage_labels` via models.py's
    _class_conditional_threshold. `stage_col` names the column in `train_df`
    holding this stage's own label values -- copied into `label_d` directly (no
    dependence on a "label" column existing under that literal name, since Stage
    1 uses a relabeled column)."""
    work = train_df.copy()
    work["label"] = work[stage_col]  # so _class_conditional_threshold's own groupby sees the right values
    thresholds = {}
    for raw_col, (disc_col, prefix) in BN_RAW_TO_DISCRETE.items():
        cleaned = work[raw_col].apply(lambda v, c=raw_col: _bn_clean(c, v))
        magnitude = cleaned.abs()
        if discretization == "fixed":
            t = FIXED_THRESHOLDS[raw_col]
        else:
            t = _class_conditional_threshold(work, raw_col, magnitude, labels=stage_labels)
            if t is None:
                t = magnitude.dropna().median()
        thresholds[raw_col] = t
        work[disc_col] = magnitude.apply(
            lambda m, tt=t, p=prefix: np.nan if pd.isna(m) else (f"{p}_high" if m > tt else f"{p}_low"))
    work["label_d"] = work[stage_col]
    disc_cols = ["label_d"] + [v[0] for v in BN_RAW_TO_DISCRETE.values()]
    return work[disc_cols], thresholds


def _discretize_row(row: pd.Series, thresholds: dict) -> dict:
    evidence = {}
    for raw_col, (disc_col, prefix) in BN_RAW_TO_DISCRETE.items():
        x = _bn_clean(raw_col, row[raw_col])
        if pd.isna(x):
            continue
        evidence[disc_col] = f"{prefix}_high" if abs(x) > thresholds[raw_col] else f"{prefix}_low"
    return evidence


def _entropy3(p_manip, p_malf, p_vol):
    p = np.array([p_manip, p_malf, p_vol])
    p = p[p > 0]
    return float(-(p * np.log(p)).sum() / MAX_ENTROPY_3CLASS)


def fit_stage(train: pd.DataFrame, stage_col: str, stage_labels: list, discretization: str = "fixed"):
    """stage_col: column in `train` holding this stage's own label values
    (already relabeled for Stage 1, or the raw label for Stage 2)."""
    disc, thresholds = _discretize(train, stage_col, stage_labels, discretization=discretization)
    import models as _models
    original_state_names = dict(_models.BN_STATE_NAMES)
    _models.BN_STATE_NAMES["label_d"] = stage_labels
    try:
        model = fit_cpds(BN_EDGES, disc)
    finally:
        _models.BN_STATE_NAMES.clear()
        _models.BN_STATE_NAMES.update(original_state_names)
    return model, thresholds


def predict_stage(model, thresholds, row, stage_labels):
    import models as _models
    original_state_names = dict(_models.BN_STATE_NAMES)
    _models.BN_STATE_NAMES["label_d"] = stage_labels
    try:
        evidence = _discretize_row(row, thresholds)
        post = predict(model, evidence)
    finally:
        _models.BN_STATE_NAMES.clear()
        _models.BN_STATE_NAMES.update(original_state_names)
    return post


def run_two_stage_loocv(df: pd.DataFrame, discretization: str = "fixed") -> pd.DataFrame:
    rows = []
    for i in range(len(df)):
        held_out = df.iloc[i]
        train = df.drop(df.index[i]).copy()
        true_label = held_out["label"]
        true_stage1 = _stage1_label(true_label)

        # --- Stage 1: fit on ALL training incidents, relabeled ---
        train["stage1_label"] = train["label"].apply(_stage1_label)
        s1_model, s1_thresholds = fit_stage(train, "stage1_label", STAGE1_LABELS, discretization=discretization)

        stage1_fit_failed = s1_model is None
        if stage1_fit_failed:
            p_of = np.nan
            p_vol_s1 = np.nan
            pred_stage1 = None
        else:
            post1 = predict_stage(s1_model, s1_thresholds, held_out, STAGE1_LABELS)
            p_of = post1["oracle_failure"]
            p_vol_s1 = post1["large volatility event"]
            pred_stage1 = max(post1, key=post1.get)

        # --- Stage 2: fit ONLY on training incidents that are true oracle-failures ---
        train_of = train[train["label"] != "large volatility event"]
        s2_model, s2_thresholds = fit_stage(train_of, "label", STAGE2_LABELS, discretization=discretization)

        stage2_fit_failed = s2_model is None
        if stage2_fit_failed:
            p_manip_given_of = np.nan
            p_malf_given_of = np.nan
            pred_stage2 = None
        else:
            post2 = predict_stage(s2_model, s2_thresholds, held_out, STAGE2_LABELS)
            p_manip_given_of = post2["manipulation"]
            p_malf_given_of = post2["malfunction"]
            pred_stage2 = max(post2, key=post2.get)

        # --- Chain-rule combination (coherent, no hard-zeroing) ---
        if stage1_fit_failed or stage2_fit_failed:
            final_p_manip = final_p_malf = final_p_vol = np.nan
            final_pred = None
        else:
            final_p_vol = p_vol_s1
            final_p_manip = p_of * p_manip_given_of
            final_p_malf = p_of * p_malf_given_of
            total = final_p_manip + final_p_malf + final_p_vol
            final_p_manip, final_p_malf, final_p_vol = final_p_manip / total, final_p_malf / total, final_p_vol / total
            posts = {"manipulation": final_p_manip, "malfunction": final_p_malf, "large volatility event": final_p_vol}
            final_pred = max(posts, key=posts.get)

        rows.append({
            "incident": held_out["incident"], "label": true_label,
            "true_stage1": true_stage1, "pred_stage1": pred_stage1,
            "stage1_correct": (pred_stage1 == true_stage1) if pred_stage1 else False,
            "true_stage2": true_label if true_stage1 == "oracle_failure" else None,
            "pred_stage2": pred_stage2,
            "stage2_correct": (pred_stage2 == true_label) if (pred_stage2 and true_stage1 == "oracle_failure") else None,
            "final_pred": final_pred,
            "final_p_manipulation": final_p_manip, "final_p_malfunction": final_p_malf,
            "final_p_volatility": final_p_vol,
            "final_confidence": (max(final_p_manip, final_p_malf, final_p_vol)
                                   if not stage1_fit_failed and not stage2_fit_failed else np.nan),
            "final_entropy": (_entropy3(final_p_manip, final_p_malf, final_p_vol)
                                if not stage1_fit_failed and not stage2_fit_failed else np.nan),
            "final_correct": (final_pred == true_label) if final_pred else False,
            "note": ("stage1 fit failed" if stage1_fit_failed else
                     "stage2 fit failed" if stage2_fit_failed else ""),
        })
    return pd.DataFrame(rows)


def brier_score3(result: pd.DataFrame) -> float:
    valid = result.dropna(subset=["final_p_manipulation"])
    briers = []
    for _, r in valid.iterrows():
        onehot = {"manipulation": 1.0 if r["label"] == "manipulation" else 0.0,
                  "malfunction": 1.0 if r["label"] == "malfunction" else 0.0,
                  "large volatility event": 1.0 if r["label"] == "large volatility event" else 0.0}
        p = {"manipulation": r["final_p_manipulation"], "malfunction": r["final_p_malfunction"],
             "large volatility event": r["final_p_volatility"]}
        briers.append(sum((p[l] - onehot[l]) ** 2 for l in LABELS))
    return float(np.mean(briers))


def log_loss3(result: pd.DataFrame) -> float:
    eps = 1e-15
    valid = result.dropna(subset=["final_p_manipulation"])
    col = {"manipulation": "final_p_manipulation", "malfunction": "final_p_malfunction",
           "large volatility event": "final_p_volatility"}
    losses = []
    for _, r in valid.iterrows():
        p_true = min(max(r[col[r["label"]]], eps), 1 - eps)
        losses.append(-np.log(p_true))
    return float(np.mean(losses))


def ece3(result: pd.DataFrame, bins=((0.9, 1.01), (0.7, 0.9), (0.5, 0.7), (0.0, 0.5))):
    valid = result.dropna(subset=["final_confidence"])
    total_n = len(valid)
    ece = 0.0
    rows = []
    for lo, hi in bins:
        subset = valid[(valid["final_confidence"] >= lo) & (valid["final_confidence"] < hi)]
        if len(subset) == 0:
            continue
        avg_conf = subset["final_confidence"].mean()
        acc = subset["final_correct"].mean()
        gap = abs(avg_conf - acc)
        ece += (len(subset) / total_n) * gap
        rows.append({"bin": f"{lo}-{hi}", "n": len(subset), "avg_conf": avg_conf, "acc": acc, "gap": gap})
    return ece, pd.DataFrame(rows)


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    df = load_data()
    print(f"n = {len(df)}")
    result = run_two_stage_loocv(df)
    result.to_csv("/tmp/two_stage_v2_result.csv", index=False)

    n_s1_fail = (result["note"] == "stage1 fit failed").sum()
    n_s2_fail = (result["note"] == "stage2 fit failed").sum()
    print(f"Stage 1 fit failures: {n_s1_fail}/165")
    print(f"Stage 2 fit failures: {n_s2_fail}/165")

    print("\n=== STAGE 1 (oracle_failure vs volatility) ===")
    print(f"Accuracy: {result['stage1_correct'].sum()}/{len(result)} = {result['stage1_correct'].mean():.1%}")
    print(pd.crosstab(result["true_stage1"], result["pred_stage1"]))

    print("\n=== STAGE 2 (manipulation vs malfunction | true oracle_failure) ===")
    s2 = result[result["true_stage1"] == "oracle_failure"]
    s2_valid = s2.dropna(subset=["stage2_correct"])
    print(f"Accuracy: {s2_valid['stage2_correct'].sum()}/{len(s2_valid)} = {s2_valid['stage2_correct'].mean():.1%} "
          f"(of {len(s2)} true oracle-failure incidents, {len(s2) - len(s2_valid)} had a fit failure)")
    print(pd.crosstab(s2["true_stage2"], s2["pred_stage2"], dropna=False))

    print("\n=== END-TO-END 3-CLASS ===")
    print(f"Overall accuracy: {result['final_correct'].sum()}/{len(result)} = {result['final_correct'].mean():.1%}")
    for label in LABELS:
        sub = result[result.label == label]
        print(f"  {label:28s}: {sub['final_correct'].sum()}/{len(sub)} = {sub['final_correct'].mean():.1%}")
    print("Confusion:")
    print(pd.crosstab(result["label"], result["final_pred"], dropna=False))

    print("\n=== CALIBRATION ===")
    brier = brier_score3(result)
    ll = log_loss3(result)
    ece, ece_table = ece3(result)
    print(f"Brier={brier:.3f}  ECE={ece:.3f}  log-loss={ll:.3f}")
    print(ece_table.to_string(index=False))

    print("\n=== Malfunction detail ===")
    print(result[result.label == "malfunction"][
        ["incident", "true_stage1", "pred_stage1", "pred_stage2", "final_pred", "final_confidence"]
    ].to_string(index=False))

    print("\nDONE")
