"""CJSJ item 11: export the A2 label sheet to data/processed/labels_a2.csv (join key `incident` == features.parquet `incident`).

Merges reports/a2_label_sheet.csv (cjsj_01) with the receipt-based atomicity classes (reports/cjsj_06_atomicity.csv, cjsj_06).
data/ is gitignored in this repo, so this file is a local artifact; regenerate with this script (needs cjsj_01 and cjsj_06 outputs).
Columns: incident, date, T_block, T_tx, a2_category (M/R/A/K/O), a2_M_any, a2_verified_M (M and 2-source), a2_verified_M_strict
(verified M without math_enabled), evidence_tier, subflags, atomic_label (source-derived), single_tx_class (cjsj_06, repeat-verified,
W=100), flash_loan_detected, S, C, confidence, sources, notes, labeler, labeled_at, model_results_seen_before_label.
"""
import pandas as pd
from cjsj_common import ROOT, TAG_CONFOUNDED, write_section

sh = pd.read_csv(ROOT / "reports/a2_label_sheet.csv")
at = pd.read_csv(ROOT / "reports/cjsj_06_atomicity.csv")
ft = pd.read_parquet(ROOT / "data/processed/features.parquet")[["incident", "date", "label"]]
m = sh.rename(columns={"incident_id": "incident"}).merge(
    at[["incident", "class100", "flash"]].rename(columns={"class100": "single_tx_class", "flash": "flash_loan_detected"}), on="incident", how="left")
m["flash_loan_detected"] = m.flash_loan_detected.ne("none detected")
m = m.merge(ft, on="incident", how="left", validate="one_to_one")
m["a2_M_any"] = m.category.eq("M")
out = m.rename(columns={"category": "a2_category", "verified_M": "a2_verified_M", "verified_M_strict": "a2_verified_M_strict", "atomic": "atomic_label"})
cols = ["incident", "date", "T_block", "T_tx", "a2_category", "a2_M_any", "a2_verified_M", "a2_verified_M_strict", "evidence_tier", "subflags",
        "atomic_label", "single_tx_class", "flash_loan_detected", "S", "C", "confidence", "sources", "notes", "labeler", "labeled_at",
        "model_results_seen_before_label"]
out = out[cols]
assert len(out) == 24 and out.incident.is_unique and (m.label == "manipulation").all()
out.to_csv(ROOT / "data/processed/labels_a2.csv", index=False)
body = (f"Wrote `data/processed/labels_a2.csv` ({len(out)} rows x {len(cols)} columns); join key `incident` matches `features.parquet` (all 24 matched, none missing). "
        f"a2_category counts: {out.a2_category.value_counts().to_dict()}; a2_verified_M={int(out.a2_verified_M.sum())}, strict={int(out.a2_verified_M_strict.sum())}, "
        f"a2_M_any={int(out.a2_M_any.sum())}. single_tx_class: {out.single_tx_class.value_counts().to_dict()}. `data/` is gitignored: local file only. "
        f"Only the 24 manipulation incidents are labeled; volatility/malfunction rows are absent, so left-join on `incident` and treat missing as 'not an A2-labeled attack'.  [cjsj_11_export_labels.py]")
print(body)
write_section("cjsj_11_export_labels.py", "11", "Label sheet exported to data/processed/labels_a2.csv", TAG_CONFOUNDED, body)
