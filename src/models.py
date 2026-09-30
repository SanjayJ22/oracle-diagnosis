"""Three diagnostic models over data/processed/features.parquet, in order:
  1. Deterministic rule-based baseline
  2. Naive Bayes (features treated independent)
  3. Small Bayesian network (pgmpy) with one dependency edge: heartbeat_elapsed | congestion

Includes 3-4 trajectory-derived temporal features (src/compute_temporal_features.py)
on top of the original 7 static ones -- see reports/temporal_features.md for the
full evaluation and reports/temporal_trajectories.md for the original standalone
analysis these were promoted from. NB and BN use slightly different feature sets
(TEMPORAL_COLS vs BN_RAW_TO_DISCRETE), by design -- see TEMPORAL_COLS's comment.

Also includes reserve_skew_localization (src/compute_crash_attack_feature.py,
reports/crash_vs_attack_feature.md), a BN-ONLY addition (not in FEATURE_COLS,
same asymmetric-split precedent as temporal_gap_trend being NB-only) -- see its
comment at BN_RAW_TO_DISCRETE below.
"""

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

FEATURES_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "features.parquet"
LABELS = ["manipulation", "malfunction", "large volatility event"]

# 4 trajectory-derived temporal features (src/compute_temporal_features.py), added
# on top of the original 7 static (single-snapshot) features -- see
# reports/temporal_features.md for the full evaluation. All computed from a
# strictly-trailing 24h window ending at each incident's own anchor round (no
# lookahead by construction). NB and BN use DIFFERENT subsets of these 4, by
# design, based on a leave-one-out ablation: temporal_gap_trend measurably HELPS
# NB (malfunction recall 100% with it vs 66.7% without, at n=165) but measurably
# HURTS BN (manipulation recall 79.2% with it vs 83.3% without, log-loss 0.230 vs
# 0.215) -- an honest, evidence-driven asymmetry, not an oversight. This mirrors
# this project's own earlier finding that feature attribution is model-dependent
# (reports/project_summary.md Sec 6).
TEMPORAL_COLS = ["temporal_deviation_persistence", "temporal_slope",
                  "temporal_step_change_count", "temporal_gap_trend"]

FEATURE_COLS = ["price_dev", "cross_venue_spread", "dex_oracle_spread", "heartbeat_elapsed", "congestion", "reserve_skew", "ref_realized_vol"] + TEMPORAL_COLS

# Cream Finance's reserve_skew is literally inf (vault went from 0 to ~1.0 backing).
# Clip to a large-but-finite sentinel for any arithmetic that can't handle inf directly
# (discretization, variance estimation); the deterministic rule handles inf natively.
RESERVE_SKEW_CLIP = 3.0


def load_data():
    df = pd.read_parquet(FEATURES_PATH)
    df["reserve_skew_clipped"] = df["reserve_skew"].clip(lower=-RESERVE_SKEW_CLIP, upper=RESERVE_SKEW_CLIP)
    return df


# ============================================================================
# 1. Deterministic baseline
# ============================================================================

HEARTBEAT_STALE_THRESHOLD_SECONDS = 3600  # 1 hour: a genuinely "stale feed" threshold
RESERVE_SKEW_THRESHOLD = 0.05  # 5%: a "large" reserve imbalance


def deterministic_predict(row) -> str:
    if pd.notna(row["heartbeat_elapsed"]) and row["heartbeat_elapsed"] > HEARTBEAT_STALE_THRESHOLD_SECONDS:
        return "malfunction"
    if pd.notna(row["reserve_skew"]) and abs(row["reserve_skew"]) > RESERVE_SKEW_THRESHOLD:
        return "manipulation"
    return "large volatility event"


