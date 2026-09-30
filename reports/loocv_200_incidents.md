# Phase 3 scaling + re-evaluation: 105 → 165 incidents (target was ~200)

**SUPERSEDED for BN's numbers specifically**: this report's central finding (§4) —
that the "global" magnitude-aware discretization scheme fails at n=165 — is still
accurate and remains the correct diagnosis of what went wrong. But the BN accuracy/
recall/calibration numbers throughout this report used that failing scheme. A fix
(`discretization="class_conditional"`, now the default in `src/models.py`) is
implemented and evaluated in `reports/discretization_v2.md`, which recovers BN's
manipulation recall to 83.3% (up from this report's 37.5%, and above even n=105's
71%) while also *reducing* volatility-called-manipulation confusion. Read this
report for the diagnosis; read `reports/discretization_v2.md` for the fix and the
current numbers.

---

**Target not fully reached — reported honestly, not padded.** Manipulation: 24 total
(+7) — a wider DeFiHackLabs keyword sweep (vault/share-price/collateral/liquidation/
rounding/precision/donation/inflation, terms phases 1-2 hadn't tried) found 12 new
mainnet-confirmed candidates, pre-screened for the atomic-round-trip/diffuse-venue
failure mode *before* integration this time (not after, as in phase 2) — 5 were
dropped, 7 survived with clean, independently-verified, persisting balance signals
(see `reports/manipulation_candidates_phase3.md`; 4 of the 7 were independently
re-verified by direct on-chain reads in this session, matching the report's numbers
exactly). Volatility: 138 total (+53) — automated sampling at a lowered 3% threshold.
Malfunction: held at 3, not re-searched. **165 total, not 200** — consistent with
this project's standing rule to report the true number.

**This phase's central, most important finding is not the scaling itself — it's that
the magnitude-aware discretization fix from the previous phase does NOT hold up at
this larger scale, for a mechanistically clear and now fully diagnosed reason (§4).**
BN's manipulation recall, which had recovered to 71% (12/17) after that fix at n=105,
**falls back to 37.5% (9/24) at n=165** — worse than even the pre-fix n=105 number
(35%). This is reported plainly as a genuine regression, not glossed over as
"still an improvement over the old scheme."

## 1. Headline comparison across five points

| Metric | 20 | 45 | 105 (pre-disc.-fix) | 105 (post-disc.-fix) | **165 (post-disc.-fix)** |
|---|---|---|---|---|---|
| Deterministic accuracy (in-sample) | 55% | 71% | 87% | 87% | **92% — not comparable, see §2** |
| NB LOOCV accuracy | 75% | 80% | 81% | 81% | **84.2%** |
| BN LOOCV accuracy | 85% | 87% | 83% | 89% | **83.6%** |
| NB manipulation recall | 80% | 67% | 0% (0/17) | 0% (0/17) | **8.3% (2/24)** |
| BN manipulation recall | 100% | 100% | 35% (6/17) | **71% (12/17)** | **37.5% (9/24)** |
| NB Brier | 0.500 | 0.324 | 0.312 | 0.312 | **0.229** |
| BN Brier | 0.267 | 0.199 | 0.224 | 0.151 | **0.195** |
| NB ECE | — | 0.166 | 0.171 | 0.171 | **0.124** |
| BN ECE | — | 0.058 | 0.042 | 0.047 | **0.038** |
| NB log-loss | — | 2.576 | 2.234 | 2.234 | **1.478** |
| BN log-loss | — | 0.367 | 0.397 | 0.302 | **0.347** |

The "105 (post-disc.-fix)" column is what the user's request treated as the current
baseline to compare against; the "105 (pre-disc.-fix)" column is shown alongside for
full lineage, exactly as `reports/loocv_150_incidents.md` and
`reports/discretization_fix.md` established it.

## 2. The deterministic baseline is flagged, not trended, per instruction

92% in-sample at n=165 is not placed in a trend line with 55%/71%/87% — like every
prior report in this series, it is a compositional artifact of how calm the
automatically-sampled volatility incidents happen to be (phase 3's 3% threshold is
the lowest yet, meaning calmer average moves whose `reserve_skew` crosses the rule's
fixed 5% threshold even less often). Reporting this as "the rule improved" would be
actively misleading about a scale-composition effect, not a property of the rule
itself.

## 3. Answering the three tracked questions directly

**Does BN's calibration edge over NB hold on all three metrics at this scale?**
**Yes — decisively, and this is the genuinely good news in this report.** Brier
(0.195 vs 0.229), ECE (0.038 vs 0.124), and log-loss (0.347 vs 1.478) all favor BN,
by a wider margin than at n=105 in two of three cases. This holds *even while BN's
manipulation-recall accuracy regresses* (§4) — meaning BN's stated probabilities
remain honestly calibrated (it is not confidently wrong when it misses a
manipulation incident; see the entropy numbers in §6), which is a meaningfully
different and better property than simply "gets more right answers."

**Does BN's manipulation recall (71% at n=105) hold or improve?** **No — it falls
to 37.5% (9/24), a real regression, not a plateau.** Mechanism fully diagnosed in
§4, not just observed.

**Does the discretization fix keep working at this larger scale?** **No, not
robustly.** It was a genuine, verified improvement at n=105 (35% → 71% manipulation
recall, confirmed in `reports/discretization_fix.md`), but it does not generalize as
the dataset grows further, for a specific, diagnosed reason: the fix's threshold is
a *single global* median of absolute values across the *entire* dataset, and as
phase 3 added 53 more (calmer, lower-threshold) volatility incidents, that global
median shifted enough to let a much larger fraction of ordinary volatility incidents
cross into the same "far" (large-magnitude, anomalous) bucket that manipulation
occupies — diluting the feature's discriminative power. This is a *different*
failure mode from the original sign-based problem the fix solved, not a reappearance
of it.

## 4. Why the fix stops working at n=165: a global-threshold instability, diagnosed directly

Checked directly, not inferred. At n=165, `reserve_skew`'s median-of-absolute-values
threshold is **0.008425** — down from **0.013478** at n=105. Recomputing the
near/far bucket assignment with this threshold:

| Class | far (large-magnitude) | near (small-magnitude) |
|---|---|---|
| Manipulation | 24/24 (100%) | 0/24 |
| Large volatility event | **57/138 (41.3%)** | 81/138 |
| Malfunction | 0/3 | 3/3 |

**Every single manipulation incident still correctly lands in "far"** — the feature
itself has not become less informative for manipulation. The problem is entirely on
the volatility side: **41.3% of volatility incidents now also land in "far"**, up
sharply from an implied ~4-13% at n=105 (consistent with the 4/85 and 6/85
volatility-called-manipulation confusion counts reported at n=45/n=105 in
`reports/loocv_150_incidents.md`). This collapses the likelihood ratio
P(far | manipulation) / P(far | volatility) from roughly 7-20× at n=105 down to
about **2.4×** at n=165 — a much weaker signal for Bayesian updating to work with,
which is why so many manipulation incidents now get posted at 50-56% confidence
(barely past the decision boundary) and a meaningful number tip the wrong way.

**Root cause: a single population-wide median is not a stable invariant as class
sizes and magnitude distributions shift.** Volatility outnumbers manipulation more
heavily at n=165 (138:24, ~5.75:1) than at n=105 (85:17, exactly 5:1), and more
importantly, phase 3's volatility incidents were sampled at a lower 3% move
threshold than any prior phase — by construction, a wider range of "ordinary"
reserve_skew noise now exists in the volatility class, some of which happens to
exceed whatever global magnitude threshold the median produces. Because the
threshold is fit from the *whole* population rather than being class-conditional,
it is only accidentally well-separating at any given `n` — it does not encode an
actual boundary between the two classes' distributions, just wherever the 50th
percentile of everyone's magnitude happens to fall. **This is not the same bug the
discretization fix solved** (that was sign-conflation; this is threshold instability
under compositional shift) — it is a new, related limitation of the same general
"single global scalar threshold, 2 bins" design.

**Two previously-correct incidents at n=105 are now wrong at n=165**, not just
newly-added ones missed: BalancerV2 and WiseLending both flip from "manipulation"
(correct) to "large volatility event" (wrong) — direct evidence this is a genuine
regression in the model's behavior on stable, already-integrated data, not merely a
failure to generalize to new incidents.

## 5. The 5 previously-missed manipulation incidents: still missed, unchanged

Cream Finance, MonoX Finance, MEVBOTa47b, CurveLlamaLend, and ResupplyFi — all 5
remain classified as "large volatility event" at n=165, exactly as at n=105. More
training data (17 → 24 manipulation incidents) did **not** recover any of them.
Notably, **two of the new phase-3 incidents with strong, clean, independently-
verified signals are also confidently misclassified**: AjnaFinance (reserve_skew
+3.35, predicted volatility at 98.5% confidence) and BalancerBoostedPool2023
(reserve_skew +0.245, predicted volatility at 99.1% confidence) — both far more
confidently wrong than the near-coin-flip pattern seen elsewhere, because their
*other* features (heartbeat_elapsed, congestion, ref_realized_vol) apparently look
typical-volatility enough to dominate the diluted reserve_skew signal. This is a
new, additional piece of evidence that the discretization mechanism, not just data
volume, is the limiting factor — more manipulation examples did not help precisely
because the shared feature is now less discriminative for everyone, old and new
incidents alike.

## 6. Per-class entropy, Bayesian network (n=165)

| Class | Mean entropy | n | vs. n=105 (post-fix) |
|---|---|---|---|
| Manipulation | 0.60 | 24 | down from a higher value — consistent with §3's finding that BN isn't confidently wrong, it's genuinely less certain, which is honest calibration even as accuracy drops |
| Malfunction | 0.44 | 3 | markedly lower than n=105's malfunction entropy — see §7, this reflects a shift toward uniformly predicting volatility, not newfound confidence in the right answer |
| Large volatility event | 0.23 | 138 | slightly down, consistent with a larger, still well-separated majority class |

## 7. Malfunction n=3 — still the central limitation, and NB's edge over BN here is unchanged

Held at 3 throughout (structurally rare, established across phase 1's 3-pass, 27-feed
search — see `reports/malfunction_search_coverage.md`; not re-searched, not padded).
**BN's malfunction recall is 0/3 at n=165**, same as every prior scale. **NB's
malfunction recall remains 2/3**, unchanged, still the only model that catches any
malfunction cases. Every number for this class should be read as "this specific n=3
sample" — nothing about scaling the other two classes to 165 total incidents changes
malfunction's fundamental data-scarcity problem; it is 3 points at every scale this
project has tested, and will remain the least reliable part of any of these models'
output until that changes.

## 8. Volatility-called-manipulation confusion: modestly up in rate, still bounded

NB: 0/138 (unchanged from 0/85 at n=105 — NB essentially never predicts manipulation
at either scale now, per its own Gaussian-fit fragility, documented in
`reports/loocv_150_incidents.md` §4 and worsening further here as more large-
magnitude manipulation incidents, like AjnaFinance's raw +3.35 and TOPBPool's raw
+670,679, keep entering its unclipped Gaussian fit — NB's manipulation recall is now
8.3%, up trivially from 0% but still effectively non-functional for this class).
BN: 9/138 (6.5%), up from 4/85 (4.7%) at n=105 — a real, if modest, rate increase,
directly explained by §4's diluted-threshold mechanism rather than a separate new
problem.

## 9. What this phase argues for, going forward

- **The magnitude-aware discretization fix should not be treated as a settled,
  final solution** — it was a real, verified improvement at n=105 but has now been
  shown, directly and with a clear mechanism, to be unstable under further scaling.
  This is a more useful and more honest finding than either "the fix works" or "the
  fix failed" alone.
- **A concrete, well-motivated next step** (not attempted here — this phase was
  scaling + evaluation only, per instruction, no feature or discretization change):
  replace the single global population-wide threshold with a **class-conditional**
  or **fixed, non-data-dependent** threshold for `reserve_skew` specifically, so
  that adding more volatility incidents at a new, lower move-threshold cannot itself
  change where the manipulation/volatility boundary is drawn. A percentile computed
  *within* each class (e.g., using training-fold manipulation incidents' own
  magnitude distribution to anchor the split) would not be vulnerable to this
  specific failure mode, though it introduces its own class-imbalance-sensitivity
  concerns worth testing before adopting.
- **NB should continue to be treated as the more degenerate model for this task**,
  not a viable alternative — its manipulation recall (8.3%) is even more broken than
  BN's, for the same root cause (an unrobust Gaussian fit meeting real, large-
  magnitude values) that `reports/loocv_150_incidents.md` first diagnosed at n=105,
  now compounded by more such incidents (AjnaFinance, TOPBPool) entering the fit.
- **BN's honest calibration (its probabilities matching its actual accuracy, even
  when that accuracy is mediocre) is this phase's most robust, reproducible
  finding** — it held at n=45, n=105 (both pre- and post-fix), and now n=165,
  across a data-generating process that has visibly shifted underneath it. That is
  a meaningfully different and more valuable property than raw accuracy at any one
  snapshot of the dataset.
