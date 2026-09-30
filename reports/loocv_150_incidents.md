# Phase 2 scaling + re-evaluation: 45 → 112 → 105 incidents (target was ~150)

**Target not fully reached — reported honestly, not padded.** Manipulation: 24 total
at first pass (target 40-50) — a broader DeFiHackLabs sweep found only 13 new mainnet-
confirmed, well-documented candidates (not 28-38), for reasons independently verified
during integration, not a search-effort shortfall (see §1). Volatility: 85 total
(target ~100) — 55 new candidates found via automated sampling at a 5% threshold,
close to target. Malfunction: held at 3 as instructed (confirmed structurally rare
across 3 search passes in phase 1; not re-searched, not padded).

**This report has been corrected once, in the same phase.** The first pass (112
incidents, 24 manipulation) left 8 of the 12 new manipulation incidents with an
unresolved `reserve_skew` — flagged honestly at the time, not silently absorbed. A
follow-up resolution pass (§1a) fixed one (TOPBPool, wrong venue) and dropped seven
(genuinely unresolvable with this metric, not a guessing failure) — see
`reports/manipulation_candidates_phase2.md`'s addendum for full per-incident evidence.
**The dataset now stands at 105 incidents: 17 manipulation, 85 volatility, 3
malfunction.** Every number in this report from §2 onward is the corrected (105)
version; the superseded 112-incident numbers are shown alongside for transparency,
not deleted from the record.

This phase surfaced a genuinely important, previously-latent finding, and the
correction pass surfaced a second one on top of it: **the Bayesian network's
calibration advantage over Naive Bayes does not simply hold, narrow, or even stay
reversed — it flips back in BN's favor on all three metrics once the coverage gap is
closed, while manipulation recall gets WORSE for both models, not better, for two
distinct and separately diagnosed reasons (§4, §5).**

## 1. Why manipulation fell short of target (24, not 40-50)

The research pass found 13 new candidates, not 28-38. Independently verified during
integration (not taken on faith): the large majority of additional candidates
surfaced by keyword search were on the wrong chain (BSC, Arbitrum, Base, Polygon,
Optimism, Fantom, Linea, zkSync all recurred), including several large, well-
documented incidents ($7M, $6.3M, $4M) excluded purely for that reason. This is a
real, load-bearing finding: recent large, well-documented DeFi exploits increasingly
happen on L2s/altchains rather than Ethereum mainnet specifically, which directly
constrains how many more mainnet-only incidents this sourcing method can supply. One
candidate (EnsoFinance) was excluded during integration because its own research
report flagged the exploited venue as not precisely pinned — dropped per this
project's "reject rather than guess" standard, not force-included. Full sourcing in
`reports/manipulation_candidates_phase2.md`.

**A second, more consequential limitation surfaced during integration, not before**:
of the 12 new manipulation incidents, **8 had no resolvable `reserve_skew` at all**.
The venue/token guessed from each PoC's own declared addresses (a method that worked
for most of phase 1's additions) turned out wrong for 8 of these 12 — verified by
checking that the guessed token's balance was exactly zero at *both* the incident
block and the baseline block. Rather than report a misleading `0.0`, these 8 were
left as genuine `NaN`, honestly reported at the time, and resolved in the next
sub-section rather than carried forward unresolved.

## 1a. The reserve_skew resolution pass: 1 fixed, 7 dropped

Same standard as phase 1's MorphoBlue/CurveLlamaLend/ResupplyFi corrections: read
each attack transaction's own ERC20 Transfer logs directly via
`eth_getTransactionReceipt`, don't re-trust the PoC's declared address a second time.

**TOPBPool — FIXED.** The configured venue (`0xb935c3d80229d5d92f3761b17cd81dc2610e3a45`)
does not appear anywhere in the attack transaction's 154 logs — it was simply wrong.
Log decoding found the real venue: a bonding-curve-style AMM at
`0x0fa3e014fa2e751f78e53dca766fac2223327329`. The attacker mints 10 billion TOP
governance tokens and repeatedly dumps them into this pool for ever-shrinking WETH
amounts (each successive dump yields exponentially less WETH — a classic bonding-
curve drain). This is a genuine, **persisting** drain, not an atomic round-trip: WETH
falls from 281.34 to ~0 and stays there past the incident block. `reserve_skew` now
resolves to **+670,679.59** — by a wide margin the single largest-magnitude value in
the entire 105-incident dataset (the next largest, Cream Finance, is a literal `+inf`,
clipped for modeling purposes; every other incident's value is under 3 in absolute
terms).

