"""Test adding price_dev_d -> congestion_d to the current hand-drawn BN structure.

Candidate surfaced by src/structure_learning.py: this edge appeared in 99% of
Chow-Liu folds and, unlike most of that experiment's learned edges, is NOT
explained by the missingness confound (reports/structure_learning.md Sec 3 --
price_dev and congestion have 0% co-missingness overlap, verified there
directly). This script adds ONLY this one edge to the current production
structure (7 static + 3 temporal features, "fixed" discretization default,
reports/production_baseline_fixed.md) and re-evaluates under LOOCV, holding
every other structural and discretization choice constant.

Implementation: temporarily monkey-patches models.BN_EDGES (append the one new
edge, restore in a finally block) rather than reimplementing fit/predict --
models.fit_bayesian_network already resolves BN_EDGES from the module
namespace at call time (confirmed by reading its source: `edges = [(a, b) for
(a, b) in BN_EDGES if ...]`), the same pattern already used safely in
src/temporal_features_eval.py for BN_STATE_NAMES.
"""

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import models as _models
from models import LABELS, load_data
from loocv_validation import loocv_bayesian_network
from calibration_metrics import brier_score, expected_calibration_error, multiclass_log_loss

NEW_EDGE = ("price_dev_d", "congestion_d")


def with_extra_edge(fn, *args, **kwargs):
    original_edges = list(_models.BN_EDGES)
    _models.BN_EDGES.append(NEW_EDGE)
    try:
        return fn(*args, **kwargs)
    finally:
        _models.BN_EDGES.clear()
        _models.BN_EDGES.extend(original_edges)


def summarize(name, result):
    overall = result["correct"].mean()
    print(f"\n--- {name} ---")
    print(f"Overall accuracy: {result['correct'].sum()}/{len(result)} = {overall:.1%}")
    for label in LABELS:
        sub = result[result.label == label]
        print(f"  {label:28s}: {sub['correct'].sum()}/{len(sub)} = {sub['correct'].mean():.1%}")
    brier = brier_score(result)
    ece, _ = expected_calibration_error(result)
    ll = multiclass_log_loss(result)
    print(f"Brier={brier:.4f}  ECE={ece:.4f}  log-loss={ll:.4f}")
    return {"accuracy": overall, "brier": brier, "ece": ece, "log_loss": ll,
            "manip_recall": result[result.label == "manipulation"]["correct"].mean(),
            "malf_recall": result[result.label == "malfunction"]["correct"].mean(),
            "vol_recall": result[result.label == "large volatility event"]["correct"].mean()}


def congestion_cpd_thinning_report(df):
    """Quantify the 'spreading data thin' concern directly. Correction of an
    initial assumption, verified before writing this: congestion_d currently has
    ZERO parents in the production structure (it's a root node -- its only edge
    is congestion_d -> heartbeat_elapsed_d, where it's the PARENT, not the
    child; label_d does NOT point to congestion_d in the current star). Adding
    price_dev_d -> congestion_d therefore takes congestion_d from an
    unconditional (root) distribution to ONE parent, not from one parent to two
    as originally assumed -- a real but smaller data-split than initially
    worried about. Quantified here directly (root vs 1-parent row counts) rather
    than assumed either way."""
    from models import fit_bayesian_network
    work = df.copy()
    work["label_d"] = work["label"]

    print("\n=== congestion_d CPD data availability: 1 parent vs 2 parents ===")
    model_base, _ = fit_bayesian_network(df, verbose=False)
    cpd_base = model_base.get_cpds("congestion_d")
    print(f"Baseline (parents: {model_base.get_parents('congestion_d')}): "
          f"CPD shape {cpd_base.values.shape}, {cpd_base.values.size} cells")

    model_ext, _ = with_extra_edge(fit_bayesian_network, df, verbose=False)
    cpd_ext = model_ext.get_cpds("congestion_d")
    print(f"Extended (parents: {model_ext.get_parents('congestion_d')}): "
          f"CPD shape {cpd_ext.values.shape}, {cpd_ext.values.size} cells")

    # rows with both label and price_dev and congestion non-missing (what the
    # extended CPD's estimation actually has to work with, per class)
    complete = df.dropna(subset=["price_dev", "congestion"])
    print("\nRows with BOTH price_dev and congestion non-missing, by class "
          "(this is what the 2-parent CPD must be estimated from):")
    print(complete["label"].value_counts())
    print("\n(compare to congestion alone, what the 1-parent CPD uses):")
    print(df.dropna(subset=["congestion"])["label"].value_counts())


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    df = load_data()
    print(f"n = {len(df)}")

    print("\n" + "=" * 78)
    print("BASELINE: current production structure (no price_dev_d -> congestion_d)")
    print("=" * 78)
    baseline_result = loocv_bayesian_network(df)
    baseline_summary = summarize("baseline", baseline_result)
    baseline_result.to_csv("/tmp/edge_test_baseline.csv", index=False)

    print("\n" + "=" * 78)
    print("EXTENDED: + price_dev_d -> congestion_d")
    print("=" * 78)
    extended_result = with_extra_edge(loocv_bayesian_network, df)
    extended_summary = summarize("extended", extended_result)
    extended_result.to_csv("/tmp/edge_test_extended.csv", index=False)

    congestion_cpd_thinning_report(df)

    print("\n" + "=" * 78)
    print("SIDE BY SIDE")
    print("=" * 78)
    comp = pd.DataFrame({"baseline": baseline_summary, "extended": extended_summary}).T
    print(comp.to_string())

    print("\nDONE")
