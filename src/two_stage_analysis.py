"""Two-stage hierarchical Bayesian-network diagnosis, evaluated ALONGSIDE (not
replacing) the flat three-class model in models.py/loocv_validation.py -- that file
is untouched, this is a new, separate pipeline built on the same underlying BN
primitives.

Motivation (reports/two_class_analysis.md): "oracle is wrong vs genuine market move"
separates easily (~90% for the flat BN's 2-class collapse), "manipulation vs
malfunction" is where the difficulty concentrates. A two-stage design puts a
dedicated binary classifier at each of those two decision points instead of one flat
3-way classifier making both distinctions at once.

  Stage 1: BN binary classifier, "oracle failure" (manipulation OR malfunction) vs
           "large volatility event".
  Stage 2: BN binary classifier, "manipulation" vs "malfunction", trained ONLY on the
           oracle-failure subset (12 manipulation + 3 malfunction = 15 incidents).

Both stages reuse models.py's BN_EDGES / BN_RAW_TO_DISCRETE / _bn_clean /
predict_bayesian_network UNCHANGED -- only the "label_d" node's state space differs
per stage (2 states each, vs the flat model's 3) via a generalized fit function
(_fit_bn_generic below), parallel to the one already built for
src/two_class_analysis.py's single-stage 2-class collapse.

End-to-end LOOCV, hard-gated (matching how a real two-stage pipeline would run): for
each held-out incident, Stage 1 is fit on the other 44 (relabeled), and:
  - if Stage 1 predicts "large volatility event", that IS the final 3-class
    prediction -- Stage 2 is not invoked.
  - if Stage 1 predicts "oracle failure", Stage 2 is fit on the oracle-failure subset
    of the other 44 (14 or 15 incidents depending on the fold) and its
    manipulation/malfunction call becomes the final 3-class prediction.
A Stage 1 error on a true volatility incident is therefore FORCED through Stage 2,
producing a manipulation-or-malfunction call that's necessarily wrong for the 3-class
metric -- real error propagation, not corrected after the fact.

For Brier/ECE/log-loss, the two stages' posteriors are combined via the chain rule
into one coherent 3-class posterior (P(manipulation) = P(oracle failure) x
P(manipulation | oracle failure), etc.) -- this sums to 1 and is the statistically
correct way to get a single "final posterior" out of a 2-stage decomposition, even
though the DISCRETE prediction follows the hard-gated procedure above, not this
joint posterior's own argmax (which can occasionally differ -- noted in the report
if it comes up, not treated as a second pipeline).
"""

import warnings

import numpy as np
import pandas as pd

from models import (
    BN_EDGES,
    BN_RAW_TO_DISCRETE,
    BN_STATE_NAMES,
    LABELS,
    _bn_clean,
    load_data,
    predict_bayesian_network,
)

STAGE1_LABELS = ["oracle failure", "large volatility event"]
STAGE2_LABELS = ["manipulation", "malfunction"]
ORACLE_FAILURE_CLASSES = {"manipulation", "malfunction"}
EPS = 1e-15


def _fit_bn_generic(df: pd.DataFrame, label_states: list, verbose: bool = False):
    """Same fitting logic as models.py's fit_bayesian_network, generalized to an
    arbitrary label_states list for the "label_d" node instead of the flat model's
    hardcoded 3-class LABELS -- pgmpy's BayesianEstimator requires state_names to
    match the actual column's value domain, so this can't just reuse
    fit_bayesian_network directly with a 2-class-relabeled df."""
    from pgmpy.estimators import BayesianEstimator
    from pgmpy.models import DiscreteBayesianNetwork

    state_names = {**BN_STATE_NAMES, "label_d": label_states}
    work = df.copy()
    work["label_d"] = work["label"]
    thresholds = {}
    for raw_col, (disc_col, prefix) in BN_RAW_TO_DISCRETE.items():
        cleaned = work[raw_col].apply(lambda v, c=raw_col: _bn_clean(c, v))
        med = cleaned.dropna().median()
        thresholds[raw_col] = med
        work[disc_col] = cleaned.apply(
            lambda x, m=med, p=prefix: np.nan if pd.isna(x) else (f"{p}_high" if x > m else f"{p}_low")
        )

    model = DiscreteBayesianNetwork(BN_EDGES)
    fitted_cpds = []
    for node in model.nodes():
        parents = list(model.get_parents(node))
        cols = [node] + parents
        complete = work.dropna(subset=cols)
        if verbose:
            print(f"    fitting CPD({node} | {parents}) from {len(complete)}/{len(df)} rows")
        if len(complete) == 0:
            return None, thresholds
        est = BayesianEstimator(model, complete, state_names={c: state_names[c] for c in cols})
        cpd = est.estimate_cpd(node, prior_type="BDeu", equivalent_sample_size=2)
        fitted_cpds.append(cpd)
    model.add_cpds(*fitted_cpds)
    if not model.check_model():
        return None, thresholds
    return model, thresholds


