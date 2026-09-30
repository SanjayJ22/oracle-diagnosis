"""Supporting analysis only -- does NOT modify or re-score the primary three-class
pipeline (models.py, loocv_validation.py); it imports their fitted building blocks
read-only and leaves their results untouched.

Tests a specific hypothesis: that "the oracle is wrong" (manipulation OR malfunction)
is easy to separate from "the oracle is right, the market actually moved" (large
volatility event), and that the genuinely hard part of the three-class problem is
distinguishing manipulation from malfunction specifically, not either of them from
volatility. Collapses manipulation+malfunction into one "oracle failure" class and
re-runs LOOCV Naive Bayes and the Bayesian network on this 2-class relabeling.

Reimplements the label-dependent halves of NB and BN fitting/prediction generically
over an arbitrary label list: models.py's versions hardcode the three-class LABELS /
BN_STATE_NAMES at the module level, and pgmpy's BayesianEstimator requires
state_names to match the actual column's value domain, so a 2-class label column
can't reuse the 3-class state_names as-is. The BN edge structure, feature
discretization (per-fold median split), and NB Gaussian-independence assumption are
otherwise byte-for-byte identical to models.py -- only the number of label classes
differs. `predict_bayesian_network` itself is reused unchanged from models.py since
it does not reference the label state space directly.
"""

import warnings

import numpy as np
import pandas as pd

from models import (
    BN_EDGES,
    BN_RAW_TO_DISCRETE,
    BN_STATE_NAMES,
    FEATURE_COLS,
    FIXED_THRESHOLDS,
    RESERVE_SKEW_CLIP,
    _bn_clean,
    _gaussian_logpdf,
    load_data,
    predict_bayesian_network,
)
from loocv_validation import loocv_bayesian_network as loocv_bn_3class
from loocv_validation import loocv_naive_bayes as loocv_nb_3class

TWO_CLASS_LABELS = ["oracle failure", "large volatility event"]
STATE_NAMES_2CLASS = {**BN_STATE_NAMES, "label_d": TWO_CLASS_LABELS}


def to_two_class(df: pd.DataFrame) -> pd.DataFrame:
    """Relabels manipulation+malfunction -> 'oracle failure'. Keeps the original
    3-class label as 'label_3class' so per-incident output can still show which
    original class each 'oracle failure' incident came from."""
    df = df.copy()
    df["label_3class"] = df["label"]
    df["label"] = df["label_3class"].map(lambda l: "oracle failure" if l in ("manipulation", "malfunction") else l)
    return df


def _entropy(posterior: dict, labels) -> float:
    """Normalized entropy: 0 = certain, 1 = maximally uncertain (uniform over len(labels) classes)."""
    p = np.array([posterior[l] for l in labels])
    p = p[p > 0]
    max_entropy = np.log(len(labels))
    return float(-(p * np.log(p)).sum() / max_entropy)


# ============================================================================
# Naive Bayes, generalized over an arbitrary `labels` list (models.py's
# _fit_gaussian_nb / naive_bayes_posterior hardcode the 3-class LABELS global)
# ============================================================================

def _fit_gaussian_nb_2class(df: pd.DataFrame, labels, feature_cols=FEATURE_COLS):
    stats = {}
    for label in labels:
        subset = df[df["label"] == label]
        stats[label] = {}
        for col in feature_cols:
            vals = subset[col].replace([np.inf, -np.inf], RESERVE_SKEW_CLIP).dropna()
            n = len(vals)
            mean = vals.mean() if n > 0 else np.nan
            std = vals.std(ddof=0) if n > 1 else np.nan
            std = max(std, 1e-6) if pd.notna(std) else np.nan
            stats[label][col] = {"mean": mean, "std": std, "n": n}
    return stats


def _naive_bayes_posterior_2class(row, stats, priors, labels, feature_cols=FEATURE_COLS):
    log_post = {}
    for label in labels:
        log_p = np.log(priors[label])
        for col in feature_cols:
            x = row[col]
            if pd.isna(x):
                continue
            x = min(max(x, -RESERVE_SKEW_CLIP), RESERVE_SKEW_CLIP) if np.isinf(x) else x
            fit = stats[label][col]
            if pd.isna(fit["mean"]) or pd.isna(fit["std"]) or fit["n"] == 0:
                continue
            log_p += _gaussian_logpdf(x, fit["mean"], fit["std"])
        log_post[label] = log_p
    max_log = max(log_post.values())
    exp_vals = {k: np.exp(v - max_log) for k, v in log_post.items()}
    total = sum(exp_vals.values())
    return {k: v / total for k, v in exp_vals.items()}


