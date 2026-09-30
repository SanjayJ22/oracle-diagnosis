"""Structure learning for the Bayesian network: compare the hand-drawn structure
(BN_EDGES in models.py -- a label->everything star, plus one hand-added edge
congestion_d -> heartbeat_elapsed_d) against structures LEARNED from the data via
Chow-Liu (tree-structured) and Hill-Climbing + BDeu score (a less-constrained DAG).

Structure is learned PER LOOCV FOLD, from training data only, to avoid leakage --
exactly like `fit_bayesian_network`'s discretization thresholds are already
recomputed per fold. discretization is class_conditional throughout (the current
default, reports/discretization_v2.md), reusing models.py's own threshold function
unchanged.

METHODOLOGICAL NOTE, worth reading before trusting any edge this file reports:
Chow-Liu and Hill-Climbing both need ONE COMPLETE data matrix (no per-cell NaNs) --
unlike CPD-fitting, which already tolerates missingness via a per-node dropna().
Naively dropping any row with a missing feature leaves only 1 manipulation
incident and ZERO malfunction incidents in the training data (price_dev,
cross_venue_spread, and dex_oracle_spread are missing together for 81-96% of
manipulation/malfunction incidents -- verified directly, see the co-missingness
table this module's __main__ prints). That would make structure learning blind to
two of the three classes entirely. Fixed by encoding "missing" as its own explicit
discrete state (f"{prefix}_missing") for the structure-learning step ONLY -- CPD
fitting and prediction, for all three structures compared here, still use the
original 2-state (low/high, NaN skipped) encoding and per-node dropna, identical
to models.py's production methodology, so accuracy numbers reported here are
directly comparable to reports/discretization_v2.md's hand-drawn-structure numbers.

This fix has a real, documented side effect: because several features are missing
almost perfectly together (not at random), their "_missing" states are highly
correlated with EACH OTHER (not just with the label) -- Chow-Liu / Hill-Climbing
can and do pick up on this as spurious mutual information between features that
never actually co-occur with real values, not a genuine value-level dependency.
This is diagnosed explicitly, not swept under the rug -- see report Section 3.
"""

import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from models import (
    BN_EDGES,
    BN_RAW_TO_DISCRETE,
    BN_STATE_NAMES,
    LABELS,
    RESERVE_SKEW_CLIP,
    _bn_clean,
    _class_conditional_threshold,
    load_data,
)

MAX_ENTROPY = np.log(len(LABELS))
DISC_COLS = ["label_d"] + [v[0] for v in BN_RAW_TO_DISCRETE.values()]


def _entropy(posterior: dict) -> float:
    p = np.array(list(posterior.values()))
    p = p[p > 0]
    return float(-(p * np.log(p)).sum() / MAX_ENTROPY)


def _discretize(train_df: pd.DataFrame, missing_as_category: bool) -> tuple[pd.DataFrame, dict]:
    """Discretize `train_df` (class-conditional thresholds, computed from this df
    only) into a DataFrame with columns DISC_COLS. Returns (discretized_df,
    thresholds). If missing_as_category, NaN -> f"{prefix}_missing" (used only for
    structure learning); otherwise NaN is preserved (used for CPD fitting/
    prediction, matching models.py's production behavior)."""
    work = train_df.copy()
    work["label_d"] = work["label"]
    thresholds = {}
    for raw_col, (disc_col, prefix) in BN_RAW_TO_DISCRETE.items():
        cleaned = work[raw_col].apply(lambda v, c=raw_col: _bn_clean(c, v))
        magnitude = cleaned.abs()
        t = _class_conditional_threshold(work, raw_col, magnitude)
        if t is None:
            t = magnitude.dropna().median()
        thresholds[raw_col] = t
        if missing_as_category:
            work[disc_col] = magnitude.apply(
                lambda m, tt=t, p=prefix: (f"{p}_missing" if pd.isna(m) else (f"{p}_high" if m > tt else f"{p}_low"))
            )
        else:
            work[disc_col] = magnitude.apply(
                lambda m, tt=t, p=prefix: np.nan if pd.isna(m) else (f"{p}_high" if m > tt else f"{p}_low")
            )
    return work[DISC_COLS], thresholds


def _discretize_row(row: pd.Series, thresholds: dict) -> dict:
    """Discretize a single held-out row using fold-fixed thresholds (2-state,
    missing features simply absent from the returned evidence dict) -- identical
    behavior to models.py's predict_bayesian_network."""
    evidence = {}
    for raw_col, (disc_col, prefix) in BN_RAW_TO_DISCRETE.items():
        x = _bn_clean(raw_col, row[raw_col])
        if pd.isna(x):
            continue
        evidence[disc_col] = f"{prefix}_high" if abs(x) > thresholds[raw_col] else f"{prefix}_low"
    return evidence


def learn_chow_liu(train_disc_missing: pd.DataFrame):
    from pgmpy.estimators import TreeSearch
    ts = TreeSearch(train_disc_missing, root_node="label_d")
    tree = ts.estimate(estimator_type="chow-liu", show_progress=False)
    return list(tree.edges())