def run_deterministic_baseline(df: pd.DataFrame):
    print("=" * 78)
    print("1. DETERMINISTIC BASELINE")
    print(f"   Rule: heartbeat_elapsed > {HEARTBEAT_STALE_THRESHOLD_SECONDS}s -> malfunction")
    print(f"         elif |reserve_skew| > {RESERVE_SKEW_THRESHOLD} -> manipulation")
    print(f"         else -> large volatility event")
    print("=" * 78)

    df = df.copy()
    df["pred_deterministic"] = df.apply(deterministic_predict, axis=1)

    print("\nConfusion (rows=true, cols=predicted):")
    confusion = pd.crosstab(df["label"], df["pred_deterministic"], dropna=False)
    confusion = confusion.reindex(index=LABELS, columns=LABELS, fill_value=0)
    print(confusion.to_string())

    print("\nPer-class recall (accuracy within true class):")
    for label in LABELS:
        subset = df[df["label"] == label]
        correct = (subset["pred_deterministic"] == label).sum()
        print(f"  {label:26s}: {correct}/{len(subset)} = {correct/len(subset):.0%}")

    overall = (df["pred_deterministic"] == df["label"]).mean()
    print(f"\nOverall accuracy: {(df['pred_deterministic'] == df['label']).sum()}/{len(df)} = {overall:.0%}")

    print("\nWrong calls (true -> predicted):")
    wrong = df[df["pred_deterministic"] != df["label"]][["incident", "label", "pred_deterministic",
                                                           "heartbeat_elapsed", "reserve_skew"]]
    print(wrong.to_string(index=False))

    print(
        "\nNOTE: heartbeat_elapsed was previously 0 for all 15 non-manipulation incidents due to\n"
        "an anchoring artifact (fixed -- see recompute_heartbeat_elapsed.py). It now reflects the\n"
        "gap preceding each incident's own defining block, computed the same way for all 20\n"
        "incidents. With real values, this rule now catches 2/3 malfunction cases (stETH's 86,428s\n"
        "and FTT's 22,632s both clear the 3600s threshold) but still misses UST/USD (950s -- its\n"
        "'malfunction' is a permanent freeze that *starts* after this point, not a preceding stale\n"
        "gap, so there's no large elapsed value for a threshold to catch). The volatility\n"
        "false-positives-as-manipulation are unrelated to heartbeat_elapsed -- they come entirely\n"
        "from |reserve_skew| overlapping between genuine market moves and actual manipulation."
    )
    return df


# ============================================================================
# 2. Naive Bayes (Gaussian per-feature likelihood, independent features)
# ============================================================================

def _fit_gaussian_nb(df: pd.DataFrame, feature_cols=None):
    feature_cols = FEATURE_COLS if feature_cols is None else feature_cols
    """Per-class, per-feature mean/std, computed only from non-missing values.
    A tiny variance floor avoids zero-variance blowups on classes with few points
    (malfunction has only 3 incidents, some features have just 1 non-missing value)."""
    stats = {}
    for label in LABELS:
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


def _gaussian_logpdf(x, mean, std):
    return -0.5 * np.log(2 * np.pi * std**2) - ((x - mean) ** 2) / (2 * std**2)


def naive_bayes_posterior(row, stats, priors, feature_cols=None):
    """Returns dict label -> posterior probability. Missing features are simply
    excluded from the likelihood product for this instance (no imputation)."""
    feature_cols = FEATURE_COLS if feature_cols is None else feature_cols
    log_post = {}
    for label in LABELS:
        log_p = np.log(priors[label])
        for col in feature_cols:
            x = row[col]
            if pd.isna(x):
                continue  # feature missing for this incident -> skip, don't guess
            x = min(max(x, -RESERVE_SKEW_CLIP), RESERVE_SKEW_CLIP) if np.isinf(x) else x
            fit = stats[label][col]
            if pd.isna(fit["mean"]) or pd.isna(fit["std"]) or fit["n"] == 0:
                # Either zero training examples for this class/feature, or exactly
                # one (mean exists but std is undefined -- can't estimate spread
                # from a single point, so skip rather than assume zero variance).
                continue
            log_p += _gaussian_logpdf(x, fit["mean"], fit["std"])
        log_post[label] = log_p

    max_log = max(log_post.values())
    exp_vals = {k: np.exp(v - max_log) for k, v in log_post.items()}
    total = sum(exp_vals.values())
    return {k: v / total for k, v in exp_vals.items()}


