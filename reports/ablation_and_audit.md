# Final Certification Pass: Ablation + Leakage/Robustness Audit

**Refreshed as part of `reports/refresh_summary.md`'s staleness pass.**
Previously ran on 20 incidents with the original 6-feature set; re-run on the
current 165-incident production model (fixed discretization, hand-drawn
structure, 11 features — 7 static + 4 temporal for NB, 7 static + 3 temporal
for BN). **A real bug was found and fixed while refreshing this**: the
ablation loop iterates `FEATURE_COLS` (NB's list, which includes
`temporal_gap_trend`) and calls the BN ablation for every feature in it —
but `temporal_gap_trend` was deliberately excluded from BN's structure
(`reports/temporal_features.md`'s per-model split), so `fit_bayesian_network`
raised a `KeyError` the moment the loop reached it. Fixed in `src/
ablation_audit.py` (not `models.py` — scoped to the ablation script, no
production change) by skipping BN's ablation for any feature not present in
`BN_RAW_TO_DISCRETE` and reporting it explicitly as N/A, not a crash and not a
silently-wrong zero.

**A second, separate issue found**: the script's own printed "Interpretation"
narrative and part of its leakage-audit section (§2's structural-asymmetry
commentary) contain **prose hardcoded for the original n=20 run** that is not
dynamically regenerated from the current data — e.g. it claims dropping
`ref_realized_vol` is "the single biggest effect" on BN's manipulation
detection, when the actual freshly-computed table below shows a 0% effect
from that drop and a **-75% effect from dropping `reserve_skew`**, by far the
largest number in the entire table. This report uses the actual computed
tables (confirmed fresh and correct) and provides corrected interpretation
below; the script's own stale narrative text was not trusted or reproduced.
Not fixed in code this pass (would require making that narrative
data-driven, a larger change than the scope of this refresh) — flagged
here plainly rather than silently worked around.

## 1. Ablation (drop-one-feature, LOOCV), n=165

Baseline (all 11 features): **NB 95% overall** (manipulation 75%, malfunction
100%, volatility 99%); **BN 93% overall** (manipulation 83%, malfunction 33%,
volatility 96%) — matches current production exactly.

| Feature dropped | NB overall Δ | NB manip Δ | NB malf Δ | BN overall Δ | BN manip Δ | BN malf Δ |
|---|---|---|---|---|---|---|
| price_dev | -1% | -4% | +0% | +1% | +0% | +0% |
| cross_venue_spread | +0% | +0% | +0% | +1% | +0% | +0% |
| dex_oracle_spread | +0% | +0% | +0% | +0% | +0% | +0% |
| heartbeat_elapsed | -2% | +0% | **-33%** | -1% | +0% | **-33%** |
| congestion | +0% | +0% | +0% | +1% | +0% | **+33%** |
| **reserve_skew** | **+2%** | **+12%** | +0% | **-10%** | **-75%** | +0% |
| ref_realized_vol | -1% | +0% | +0% | +0% | +0% | +0% |
| temporal_deviation_persistence | +1% | +4% | +0% | -1% | -4% | +0% |
| temporal_slope | -1% | +0% | +0% | +0% | +0% | +0% |
| temporal_step_change_count | +0% | +0% | +0% | -1% | -4% | **-33%** |
| temporal_gap_trend | -1% | +0% | **-33%** | N/A (not in BN) | N/A | N/A |

(`+` in a Δ column means dropping the feature *improved* that metric; `-`
means it hurt. A 0% net can hide a correct→wrong flip cancelling a
wrong→correct flip — the script's own per-incident flip log, not reproduced
here in full, confirms every 0% row that has one.)

## 2. Corrected interpretation (the script's own printed narrative for this section is stale — see above)

**BN manipulation is now overwhelmingly carried by `reserve_skew`** — dropping
it costs **75 percentage points** of manipulation recall, by a wide margin the
single largest effect anywhere in this table. This is close to a full
reversal of the original n=20/n=112-era finding that BN's manipulation calls
leaned on `ref_realized_vol` and `heartbeat_elapsed` instead — at the current
scale, with the current discretization scheme, `reserve_skew` is doing almost
all of the work. `temporal_deviation_persistence` and
`temporal_step_change_count` each contribute a smaller, real amount (-4 points
each).

**NB manipulation shows the opposite relationship with `reserve_skew`** —
dropping it *improves* NB's manipulation recall by 12 points. This is not new
evidence that `reserve_skew` is a bad feature; it is the same, already-
documented mechanism (`reports/loocv_150_incidents.md` §4, `reports/
temporal_features.md`) where NB's unclipped Gaussian fit is distorted by
`reserve_skew`'s legitimately extreme values (TOPBPool's raw +670,679.59, e.g.)
— removing the feature entirely sidesteps that distortion rather than fixing
it. `temporal_deviation_persistence`'s drop also improves NB manipulation
recall slightly (+4 points), suggesting it may share some of this same
extreme-value sensitivity, though at a much smaller scale.

