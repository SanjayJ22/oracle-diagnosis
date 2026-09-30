"""Leave-one-incident-out cross-validation (LOOCV) for Naive Bayes and the Bayesian
network, plus calibration/uncertainty analysis on the held-out predictions.

The full-data fit-and-score numbers in models.py (NB 100%, BN 80%) are NOT validated
results -- they're fit and scored on the same 20 points. This script retrains each
model 20 times, holding out one incident each time, and reports the honest held-out
accuracy. With only 20 incidents (3 in the smallest class), expect this to be lower,
and expect the malfunction class especially to be fragile.

Does not touch the temporal model -- that's the next step.
"""

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from models import (
    FEATURES_PATH,
    LABELS,
    RESERVE_SKEW_CLIP,
    _fit_gaussian_nb,
    fit_bayesian_network,
    naive_bayes_posterior,
    predict_bayesian_network,
)

MAX_ENTROPY = np.log(len(LABELS))  # ln(3), for normalizing to a 0-1 scale


def _entropy(posterior: dict) -> float:
    """Normalized entropy: 0 = certain, 1 = maximally uncertain (uniform over 3 classes)."""
    p = np.array(list(posterior.values()))
    p = p[p > 0]
    return float(-(p * np.log(p)).sum() / MAX_ENTROPY)