def loocv_naive_bayes_2class(df: pd.DataFrame, labels=TWO_CLASS_LABELS) -> pd.DataFrame:
    rows = []
    for i in range(len(df)):
        held_out = df.iloc[i]
        train = df.drop(df.index[i])
        priors = {label: (train["label"] == label).mean() for label in labels}
        stats = _fit_gaussian_nb_2class(train, labels)
        post = _naive_bayes_posterior_2class(held_out, stats, priors, labels)
        pred = max(post, key=post.get)
        rows.append({
            "incident": held_out["incident"], "label": held_out["label"],
            "label_3class": held_out["label_3class"], "pred": pred,
            **{f"p_{l}": post[l] for l in labels},
            "confidence": post[pred], "entropy": _entropy(post, labels),
            "correct": pred == held_out["label"],
        })
    return pd.DataFrame(rows)


# ============================================================================
# Bayesian network, generalized over the label state space (models.py's
# fit_bayesian_network hardcodes BN_STATE_NAMES["label_d"] = the 3-class LABELS)
# ============================================================================

def _fit_bn_2class(df: pd.DataFrame, verbose: bool = False):
    """Discretization FIXED to match current production (reports/
    refresh_summary.md): this previously used a raw sign-based median split
    (`x > median -> high`), the scheme production abandoned first for magnitude-
    aware class-conditional, then for "fixed" (reports/discretization_v2.md,
    reports/discretization_robustness.md). That old split was ALSO, independent
    of being stale, a real bug by the time it was found: this file reuses
    models.py's own predict_bayesian_network unchanged for scoring, which
    already compares `abs(x) > threshold` (magnitude-based) -- meaning fit and
    predict were discretizing on two DIFFERENT rules, silently. Now both use the
    same "fixed" scheme (a constant per feature from FIXED_THRESHOLDS, not fit
    from data), matching production and eliminating that mismatch."""
    from pgmpy.estimators import BayesianEstimator
    from pgmpy.models import DiscreteBayesianNetwork

    work = df.copy()
    work["label_d"] = work["label"]
    thresholds = {}
    for raw_col, (disc_col, prefix) in BN_RAW_TO_DISCRETE.items():
        cleaned = work[raw_col].apply(lambda v, c=raw_col: _bn_clean(c, v))
        magnitude = cleaned.abs()
        t = FIXED_THRESHOLDS[raw_col]
        thresholds[raw_col] = t
        work[disc_col] = magnitude.apply(
            lambda m, tt=t, p=prefix: np.nan if pd.isna(m) else (f"{p}_high" if m > tt else f"{p}_low")
        )

    model = DiscreteBayesianNetwork(BN_EDGES)
    fitted_cpds = []
    for node in model.nodes():
        parents = list(model.get_parents(node))
        cols = [node] + parents
        complete = work.dropna(subset=cols)
        if verbose:
            print(f"  fitting CPD({node} | {parents}) from {len(complete)}/{len(df)} incidents with {cols} observed")
        if len(complete) == 0:
            return None, thresholds
        est = BayesianEstimator(model, complete, state_names={c: STATE_NAMES_2CLASS[c] for c in cols})
        cpd = est.estimate_cpd(node, prior_type="BDeu", equivalent_sample_size=2)
        fitted_cpds.append(cpd)
    model.add_cpds(*fitted_cpds)
    if not model.check_model():
        return None, thresholds
    return model, thresholds


def loocv_bayesian_network_2class(df: pd.DataFrame, labels=TWO_CLASS_LABELS) -> pd.DataFrame:
    rows = []
    for i in range(len(df)):
        held_out = df.iloc[i]
        train = df.drop(df.index[i])
        model, thresholds = _fit_bn_2class(train, verbose=False)
        if model is None:
            rows.append({
                "incident": held_out["incident"], "label": held_out["label"],
                "label_3class": held_out["label_3class"], "pred": None,
                **{f"p_{l}": np.nan for l in labels},
                "confidence": np.nan, "entropy": np.nan, "correct": False,
            })
            continue
        post, _evidence = predict_bayesian_network(model, thresholds, held_out)
        pred = max(post, key=post.get)
        rows.append({
            "incident": held_out["incident"], "label": held_out["label"],
            "label_3class": held_out["label_3class"], "pred": pred,
            **{f"p_{l}": post[l] for l in labels},
            "confidence": post[pred], "entropy": _entropy(post, labels),
            "correct": pred == held_out["label"],
        })
    return pd.DataFrame(rows)


# ============================================================================
# Reporting
# ============================================================================