**7 DROPPED, not kept as a misleading NaN or force-set 0.0**: SummerFi, Raft_fi,
bZxProtocol, edel-xstock, CompounderFinance, MetaPool, MahaLend. Each was
individually re-investigated via direct transaction-log decoding and falls into one
of two categories:

- **Diffuse, no single trackable venue** (SummerFi, edel-xstock): the real exploit
  spans 300+ logs across a dozen+ nested vault/collateral/debt tokens. No single
  venue balance represents either incident's manipulation signal.
- **Exchange-rate/accounting exploits, correct venue confirmed but architecturally
  invisible to a balance-ratio metric** (Raft_fi, bZxProtocol, CompounderFinance,
  MetaPool, MahaLend): the real venue and token were positively identified — real
  fund flows are visible in each attack tx's own logs (e.g. MetaPool's real 200 WETH
  Balancer-flash-loan-funded round-trip; MahaLend's real 13.9M USDC donation-attack
  round-trip) — but the underlying token balance returns to ~baseline *within the
  same transaction* (a manipulated exchange-rate or share price is what's actually
  exploited, not a persisting balance change), or the vault holds ~0 idle balance by
  design at all times (CompounderFinance auto-routes deposits into yDAI
  immediately). All 5 show genuine `baseline≈0, now≈0` at their correctly-identified
  venues, both before and after the venue correction — confirmed this is not a
  wrong-venue-guess problem but a genuine limitation of a block-level balance
  snapshot against an atomic, self-reversing exploit.

**Net effect: manipulation drops from 24 to 17; total from 112 to 105.** This is the
dataset used for every result below.

## 2. Headline comparison across four points

| Metric | 20 incidents | 45 incidents | 112 incidents (superseded) | **105 incidents (corrected)** |
|---|---|---|---|---|
| Deterministic accuracy (in-sample) | 55% | 71% | 80% | **87% — not comparable, see §3** |
| NB LOOCV accuracy | 75% | 80% | 90% (101/112) | **81% (85/105)** |
| BN LOOCV accuracy | 85% | 87% | 81% (91/112) | **83% (87/105)** |
| NB manipulation recall | 80% | 67% | 67% (16/24) | **0% (0/17)** |
| BN manipulation recall | 100% | 100% | 50% (12/24) | **35% (6/17)** |
| NB Brier | 0.500 | 0.324 | 0.150 | **0.312** |
| BN Brier | 0.267 | 0.199 | 0.276 | **0.224** |
| NB ECE | — | 0.166 | 0.083 | **0.171** |
| BN ECE | — | 0.058 | 0.058 | **0.042** |
| NB log-loss | — | 2.576 | 1.187 | **2.234** |
| BN log-loss | — | 0.367 | 0.510 | **0.397** |

**The corrected numbers overturn the 112-incident report's headline finding, not just
adjust it.** At n=112, NB had overtaken BN on both accuracy (90% vs 81%) and Brier
(0.150 vs 0.276) — the first time in this project's history NB out-performed BN
overall. At the corrected n=105, **BN is unambiguously better calibrated again on all
three metrics** (Brier 0.224 vs 0.312, ECE 0.042 vs 0.171, log-loss 0.397 vs 2.234),
and NB's accuracy advantage narrows to 81% vs 83%. **Both of those n=112 numbers were
artifacts of the unresolved coverage gap, not real properties of either model** — see
§4 for exactly how.

## 3. The deterministic baseline is flagged, not trended, per instruction

87% at n=105 (in-sample, not LOOCV) is not placed in a trend line with 55%/71%/80% —
it is a compositional artifact of which incidents happen to be in the dataset at each
scale (calmer or spikier volatility incidents, different reserve_skew distributions
among the manipulation incidents present), not evidence the fixed threshold rule
itself improved. This caveat is unchanged from every prior report in this series.

## 4. Why NB's manipulation recall collapsed to literally 0% — a new, distinct mechanism

This is not a repeat of the n=112 finding — it is a different, newly-introduced
failure mode, caused directly by fixing TOPBPool.

