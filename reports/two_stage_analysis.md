# Two-stage hierarchical Bayesian network: a new analysis alongside the flat model

**SUPERSEDED — see `reports/two_stage_v2.md`.** This analysis ran on ~45
incidents with the original sign-based discretization scheme, before any of
the dataset scaling, discretization fixes, or temporal features in this
project's later history. `reports/two_stage_v2.md` re-tests the same
architecture on the current 165-incident production model and reaches a
materially different verdict (mixed — loses on accuracy/recall, wins on
calibration — rather than "worse across the board"). Kept here for historical
reference only; not re-run, not treated as current.

**Verdict up front: the two-stage design is worse than the flat three-class Bayesian
network, on every metric measured — accuracy, Brier, log-loss, and ECE.** Not
"similar with tradeoffs" — worse across the board. The mechanism is precise and
well-evidenced, not just a fitting quirk: see §3. The flat model
(`src/models.py`/`src/loocv_validation.py`) is untouched; this is a new, separate
pipeline (`src/two_stage_analysis.py`), evaluated alongside it, not replacing it.

## 1. Architecture

- **Stage 1**: BN binary classifier, "oracle failure" (manipulation ∪ malfunction) vs.
  "large volatility event". Same BN structure as the flat model (star from `label_d`
  to each feature, `congestion_d → heartbeat_elapsed_d`), 2 label states instead of 3.
- **Stage 2**: BN binary classifier, "manipulation" vs. "malfunction", trained ONLY on
  the 15 true oracle-failure incidents (12 manipulation + 3 malfunction).
- **Hard-gated LOOCV**: for each held-out incident, Stage 1 is fit on the other 44
  (relabeled). If Stage 1 predicts volatility, that's the final answer — Stage 2 is
  never consulted for the decision. If Stage 1 predicts oracle failure, Stage 2 (fit
  on the oracle-failure subset of the other 44) makes the manipulation/malfunction
  call, which becomes the final answer. A Stage 1 mistake on a true volatility
  incident is therefore forced through Stage 2, which can only answer
  manipulation-or-malfunction — guaranteed wrong for that incident, exactly the real
  cost a deployed two-stage pipeline would pay.
- **Calibration posterior**: combined via the chain rule, `P(manipulation) =
  P(oracle failure) × P(manipulation | oracle failure)`, etc., so the three
  probabilities sum to 1. A methodological note, flagged rather than buried: an
  earlier version of this script computed Stage 2's posterior only when Stage 1's
  hard decision was "oracle failure", and hard-zeroed manipulation/malfunction to
  exactly 0.0 whenever Stage 1 said "volatility" — this manufactured `log(0)`
  penalties even when Stage 1's own call was a near-coin-flip (stETH/ETH: 53%/47%,
  nowhere near confident), overstating how bad the architecture's calibration is as
  an artifact of that implementation choice, not a real property of the two-stage
  approach. Fixed to always compute Stage 2's posterior (using the same training-fold
  exclusion rules) for calibration purposes, regardless of Stage 1's hard decision —
  the discrete final answer still follows the hard gate exactly as specified.

## 2. Headline comparison

| Metric | Flat 3-class BN | Two-stage BN | Verdict |
|---|---|---|---|
| Accuracy | 87% (39/45) | **75.6% (34/45)** | Worse (−11.4pp) |
| Brier score | 0.199 | **0.288** | Worse |
| Log-loss | 0.367 | **0.546** | Worse |
| ECE | 0.058 | **0.082** | Worse |

(Two-stage accuracy counts a genuine Stage 2 fit failure — see §4 — as a miss, the
fair, conservative denominator of 45; excluding it gives 34/44 = 77.3%, still clearly
worse.)

## 3. Why it's worse: Stage 2 loses more from a tiny training set than it gains from specialization

This is the central, most concretely evidenced finding, not a vague impression.
**Restricting to the exact same 13 incidents both architectures keep within
manipulation/malfunction space** (i.e., excluding the 2 malfunction incidents both
architectures separately misroute toward volatility — see §4):

| | Correct | Total | Accuracy |
|---|---|---|---|
| **Flat BN**, manip-vs-malfunction implicit in its single 3-way fit | 12 | 13 | **92.3%** |
| **Two-stage's dedicated Stage 2** classifier | 8 | 13 | **61.5%** |

Same 13 incidents (all 12 manipulation + FTT/USD), same underlying features, same BN
structure — the only difference is that the flat model's manipulation/malfunction
discrimination benefits from being fit jointly with all 45 incidents' worth of
evidence in each LOOCV fold (44 training points), while Stage 2 is fit on only the
oracle-failure subset (13–15 training points depending on the fold). **Specialization
lost more from the drastically smaller effective training set than it gained from
only having to make one distinction instead of two.** This is the single clearest
answer to "is a two-stage design better because the sub-problems are individually
easier" — no, not when the price of narrowing the training set outweighs the benefit
of narrowing the question, and at this dataset size it does.

## 4. Where the errors concentrate

