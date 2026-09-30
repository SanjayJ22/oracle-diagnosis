"""Evaluate adding the crash-vs-attack discriminating feature pair
(src/compute_crash_attack_feature.py, reports/crash_vs_attack_feature.md) to the
classifier, on top of the current production feature set, keeping the hand-drawn
structure and "fixed" discretization (current defaults) unchanged -- only the
FEATURE SET is being tested, via the same temporary monkey-patch pattern already
used in src/structure_edge_test.py, src/temporal_features_eval.py, and
src/dex_twap_feature_eval.py. No permanent change to src/models.py from running
this script -- every patched constant is restored in a `finally` block.

Tests three variants: +reserve_skew_localization alone, +skew_vol_ratio alone,
and +both together, against the unmodified baseline, for both NB and BN.
"""

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

import models as _models
from models import LABELS, load_data
from loocv_validation import loocv_bayesian_network, loocv_naive_bayes
from calibration_metrics import brier_score, expected_calibration_error, multiclass_log_loss

# FIXED_THRESHOLDS reuse: reserve_skew_localization is an excess-over-market-in-
# percentage-points quantity, same units/scale as every other spread/skew feature
# in this project -> reuse the same 0.05 (5 percentage point) convention.
# skew_vol_ratio is a unitless disproportion ratio (not a percentage) -- 10x is
# used as a round, domain-motivated "order of magnitude disproportionate" cutoff,
# not fit to this dataset's class labels (consistent with every other FIXED_
# THRESHOLDS entry's philosophy: a reused/motivated constant, not a population
# statistic).
FEATURE_SPECS = {
    "reserve_skew_localization": {"disc": "rsl_d", "prefix": "rsl", "threshold": 0.05},
    "skew_vol_ratio": {"disc": "svr_d", "prefix": "svr", "threshold": 10.0},
}


def with_features_added(fn, cols, *args, **kwargs):
    orig_feature_cols = list(_models.FEATURE_COLS)
    orig_raw_to_discrete = dict(_models.BN_RAW_TO_DISCRETE)
    orig_edges = list(_models.BN_EDGES)
    orig_state_names = dict(_models.BN_STATE_NAMES)
    orig_fixed = dict(_models.FIXED_THRESHOLDS)

    for col in cols:
        spec = FEATURE_SPECS[col]
        _models.FEATURE_COLS.append(col)
        _models.BN_RAW_TO_DISCRETE[col] = (spec["disc"], spec["prefix"])
        _models.BN_EDGES.append(("label_d", spec["disc"]))
        _models.BN_STATE_NAMES[spec["disc"]] = [f"{spec['prefix']}_low", f"{spec['prefix']}_high"]
        _models.FIXED_THRESHOLDS[col] = spec["threshold"]
    try:
        return fn(*args, **kwargs)
    finally:
        _models.FEATURE_COLS.clear()
        _models.FEATURE_COLS.extend(orig_feature_cols)
        _models.BN_RAW_TO_DISCRETE.clear()
        _models.BN_RAW_TO_DISCRETE.update(orig_raw_to_discrete)
        _models.BN_EDGES.clear()
        _models.BN_EDGES.extend(orig_edges)
        _models.BN_STATE_NAMES.clear()
        _models.BN_STATE_NAMES.update(orig_state_names)
        _models.FIXED_THRESHOLDS.clear()
        _models.FIXED_THRESHOLDS.update(orig_fixed)


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
            "vol_recall": result[result.label == "large volatility event"]["correct"].mean(),
            "vol_called_manip": (result[result.label == "large volatility event"]["pred"] == "manipulation").sum(),
            "manip_called_vol": (result[result.label == "manipulation"]["pred"] == "large volatility event").sum()}


def confusion(result):
    return pd.crosstab(result["label"], result["pred"])


ERROR_WATCHLIST = [
    # Group A: volatility -> manipulation (5)
    "Oct 10-11 2025 flash crash", "Aug 2023 selloff", "Aug 5 2024 carry-trade unwind",
    "May 19 2021 crash", "April 2025 tariff shock",
    # Group B: manipulation -> volatility (4)
    "MEVBOTa47b", "CurveLlamaLend", "Conic Finance 02", "Inverse Finance",
    # Group C: malfunction -> volatility (2)
    "UST/USD feed freeze", "stETH/ETH heartbeat lag",
]


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    df = load_data()
    print(f"n = {len(df)}")
    print("\nCoverage of new columns:")
    for col in ["market_basket_skew", "reserve_skew_localization", "skew_vol_ratio"]:
        print(f"  {col}: overall {df[col].notna().sum()}/{len(df)}")
        print(df.groupby("label")[col].apply(lambda s: f"{s.notna().sum()}/{len(s)}").to_string())

    variants = {
        "baseline": [],
        "+localization": ["reserve_skew_localization"],
        "+skew_vol_ratio": ["skew_vol_ratio"],
        "+both": ["reserve_skew_localization", "skew_vol_ratio"],
    }

    results = {}
    summaries = {}
    for vname, cols in variants.items():
        print("\n" + "=" * 78 + f"\nBN {vname}\n" + "=" * 78)
        bn_res = with_features_added(loocv_bayesian_network, cols, df) if cols else loocv_bayesian_network(df)
        summaries[f"BN {vname}"] = summarize(f"BN {vname}", bn_res)
        results[f"BN {vname}"] = bn_res

        print("\n" + "=" * 78 + f"\nNB {vname}\n" + "=" * 78)
        nb_res = with_features_added(loocv_naive_bayes, cols, df) if cols else loocv_naive_bayes(df)
        summaries[f"NB {vname}"] = summarize(f"NB {vname}", nb_res)
        results[f"NB {vname}"] = nb_res

    print("\n" + "=" * 78 + "\nSIDE BY SIDE\n" + "=" * 78)
    comp = pd.DataFrame(summaries).T
    print(comp.to_string())

    print("\n" + "=" * 78 + "\nCONFUSION MATRICES: BN baseline vs BN +both\n" + "=" * 78)
    print("BN baseline:\n", confusion(results["BN baseline"]))
    print("\nBN +both:\n", confusion(results["BN +both"]))

    print("\n" + "=" * 78 + "\nERROR WATCHLIST: are the 11 originally-misclassified incidents corrected?\n" + "=" * 78)
    base = results["BN baseline"].set_index("incident")
    for vname in ["+localization", "+skew_vol_ratio", "+both"]:
        ext = results[f"BN {vname}"].set_index("incident")
        print(f"\n--- BN {vname} ---")
        for name in ERROR_WATCHLIST:
            if name not in base.index or name not in ext.index:
                continue
            b_correct = bool(base.loc[name, "correct"])
            e_correct = bool(ext.loc[name, "correct"])
            b_pred, e_pred = base.loc[name, "pred"], ext.loc[name, "pred"]
            flip = "FIXED" if (not b_correct and e_correct) else ("BROKEN" if (b_correct and not e_correct) else "unchanged")
            print(f"  {name:32s} base={b_pred:12s}({'ok' if b_correct else 'ERR'})  "
                  f"new={e_pred:12s}({'ok' if e_correct else 'ERR'})  [{flip}]")

    for r in results.values():
        pass  # results already in memory; csvs not needed unless debugging

    print("\nDONE")