def run_naive_bayes(df: pd.DataFrame):
    print("\n" + "=" * 78)
    print("2. NAIVE BAYES (Gaussian, features treated independent)")
    print("=" * 78)

    priors = {label: (df["label"] == label).mean() for label in LABELS}
    print(f"\nClass priors (empirical, from the 20 incidents): {priors}")

    stats = _fit_gaussian_nb(df)
    print("\nPer-class feature stats (mean, std, n non-missing):")
    for label in LABELS:
        print(f"  {label}:")
        for col in FEATURE_COLS:
            s = stats[label][col]
            print(f"    {col:20s} mean={s['mean']:.4f} std={s['std']:.4f} n={s['n']}" if pd.notna(s["mean"])
                  else f"    {col:20s} (no non-missing values in this class)")

    preds, posteriors_all = [], []
    for _, row in df.iterrows():
        post = naive_bayes_posterior(row, stats, priors)
        preds.append(max(post, key=post.get))
        posteriors_all.append(post)

    df = df.copy()
    df["pred_nb"] = preds
    for label in LABELS:
        df[f"nb_p_{label}"] = [p[label] for p in posteriors_all]

    print("\nPosterior probabilities per incident:")
    show_cols = ["incident", "label", "pred_nb"] + [f"nb_p_{l}" for l in LABELS]
    print(df[show_cols].to_string(index=False, float_format=lambda x: f"{x:.3f}" if isinstance(x, float) else str(x)))

    print("\nConfusion (rows=true, cols=predicted):")
    confusion = pd.crosstab(df["label"], df["pred_nb"], dropna=False).reindex(index=LABELS, columns=LABELS, fill_value=0)
    print(confusion.to_string())

    print("\nPer-class precision / recall:")
    for label in LABELS:
        tp = ((df["pred_nb"] == label) & (df["label"] == label)).sum()
        predicted_pos = (df["pred_nb"] == label).sum()
        actual_pos = (df["label"] == label).sum()
        precision = tp / predicted_pos if predicted_pos else float("nan")
        recall = tp / actual_pos if actual_pos else float("nan")
        print(f"  {label:26s}: precision={precision:.0%} ({tp}/{predicted_pos}), recall={recall:.0%} ({tp}/{actual_pos})")

    print(
        "\nCAVEAT: this is IN-SAMPLE accuracy -- the Gaussian means/stds above were fit from these\n"
        "exact 20 incidents, then scored on the same 20. With only 20 points total (3 in the\n"
        "smallest class), there's no meaningful held-out split available. A clean per-class\n"
        "separation here means the classes ARE separable under a Gaussian-independence assumption\n"
        "on these specific incidents -- it is not evidence the model will get incident #21 right."
    )
    return df


# ============================================================================
# 3. Small Bayesian network (pgmpy)
# ============================================================================

