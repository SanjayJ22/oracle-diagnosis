# Supporting analysis: two-class collapse (oracle failure vs. large volatility)

**Refreshed as part of `reports/refresh_summary.md`'s staleness pass — full
rewrite, not a patch.** This report previously ran on the original 20
incidents. Re-run on the current 165-incident production model (fixed
discretization, hand-drawn structure, temporal features per the production
per-model split). **The headline finding reverses.** The original n=20 result
was "the Bayesian network gets meaningfully cleaner under the two-class
collapse (accuracy +10 points, Brier roughly halved)." At n=165, **BN's
accuracy is exactly flat between 3-class and 2-class (93% both), and its
Brier score gets *worse*, not better, under the collapse (0.133 → 0.145)**.
More decisively: **11 of BN's 11 three-class errors cross the oracle-failure/
volatility boundary; zero are manipulation↔malfunction confusions** — the
exact opposite of what the original hypothesis predicted.

**A real bug was also found and fixed while refreshing this**, not just
staleness: `_fit_bn_2class`'s discretization had never been updated past the
original sign-based median split, even as `src/models.py`'s own
`predict_bayesian_network` — reused here unchanged for scoring — moved to a
magnitude-based comparison. Fit and predict were silently using two different
rules. Fixed to use `"fixed"` discretization throughout (matching current
production), eliminating the mismatch.

## Hypothesis being tested

That "the oracle is wrong" (manipulation OR malfunction) is easy to separate
from "the oracle is right, the market genuinely moved" (large volatility
event), and that the hard part of the three-class problem is specifically
**manipulation vs. malfunction**, not either of them vs. volatility.

## Setup

Manipulation (24) + malfunction (3) → **oracle failure** (27); large
volatility event (138) unchanged. Same 165 incidents, current production
feature set, `"fixed"` discretization, hand-drawn BN structure, LOOCV protocol
throughout — unchanged from the flat 3-class production model in every
respect except the label collapse itself.

## Headline numbers

| | Naive Bayes | Bayesian Network |
|---|---|---|
| 3-class LOOCV accuracy | 95% (157/165) | 93% (154/165) |
| 2-class LOOCV accuracy | 96% (159/165) | **93% (153/165) — unchanged** |
| 3-class LOOCV Brier | 0.097 | 0.133 |
| 2-class LOOCV Brier | 0.073 | **0.145 — worse, not better** |

**The original hypothesis is no longer supported for BN, and was already only
weakly supported for NB.** At n=20, BN's accuracy jumped +10 points and its
Brier roughly halved under the 2-class collapse — the headline evidence for
"oracle-failure-vs-volatility is the easy part." At n=165, BN's accuracy does
not move at all, and its calibration measurably *worsens*. NB's pattern is
qualitatively similar to before (a real but modest calibration improvement,
accuracy essentially flat-to-slightly-up), but the far more informative
number is the error-direction breakdown below, which was always the more
direct test of the actual hypothesis than the headline accuracy/Brier
comparison.

## Error-direction breakdown: the decisive test, and it refutes the hypothesis outright for BN

For each model's 3-class LOOCV errors, whether the error is a manipulation↔
malfunction confusion (would *disappear* if the classes were collapsed) or
crosses the oracle-failure/volatility boundary (would *persist* under the
collapse):

| Model | Total 3-class errors | Manip↔malfunction (would disappear) | Crosses oracle-failure/volatility boundary (would persist) |
|---|---|---|---|
| Naive Bayes | 8 | 2/8 (25%) | 6/8 (75%) |
| **Bayesian Network** | 11 | **0/11 (0%)** | **11/11 (100%)** |