def _entropy(posterior: dict, labels: list) -> float:
    p = np.array([posterior[l] for l in labels])
    p = p[p > 0]
    max_entropy = np.log(len(labels))
    return float(-(p * np.log(p)).sum() / max_entropy) if max_entropy > 0 else 0.0


def run_two_stage_loocv(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["stage1_label"] = df["label"].apply(lambda l: "oracle failure" if l in ORACLE_FAILURE_CLASSES else l)

    rows = []
    for i in range(len(df)):
        held_out = df.iloc[i]
        train = df.drop(df.index[i])

        # ---- Stage 1: oracle failure vs volatility ----
        train_s1 = train.copy()
        train_s1["label"] = train_s1["stage1_label"]
        model1, thresh1 = _fit_bn_generic(train_s1, STAGE1_LABELS)
        if model1 is None:
            rows.append({
                "incident": held_out["incident"], "true_label": held_out["label"],
                "stage1_pred": None, "stage1_fit_failed": True,
                "final_pred": None, "final_correct": False,
                "final_p_manipulation": np.nan, "final_p_malfunction": np.nan, "final_p_volatility": np.nan,
            })
            continue
        post1, _ = predict_bayesian_network(model1, thresh1, held_out)
        pred1 = max(post1, key=post1.get)

        row = {
            "incident": held_out["incident"], "true_label": held_out["label"],
            "stage1_pred": pred1,
            "stage1_p_oracle_failure": post1["oracle failure"],
            "stage1_p_volatility": post1["large volatility event"],
            "stage1_entropy": _entropy(post1, STAGE1_LABELS),
            "stage1_correct": pred1 == held_out["stage1_label"],
            "stage1_fit_failed": False,
            "stage2_invoked": pred1 == "oracle failure",
        }

        # Stage 2 is fit and queried EVERY fold, regardless of Stage 1's discrete
        # decision -- needed so the reported 3-class posterior (used only for
        # Brier/log-loss/ECE) is coherent via the chain rule even in folds where
        # Stage 1's hard decision was "volatility". Zeroing manipulation/malfunction
        # outright in that branch (an earlier version of this script did that) is
        # indefensible whenever Stage 1's own call was close, not confident -- e.g.
        # stETH/ETH's Stage 1 posterior is 53%/47%, nowhere near certain, so claiming
        # its resulting P(malfunction) is exactly 0.0 manufactures a log(0) penalty
        # that reflects an implementation shortcut, not a real property of the
        # two-stage design. The DISCRETE final_pred still follows the hard gate
        # exactly as specified (Stage 2's call only becomes the answer when Stage 1
        # actually says "oracle failure") -- only the calibration posterior changes.
        p_of = post1["oracle failure"]
        train_s2 = train[train["label"].isin(ORACLE_FAILURE_CLASSES)]
        model2, thresh2 = _fit_bn_generic(train_s2, STAGE2_LABELS)
        if model2 is None:
            stage2_fit_failed = True
            post2 = None
        else:
            stage2_fit_failed = False
            post2, _ = predict_bayesian_network(model2, thresh2, held_out)

        if pred1 == "large volatility event":
            if post2 is None:
                # No stage-2 read available in this fold to split the oracle-failure
                # mass coherently either -- fall back to the empirical class split
                # among the training fold's own oracle-failure incidents (a neutral,
                # data-driven prior split, not an arbitrary 50/50).
                manip_share = (train_s2["label"] == "manipulation").mean()
            else:
                manip_share = post2["manipulation"]
            row.update({
                "stage2_pred": None, "stage2_fit_failed": stage2_fit_failed, "stage2_correct": None,
                "final_pred": "large volatility event",
                "final_p_manipulation": p_of * manip_share,
                "final_p_malfunction": p_of * (1 - manip_share),
                "final_p_volatility": post1["large volatility event"],
            })
        else:
            if stage2_fit_failed:
                row.update({
                    "stage2_pred": None, "stage2_fit_failed": True, "stage2_correct": False,
                    "final_pred": None,
                    "final_p_manipulation": np.nan, "final_p_malfunction": np.nan, "final_p_volatility": np.nan,
                })
            else:
                pred2 = max(post2, key=post2.get)
                row.update({
                    "stage2_pred": pred2, "stage2_fit_failed": False,
                    "stage2_p_manipulation": post2["manipulation"],
                    "stage2_p_malfunction": post2["malfunction"],
                    "stage2_entropy": _entropy(post2, STAGE2_LABELS),
                    "stage2_correct": (pred2 == held_out["label"]) if held_out["label"] in ORACLE_FAILURE_CLASSES else None,
                    "final_pred": pred2,
                    "final_p_manipulation": p_of * post2["manipulation"],
                    "final_p_malfunction": p_of * post2["malfunction"],
                    "final_p_volatility": post1["large volatility event"],
                })

        row["final_correct"] = row["final_pred"] == held_out["label"]
        rows.append(row)

    return pd.DataFrame(rows)


LABEL_TO_COL = {"manipulation": "final_p_manipulation", "malfunction": "final_p_malfunction",
                 "large volatility event": "final_p_volatility"}


def brier_score(result: pd.DataFrame) -> float:
    valid = result.dropna(subset=["final_p_manipulation"])
    briers = []
    for _, r in valid.iterrows():
        onehot = {label: (1.0 if label == r["true_label"] else 0.0) for label in LABELS}
        briers.append(sum((r[LABEL_TO_COL[l]] - onehot[l]) ** 2 for l in LABELS))
    return float(np.mean(briers))


def log_loss(result: pd.DataFrame) -> float:
    valid = result.dropna(subset=["final_p_manipulation"])
    losses = []
    for _, r in valid.iterrows():
        p_true = min(max(r[LABEL_TO_COL[r["true_label"]]], EPS), 1 - EPS)
        losses.append(-np.log(p_true))
    return float(np.mean(losses))


def expected_calibration_error(result: pd.DataFrame):
    """Same 4-bucket scheme as src/calibration_metrics.py, applied to the final
    combined-posterior confidence (max of the 3 final_p_* columns) for consistency."""
    valid = result.dropna(subset=["final_p_manipulation"]).copy()
    valid["final_confidence"] = valid[["final_p_manipulation", "final_p_malfunction", "final_p_volatility"]].max(axis=1)
    bins = [(0.9, 1.01, "very high (>90%)"), (0.7, 0.9, "high (70-90%)"),
            (0.5, 0.7, "medium (50-70%)"), (0.0, 0.5, "low (<50%)")]
    total_n = len(valid)
    ece = 0.0
    rows = []
    for lo, hi, name in bins:
        subset = valid[(valid["final_confidence"] >= lo) & (valid["final_confidence"] < hi)]
        if len(subset) == 0:
            rows.append({"bin": name, "n": 0, "avg_confidence": None, "accuracy": None, "gap": None})
            continue
        avg_conf = subset["final_confidence"].mean()
        acc = subset["final_correct"].mean()
        gap = abs(avg_conf - acc)
        ece += (len(subset) / total_n) * gap
        rows.append({"bin": name, "n": len(subset), "avg_confidence": avg_conf, "accuracy": acc, "gap": gap})
    return ece, pd.DataFrame(rows)


def main():
    warnings.filterwarnings("ignore")
    df = load_data()
    result = run_two_stage_loocv(df)

    print("=" * 90)
    print(f"TWO-STAGE LOOCV ({len(df)} incidents)")
    print("=" * 90)

    stage1_valid = result[~result["stage1_fit_failed"]]
    stage1_acc = stage1_valid["stage1_correct"].mean()
    print(f"\nStage 1 (oracle failure vs volatility) accuracy: "
          f"{stage1_valid['stage1_correct'].sum()}/{len(stage1_valid)} = {stage1_acc:.1%}")

    stage2_attempted = result[result["stage2_correct"].notna()]
    stage2_acc = stage2_attempted["stage2_correct"].mean() if len(stage2_attempted) else float("nan")
    print(f"Stage 2 (manipulation vs malfunction, only when invoked on a TRUE oracle-failure "
          f"incident) accuracy: {stage2_attempted['stage2_correct'].sum()}/{len(stage2_attempted)} = {stage2_acc:.1%}")

    final_valid = result.dropna(subset=["final_pred"])
    final_acc = final_valid["final_correct"].mean()
    print(f"\nEnd-to-end 3-class accuracy: {final_valid['final_correct'].sum()}/{len(final_valid)} = {final_acc:.1%}")

    print("\nConfusion (rows=true, cols=final predicted):")
    confusion = pd.crosstab(result["true_label"], result["final_pred"], dropna=False).reindex(
        index=LABELS, columns=LABELS, fill_value=0)
    print(confusion.to_string())

    print("\nPer-class recall:")
    for label in LABELS:
        subset = result[result["true_label"] == label]
        correct = (subset["final_pred"] == label).sum()
        print(f"  {label:26s}: {correct}/{len(subset)} = {correct/len(subset):.0%}")

    print("\nMisclassified (end-to-end):")
    wrong = result[~result["final_correct"]]
    for _, r in wrong.iterrows():
        print(f"  {r['incident']:35s} true={r['true_label']:24s} stage1={r['stage1_pred']!s:16s} "
              f"stage2={r.get('stage2_pred')!s:16s} final={r['final_pred']!s:24s}")

    brier = brier_score(result)
    ll = log_loss(result)
    ece, ece_table = expected_calibration_error(result)
    print(f"\nBrier score: {brier:.3f}")
    print(f"Log-loss: {ll:.3f}")
    print(f"ECE: {ece:.3f}")
    print(ece_table.to_string(index=False, float_format=lambda x: f"{x:.3f}" if isinstance(x, float) else str(x)))

    n_stage2_fit_failed = (result["stage2_fit_failed"] == True).sum()
    print(f"\nStage 2 fit failures (zero complete rows for some CPD in that fold): {n_stage2_fit_failed}")

    return result, {"stage1_acc": stage1_acc, "stage2_acc": stage2_acc, "final_acc": final_acc,
                     "brier": brier, "log_loss": ll, "ece": ece}


if __name__ == "__main__":
    main()