def learn_hillclimb(train_disc_missing: pd.DataFrame, max_indegree: int = 3):
    from pgmpy.estimators import HillClimbSearch, BDeu
    scorer = BDeu(train_disc_missing, equivalent_sample_size=2)
    hc = HillClimbSearch(train_disc_missing)
    dag = hc.estimate(scoring_method=scorer, max_indegree=max_indegree, show_progress=False)
    return list(dag.edges())


def fit_cpds(edges: list, train_disc_2state: pd.DataFrame):
    """Fit CPDs on `edges` (arbitrary DAG, node names among DISC_COLS) using the
    2-state (NaN-preserving) discretized training data, per-node dropna, BDeu
    prior -- identical methodology to models.py's fit_bayesian_network. Returns
    None if any CPD has zero complete training rows (a fit failure for this fold)."""
    from pgmpy.estimators import BayesianEstimator
    from pgmpy.models import DiscreteBayesianNetwork

    nodes_needed = set()
    for a, b in edges:
        nodes_needed.add(a)
        nodes_needed.add(b)
    if "label_d" not in nodes_needed:
        return None  # label must appear somewhere in the graph to be queryable

    model = DiscreteBayesianNetwork(edges)
    fitted_cpds = []
    for node in model.nodes():
        parents = list(model.get_parents(node))
        cols = [node] + parents
        complete = train_disc_2state.dropna(subset=cols)
        if len(complete) == 0:
            return None
        est = BayesianEstimator(model, complete, state_names={c: BN_STATE_NAMES[c] for c in cols})
        try:
            cpd = est.estimate_cpd(node, prior_type="BDeu", equivalent_sample_size=2)
        except Exception:
            return None
        fitted_cpds.append(cpd)
    model.add_cpds(*fitted_cpds)
    if not model.check_model():
        return None
    return model


def predict(model, evidence: dict):
    from pgmpy.inference import VariableElimination
    # Only pass evidence for nodes actually present in this structure -- a learned
    # structure may not include every feature (Hill-Climbing found none of these
    # cases in practice, but Chow-Liu / the star each keep all 7, so this is a
    # defensive no-op for the structures actually evaluated here).
    usable_evidence = {k: v for k, v in evidence.items() if k in model.nodes()}
    infer = VariableElimination(model)
    result = infer.query(variables=["label_d"], evidence=usable_evidence, show_progress=False)
    return dict(zip(result.state_names["label_d"], result.values))


def run_loocv_for_structure(df: pd.DataFrame, structure_fn, structure_name: str, fixed_edges=None):
    """structure_fn(train_disc_missing) -> edges, OR fixed_edges is used directly
    (for the hand-drawn structure, which doesn't need per-fold learning since it's
    not learned from data at all -- included in the same loop for a uniform
    comparison harness). Returns (result_df, edges_per_fold: list[list[edge]])."""
    rows = []
    edges_per_fold = []
    for i in range(len(df)):
        held_out = df.iloc[i]
        train = df.drop(df.index[i])

        train_2state, thresholds = _discretize(train, missing_as_category=False)

        if fixed_edges is not None:
            edges = fixed_edges
        else:
            train_missing, _ = _discretize(train, missing_as_category=True)
            edges = structure_fn(train_missing)
        edges_per_fold.append(edges)

        model = fit_cpds(edges, train_2state)
        if model is None:
            rows.append({
                "incident": held_out["incident"], "label": held_out["label"], "pred": None,
                "p_manipulation": np.nan, "p_malfunction": np.nan, "p_volatility": np.nan,
                "confidence": np.nan, "entropy": np.nan, "correct": False,
                "note": "CPD fit failed on this fold",
            })
            continue

        evidence = _discretize_row(held_out, thresholds)
        post = predict(model, evidence)
        pred = max(post, key=post.get)
        rows.append({
            "incident": held_out["incident"], "label": held_out["label"], "pred": pred,
            "p_manipulation": post["manipulation"], "p_malfunction": post["malfunction"],
            "p_volatility": post["large volatility event"],
            "confidence": post[pred], "entropy": _entropy(post), "correct": pred == held_out["label"],
            "note": "",
        })
    return pd.DataFrame(rows), edges_per_fold


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    df = load_data()
    cols = ["price_dev", "cross_venue_spread", "dex_oracle_spread", "reserve_skew",
            "ref_realized_vol", "heartbeat_elapsed", "congestion"]
    miss = df[cols].isna()
    print("Missingness co-occurrence check (why missing-as-category is necessary):")
    import itertools
    for a, b in itertools.combinations(cols, 2):
        both = (miss[a] & miss[b]).sum()
        either = (miss[a] | miss[b]).sum()
        if either > 3:
            print(f"  {a:20s} & {b:20s}: both={both:3d} either={either:3d} overlap={both/either:.0%}")