BN_STATE_NAMES = {
    # NOTE: "_low"/"_high" suffix strings are kept as-is (not renamed to "_near"/
    # "_far") purely so two_stage_analysis.py and two_class_analysis.py -- which
    # import this dict but keep their own separate, unmodified sign-based-median
    # discretization copy, out of scope for this fix -- don't break on a state-name
    # mismatch. In fit_bayesian_network/predict_bayesian_network below, "_high" now
    # means "far from zero in magnitude" and "_low" means "near zero in magnitude",
    # not "raw value is numerically high/low" -- see fit_bayesian_network's docstring.
    "label_d": LABELS,
    "price_dev_d": ["pd_low", "pd_high"],
    "cross_venue_spread_d": ["cvs_low", "cvs_high"],
    "dex_oracle_spread_d": ["do_low", "do_high"],
    "reserve_skew_d": ["rs_low", "rs_high"],
    "ref_realized_vol_d": ["vol_low", "vol_high"],
    "heartbeat_elapsed_d": ["hb_low", "hb_high"],
    "congestion_d": ["cong_low", "cong_high"],
    # 3 of the 4 temporal features (reports/temporal_features.md) -- NOT
    # temporal_gap_trend, which a leave-one-out ablation showed measurably hurts
    # BN specifically (manipulation recall 79.2% with it vs 83.3% without, at
    # n=165) even though it measurably helps NB (included in FEATURE_COLS above).
    "temporal_deviation_persistence_d": ["tdp_low", "tdp_high"],
    "temporal_slope_d": ["tsl_low", "tsl_high"],
    "temporal_step_change_count_d": ["tsc_low", "tsc_high"],
    # BN-ONLY (not in NB's FEATURE_COLS -- see reserve_skew_localization's own
    # comment at BN_RAW_TO_DISCRETE below for why).
    "reserve_skew_localization_d": ["rsl_low", "rsl_high"],
}
BN_EDGES = [
    ("label_d", "price_dev_d"),
    ("label_d", "cross_venue_spread_d"),
    ("label_d", "dex_oracle_spread_d"),
    ("label_d", "reserve_skew_d"),
    ("label_d", "ref_realized_vol_d"),
    ("label_d", "heartbeat_elapsed_d"),
    ("congestion_d", "heartbeat_elapsed_d"),
    ("label_d", "temporal_deviation_persistence_d"),
    ("label_d", "temporal_slope_d"),
    ("label_d", "temporal_step_change_count_d"),
    ("label_d", "reserve_skew_localization_d"),
]
# raw column -> (discretized column, label prefix)
BN_RAW_TO_DISCRETE = {
    "price_dev": ("price_dev_d", "pd"),
    "cross_venue_spread": ("cross_venue_spread_d", "cvs"),
    "dex_oracle_spread": ("dex_oracle_spread_d", "do"),
    "reserve_skew": ("reserve_skew_d", "rs"),
    "ref_realized_vol": ("ref_realized_vol_d", "vol"),
    "heartbeat_elapsed": ("heartbeat_elapsed_d", "hb"),
    "congestion": ("congestion_d", "cong"),
    "temporal_deviation_persistence": ("temporal_deviation_persistence_d", "tdp"),
    "temporal_slope": ("temporal_slope_d", "tsl"),
    "temporal_step_change_count": ("temporal_step_change_count_d", "tsc"),
    # reports/crash_vs_attack_feature.md: |reserve_skew| minus a fixed 2-3-pool
    # reference-basket's own median |skew| (src/compute_crash_attack_feature.py)
    # -- measures how LOCALIZED a venue's deviation is vs. the broader market.
    # BN-ONLY: adding it to NB's FEATURE_COLS as well was tested and found to
    # collapse NB's manipulation recall (75.0% -> 33.3%) because this feature
    # inherits reserve_skew's own extreme/infinite raw values (Cream Finance,
    # ResupplyFi), which NB's unclipped Gaussian fit cannot absorb -- the same
    # asymmetric-split precedent as temporal_gap_trend (NB-only), mirrored here
    # (BN-only). Small, real, well-understood BN win: fixes 1 of 11 LOOCV errors
    # (April 2025 tariff shock) net, touches no other prediction, improves BN's
    # Brier ~20% (0.133 -> 0.106). Does NOT solve the underlying error mode --
    # the 9 boundary-region incidents (the ones this was built to separate) fully
    # interleave on this feature's own scale, so no threshold on it (or on any
    # other block-level signal tried so far) cleanly separates them. See
    # reports/crash_vs_attack_feature.md Sec 6 for the mechanism.
    "reserve_skew_localization": ("reserve_skew_localization_d", "rsl"),
}


def _bn_clean(col, value):
    """Clip inf (Cream's reserve_skew) to a finite sentinel; identity otherwise."""
    if col == "reserve_skew" and pd.notna(value) and np.isinf(value):
        return np.sign(value) * RESERVE_SKEW_CLIP
    return value


