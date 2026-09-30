"""Definitive robustness comparison: class-conditional vs. fixed discretization,
under simulated distribution shift, at the current n=165 production feature set
(7 static + 3 temporal for BN -- reports/temporal_features.md).

Directly reuses models.py's production fit_bayesian_network/predict_bayesian_network
UNCHANGED (both already support discretization="class_conditional"/"fixed" and
already include the current full BN feature set) -- the only new code here is a
perturbation step applied to each LOOCV fold's TRAINING data before fitting,
leaving the held-out evaluation incident completely untouched. This means the
"no perturbation" condition exactly reproduces loocv_bayesian_network's normal
output for each scheme (a built-in sanity check), and every perturbed condition
differs only in what the model was trained on, never in how it's scored -- no
leakage from oversampling, since duplicated rows only ever appear in `train`,
never contribute to `held_out`.

Perturbations, each chosen to mimic a concrete, already-documented real shift:
  - oversample_calm_volatility: triples the calmest half of volatility incidents
    (by |reserve_skew|) in each fold's training pool -- this is the literal
    mechanism that broke the "global" discretization scheme at n=165
    (reports/loocv_200_incidents.md Sec 4): phase 3 added 53 calmer,
    lower-threshold volatility incidents, shifting the population median.
  - manip_ratio(factor): duplicates (factor>1) or downsamples (factor<1)
    manipulation incidents in the training pool, testing sensitivity to the
    manipulation:volatility ratio specifically (currently ~1:5.75).
  - combined: oversample_calm_volatility AND manip_ratio(0.5) together -- the
    closest single-perturbation analog to "the pattern this project's own
    scaling phases have actually shown" (volatility easy to scale via automated
    sampling and trending calmer each phase; manipulation scarce and hard to
    grow, reports/manipulation_candidates_phase3.md).
"""

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from models import LABELS, fit_bayesian_network, predict_bayesian_network, load_data, _bn_clean

MAX_ENTROPY = np.log(len(LABELS))


def _entropy(posterior: dict) -> float:
    p = np.array(list(posterior.values()))
    p = p[p > 0]
    return float(-(p * np.log(p)).sum() / MAX_ENTROPY)


def no_perturb(train: pd.DataFrame) -> pd.DataFrame:
    return train


def oversample_calm_volatility(train: pd.DataFrame, multiplier: int = 3) -> pd.DataFrame:
    vol = train[train["label"] == "large volatility event"].copy()
    other = train[train["label"] != "large volatility event"]
    abs_skew = vol["reserve_skew"].apply(lambda v: _bn_clean("reserve_skew", v)).abs()
    median_skew = abs_skew.median()
    calm = vol[abs_skew <= median_skew]
    extra = pd.concat([calm] * (multiplier - 1), ignore_index=True)
    return pd.concat([other, vol, extra], ignore_index=True)


def manip_ratio(train: pd.DataFrame, factor: float, seed: int = 42) -> pd.DataFrame:
    manip = train[train["label"] == "manipulation"]
    rest = train[train["label"] != "manipulation"]
    if factor >= 1:
        n_full_copies = int(factor)
        frac = factor - n_full_copies
        parts = [rest] + [manip] * n_full_copies
        if frac > 0:
            parts.append(manip.sample(frac=frac, random_state=seed))
        return pd.concat(parts, ignore_index=True)
    else:
        keep = manip.sample(frac=factor, random_state=seed)
        return pd.concat([rest, keep], ignore_index=True)


def combined_perturb(train: pd.DataFrame) -> pd.DataFrame:
    return manip_ratio(oversample_calm_volatility(train, multiplier=3), factor=0.5)


PERTURBATIONS = {
    "baseline (no perturbation)": no_perturb,
    "oversample_calm_volatility (3x calmest half)": oversample_calm_volatility,
    "manip_ratio_down (0.5x)": lambda t: manip_ratio(t, 0.5),
    "manip_ratio_up (2x)": lambda t: manip_ratio(t, 2.0),
    "combined (calm-vol 3x + manip 0.5x)": combined_perturb,
}


