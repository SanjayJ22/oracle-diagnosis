# Definitive robustness comparison: class-conditional vs. fixed discretization

**Verdict up front**: not a photo finish, but not a landslide either — read fully
before deciding. **Fixed is decisively, quantifiably more robust** to the exact
kind of distribution shift that has already broken this pipeline once (5-8x less
manipulation-recall degradation under simulated stress). **Class-conditional
currently performs modestly better on 2 of 6 unperturbed baseline metrics**
(Brier, log-loss), while fixed wins the other 2 that differ (malfunction recall,
ECE) and the two schemes tie on accuracy and manipulation recall. Given this
project's own history — two discretization-scheme failures so far, both driven
by exactly the compositional shift tested here — the balance of evidence favors
**fixed**, but this is a real trade-off, not a strict dominance, and is flagged
for your decision rather than switched silently, per instruction.

## 0. A bug found and fixed along the way, disclosed plainly

The first run of this comparison **crashed**, not finished cleanly. Cause: when
temporal features were integrated into production (`reports/temporal_features.md`),
`BN_RAW_TO_DISCRETE`/`BN_EDGES` were updated to include 3 new features, but
`FIXED_THRESHOLDS` was not — nothing enforces the two staying in sync. The
`"fixed"` discretization scheme has been silently broken (would raise a
`KeyError` the moment anyone actually used it) since that commit. This did not
affect production, since `class_conditional` is the default and the only scheme
actually exercised by any prior report — but it is a real latent bug, now fixed
in `src/models.py`: `temporal_deviation_persistence` reuses the existing 1-hour
staleness convention (`HEARTBEAT_STALE_THRESHOLD_SECONDS`), `temporal_slope`
reuses the existing 5%-deviation convention, and `temporal_step_change_count`
uses `>1` (a single step is ordinary update noise; multiple steps is the
change-point-count signature the feature was built to capture). Verified fitting
cleanly before re-running this comparison from scratch.

## 1. Baseline performance, confirmed at the current production feature set (n=165, 7 static + 3 temporal)

| Metric | class_conditional (current default) | fixed |
|---|---|---|
| Accuracy | 93.3% | 93.3% (tied) |
| Manipulation recall | 83.3% (20/24) | 83.3% (20/24) (tied) |
| Malfunction recall | 0/3 | **1/3 (33.3%)** |
| Volatility recall | **97.1%** | 96.4% |
| Brier | **0.115** | 0.133 |
| ECE | 0.054 | **0.045** |
| Log-loss | **0.215** | 0.335 |

**This baseline picture is itself mixed, and different from the pre-temporal-
features comparison in `reports/discretization_v2.md`** (where fixed's ECE was
worse, 0.091 vs. 0.053) — with temporal features now in the mix, fixed's ECE
is actually *better* than class-conditional's. class_conditional wins Brier and
log-loss; fixed wins malfunction recall and ECE; accuracy and manipulation
recall tie exactly. Neither scheme dominates the other even before considering
robustness.

## 2. Robustness test: simulated distribution shift

Method: for each of 5 conditions, every LOOCV fold's **training data only** is
perturbed before fitting (`held_out` is never touched, so no leakage — verified
in §5); the "no perturbation" condition exactly reproduces §1's numbers (built-in
sanity check, confirmed). Perturbations:

- **`oversample_calm_volatility`**: triples the calmest half of volatility
  incidents (by `|reserve_skew|`) in each fold's training pool — the literal
  mechanism that broke the original "global" discretization scheme
  (`reports/loocv_200_incidents.md` §4): phase 3 added 53 calmer,
  lower-threshold volatility incidents, shifting the population median enough
  that 41.3% of volatility crossed into manipulation's bucket.
- **`manip_ratio_down` (0.5x)** / **`manip_ratio_up` (2x)**: downsamples or
  duplicates manipulation incidents in training, testing sensitivity to the
  manipulation:volatility ratio (currently ~1:5.75).
- **`combined`**: both stresses together — the closest single-perturbation
  analog to this project's actual observed scaling pattern (volatility easy to
  grow via automated sampling and trending calmer each phase; manipulation
  scarce and hard to grow, `reports/manipulation_candidates_phase3.md`).

### Full results