# Fixed, domain-motivated discretization thresholds (see fit_bayesian_network's
# docstring, discretization="fixed") -- each pulled from a constant this project
# already established for an independent reason, NOT fit from any incident data,
# so it cannot drift as the dataset's composition changes:
#   - 0.05 (5%) for every price/spread/skew-type feature: the same "meaningful
#     deviation" convention already used by RESERVE_SKEW_THRESHOLD below (the
#     deterministic baseline's own manipulation-call threshold) and by every
#     volatility-mining script's CROSS_VENUE_TOLERANCE (the cross-venue agreement
#     bar for calling an incident "clean"). Reused here rather than invented fresh.
#   - 3600s for heartbeat_elapsed: identical to HEARTBEAT_STALE_THRESHOLD_SECONDS
#     below (the deterministic baseline's own "genuinely stale feed" threshold).
#   - 0.5 for congestion: EIP-1559's actual target gas-usage ratio -- Ethereum
#     blocks are defined as "above target" once usage exceeds 50% of the max gas
#     limit, a real protocol constant, not a statistic fit from this dataset.
FIXED_THRESHOLDS = {
    "price_dev": 0.05,
    "cross_venue_spread": 0.05,
    "dex_oracle_spread": 0.05,
    "reserve_skew": 0.05,
    "ref_realized_vol": 0.05,
    "heartbeat_elapsed": 3600,
    "congestion": 0.5,
    # 3 temporal features (reports/temporal_features.md), added here after their
    # absence caused a live KeyError the first time "fixed" was actually
    # exercised post-integration (reports/discretization_robustness.md) --
    # "fixed" was silently broken for any BN feature added after this dict was
    # first written, since nothing enforces FIXED_THRESHOLDS staying in sync with
    # BN_RAW_TO_DISCRETE. Each reuses an existing project convention rather than
    # inventing a new constant:
    "temporal_deviation_persistence": HEARTBEAT_STALE_THRESHOLD_SECONDS,  # same "meaningfully stale" 1h bar
    "temporal_slope": 0.05,  # same 5%-per-unit-time "meaningful deviation" convention, applied hourly
    "temporal_step_change_count": 1,  # >1 discrete step is notable; a single step is ordinary update noise
                                        # (matches the original trajectory finding: manipulation showed 5
                                        # step-changes, ordinary incidents 0-1 -- reports/temporal_trajectories.md)
    # reports/crash_vs_attack_feature.md: same 5-percentage-point "meaningful
    # deviation" convention as every other spread/skew feature above, reused
    # rather than fit to this feature's own scale (which would reintroduce the
    # population/class-statistic drift risk "fixed" exists specifically to avoid).
    "reserve_skew_localization": 0.05,
}


def _class_conditional_threshold(work: pd.DataFrame, raw_col: str, magnitude: pd.Series, labels=None):
    """Threshold = geometric mean of the LARGEST and SMALLEST per-class median
    absolute value for `raw_col`, computed from `work` (training data only under
    LOOCV). A class with zero non-missing values for this feature is excluded.

    Why this, and why it fixes the diagnosed failure (reports/loocv_200_incidents.md
    Sec 4): the "global" scheme's threshold is the median magnitude across the WHOLE
    population, which is implicitly dominated by whichever class has the most
    incidents (large volatility event: 138 of 165) -- as that class's own typical
    magnitude drifts (phase 3 added calmer, lower-threshold volatility incidents),
    the population median drifts with it, silently moving the manipulation/
    volatility boundary. This threshold instead looks at where EACH class's own
    typical magnitude sits and splits the gap between the two extremes -- adding
    more of an already-represented class shifts that class's OWN median only
    slightly (a median is robust to how many more points join near where it
    already was), and does not on its own drag the boundary toward or away from a
    different class. Geometric (not arithmetic) mean is used because these
    magnitudes span multiple orders of magnitude (e.g. reserve_skew's typical
    volatility-class value is ~0.01, its typical manipulation-class value is often
    close to 1, and extreme cases reach into the hundreds of thousands) -- a
    geometric mean finds the natural midpoint in log-space, matching how the two
    classes are actually separated, where an arithmetic mean would be dominated by
    whichever class's magnitude happens to be larger.

    Returns None if no class has any non-missing value for this feature in `work`
    (caller falls back to the global scheme for that one feature/fold).

    `labels`, if given, overrides which class values to condition on -- added so
    a relabeled 2-class frame (e.g. reports/two_stage_v2.md's Stage 1/Stage 2
    splits) can reuse this exact function instead of a parallel copy. Defaults to
    the module-level 3-class LABELS, so every existing caller's behavior is
    unchanged unless it explicitly opts in."""
    medians = {}
    for label in (labels if labels is not None else LABELS):
        vals = magnitude[work["label"] == label].dropna()
        if len(vals) > 0:
            m = vals.median()
            if m > 0:  # a class whose typical value is exactly 0 can't contribute
                medians[label] = m  # a meaningful geometric-mean endpoint
    if not medians:
        return None
    if len(medians) == 1:
        return next(iter(medians.values()))
    lo, hi = min(medians.values()), max(medians.values())
    return (lo * hi) ** 0.5