**Stage 1 (86.7%, 39/45 — 6 errors):**
- **2 malfunction incidents routed to "volatility"**: stETH/ETH (a near-coin-flip
  53%/47% call) and UST/USD (80%/20%). Once routed here, they can never be
  recovered — Stage 2 is never consulted for them.
- **4 volatility incidents routed to "oracle failure"**: March 2024 cycle-high rally,
  Dec 4 2021 selloff, Nov 21 2025 selloff, June 6 2026 selloff. All 4 are then FORCED
  through Stage 2, which necessarily answers manipulation-or-malfunction —
  guaranteed end-to-end errors. This is hard-gating's specific cost: a flat model
  wrongly calling one of these "manipulation" is one error; a two-stage pipeline
  making the same routing mistake is *also* one error, but structurally cannot do
  otherwise once Stage 1 commits — there's no path back to "volatility" downstream.

**Stage 2 (61.5%, 8/13 on the incidents Stage 1 actually routes to it):**
- Wrong on Cream Finance, MonoX Finance, CurveLlamaLend (all true manipulation, called
  malfunction) and FTT/USD (true malfunction, called manipulation) — 4 genuine
  misses, plus MEVBOTa47b's fit failure (below) counted as a 5th.
- Also inherits the 4 forced-through volatility incidents from Stage 1's routing
  errors (March 2024 rally, Dec 2021 selloff, Nov 2025 selloff, June 2026 selloff),
  which aren't "Stage 2 mistakes" in the discrimination sense — Stage 2 is answering
  a question (manipulation or malfunction?) that shouldn't have been asked of these
  incidents at all.

**A genuine Stage 2 fit failure, not glossed over**: when MEVBOTa47b is held out,
Stage 2's training set (the other 14 oracle-failure incidents) has **zero** rows with
`cross_venue_spread` observed for *either* class — MEVBOTa47b is the only
manipulation incident with that feature populated at all (it uses the standard
WETH/USDC V3 pool directly), and malfunction never has it. The `cross_venue_spread_d`
CPD has no complete training rows in this specific fold, so the fit fails outright.
This is a direct, mechanistic consequence of feature sparsity being concentrated in a
now much-smaller training set — the flat model never hits this because it always has
44 training incidents to draw from regardless of which class-conditional CPD is being
estimated.

## 5. Malfunction n=3 — explicit, and it drives most of what's above

**Malfunction's end-to-end recall is 0/3 in both the flat model and the two-stage
pipeline** — the same headline outcome, but reached differently:
- **Flat model**: 2 of 3 (stETH, UST) get called volatility directly; 1 (FTT) gets
  called manipulation directly. One shot, three ways to be wrong, all three occur.
- **Two-stage**: the *same* 2 (stETH, UST) get misrouted by Stage 1 before Stage 2 is
  ever consulted; FTT reaches Stage 2 and is called manipulation there.

This convergence on the *same two* incidents in both architectures is not a two-stage
artifact — it's the same root cause already documented in `reports/cohesion_findings.md`
(the BN's median-split discretization of `heartbeat_elapsed` erasing the magnitude gap
between "moderately stale" and "extremely stale"), inherited unchanged by Stage 1's
oracle-failure/volatility BN since it uses the identical discretization mechanism.

**Stage 2 leans on the tiny malfunction class more heavily than the flat model does,
structurally, not just in degree**: every LOOCV fold fits Stage 2's malfunction-side
CPDs from only 2–3 malfunction incidents (vs. the flat model's same 2–3, but embedded
in a 44-point joint fit that borrows statistical strength — via BDeu smoothing and
shared structure — from the other 41 incidents' worth of data on every node except the
`label_d`-conditional ones). §3's 92.3%-vs-61.5% comparison is the direct, measured
consequence of this. Any future change to this dataset's malfunction count (phase 2
scaling, if it ever adds malfunction incidents) would likely benefit Stage 2's
accuracy more than it changes the flat model's, precisely because Stage 2 is more
exposed to this specific class's sample size today.

## 6. Bottom line

The motivating hypothesis — that separating "is the oracle wrong at all" from "which
kind of wrong" should help, because the first question is easy (~90%, per
`reports/two_class_analysis.md`) and the second is hard — is directionally correct
about *where the difficulty lives*, but **the fix doesn't follow from correctly
diagnosing the problem**. Isolating the hard sub-problem (manipulation vs.
malfunction) into its own classifier also isolates it into a much smaller training
set, and at n=45 that costs more than the specialization gains. Stage 1's own
accuracy (86.7%) is close to but not better than the flat model's already-decent
performance on the same distinction (the flat model, restricted to the same
oracle-failure-vs-not question implicitly, gets the same 2 malfunction incidents
wrong that Stage 1 does) — so Stage 1 isn't adding value the flat model didn't
already have, while Stage 2 measurably subtracts value relative to what the flat
model's joint fit achieves on the identical sub-question. Net effect: worse, not
better, not merely "different with tradeoffs."

This isn't an argument against ever trying hierarchical decomposition — it's an
argument that this dataset is currently too small for the specific way this pipeline
splits its training data. Revisiting this once the dataset is substantially larger
(so Stage 2's effective training set is no longer the bottleneck) is a reasonable
target for a future phase, not this one.
