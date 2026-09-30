# Production baseline: fixed discretization is now the default

**Switched, as directed, based on `reports/discretization_robustness.md`**:
`src/models.py`'s `fit_bayesian_network` and `src/loocv_validation.py`'s
`loocv_bayesian_network` both now default to `discretization="fixed"` (previously
`"class_conditional"`). Rationale, in one line: fixed degrades 7-8x less under
simulated distribution shift matching the pattern that already broke this
project's original "global" scheme once, and its threshold cannot drift at all
by construction, at the cost of a real but modest calibration hit on the exact
current 165-incident snapshot. `"class_conditional"` and `"global"` remain fully
available via the `discretization` parameter for reproducibility — nothing was
removed or hardcoded away, only the default value changed, and both docstrings
were updated to explain why.

## 1. New production baseline, n=165, LOOCV

| Model | Accuracy | Manipulation recall | Malfunction recall | Volatility recall | Brier | ECE | Log-loss |
|---|---|---|---|---|---|---|---|
| Deterministic (in-sample, unaffected by discretization) | 92% (151/165) | 83% (20/24) | 67% (2/3) | 93% (129/138) | — | — | — |
| Naive Bayes (unaffected by BN's discretization scheme) | 95.2% (157/165) | 75.0% (18/24) | **100.0% (3/3)** | 98.6% (136/138) | 0.097 | 0.048 | 1.219 |
| **Bayesian network (fixed, new default)** | **93.3% (154/165)** | **83.3% (20/24)** | **33.3% (1/3)** | 96.4% (133/138) | **0.133** | **0.045** | **0.335** |

**Confirmed matching `reports/discretization_robustness.md`'s "fixed, baseline"
row exactly**: accuracy 93.3%, manipulation recall 83.3%, malfunction recall 1/3
(33.3%), Brier 0.133, ECE 0.045, log-loss 0.335 — re-verified by directly
re-running `loocv_bayesian_network(df)` (no explicit `discretization` argument,
confirming the new default is genuinely in effect) rather than assumed from the
prior report. Deterministic and Naive Bayes are both unaffected by this change
(the deterministic rule doesn't discretize anything; NB uses its own Gaussian
fit, entirely separate from the BN's discretization scheme) — their numbers are
unchanged from before the switch, shown here for a complete current-state
picture, not because the switch touched them.

**Bayesian network is now the only model with any positive malfunction recall
among probabilistic classifiers besides NB** — 1/3 vs. the previous
`class_conditional` default's 0/3. This is the single clearest practical
improvement from the switch, alongside the robustness gain that motivated it.

## 2. Fixed thresholds, with domain motivation (already documented in code, reproduced here per instruction)

From `src/models.py`'s `FIXED_THRESHOLDS`, each pulled from a project convention
established for an independent reason — never fit from incident data, so none
can drift as the dataset's composition changes:

| Feature | Threshold | What it represents | Why this value |
|---|---|---|---|
| `price_dev`, `cross_venue_spread`, `dex_oracle_spread`, `reserve_skew`, `ref_realized_vol` | **0.05** (5%) | A price/spread/skew deviation large enough to be meaningfully anomalous, not ordinary noise | Reuses the deterministic baseline's own `RESERVE_SKEW_THRESHOLD` (its manipulation-call bar) and every volatility-mining script's `CROSS_VENUE_TOLERANCE` (the cross-venue agreement bar for calling an incident "clean") — the same 5% bar this project already uses twice elsewhere for "is this deviation real," not invented fresh for this purpose |
| `heartbeat_elapsed` | **3600s** (1 hour) | An oracle update gap long enough to call the feed stale | Identical to `HEARTBEAT_STALE_THRESHOLD_SECONDS`, the deterministic baseline's own "genuinely stale feed" threshold |
| `congestion` | **0.5** | Network gas usage above its designed-for equilibrium | EIP-1559's actual target gas-usage ratio — Ethereum blocks are protocol-defined as "above target" once usage exceeds 50% of the max gas limit; a real protocol constant, not a statistic fit from this dataset |
| `temporal_deviation_persistence` | **3600s** (1 hour) | How long a price excursion must persist, counting backward from the incident, to be notable | Same reasoning and same constant as `heartbeat_elapsed` above — reused, not a new invented number |
| `temporal_slope` | **0.05** (5%/hour) | A sustained hourly rate of price change large enough to be notable | Same 5%-deviation convention as the price/spread/skew group above, applied per unit time |
| `temporal_step_change_count` | **1** (i.e., >1 is "high") | Whether a price trajectory shows multiple distinct jumps, not just ordinary single-update noise | A single step is ordinary; the original trajectory analysis (`reports/temporal_trajectories.md`) found manipulation showing 5 distinct step-changes over ~2 hours while other classes typically show 0-1 — the threshold reflects that documented finding directly |

**A defensibility note, stated plainly**: this table shows every fixed threshold
traces to a constant already established in this project for a reason unrelated
to being a discretization boundary — none was chosen by inspecting how well it
happens to split this specific dataset. That is the entire basis for calling the
scheme "fixed" rather than data-fit, and is what gives it its distribution-shift
immunity (§3 of `reports/discretization_robustness.md`). It is also the honest
limit of that defensibility: these are *reasonable, precedented* choices, not
*provably optimal* ones — a different, equally defensible convention (e.g. a 3%
or 10% deviation bar) was not tested against these specific values, so "fixed"
should be read as "principled and stable," not "uniquely correct."

## 3. Leakage / no-lookahead check, including a nuance worth reporting honestly

Verified directly, going beyond confirming the trivial fact that a constant
cannot move. **A genuinely useful check**: does the CPD-fitting step still
correctly use only each fold's own training data, given that the threshold
itself never changes? Confirmed by direct inspection, not assumed:

- Excluding `TOPBPool` (a majority-bucket, `|reserve_skew|`-"high" manipulation
  incident, 20 of 24 manipulation incidents share this bucket) from training and
  refitting produces a CPD for `reserve_skew_d` with a specific set of values;
  excluding `Harvest Finance` (also "high"-bucket) instead produces a
  **byte-identical** CPD at the displayed precision — at first glance
  suspicious, but explained and confirmed correct, not a caching bug: `model_a
  is model_b` and `cpd_a is cpd_b` both return `False` (genuinely different
  Python objects, freshly fit each time), and removing any single instance out
  of a ~20-member majority bucket moves a BDeu-smoothed probability by too
  little to show at this precision.
- **Confirmed the model is genuinely composition-sensitive, not silently
  stuck**: excluding `MEVBOTa47b` instead (one of only 4 manipulation incidents
  in the *minority* `|reserve_skew|`-"low" bucket) produces a CPD with visibly
  different values (`0.183 → 0.141` for one cell, `0.817 → 0.859` for another) —
  exactly the expected behavior when a minority-bucket instance, which carries
  much more relative weight in a 4-member group than in a 20-member one, is
  added or removed.
- Every held-out incident confirmed absent from its own fold's training set by
  direct membership check (`'TOPBPool' in train_a['incident'].values` →
  `False`), consistent with every prior no-lookahead verification in this
  project (`train = df.drop(df.index[i])`, applied before any other step).

**Conclusion**: the "fixed" scheme's threshold is (and must be) training-
invariant by design, but the surrounding LOOCV machinery — per-fold CPD
refitting, held-out exclusion — is confirmed working exactly as it does for
every other discretization scheme, with no shortcut or leakage introduced by
the switch.

## 4. Malfunction n=3 — explicit, unresolved by this switch

The switch to `fixed` improves malfunction recall from 0/3 to 1/3 — a genuine
change, but still a statement about 3 specific incidents, not a stable rate.
`reports/discretization_robustness.md` §6 already noted malfunction was
deliberately excluded from every perturbation test (too few points to resample
meaningfully), so this switch's robustness case rests entirely on the
manipulation/volatility evidence, not on any malfunction-specific
robustness claim. Every number in §1's malfunction column, for every model,
should still be read as "these exact 3 points," exactly as throughout this
project's history — nothing about this discretization-scheme change resolves
malfunction's fundamental data-scarcity problem, and none of the perturbation
testing that motivated this switch was designed to address it.