def report_accuracy(name: str, result: pd.DataFrame, labels):
    print(f"\n--- {name}: per-class LOOCV accuracy ---")
    for label in labels:
        subset = result[result["label"] == label]
        correct = subset["correct"].sum()
        print(f"  {label:26s}: {correct}/{len(subset)} = {correct/len(subset):.0%}")
    overall = result["correct"].sum()
    print(f"  {'OVERALL':26s}: {overall}/{len(result)} = {overall/len(result):.0%}")

    print("\n  Confusion (rows=true, cols=predicted):")
    confusion = pd.crosstab(result["label"], result["pred"], dropna=False).reindex(index=labels, columns=labels, fill_value=0)
    print(confusion.to_string().replace("\n", "\n  "))

    print("\n  Per-class precision / recall:")
    for label in labels:
        tp = ((result["pred"] == label) & (result["label"] == label)).sum()
        predicted_pos = (result["pred"] == label).sum()
        actual_pos = (result["label"] == label).sum()
        precision = tp / predicted_pos if predicted_pos else float("nan")
        recall = tp / actual_pos if actual_pos else float("nan")
        print(f"    {label:26s}: precision={precision:.0%} ({tp}/{predicted_pos}), recall={recall:.0%} ({tp}/{actual_pos})")

    misclassified = result[~result["correct"]]
    print(f"\n  Misclassified when held out ({len(misclassified)}/{len(result)}):")
    for _, r in misclassified.iterrows():
        print(f"    {r['incident']:35s} true={r['label']:22s} (orig: {r['label_3class']:12s}) "
              f"pred={r['pred']!s:22s} confidence={r['confidence']:.0%} entropy={r['entropy']:.2f}")


def report_calibration(name: str, result: pd.DataFrame, labels, col_for_label=None):
    """col_for_label maps a label string to its posterior-probability column name.
    Defaults to 'p_<label>' (how this file's own loocv_*_2class results are built);
    loocv_validation.py's 3-class results instead use the special-cased
    'p_manipulation'/'p_malfunction'/'p_volatility' (not 'p_large volatility event'),
    so the caller passes a matching mapper for those."""
    if col_for_label is None:
        col_for_label = lambda l: f"p_{l}"

    print(f"\n--- {name}: calibration ---")
    valid = result.dropna(subset=["confidence"])
    bins = [(0.9, 1.01, "very high (>90%)"), (0.7, 0.9, "high (70-90%)"),
            (0.5, 0.7, "medium (50-70%)"), (0.0, 0.5, "low (<50%)")]
    for lo, hi, bin_name in bins:
        subset = valid[(valid["confidence"] >= lo) & (valid["confidence"] < hi)]
        if len(subset) == 0:
            print(f"  {bin_name:20s}: 0 predictions in this range")
            continue
        acc = subset["correct"].mean()
        print(f"  {bin_name:20s}: {subset['correct'].sum()}/{len(subset)} = {acc:.0%} correct")

    briers = []
    for _, r in valid.iterrows():
        onehot = {label: (1.0 if label == r["label"] else 0.0) for label in labels}
        briers.append(sum((r[col_for_label(l)] - onehot[l]) ** 2 for l in labels))
    uniform_brier = len(labels) * (1.0 / len(labels)) ** 2
    print(f"  Brier score (0=perfect, {len(labels)-1}=worst): {np.mean(briers):.3f} "
          f"(reference: always-uniform 1/{len(labels)} guess scores {uniform_brier:.3f})")
    return float(np.mean(briers))


def report_error_direction(name: str, result_3class: pd.DataFrame):
    """Among the 3-class LOOCV's misclassified incidents, break down error direction:
    oracle-failure<->oracle-failure (manip<->malfunction) confusions vs
    oracle-failure<->volatility confusions in either direction. Directly tests
    whether the errors that a 2-class merge would erase are manip/malfunction
    confusions specifically, or whether they also cross into/out of volatility."""
    oracle_failure_classes = {"manipulation", "malfunction"}
    wrong = result_3class[~result_3class["correct"]].copy()
    print(f"\n--- {name}: 3-class error-direction breakdown ({len(wrong)} errors) ---")
    within_oracle_failure = 0
    crosses_volatility = 0
    for _, r in wrong.iterrows():
        true_l, pred_l = r["label"], r["pred"]
        true_is_of = true_l in oracle_failure_classes
        pred_is_of = pred_l in oracle_failure_classes
        if true_is_of and pred_is_of:
            within_oracle_failure += 1
            kind = "manipulation<->malfunction (would DISAPPEAR under 2-class merge)"
        else:
            crosses_volatility += 1
            kind = "crosses the oracle-failure/volatility boundary (would REMAIN under 2-class merge)"
        print(f"  {r['incident']:35s} true={true_l:24s} pred={pred_l!s:24s} -- {kind}")
    print(f"\n  {within_oracle_failure}/{len(wrong)} errors are manipulation<->malfunction confusions "
          f"(erased by the 2-class merge)")
    print(f"  {crosses_volatility}/{len(wrong)} errors cross the oracle-failure/volatility boundary "
          f"(would persist under the 2-class merge)")
    return within_oracle_failure, crosses_volatility