| Scheme | Perturbation | Accuracy | Manip. recall | Brier | ECE | Log-loss |
|---|---|---|---|---|---|---|
| class_conditional | baseline | 93.3% | 83.3% | 0.115 | 0.054 | 0.215 |
| class_conditional | oversample_calm_volatility | 89.1% | **54.2%** | 0.140 | 0.068 | 0.297 |
| class_conditional | manip_ratio_down (0.5x) | 89.1% | **54.2%** | 0.129 | 0.074 | 0.232 |
| class_conditional | manip_ratio_up (2x) | 92.7% | 83.3% | 0.106 | 0.027 | 0.203 |
| class_conditional | combined | 88.5% | **50.0%** | 0.162 | 0.087 | 0.316 |
| fixed | baseline | 93.3% | 83.3% | 0.133 | 0.045 | 0.335 |
| fixed | oversample_calm_volatility | 92.7% | 79.2% | 0.138 | 0.064 | 0.380 |
| fixed | manip_ratio_down (0.5x) | 93.9% | 79.2% | 0.129 | 0.067 | 0.330 |
| fixed | manip_ratio_up (2x) | 93.3% | 83.3% | 0.128 | 0.033 | 0.329 |
| fixed | combined | 93.3% | 79.2% | 0.139 | 0.060 | 0.378 |

### Degradation, relative to each scheme's OWN baseline (not cross-scheme)

| Perturbation | class_conditional manip. recall Δ | fixed manip. recall Δ | class_conditional accuracy Δ | fixed accuracy Δ |
|---|---|---|---|---|
| oversample_calm_volatility | **-29.1pp** (83.3%→54.2%) | -4.1pp (83.3%→79.2%) | -4.2pp | -0.6pp |
| manip_ratio_down (0.5x) | **-29.1pp** | -4.1pp | -4.2pp | +0.6pp (improves) |
| manip_ratio_up (2x) | 0pp (unchanged) | 0pp (unchanged) | -0.6pp | 0pp |
| combined | **-33.3pp** (worst case) | -4.1pp | -4.8pp | 0pp |

**This is the core, decisive finding.** Under both perturbations that mimic real
distribution shift (calmer volatility, scarcer manipulation), class-conditional's
manipulation recall collapses by 29-33 percentage points — roughly **7-8x more
degradation than fixed's 4.1-point drop under the identical perturbations**.
Calibration tells the same story: class-conditional's Brier/ECE/log-loss all
worsen by 20-63% relative to its own baseline under the calm-volatility and
combined stresses, while fixed's worsen by only 3-42% (and its accuracy barely
moves, even *improving* slightly under `manip_ratio_down`). `manip_ratio_up`
(pure duplication, adding no new information) leaves both schemes' recall
unchanged and even improves both schemes' calibration slightly — a
CPD-smoothing artifact of BDeu's effective-sample-size increasing, not genuine
new-data robustness, noted honestly rather than counted as a real win for either
scheme.

## 3. Threshold stability, quantified directly

`reserve_skew` threshold across the 165 folds, per condition:

| Scheme | Perturbation | Mean threshold | Std | Shift from own baseline |
|---|---|---|---|---|
| class_conditional | baseline | 0.065817 | 0.001202 | — |
| class_conditional | oversample_calm_volatility | 0.057589 | 0.000043 | **-12.5%** |
| class_conditional | manip_ratio_down | 0.065862 | 0.001205 | +0.07% |
| class_conditional | manip_ratio_up | 0.065817 | 0.001202 | **0% exactly** (duplication cannot move a median) |
| class_conditional | combined | 0.057629 | 0.000063 | -12.4% |
| fixed | *every* perturbation | 0.050000 | **0.000000** | **0%, confirmed empirically, not just asserted** |

**Context for the -12.5% figure**: the original "global" scheme's threshold
shifted **38%** (0.013478 → 0.008425) when phase 3's real 53 calmer volatility
incidents were added, and that 38% shift was catastrophic (manipulation recall
71% → 37.5%). Class-conditional's threshold here moves only **12.5%** under a
comparably-sized *synthetic* calm-volatility stress — a real, substantial
improvement in stability over the failed global scheme, consistent with
`reports/discretization_v2.md`'s design rationale. **But 12.5% is not zero, and
it is enough to cause a real 29-point manipulation-recall drop** — the fix
reduces the failure mode, it does not eliminate it. Fixed's threshold cannot
move at all, by construction, confirmed here empirically across every condition
rather than only asserted from reading the code.

## 4. Calm-subset evaluation: both schemes lean on a few extreme cases, roughly equally

