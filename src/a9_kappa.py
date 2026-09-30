"""A9: agreement between the first labeler (reports/a2_label_sheet.csv) and the blind
second labeler (reports/second_labeler_answers.xlsx). Run from src/:
    ../.venv/bin/python a9_kappa.py
Reports Cohen's kappa for the 5 categories and for M vs not-M, percent agreement,
and every disagreement. Disagreements are resolved by the written rule in
a2_label_protocol.md, not by majority or by model results."""
from pathlib import Path
import csv
import pandas as pd
from sklearn.metrics import cohen_kappa_score, confusion_matrix

R = Path(__file__).resolve().parent.parent / "reports"
first = {r["incident_id"]: r for r in csv.DictReader(open(R / "a2_label_sheet.csv"))}
ans = pd.read_excel(R / "second_labeler_answers.xlsx", sheet_name="Answers")
ans = ans.rename(columns={"Incident": "incident", "Category (M/R/A/K/O)": "cat2"})
ans["cat2"] = ans["cat2"].astype(str).str.strip().str.upper()
missing = ans[~ans.cat2.isin(list("MRAKO"))]
if len(missing):
    print("WARNING: blank or invalid categories for:", list(missing.incident))
ans = ans[ans.cat2.isin(list("MRAKO"))]
ans["cat1"] = ans.incident.map(lambda n: first[n]["category"])

cats = list("MRAKO")
k5 = cohen_kappa_score(ans.cat1, ans.cat2, labels=cats)
b1, b2 = (ans.cat1 == "M"), (ans.cat2 == "M")
k2 = cohen_kappa_score(b1, b2)
print(f"n labeled by both: {len(ans)} of 24")
print(f"5-category: agreement {(ans.cat1 == ans.cat2).mean():.1%}, Cohen's kappa {k5:.2f}")
print(f"M vs not-M: agreement {(b1 == b2).mean():.1%}, Cohen's kappa {k2:.2f}")
print("\nConfusion (rows = first labeler, cols = second labeler):")
print(pd.DataFrame(confusion_matrix(ans.cat1, ans.cat2, labels=cats), index=cats, columns=cats).to_string())
dis = ans[ans.cat1 != ans.cat2][["incident", "cat1", "cat2"]]
print(f"\nDisagreements ({len(dis)}): resolve each by the written rule, record the reason.")
print(dis.to_string(index=False))
print("\nInterpretation guide (Landis & Koch): <0.20 slight, 0.21-0.40 fair, 0.41-0.60 moderate, "
      "0.61-0.80 substantial, >0.80 almost perfect. With n=24 the kappa CI is wide; report it as such.")