**For BN, literally none of its errors would be fixed by merging manipulation
and malfunction together.** Every single one of BN's 11 three-class mistakes
is a case where it confused an oracle-failure incident with a volatility
incident (or vice versa) — `Inverse Finance`, `stETH/ETH heartbeat lag`, `UST/
USD feed freeze`, `MEVBOTa47b`, `Conic Finance 02`, and `CurveLlamaLend` all
get called `large volatility event` when they're really oracle failures;
`May 19 2021 crash`, `Aug 2023 selloff`, `Aug 5 2024 carry-trade unwind`,
`April 2025 tariff shock`, and `Oct 10-11 2025 flash crash` all get called
`manipulation` when they're really ordinary volatility. This is the direct
opposite of "the hard part is manipulation vs. malfunction" — for BN at this
scale, **the hard part is entirely the oracle-failure/volatility boundary
itself**, the boundary the original hypothesis assumed was the easy part.

NB's picture is less extreme but points the same direction: 6 of 8 errors
(75%) cross the oracle-failure/volatility boundary, only 2 (25%) are
manipulation↔malfunction confusions — the majority pattern already favors
"boundary is hard," even for the model where the original hypothesis had more
apparent support.

## Two-class per-class breakdown

| | Naive Bayes | Bayesian Network |
|---|---|---|
| Oracle failure recall | 81% (22/27) | 74% (20/27) |
| Volatility recall | 99% (137/138) | 96% (133/138) |

Both models' 2-class oracle-failure recall (81% NB, 74% BN) is notably close
to their corresponding 3-class manipulation-or-malfunction-combined recall
would be — consistent with the error-direction finding above: collapsing the
classes doesn't meaningfully change *which* incidents get missed, because the
errors were never primarily about the manipulation/malfunction distinction to
begin with.

**Incidents missed under the 2-class collapse are a strict subset-ish overlap
with the 3-class misses**, not a new error pattern: `Inverse Finance`,
`MEVBOTa47b`, `Conic Finance 02`, and `CurveLlamaLend` appear as errors under
both NB and BN, in both the 2-class and 3-class framings — these are
consistently the hardest incidents in the current dataset regardless of how
many classes the problem is framed as.

## Calibration detail

| | Naive Bayes | Bayesian Network |
|---|---|---|
| 2-class Brier | 0.073 | 0.145 |
| >90% confidence bucket accuracy | 96% (159/159) | 93% (131/141) |
| 70-90% confidence bucket accuracy | — (0 predictions) | 100% (19/19) |
| 50-70% confidence bucket accuracy | — (0 predictions) | 60% (3/5) |

NB's calibration is close to degenerate here (every single 2-class prediction
falls in the >90% confidence bucket — consistent with this project's
long-documented finding that NB tends toward overconfident, near-binary
posteriors). BN spreads its confidence more realistically across buckets, and
its lower-confidence bucket (50-70%) is appropriately less accurate (60%) than
its high-confidence bucket (93-100%) — genuinely informative uncertainty, even
though its overall Brier score is worse than NB's in absolute terms.

## What this means for the project going forward

The two-class collapse was originally motivated as a way to simplify the
classification problem by removing what was assumed to be its hardest
distinction. **That motivation doesn't hold up at the current scale.** The
harder problem — as directly evidenced by where errors actually concentrate —
is distinguishing a genuine oracle failure (of either kind) from ordinary
market volatility, not distinguishing the two failure kinds from each other
once a failure is suspected. This is a materially different picture from what
this analysis originally suggested, and it should inform how much weight any
future two-class simplification (including the two-stage architecture in
`reports/two_stage_v2.md`, which structurally assumes the same "easy first
split" premise) is given: Stage 1 of that architecture is solving exactly the
problem this analysis now shows is the *hard* one, not the easy one.

## Malfunction n=3 — explicit, unresolved by this reframing

Every number touching malfunction in this report is a statement about 3
incidents (2 of malfunction's 3 members appear as oracle-failure/volatility
boundary errors for BN: `stETH/ETH heartbeat lag` and `UST/USD feed freeze`).
Collapsing manipulation and malfunction together does not, and cannot, add
data to this class — it only changes how its existing 3 points are scored
against a different set of alternatives.