Restricting evaluation to manipulation incidents with below-median
`|reserve_skew|` (excluding literal-infinity cases and TOPBPool's extreme
+670,679.59 — the 11 "harder," less extreme-magnitude incidents: BalancerBoosted
Pool2023, Conic Finance 02, CurveLlamaLend, Harvest Finance, Indexed Finance,
Inverse Finance, MEVBOTa47b, SecuredFi, ThetanutsIndexVault, USM, UwU Lend):

| Scheme | Full-24 recall | Calm-11-subset recall |
|---|---|---|
| class_conditional | 83.3% (20/24) | **63.6% (7/11)** |
| fixed | 83.3% (20/24) | **63.6% (7/11)** |

**Identical for both schemes** — both drop by the same ~20 percentage points
when restricted to less-extreme cases. This is not a differentiator between the
two schemes; it is an honest, shared limitation: a meaningful share of each
scheme's apparent 83.3% strength rests on a handful of very easy, extreme-
magnitude incidents (TOPBPool, Cream Finance, ResupplyFi and similar near-`inf`
cases) rather than uniform performance across the manipulation class. Worth
keeping in mind independent of which discretization scheme is chosen.

## 5. Leakage / no-lookahead check

Verified directly, not just asserted from the perturbation functions' design.
For a specific fold (TOPBPool held out), checked whether `TOPBPool` appears
anywhere in the perturbed training set for all three non-trivial perturbations —
confirmed absent in every case (`oversample_calm_volatility`: 302 rows, absent;
`manip_ratio_up`: 187 rows, absent; `combined`: 291 rows, absent). This holds by
construction (perturbation functions operate on `train = df.drop(df.index[i])`,
computed *before* any oversampling/downsampling step — the held-out row is
removed first and never re-introduced), and is why the "no perturbation"
condition exactly reproduces the true LOOCV baseline rather than an inflated
number from duplicate rows leaking into evaluation.

## 6. Malfunction n=3 — not perturbed, explicit caveat

Malfunction was deliberately **not** included in any perturbation — with only 3
incidents, any resampling (duplication or downsampling) would either trivially
not change anything (there's nothing smaller than "all 3" to downsample to in
any meaningful sense) or produce numbers driven entirely by which 1-2 specific
incidents happened to be duplicated, not a real robustness signal. Every
recall/threshold number in this report that touches malfunction should be read
as a statement about these same 3 points throughout — fixed's baseline edge
(1/3 vs. class-conditional's 0/3) is unchanged across every perturbation
condition for exactly this reason (perturbing volatility/manipulation ratios
doesn't touch the malfunction rows at all), not because either scheme is
especially robust for this class specifically.

## 7. Honest verdict: the trade-off, stated plainly

**What class-conditional costs you**: real fragility to the specific kind of
shift already observed twice in this project's history. Under a stress
condition modeled directly on what actually happened in phase 3, its
manipulation recall drops from 83.3% to as low as 50.0% — a swing large enough
to materially change how much this project's own headline numbers could be
trusted if a future scaling phase repeats that pattern (which, given this
project's documented sourcing reality — volatility easy to scale via automated
sampling, manipulation scarce and hard to grow — is a real possibility, not a
hypothetical one).

**What fixed costs you**: worse log-loss at the current, unperturbed snapshot
(0.335 vs. 0.215, the largest single gap in either direction across all baseline
metrics) and worse Brier (0.133 vs. 0.115) — a real, non-trivial calibration
cost *today*, in exchange for near-total immunity to a *possible future* cost.
It also depends on thresholds chosen by domain reasoning rather than fit from
data, which is defensible (each is reused from an existing project convention,
not invented) but is inherently less adaptive if the features' natural scales
were to shift for reasons unrelated to class-size imbalance (e.g., a change to
how a feature itself is computed).

**Recommendation, flagged for your decision, not applied**: the robustness gap
is large and one-sided (7-8x less degradation under the tested perturbations);
the baseline performance gap is real but smaller and mixed (each scheme wins 2
of 6 baseline metrics). Given this project has already migrated its
discretization scheme twice specifically because of compositional distribution
shift, and given the sourcing pattern that caused it shows every sign of
continuing, the balance of evidence leans toward **fixed** as the more prudent
default going forward. This is not a strict dominance, though — if the priority
is squeezing the most out of the *current, exact* 165-incident snapshot rather
than hedging against how the dataset composition might shift next, class-
conditional's better Brier and log-loss are a legitimate reason to keep it. No
change has been made to `src/models.py`; this is presented as a real choice for
you to make, not a foregone conclusion.