def fit_bayesian_network(df: pd.DataFrame, verbose: bool = True, drop_feature: str = None,
                          discretization: str = "fixed"):
    """Fit the BN from `df`. Returns (model, thresholds) where thresholds maps each
    raw column to the magnitude threshold (learned from `df` only, method depends on
    `discretization`) used for its near/far split -- see the discretization schemes
    documented below. Returns (None, thresholds) if some CPD has zero complete rows
    in this training set (can happen in a LOOCV fold) -- caller must handle that as
    a fit failure.

    Discretization history, in order (near/far by magnitude, not low/high by raw
    sign, throughout -- see reports/discretization_fix.md for the original switch
    away from sign-based splitting):

    `discretization="global"` (the original magnitude-aware fix, reports/
    discretization_fix.md): `abs(value) > median(abs(value)) -> far, else near`,
    with the median computed across the WHOLE population. This solved the original
    sign-conflation bug at n=105 (BN manipulation recall 35% -> 71%) but was then
    shown, directly and mechanistically, to fail under distribution shift at n=165
    (recall fell to 37.5%, reports/loocv_200_incidents.md Sec 4): because the
    threshold is a population-wide statistic, it is implicitly dominated by
    whichever class has the most incidents (large volatility event), so as that
    class's own typical magnitude drifted (phase 3 added calmer, lower-threshold
    volatility incidents), the threshold silently drifted with it, letting 41.3% of
    volatility incidents cross into the same "far" bucket manipulation occupies.
    Kept only for side-by-side comparison; not the default.

    `discretization="class_conditional"` (see `_class_conditional_threshold`):
    geometric mean of the largest and smallest per-class median absolute value,
    computed from training data. Insulates the threshold from population-size
    imbalance -- adding more of an already-represented class shifts only that
    class's own median, not the class-conditional threshold directly.

    `discretization="fixed"` (see `FIXED_THRESHOLDS`): a constant per feature,
    reused from conventions this project already established for independent
    reasons (the deterministic baseline's own thresholds, the volatility-mining
    cleanliness gate, EIP-1559's real target gas ratio) -- never fit from incident
    data at all, so it cannot drift with the sample by construction. This is the
    single most distribution-shift-proof option (a constant cannot drift, full
    stop), though at n=165 it scores marginally below class_conditional on most
    axes (reports/discretization_v2.md's side-by-side comparison) except
    malfunction recall and ECE, where it's better.

    **Default is "fixed"** as of reports/discretization_robustness.md, which
    directly tested the scenario the previous default's own docstring flagged as
    a reason to reconsider it: simulated distribution shift matching the pattern
    that already broke "global" once (more, calmer volatility incidents; a
    scarcer manipulation class). Under that stress, "class_conditional" (the
    prior default, reports/discretization_v2.md, which itself first fixed
    "global"'s failure at n=165 -- manipulation recall 37.5% -> 83.3%) degraded
    7-8x more than "fixed": manipulation recall fell 29-33 points under stress
    (83.3% -> 50-54%) versus "fixed"'s 4-point drop (83.3% -> 79.2%), and its
    reserve_skew threshold itself moved up to 12.5% (smaller than "global"'s
    catastrophic 38%, but not zero) while "fixed"'s threshold cannot move at all
    by construction -- confirmed empirically, not just asserted. This traded a
    real but modest calibration cost at the exact current snapshot ("class_
    conditional" scores better on Brier/log-loss today: 0.115/0.215 vs.
    "fixed"'s 0.133/0.335) for materially better protection against a
    compositional shift this project has now driven into a discretization-scheme
    failure twice. "global" is kept only for historical comparison; "class_
    conditional" remains available and outperforms "fixed" on the exact current
    dataset if a use case specifically prioritizes that over shift-robustness.

    All three schemes are a provable no-op for the three already-nonnegative
    features (heartbeat_elapsed, congestion, ref_realized_vol) exactly as before --
    abs(x) == x for x >= 0 -- so any behavior difference between schemes is
    concentrated in the genuinely bidirectional features (price_dev,
    cross_venue_spread, dex_oracle_spread, reserve_skew).

    `drop_feature`, if given, removes that raw column's node from the graph entirely
    (for ablation). Dropping "heartbeat_elapsed" also drops "congestion", since
    congestion's only role in this network is as heartbeat_elapsed's second parent --
    with heartbeat_elapsed gone it would be a pointless orphan root node. Dropping
    "congestion" alone leaves heartbeat_elapsed in the graph but with only `label_d`
    as its parent (its Label->X edge is untouched; only the congestion_d->heartbeat_
    elapsed_d edge is removed), which falls out automatically from filtering edges
    that touch the dropped column's discretized node -- no special-casing needed."""
    from pgmpy.estimators import BayesianEstimator
    from pgmpy.models import DiscreteBayesianNetwork

    drop_cols = set()
    if drop_feature is not None:
        drop_cols.add(drop_feature)
        if drop_feature == "heartbeat_elapsed":
            drop_cols.add("congestion")

    raw_to_discrete = {k: v for k, v in BN_RAW_TO_DISCRETE.items() if k not in drop_cols}
    drop_disc_cols = {BN_RAW_TO_DISCRETE[c][0] for c in drop_cols}
    edges = [(a, b) for (a, b) in BN_EDGES if a not in drop_disc_cols and b not in drop_disc_cols]

    if discretization not in ("global", "class_conditional", "fixed"):
        raise ValueError(f"unknown discretization scheme: {discretization!r}")

    work = df.copy()
    work["label_d"] = work["label"]
    thresholds = {}
    for raw_col, (disc_col, prefix) in raw_to_discrete.items():
        cleaned = work[raw_col].apply(lambda v, c=raw_col: _bn_clean(c, v))
        magnitude = cleaned.abs()

        if discretization == "fixed":
            t = FIXED_THRESHOLDS[raw_col]
        elif discretization == "class_conditional":
            t = _class_conditional_threshold(work, raw_col, magnitude)
            if t is None:  # no class had any non-missing value this fold -- fall back
                t = magnitude.dropna().median()
        else:  # "global"
            t = magnitude.dropna().median()

        thresholds[raw_col] = t
        work[disc_col] = magnitude.apply(lambda m, t=t, p=prefix: np.nan if pd.isna(m) else (f"{p}_high" if m > t else f"{p}_low"))

    model = DiscreteBayesianNetwork(edges)
    fitted_cpds = []
    for node in model.nodes():
        parents = list(model.get_parents(node))
        cols = [node] + parents
        complete = work.dropna(subset=cols)
        if verbose:
            print(f"  fitting CPD({node} | {parents}) from {len(complete)}/{len(df)} incidents with {cols} observed")
        if len(complete) == 0:
            return None, thresholds
        est = BayesianEstimator(model, complete, state_names={c: BN_STATE_NAMES[c] for c in cols})
        cpd = est.estimate_cpd(node, prior_type="BDeu", equivalent_sample_size=2)
        fitted_cpds.append(cpd)
    model.add_cpds(*fitted_cpds)
    if not model.check_model():
        return None, thresholds
    return model, thresholds


