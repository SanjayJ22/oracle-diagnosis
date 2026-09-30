# Staleness refresh: supporting analyses brought in line with the current production model

**`src/models.py` was not changed.** This pass only updated three supporting-
analysis scripts and their reports so they reflect the current production
model (165 incidents, `"fixed"` discretization, hand-drawn structure, temporal
features per the production per-model split) instead of whatever configuration
happened to be current when each was first written. Confirmed directly
(`git diff --stat src/models.py` returns empty).

## What was refreshed

- **`reports/two_stage_v2.md`** (`src/two_stage_v2.py` updated to support
  `discretization="fixed"`, now its default) — numbers updated, and the
  **verdict changed materially**: the calibration advantage that was this
  analysis's headline finding (wins decisively on Brier/ECE/log-loss) has
  mostly evaporated under fixed discretization (near-parity on Brier, a
  reversal to a loss on ECE, a much smaller log-loss edge). Manipulation
  recall improved to an exact tie with the flat model (was -8.3 points behind);
  malfunction recall picked up a new loss (was tied at 0/3, flat model now
  gets 1/3 that two-stage still misses end-to-end). Net: still doesn't
  clearly win, but for a different mix of reasons than before.

- **`reports/two_class_analysis.md`** (`src/two_class_analysis.py`'s
  `_fit_bn_2class` fixed to use `"fixed"` discretization) — full rewrite from
  n=20 to n=165. **The headline finding reverses.** Original: "BN gets
  meaningfully cleaner under the 2-class collapse (+10 points accuracy, Brier
  roughly halved)." Current: BN's accuracy is exactly flat (93% both ways)
  and its Brier gets *worse* (0.133 → 0.145). More decisively, the
  error-direction breakdown (always the more direct test of the underlying
  hypothesis than the headline numbers) shows **0 of BN's 11 three-class
  errors are manipulation↔malfunction confusions — all 11 cross the oracle-
  failure/volatility boundary**, the exact opposite of what the original
  hypothesis predicted. This has a direct implication for the two-stage
  architecture above: Stage 1 of that design assumes the oracle-failure/
  volatility split is the easy part — this analysis now shows it's the hard
  part.

- **`reports/ablation_and_audit.md`** (`src/ablation_audit.py`'s ablation
  loop fixed to handle features BN doesn't have) — updated from n=20 to
  n=165. Feature attribution shifted substantially: `reserve_skew` is now
  BN's single most load-bearing feature for manipulation by a wide margin
  (dropping it costs 75 points of recall, up from a much smaller, differently-
  attributed effect at n=20), while for NB, `reserve_skew` now *hurts*
  manipulation recall when kept (dropping it gains 12 points) — a documented,
  pre-existing Gaussian-outlier-sensitivity issue, not new, but now more
  visible in the ablation table. Leakage/missingness/separation checks
  re-confirmed clean at the current scale, no new issues found.

## What was marked superseded, not refreshed

- **`reports/two_stage_analysis.md`** (the original two-stage test, ~45
  incidents, sign-based discretization) — marked superseded at the top,
  pointing to `two_stage_v2.md`. Not re-run; kept only for historical
  reference.

## Two real bugs found and fixed along the way (not just staleness)

- **`two_class_analysis.py`**: its `_fit_bn_2class` discretization had never
  been updated past the original sign-based median split, even though it
  reuses `models.py`'s own `predict_bayesian_network` unchanged for scoring —
  which had already moved to a magnitude-based comparison. Fit and predict
  were silently using two different discretization rules. Fixed to use
  `"fixed"` throughout, eliminating the mismatch.
- **`ablation_audit.py`**: its ablation loop iterates `FEATURE_COLS` (NB's
  feature list, which includes `temporal_gap_trend`) and unconditionally
  called the BN ablation for every feature in it — crashing with a `KeyError`
  on `temporal_gap_trend`, which was deliberately excluded from BN's
  structure by the temporal-features per-model split. Fixed by skipping BN's
  ablation for any feature not present in `BN_RAW_TO_DISCRETE`, reporting it
  explicitly as N/A rather than crashing or silently reporting zero. Scoped
  to the ablation script, not `models.py`.

**A third issue was found but not fixed in code**: `ablation_audit.py`
also prints a substantial amount of narrative interpretation text that is
hardcoded from the original n=20 run and does not dynamically reflect the
current data (e.g. it claims `ref_realized_vol` drives BN's manipulation
detection, when the fresh n=165 table shows a 0% effect from that feature
and a -75% effect from `reserve_skew`). `reports/ablation_and_audit.md` was
written using the script's actual computed tables, with corrected
interpretation, rather than trusting or reproducing that stale prose — noted
explicitly in that report rather than silently worked around.

## Malfunction n=3 — unchanged across every refreshed analysis

None of this refresh added malfunction data or changed its fundamental
scarcity. Every malfunction-related number across all three updated reports
is still a statement about the same 3 incidents, now just scored against a
different discretization scheme and a larger comparison set than before.