def main():
    warnings.filterwarnings("ignore")
    df3 = load_data()
    df2 = to_two_class(df3)

    print("=" * 78)
    print("SUPPORTING ANALYSIS: TWO-CLASS COLLAPSE (oracle failure vs large volatility)")
    print(f"({len(df2)} incidents: {(df2['label']=='oracle failure').sum()} oracle failure "
          f"[{(df2['label_3class']=='manipulation').sum()} manipulation + "
          f"{(df2['label_3class']=='malfunction').sum()} malfunction], "
          f"{(df2['label']=='large volatility event').sum()} large volatility event)")
    print("Does NOT modify or re-score models.py / loocv_validation.py.")
    print("=" * 78)

    # --- fresh 3-class LOOCV baseline, for direct comparison (unmodified functions) ---
    print("\n" + "=" * 78)
    print("BASELINE: three-class LOOCV (re-run via unmodified loocv_validation.py functions)")
    print("=" * 78)
    nb3 = loocv_nb_3class(df3)
    bn3 = loocv_bn_3class(df3)
    nb3_acc = nb3["correct"].mean()
    bn3_acc = bn3["correct"].mean()
    print(f"  Naive Bayes overall LOOCV accuracy:      {nb3['correct'].sum()}/{len(nb3)} = {nb3_acc:.0%}")
    print(f"  Bayesian network overall LOOCV accuracy: {bn3['correct'].sum()}/{len(bn3)} = {bn3_acc:.0%}")
    labels_3class = ["manipulation", "malfunction", "large volatility event"]
    col_3class = lambda l: f"p_{'volatility' if l == 'large volatility event' else l}"
    nb3_brier = report_calibration("Naive Bayes (3-class LOOCV)", nb3, labels_3class, col_3class)
    bn3_brier = report_calibration("Bayesian Network (3-class LOOCV)", bn3, labels_3class, col_3class)
    report_error_direction("Naive Bayes", nb3)
    report_error_direction("Bayesian Network", bn3)

    # --- 2-class LOOCV ---
    print("\n" + "=" * 78)
    print("TWO-CLASS LOOCV: oracle failure vs large volatility event")
    print("=" * 78)
    nb2 = loocv_naive_bayes_2class(df2)
    bn2 = loocv_bayesian_network_2class(df2)

    report_accuracy("Naive Bayes (2-class LOOCV)", nb2, TWO_CLASS_LABELS)
    report_accuracy("Bayesian Network (2-class LOOCV)", bn2, TWO_CLASS_LABELS)

    print("\n" + "=" * 78)
    print("CALIBRATION (2-class)")
    print("=" * 78)
    nb2_brier = report_calibration("Naive Bayes (2-class LOOCV)", nb2, TWO_CLASS_LABELS)
    bn2_brier = report_calibration("Bayesian Network (2-class LOOCV)", bn2, TWO_CLASS_LABELS)

    print("\n" + "=" * 78)
    print("SUMMARY: three-class vs two-class")
    print("=" * 78)
    nb2_acc = nb2["correct"].mean()
    bn2_acc = bn2["correct"].mean()
    summary = pd.DataFrame({
        "Naive Bayes": [f"{nb3_acc:.0%}", f"{nb3_brier:.3f}", f"{nb2_acc:.0%}", f"{nb2_brier:.3f}"],
        "Bayesian Network": [f"{bn3_acc:.0%}", f"{bn3_brier:.3f}", f"{bn2_acc:.0%}", f"{bn2_brier:.3f}"],
    }, index=["3-class LOOCV accuracy", "3-class LOOCV Brier", "2-class LOOCV accuracy", "2-class LOOCV Brier"])
    print(summary.to_string())

    return {
        "nb3": nb3, "bn3": bn3, "nb2": nb2, "bn2": bn2,
        "nb3_brier": nb3_brier, "bn3_brier": bn3_brier,
        "nb2_brier": nb2_brier, "bn2_brier": bn2_brier,
    }


if __name__ == "__main__":
    main()