def predict_bayesian_network(model, thresholds, row):
    """Discretize `row` using the fitted thresholds (median absolute value per
    feature, from training data only) and query P(label | evidence). Returns
    (posterior_dict, evidence_dict_used). See fit_bayesian_network's docstring for
    why this compares abs(x) to a magnitude threshold rather than x to a raw median."""
    from pgmpy.inference import VariableElimination

    evidence = {}
    for raw_col, (disc_col, prefix) in BN_RAW_TO_DISCRETE.items():
        if disc_col not in model.nodes():
            continue  # this feature's node was dropped from the graph (ablation)
        x = _bn_clean(raw_col, row[raw_col])
        if pd.isna(x):
            continue
        evidence[disc_col] = f"{prefix}_high" if abs(x) > thresholds[raw_col] else f"{prefix}_low"

    infer = VariableElimination(model)
    result = infer.query(variables=["label_d"], evidence=evidence, show_progress=False)
    posterior = dict(zip(result.state_names["label_d"], result.values))
    return posterior, evidence


def run_bayesian_network(df: pd.DataFrame):
    print("\n" + "=" * 78)
    print("3. SMALL BAYESIAN NETWORK (pgmpy)")
    print("   Structure: Label -> {price_dev, cross_venue_spread, dex_oracle_spread, reserve_skew,")
    print("              ref_realized_vol, heartbeat_elapsed}; Congestion -> heartbeat_elapsed")
    print("   (heartbeat_elapsed has two parents: Label AND Congestion, per instruction")
    print("   to interpret it conditional on congestion rather than assuming independence)")
    print("=" * 78)

    model, thresholds = fit_bayesian_network(df, verbose=True)
    assert model is not None, "Full-data fit should never have an empty CPD."

    print("\nPosterior per incident (evidence = only that incident's observed features):")
    rows = []
    for _, r in df.iterrows():
        post, evidence = predict_bayesian_network(model, thresholds, r)
        pred = max(post, key=post.get)
        rows.append({
            "incident": r["incident"], "label": r["label"], "pred_bn": pred,
            "bn_p_manipulation": post["manipulation"], "bn_p_malfunction": post["malfunction"],
            "bn_p_volatility": post["large volatility event"],
            "evidence_used": list(evidence.keys()),
        })

    result_df = pd.DataFrame(rows)
    print(result_df[["incident", "label", "pred_bn", "bn_p_manipulation", "bn_p_malfunction", "bn_p_volatility"]]
          .to_string(index=False, float_format=lambda x: f"{x:.3f}" if isinstance(x, float) else str(x)))

    print("\nInference path (which observed features fed the query) per incident:")
    for _, r in result_df.iterrows():
        print(f"  {r['incident']:35s} evidence used: {r['evidence_used']}")

    print("\nConfusion (rows=true, cols=predicted):")
    confusion = pd.crosstab(result_df["label"], result_df["pred_bn"], dropna=False).reindex(index=LABELS, columns=LABELS, fill_value=0)
    print(confusion.to_string())

    print("\nPer-class precision / recall:")
    for label in LABELS:
        tp = ((result_df["pred_bn"] == label) & (result_df["label"] == label)).sum()
        predicted_pos = (result_df["pred_bn"] == label).sum()
        actual_pos = (result_df["label"] == label).sum()
        precision = tp / predicted_pos if predicted_pos else float("nan")
        recall = tp / actual_pos if actual_pos else float("nan")
        print(f"  {label:26s}: precision={precision:.0%} ({tp}/{predicted_pos}), recall={recall:.0%} ({tp}/{actual_pos})")

    return result_df