def loocv_naive_bayes(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for i in range(len(df)):
        held_out = df.iloc[i]
        train = df.drop(df.index[i])
        priors = {label: (train["label"] == label).mean() for label in LABELS}
        stats = _fit_gaussian_nb(train)
        post = naive_bayes_posterior(held_out, stats, priors)
        pred = max(post, key=post.get)
        rows.append({
            "incident": held_out["incident"], "label": held_out["label"], "pred": pred,
            "p_manipulation": post["manipulation"], "p_malfunction": post["malfunction"],
            "p_volatility": post["large volatility event"],
            "confidence": post[pred], "entropy": _entropy(post), "correct": pred == held_out["label"],
        })
    return pd.DataFrame(rows)


def loocv_bayesian_network(df: pd.DataFrame, discretization: str = "fixed") -> pd.DataFrame:
    """`discretization` is passed straight through to fit_bayesian_network -- see
    its docstring for the three available schemes ("global", "class_conditional",
    "fixed"). Default is "fixed" as of reports/discretization_robustness.md:
    "class_conditional" (the previous default, reports/discretization_v2.md)
    scored slightly better at the exact n=165 snapshot (Brier 0.115 vs 0.133,
    log-loss 0.215 vs 0.335) but degraded 7-8x more under simulated distribution
    shift matching the pattern that already broke the earlier "global" scheme
    (manipulation recall fell 29-33 points under stress vs "fixed"'s 4-point
    drop, and "class_conditional"'s threshold itself moved up to 12.5% while
    "fixed"'s cannot move at all by construction). All three schemes remain
    available via this parameter for reproducibility."""
    rows = []
    for i in range(len(df)):
        held_out = df.iloc[i]
        train = df.drop(df.index[i])
        model, thresholds = fit_bayesian_network(train, verbose=False, discretization=discretization)
        if model is None:
            rows.append({
                "incident": held_out["incident"], "label": held_out["label"], "pred": None,
                "p_manipulation": np.nan, "p_malfunction": np.nan, "p_volatility": np.nan,
                "confidence": np.nan, "entropy": np.nan, "correct": False,
                "note": "CPD fit failed on this fold (a factor had zero complete training rows)",
            })
            continue
        post, _evidence = predict_bayesian_network(model, thresholds, held_out)
        pred = max(post, key=post.get)
        rows.append({
            "incident": held_out["incident"], "label": held_out["label"], "pred": pred,
            "p_manipulation": post["manipulation"], "p_malfunction": post["malfunction"],
            "p_volatility": post["large volatility event"],
            "confidence": post[pred], "entropy": _entropy(post), "correct": pred == held_out["label"],
            "note": "",
        })
    return pd.DataFrame(rows)


def report_accuracy(name: str, result: pd.DataFrame):
    print(f"\n--- {name}: per-class LOOCV accuracy ---")
    for label in LABELS:
        subset = result[result["label"] == label]
        correct = subset["correct"].sum()
        print(f"  {label:26s}: {correct}/{len(subset)} = {correct/len(subset):.0%}")
    overall = result["correct"].sum()
    print(f"  {'OVERALL':26s}: {overall}/{len(result)} = {overall/len(result):.0%}")

    print(f"\n  Confusion (rows=true, cols=predicted):")
    confusion = pd.crosstab(result["label"], result["pred"], dropna=False).reindex(index=LABELS, columns=LABELS, fill_value=0)
    print(confusion.to_string().replace("\n", "\n  "))

    misclassified = result[~result["correct"]]
    print(f"\n  Misclassified when held out ({len(misclassified)}/{len(result)}):")
    for _, r in misclassified.iterrows():
        print(f"    {r['incident']:35s} true={r['label']:24s} pred={r['pred']!s:24s} confidence={r['confidence']:.0%} entropy={r['entropy']:.2f}")


def report_calibration(name: str, result: pd.DataFrame):
    print(f"\n--- {name}: calibration (do high-confidence calls tend to be correct?) ---")
    valid = result.dropna(subset=["confidence"])
    bins = [(0.9, 1.01, "very high (>90%)"), (0.7, 0.9, "high (70-90%)"),
            (0.5, 0.7, "medium (50-70%)"), (0.0, 0.5, "low (<50%)")]
    for lo, hi, bin_name in bins:
        subset = valid[(valid["confidence"] >= lo) & (valid["confidence"] < hi)]
        if len(subset) == 0:
            print(f"  {bin_name:20s}: 0 predictions in this range")
            continue
        acc = subset["correct"].mean()
        print(f"  {bin_name:20s}: {subset['correct'].sum()}/{len(subset)} = {acc:.0%} correct "
              f"({', '.join(subset['incident'].str.slice(0, 20))})")

    # Brier score: mean squared error between the full posterior and the one-hot true label.
    briers = []
    for _, r in valid.iterrows():
        onehot = {label: (1.0 if label == r["label"] else 0.0) for label in LABELS}
        briers.append(sum((r[f"p_{'volatility' if l == 'large volatility event' else l}"] - onehot[l]) ** 2 for l in LABELS))
    print(f"  Brier score (0=perfect, {len(LABELS)-1}=worst): {np.mean(briers):.3f} "
          f"(lower is better-calibrated; a model that always outputs uniform 1/3-1/3-1/3 scores "
          f"~{2/3:.2f} regardless of correctness, as a reference point)")


def report_entropy(name: str, result: pd.DataFrame):
    print(f"\n--- {name}: posterior entropy per incident (0=certain, 1=maximally uncertain) ---")
    show = result[["incident", "label", "pred", "confidence", "entropy", "correct"]].copy()
    print(show.to_string(index=False, float_format=lambda x: f"{x:.2f}" if isinstance(x, float) else str(x)))

    print(f"\n  Mean entropy by true class:")
    for label in LABELS:
        subset = result[result["label"] == label]
        print(f"    {label:26s}: mean entropy = {subset['entropy'].mean():.2f} (n={len(subset)})")


def main():
    warnings.filterwarnings("ignore")
    df = pd.read_parquet(FEATURES_PATH)

    print("=" * 78)
    print("LEAVE-ONE-INCIDENT-OUT CROSS-VALIDATION")
    print(f"({len(df)} incidents: {(df['label']=='manipulation').sum()} manipulation, "
          f"{(df['label']=='malfunction').sum()} malfunction, "
          f"{(df['label']=='large volatility event').sum()} volatility)")
    print("=" * 78)

    nb_result = loocv_naive_bayes(df)
    bn_result = loocv_bayesian_network(df)

    report_accuracy("Naive Bayes (LOOCV)", nb_result)
    report_accuracy("Bayesian Network (LOOCV)", bn_result)

    print("\n" + "=" * 78)
    print("CALIBRATION")
    print("=" * 78)
    report_calibration("Naive Bayes (LOOCV)", nb_result)
    report_calibration("Bayesian Network (LOOCV)", bn_result)

    print("\n" + "=" * 78)
    print("UNCERTAINTY (posterior entropy)")
    print("=" * 78)
    report_entropy("Naive Bayes (LOOCV)", nb_result)
    report_entropy("Bayesian Network (LOOCV)", bn_result)

    print("\n" + "=" * 78)
    print("ROBUST vs FRAGILE")
    print("=" * 78)
    merged = nb_result[["incident", "label", "pred", "confidence", "correct"]].merge(
        bn_result[["incident", "pred", "confidence", "correct"]], on="incident", suffixes=("_nb", "_bn")
    )
    print("\nRobust (both models correct under LOOCV, both with high confidence >70%):")
    robust = merged[(merged["correct_nb"]) & (merged["correct_bn"]) &
                     (merged["confidence_nb"] > 0.7) & (merged["confidence_bn"] > 0.7)]
    for _, r in robust.iterrows():
        print(f"  {r['incident']:35s} NB conf={r['confidence_nb']:.0%}  BN conf={r['confidence_bn']:.0%}")

    print("\nFragile (at least one model wrong, OR both right but with low confidence):")
    fragile = merged[~merged.index.isin(robust.index)]
    for _, r in fragile.iterrows():
        print(f"  {r['incident']:35s} true={r['label']:24s} "
              f"NB: {r['pred_nb']!s:24s}({r['confidence_nb']:.0%})  "
              f"BN: {r['pred_bn']!s:24s}({r['confidence_bn']:.0%})")

    return nb_result, bn_result


if __name__ == "__main__":
    main()