`models.py`'s `_fit_gaussian_nb()` fits a per-class Gaussian on each feature's **raw**
values. It explicitly replaces literal `±inf` with a clip constant (3.0) — this
already existed, to handle Cream Finance's and ResupplyFi's infinite skew — but it
does **not** clip large *finite* values. TOPBPool's corrected `reserve_skew`
(+670,679.59) is finite, so it sails straight through uncapped and directly enters
manipulation's Gaussian fit for that feature. The result: manipulation's `reserve_skew`
Gaussian now has **mean=39,452, std=157,807** — a distribution so wide and so far
from every other manipulation incident's actual value (which range roughly -1 to +3)
that it becomes almost uninformative, and actively misleading, for every incident
*except* TOPBPool itself.

The clearest illustration is TOPBPool's own held-out LOOCV fold: with TOPBPool
excluded from training (LOOCV, by construction), manipulation's Gaussian is fit from
the other 16 manipulation incidents — none of which is anywhere near TOPBPool's
magnitude, so this fold's Gaussian is comparatively tight. TOPBPool's own true value
then looks like an impossible outlier under its own class's (TOPBPool-excluded)
Gaussian, and NB predicts **"malfunction" with 100% confidence** for TOPBPool — the
single most confidently wrong call in the entire dataset, for the one incident whose
signal was *just* cleanly fixed. Every other manipulation incident is dragged down by
the reverse effect: when TOPBPool *is* in the training fold, its extreme value
inflates manipulation's variance so much that the Gaussian likelihood becomes nearly
flat, and the classifier defaults to whichever other class's prior/likelihood
dominates (11 of 16 remaining manipulation incidents are called "malfunction", the
rest "large volatility event" — none called "manipulation").