def main():
    warnings.filterwarnings("ignore")
    df = load_data()

    det_df = run_deterministic_baseline(df)
    nb_df = run_naive_bayes(df)
    bn_df = run_bayesian_network(df)

    print("\n" + "=" * 78)
    print("COMPARISON")
    print("=" * 78)
    merged = df[["incident", "label"]].copy()
    merged["deterministic"] = det_df["pred_deterministic"]
    merged["naive_bayes"] = nb_df["pred_nb"]
    merged["bayes_net"] = bn_df["pred_bn"]
    print(merged.to_string(index=False))

    print("\nOverall accuracy:")
    for name, col in [("Deterministic", "deterministic"), ("Naive Bayes", "naive_bayes"), ("Bayesian Network", "bayes_net")]:
        acc = (merged[col] == merged["label"]).mean()
        print(f"  {name:20s}: {(merged[col] == merged['label']).sum()}/20 = {acc:.0%}")

    print("\nPer-class recall comparison:")
    recall_table = pd.DataFrame({
        name: [
            ((merged[col] == label) & (merged["label"] == label)).sum() / (merged["label"] == label).sum()
            for label in LABELS
        ]
        for name, col in [("Deterministic", "deterministic"), ("Naive Bayes", "naive_bayes"), ("Bayesian Network", "bayes_net")]
    }, index=LABELS)
    print(recall_table.to_string(float_format=lambda x: f"{x:.0%}"))

    print("\nIncidents where deterministic baseline is WRONG but a probabilistic model is RIGHT:")
    for _, r in merged.iterrows():
        det_wrong = r["deterministic"] != r["label"]
        nb_right = r["naive_bayes"] == r["label"]
        bn_right = r["bayes_net"] == r["label"]
        if det_wrong and (nb_right or bn_right):
            print(f"  {r['incident']:35s} true={r['label']:24s} deterministic={r['deterministic']:24s} "
                  f"NB={'right' if nb_right else 'wrong'}  BN={'right' if bn_right else 'wrong'}")


if __name__ == "__main__":
    main()