**Malfunction is genuinely contested between models**: `heartbeat_elapsed`
is load-bearing for BOTH models (-33% for each when dropped — one incident,
since malfunction is n=3), but so is `temporal_gap_trend` for NB (-33%,
likely the same single incident, a redundant confirming signal rather than
independent evidence) and `temporal_step_change_count` for BN (also -33%,
same pattern). **`congestion`'s drop actually *improves* BN's malfunction
recall by 33 points** — a genuinely new, counter-intuitive finding: at the
current scale, `congestion` is actively hurting BN's ability to catch the one
malfunction incident it currently gets right, not helping.

**Net assessment**: the original n=20 hypothesis ("`reserve_skew` carries
manipulation, `heartbeat_elapsed` carries malfunction") now holds cleanly for
BN-manipulation (dramatically so) and for both models' malfunction detection
via `heartbeat_elapsed`, but is reversed for NB-manipulation (`reserve_skew`
now hurts, not helps) — a genuinely mixed, model-dependent picture, consistent
with this project's repeated finding throughout its history that feature
attribution should never be assumed to generalize across models or scales
without being re-checked.

## 3. Leakage / robustness audit — the freshly-computed data tables, current at n=165

**(a) Missingness pattern per feature per class** (counts of missing values,
freshly computed):

| Feature | Volatility (138) | Malfunction (3) | Manipulation (24) |
|---|---|---|---|
| price_dev | 0 | 2 | 20 |
| cross_venue_spread | 0 | 3 | 23 |
| dex_oracle_spread | 0 | 2 | 23 |
| heartbeat_elapsed | 0 | 0 | 0 |
| congestion | 3 | 0 | 1 |
| reserve_skew | 0 | 2 | 0 |
| ref_realized_vol | 0 | 2 | 0 |
| temporal features (all 4) | 0 | 1-2 | 0 |

The `price_dev`/`cross_venue_spread`/`dex_oracle_spread` asymmetry
(structurally absent for most manipulation and malfunction incidents, present
for essentially all volatility incidents) is the same, already-documented
pattern from `reports/structure_learning.md`'s missingness-confound
discussion and every prior missing-feature report in this project's history —
re-confirmed at the current scale, not new.

**(b) Single-feature perfect-separation check**: re-run fresh across all 11
features × 3 classes. **Zero perfect separations found** — every feature/class
pair with data on both sides overlaps; no single feature or threshold trivially
gives away a class. This matches the original n=20 finding and holds at scale.

**(c) Manipulation `reserve_skew` cleanliness**: all 24 manipulation
incidents' raw `reserve_skew` values re-confirmed against `data/processed/
features.parquet` directly — matches every value already documented across
this project's phase reports (TOPBPool +670,679.59, Cream Finance and
ResupplyFi literal `+inf`, etc.), no discrepancy found.

**(d) Remaining lookahead check**: re-read `build_features.py`,
`recompute_manipulation_curve_features.py`, `recompute_heartbeat_elapsed.py`,
and `fetch_curve.py` fresh for this pass. No lookahead found — every state
read uses `block_identifier=<=incident_block>`, architecturally incapable of
seeing a future block. Consistent with every prior no-lookahead verification
in this project, including the newer temporal-feature and DEX-TWAP reads
added since the original n=20 audit (both independently verified for
no-lookahead in their own reports, `reports/temporal_features.md` and
`reports/dex_twap_feature.md`).

**(e) Structural/bookkeeping separability**: the `cross_venue_spread`/
`price_dev`/`dex_oracle_spread` asymmetry from §3(a) above is the one
remaining real structural gap — non-missing for essentially all volatility
incidents (138 of 138), missing for the overwhelming majority of manipulation
and malfunction incidents. As established when this was first found: **not
exploitable as a disguised zero** (both models explicitly skip missing
features rather than encoding absence as a value), but it does mean
volatility incidents structurally receive more independent evidence terms
than manipulation/malfunction incidents do — an availability asymmetry, not a
fabricated signal, unchanged in kind from the original finding, now just
re-confirmed at 165 incidents instead of 20.

## Bottom line

**Perfect single-feature separations: 0.** **Lookahead: none found,
architecturally impossible.** **Structural missingness asymmetry: 1 real one
(`cross_venue_spread`/`price_dev`/`dex_oracle_spread`'s shared missingness
pattern), unchanged in kind from the original audit, re-confirmed at scale.**
**Feature attribution is more model-dependent than the original n=20 finding
suggested, not less** — `reserve_skew` has fully reversed its relationship
with NB's manipulation recall (from neutral-to-positive at n=20 to actively
harmful at n=165) while becoming BN's single most load-bearing feature by a
wide margin. Malfunction's n=3 caveat is unchanged and unresolved by any of
this — every finding touching that class remains a description of 3 specific
points, not a validated pattern.