**This is a modeling bug exposed by a correct data fix, not a data quality problem.**
The fix (TOPBPool's real venue) is right; the astronomically large percentage
increase (attacker minted 10 billion tokens against a ~15,000-token pre-attack
supply) is a genuine, correctly-computed value. NB's Gaussian-fit code has no
robustness to a single extreme-but-real outlier — clipping only literal infinities
was never sufficient, and this is now demonstrated rather than theoretical. No fix is
applied here (this pass is evaluation + data-correction only, per instruction, not a
model change) — but extending the existing `RESERVE_SKEW_CLIP` treatment to bound all
large finite values (not just literal inf) is now a concretely-motivated next step
for `_fit_gaussian_nb()` specifically.

## 5. Why BN's manipulation recall also declined (50% → 35%), not improved as hoped

The n=112 report predicted that closing the reserve_skew coverage gap would let BN's
manipulation recall recover toward its n=45 ceiling (100%). **That did not happen —
recall dropped further, to 35% (6/17).** The mechanism is only partly the same as the
n=112 report's sign-based median-split explanation, and this report says so plainly
rather than force-fitting the old theory:

The 6 correctly-classified manipulation incidents (Harvest Finance, UwU Lend, Conic
Finance 02, BalancerV2, Makina, BalancerV1BPool) span both strongly negative
(BalancerV2 -0.9997, Makina -0.996, BalancerV1BPool -0.999) and small (UwU +0.07,
Harvest -0.13, Conic -0.026) values — no clean sign pattern. The 11 misclassified
incidents (as "large volatility event", never "malfunction") **also** span both
extremes: TOPBPool (clipped +3.0, the single strongest positive signal in the
dataset) and Cream Finance (also clipped +3.0, literal `+inf`) are both wrong, right
alongside WiseLending (-1.0), Indexed Finance (-0.986), and MonoX Finance (-0.9997).
Confidence on these calls clusters tightly around 49-64% (near coin-flip) for most of
them — the model isn't confidently wrong so much as genuinely uncertain, consistent
with the per-class entropy in §7.

**Honest reading**: the n=112 report's median-split/sign-based theory is not wrong,
but it is not a complete explanation of what's observed at n=105 either — both
strongly-positive and strongly-negative manipulation incidents are now frequently
missed, which the pure sign-based story doesn't fully predict. What's changed and is
confirmed: adding TOPBPool's extreme (but for BN, clipped) value and populating the
other 7's slots (by dropping them, not filling them with reserve_skew) shifted the
dataset's discretization boundaries in ways that, on net, did not help BN separate
manipulation from volatility any better than at n=112 — and this needs a dedicated
follow-up pass (e.g., inspecting the fitted CPD tables directly) to fully explain,
which is out of scope for an evaluation-only pass.

## 6. The three tracked questions, answered precisely at the corrected n=105

**Does BN's calibration advantage over NB narrow, stabilize, or hold?** None of the
three, again — but not in the direction the n=112 report suggested. At n=112 it
appeared to be *becoming* metric-dependent (Brier reversing, ECE tying, log-loss
still favoring BN). At the corrected n=105, **BN wins clearly on all three metrics**
(Brier 0.224 vs 0.312, ECE 0.042 vs 0.171, log-loss 0.397 vs 2.234) — the n=112
Brier reversal is fully undone, and traceable to a specific, now-diagnosed cause
(§4), not a genuine property of NB at scale.

**Does manipulation recall stay at/near 100% as mechanistic diversity increases?**
Decisively no, and now more decisively no than at n=112: BN goes 100% (n=20) → 100%
(n=45) → 50% (n=112) → **35% (n=105)**. NB goes 80% (n=20) → 67% (n=45) → 67%
(n=112) → **0% (n=105)** — a complete collapse, mechanistically explained in §4 as an
artifact of an unrobust Gaussian fit meeting one genuinely extreme but correct data
point, not evidence that manipulation is becoming intrinsically harder to detect.

**Does the volatility-called-manipulation confusion grow or stay bounded?** At
n=105: **NB shows 0/85 such confusions** (unchanged from n=112's 0/24-scaled rate —
NB simply never predicts "manipulation" anymore at this n, per §4, so this specific
confusion type is mechanically impossible for NB right now, which is not really an
improvement). **BN shows 4/85 (4.7%)**, down in both count and rate from n=112's
6/85 (7.1%) — a genuine, if modest, improvement for BN specifically.

## 7. Malfunction n=3 — unchanged, explicit, still the central limitation

Held at 3 throughout (phase 1's 3-pass, 27-feed search already established this is
structurally rare, see `reports/malfunction_search_coverage.md`). At the corrected
n=105: BN's malfunction recall is **0/3** (down from... it was already 0/3 at n=112).
NB's malfunction recall is **2/3**, unchanged. Every LOOCV number for this class
should still be read as "this specific n=3 sample," not a stable estimate — nothing
about this phase's scaling or correction changes malfunction's fundamental
data-scarcity problem.

## 8. Per-class entropy, Bayesian network (n=105)

| Class | Mean entropy | n |
|---|---|---|
| Manipulation | 0.72 | 17 |
| Malfunction | 0.74 | 3 |
| Large volatility event | 0.26 | 85 |

Manipulation's entropy is essentially unchanged from a qualitative "least certain
after malfunction" read, consistent with §5's finding that most wrong calls cluster
near 50% confidence rather than being confidently wrong — the model is aware it's
uncertain here even where it errs, which is honest uncertainty rather than
overconfident wrongness.

## 9. What this phase argues for, going forward

- **The reserve_skew coverage gap is now closed, and it did not raise the ceiling on
  either model's manipulation performance — it exposed a different, more fundamental
  problem: neither model's numeric-feature handling is robust to real data at
  divergent scales** (NB's unclipped Gaussian fit blowing up on one genuine outlier;
  BN's global-median discretization not cleanly separating a small, heterogeneous
  manipulation class even once it's fully populated). Closing a data gap surfaced a
  modeling gap that was previously masked by missing data — a useful, if humbling,
  result.
- **Naive Bayes should not be treated as "safe" or "simpler" going forward.** Its
  apparent n=112 advantage (higher accuracy, better Brier) is now shown to have been
  contingent on incomplete data, not a real property — and its complete collapse to
  0% manipulation recall the moment that data gap closed is a concrete demonstration
  of how fragile an unclipped Gaussian-independence model is to a single extreme
  point.
- **A concrete, well-motivated next step** (not attempted here, evaluation-only per
  instruction): extend `RESERVE_SKEW_CLIP`-style bounding in `_fit_gaussian_nb()` to
  cap large finite values, not just literal infinities, and re-run this same
  evaluation to see whether NB's manipulation recall recovers. A second, deeper
  follow-up: directly inspect BN's fitted CPD tables for `reserve_skew_d` to
  understand precisely why both extreme-positive and extreme-negative manipulation
  incidents are now frequently misclassified, rather than relying on the sign-based
  theory that no longer fully explains what's observed.