def perturbed_loocv(df: pd.DataFrame, discretization: str, perturb_fn) -> tuple[pd.DataFrame, list]:
    rows = []
    thresholds_log = []
    for i in range(len(df)):
        held_out = df.iloc[i]
        train = df.drop(df.index[i])
        train_p = perturb_fn(train)
        model, thresholds = fit_bayesian_network(train_p, verbose=False, discretization=discretization)
        thresholds_log.append(thresholds)
        if model is None:
            rows.append({"incident": held_out["incident"], "label": held_out["label"], "pred": None,
                         "p_manipulation": np.nan, "p_malfunction": np.nan, "p_volatility": np.nan,
                         "confidence": np.nan, "entropy": np.nan, "correct": False, "note": "fit failed"})
            continue
        post, _ = predict_bayesian_network(model, thresholds, held_out)
        pred = max(post, key=post.get)
        rows.append({"incident": held_out["incident"], "label": held_out["label"], "pred": pred,
                     "p_manipulation": post["manipulation"], "p_malfunction": post["malfunction"],
                     "p_volatility": post["large volatility event"],
                     "confidence": post[pred], "entropy": _entropy(post), "correct": pred == held_out["label"],
                     "note": ""})
    return pd.DataFrame(rows), thresholds_log


def summarize(result: pd.DataFrame):
    from calibration_metrics import brier_score, expected_calibration_error, multiclass_log_loss
    overall = result["correct"].mean()
    per_class = {l: result[result.label == l]["correct"].mean() for l in LABELS}
    brier = brier_score(result)
    ece, _ = expected_calibration_error(result)
    ll = multiclass_log_loss(result)
    return {"accuracy": overall, "manip_recall": per_class["manipulation"],
            "malf_recall": per_class["malfunction"], "vol_recall": per_class["large volatility event"],
            "brier": brier, "ece": ece, "log_loss": ll}


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    df = load_data()
    print(f"n = {len(df)}")
    print(df["label"].value_counts())

    all_results = {}
    all_thresholds = {}

    for scheme in ["class_conditional", "fixed"]:
        print(f"\n{'='*78}\nSCHEME: {scheme}\n{'='*78}")
        for pname, pfn in PERTURBATIONS.items():
            print(f"  running: {pname} ...", flush=True)
            result, thresholds_log = perturbed_loocv(df, scheme, pfn)
            s = summarize(result)
            all_results[(scheme, pname)] = s
            all_thresholds[(scheme, pname)] = thresholds_log
            result.to_csv(f"/tmp/robust_{scheme}_{pname.split()[0]}.csv", index=False)
            print(f"    acc={s['accuracy']:.1%} manip_recall={s['manip_recall']:.1%} "
                  f"malf_recall={s['malf_recall']:.1%} brier={s['brier']:.3f} "
                  f"ece={s['ece']:.3f} logloss={s['log_loss']:.3f}", flush=True)

    print(f"\n{'='*78}\nSUMMARY TABLE\n{'='*78}")
    summary_rows = []
    for (scheme, pname), s in all_results.items():
        summary_rows.append({"scheme": scheme, "perturbation": pname, **s})
    summary_df = pd.DataFrame(summary_rows)
    print(summary_df.to_string(index=False))
    summary_df.to_csv("/tmp/robust_summary.csv", index=False)

    print(f"\n{'='*78}\nTHRESHOLD STABILITY (reserve_skew)\n{'='*78}")
    for scheme in ["class_conditional", "fixed"]:
        print(f"\n--- {scheme} ---")
        for pname in PERTURBATIONS:
            thr_log = all_thresholds[(scheme, pname)]
            vals = [t["reserve_skew"] for t in thr_log if t is not None and "reserve_skew" in t]
            if vals:
                print(f"  {pname:50s} mean={np.mean(vals):.6f} std={np.std(vals):.6f} "
                      f"min={min(vals):.6f} max={max(vals):.6f}")

    print("\nDONE")
