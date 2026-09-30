"""Evaluate adding dex_twap_spread (src/compute_dex_twap_feature.py,
reports/richer_features.md Sec 2) to the classifier, on top of the current
production feature set (7 static + 3 temporal for BN, 7 static + 4 temporal for
NB), keeping the hand-drawn structure and "fixed" discretization (current
defaults) unchanged -- only the FEATURE SET is being tested, via the same
temporary monkey-patch pattern already used in src/structure_edge_test.py and
src/temporal_features_eval.py. No permanent change to src/models.py from
running this script -- every patched constant is restored in a `finally` block.
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

NEW_COL = "dex_twap_spread"
NEW_DISC_COL = "dex_twap_spread_d"
NEW_PREFIX = "dtw"


def with_feature_added(fn, *args, **kwargs):
    orig_feature_cols = list(_models.FEATURE_COLS)
    orig_raw_to_discrete = dict(_models.BN_RAW_TO_DISCRETE)
    orig_edges = list(_models.BN_EDGES)
    orig_state_names = dict(_models.BN_STATE_NAMES)
    orig_fixed = dict(_models.FIXED_THRESHOLDS)

    _models.FEATURE_COLS.append(NEW_COL)
    _models.BN_RAW_TO_DISCRETE[NEW_COL] = (NEW_DISC_COL, NEW_PREFIX)
    _models.BN_EDGES.append(("label_d", NEW_DISC_COL))
    _models.BN_STATE_NAMES[NEW_DISC_COL] = [f"{NEW_PREFIX}_low", f"{NEW_PREFIX}_high"]
    _models.FIXED_THRESHOLDS[NEW_COL] = 0.05  # same 5%-spread convention as price_dev/cross_venue_spread/dex_oracle_spread
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
            "vol_called_manip": (result[result.label == "large volatility event"]["pred"] == "manipulation").sum()}


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    df = load_data()
    print(f"n = {len(df)}")

    print("\n" + "=" * 78 + "\nBN BASELINE (no dex_twap_spread)\n" + "=" * 78)
    bn_base = loocv_bayesian_network(df)
    bn_base_s = summarize("BN baseline", bn_base)
    bn_base.to_csv("/tmp/twap_bn_baseline.csv", index=False)

    print("\n" + "=" * 78 + "\nBN + dex_twap_spread\n" + "=" * 78)
    bn_ext = with_feature_added(loocv_bayesian_network, df)
    bn_ext_s = summarize("BN extended", bn_ext)
    bn_ext.to_csv("/tmp/twap_bn_extended.csv", index=False)

    print("\n" + "=" * 78 + "\nNB BASELINE (no dex_twap_spread)\n" + "=" * 78)
    nb_base = loocv_naive_bayes(df)
    nb_base_s = summarize("NB baseline", nb_base)
    nb_base.to_csv("/tmp/twap_nb_baseline.csv", index=False)

    print("\n" + "=" * 78 + "\nNB + dex_twap_spread\n" + "=" * 78)
    nb_ext = with_feature_added(loocv_naive_bayes, df)
    nb_ext_s = summarize("NB extended", nb_ext)
    nb_ext.to_csv("/tmp/twap_nb_extended.csv", index=False)

    print("\n" + "=" * 78 + "\nSIDE BY SIDE\n" + "=" * 78)
    comp = pd.DataFrame({
        "BN baseline": bn_base_s, "BN + twap": bn_ext_s,
        "NB baseline": nb_base_s, "NB + twap": nb_ext_s,
    }).T
    print(comp.to_string())

    print("\n" + "=" * 78 + "\nMEVBOTa47b / CurveLlamaLend status (BN + twap)\n" + "=" * 78)
    watch = ["MEVBOTa47b", "CurveLlamaLend"]
    print(bn_ext[bn_ext.incident.isin(watch)][["incident", "pred", "confidence"]].to_string(index=False))

    print("\nDONE")
