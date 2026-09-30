"""Two additional calibration metrics -- Expected Calibration Error (ECE) and
multi-class log-loss -- computed alongside the existing Brier score, on the SAME
45-incident LOOCV posteriors already produced by loocv_validation.py (imported and
called unmodified, not re-derived). Evaluation only: no feature or model-structure
change, models.py and loocv_validation.py are untouched.

ECE uses the SAME 4 confidence buckets loocv_validation.py's own report_calibration()
already uses (>90%, 70-90%, 50-70%, <50%) -- not equal-width bins, but the bucketing
already established and reported elsewhere in this project, chosen here for
consistency and because it keeps bin populations as large as the small n allows
(equal-width bins, e.g. 10 of them, would leave most bins with 0-2 points at n=45 --
shown explicitly below, not just asserted). Confidence (post[pred], the top predicted
class's posterior) is what's binned, matching the "does an 80%-confidence call turn
out right ~80% of the time" question directly.

Log-loss uses each incident's held-out posterior probability assigned to its TRUE
label, clipped to [1e-15, 1-1e-15] before taking log (standard practice -- a literal
0.0 posterior, which does occur for Naive Bayes' degenerate confidence, would
otherwise produce -inf and blow up the mean).
"""

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from models import LABELS
from loocv_validation import loocv_bayesian_network, loocv_naive_bayes

LABEL_TO_COL = {
    "manipulation": "p_manipulation",
    "malfunction": "p_malfunction",
    "large volatility event": "p_volatility",
}
EPS = 1e-15
ECE_BINS = [(0.9, 1.01, "very high (>90%)"), (0.7, 0.9, "high (70-90%)"),
            (0.5, 0.7, "medium (50-70%)"), (0.0, 0.5, "low (<50%)")]
EQUAL_WIDTH_BINS = 10  # for the "few bins is noisy" illustration only, not the headline ECE


def multiclass_log_loss(result: pd.DataFrame) -> float:
    valid = result.dropna(subset=["confidence"])
    losses = []
    for _, r in valid.iterrows():
        p_true = r[LABEL_TO_COL[r["label"]]]
        p_true = min(max(p_true, EPS), 1 - EPS)
        losses.append(-np.log(p_true))
    return float(np.mean(losses))


def expected_calibration_error(result: pd.DataFrame, bins=ECE_BINS):
    valid = result.dropna(subset=["confidence"])
    total_n = len(valid)
    rows = []
    ece = 0.0
    for lo, hi, bin_name in bins:
        subset = valid[(valid["confidence"] >= lo) & (valid["confidence"] < hi)]
        if len(subset) == 0:
            rows.append({"bin": bin_name, "n": 0, "avg_confidence": None, "accuracy": None, "gap": None})
            continue
        avg_conf = subset["confidence"].mean()
        acc = subset["correct"].mean()
        gap = abs(avg_conf - acc)
        ece += (len(subset) / total_n) * gap
        rows.append({"bin": bin_name, "n": len(subset), "avg_confidence": avg_conf, "accuracy": acc, "gap": gap})
    return ece, pd.DataFrame(rows)


def equal_width_bin_populations(result: pd.DataFrame, n_bins=EQUAL_WIDTH_BINS):
    """Not the headline ECE -- purely to make the 'few bins is noisy' caveat concrete
    by showing how sparse a textbook equal-width binning gets at n=45."""
    valid = result.dropna(subset=["confidence"])
    edges = np.linspace(1.0 / len(LABELS), 1.0, n_bins + 1)  # confidence floor is 1/n_classes
    counts = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (valid["confidence"] >= lo) & (valid["confidence"] < hi) if i < n_bins - 1 else \
               (valid["confidence"] >= lo) & (valid["confidence"] <= hi)
        counts.append(int(mask.sum()))
    return edges, counts


def brier_score(result: pd.DataFrame, labels=LABELS) -> float:
    """Reproduced identically to loocv_validation.py's own report_calibration() --
    duplicated here only so this script can print all three metrics together without
    re-running the LOOCV twice; the formula itself is unchanged."""
    valid = result.dropna(subset=["confidence"])
    briers = []
    for _, r in valid.iterrows():
        onehot = {label: (1.0 if label == r["label"] else 0.0) for label in labels}
        briers.append(sum((r[LABEL_TO_COL[l]] - onehot[l]) ** 2 for l in labels))
    return float(np.mean(briers))


def report(name: str, result: pd.DataFrame):
    print(f"\n{'='*78}\n{name}\n{'='*78}")
    ece, ece_table = expected_calibration_error(result)
    ll = multiclass_log_loss(result)
    brier = brier_score(result)

    print("\nECE bucket breakdown (avg confidence vs. actual accuracy per bucket):")
    print(ece_table.to_string(index=False, float_format=lambda x: f"{x:.3f}" if isinstance(x, float) else str(x)))
    print(f"\nECE (weighted mean |avg confidence - accuracy| across buckets): {ece:.3f}")
    print(f"Multi-class log-loss: {ll:.3f}")
    print(f"Brier score (reference, unchanged from loocv_validation.py): {brier:.3f}")

    edges, counts = equal_width_bin_populations(result)
    print(f"\nFor comparison, a textbook {EQUAL_WIDTH_BINS}-equal-width-bin ECE at n=45 would have "
          f"per-bin counts: {counts} -- {sum(1 for c in counts if c <= 2)}/{EQUAL_WIDTH_BINS} bins with "
          f"<=2 points, illustrating why the 4-bucket scheme above is used as the headline number.")

    return {"ece": ece, "log_loss": ll, "brier": brier, "ece_table": ece_table}


def main():
    warnings.filterwarnings("ignore")
    from models import load_data
    df = load_data()

    nb_result = loocv_naive_bayes(df)
    bn_result = loocv_bayesian_network(df)

    nb_metrics = report("NAIVE BAYES (LOOCV, 45 incidents)", nb_result)
    bn_metrics = report("BAYESIAN NETWORK (LOOCV, 45 incidents)", bn_result)

    print(f"\n{'='*78}\nSIDE BY SIDE\n{'='*78}")
    summary = pd.DataFrame({
        "Naive Bayes": [nb_metrics["brier"], nb_metrics["ece"], nb_metrics["log_loss"]],
        "Bayesian Network": [bn_metrics["brier"], bn_metrics["ece"], bn_metrics["log_loss"]],
    }, index=["Brier score", "ECE", "Log-loss"])
    print(summary.to_string(float_format=lambda x: f"{x:.3f}"))

    return nb_metrics, bn_metrics


if __name__ == "__main__":
    main()
