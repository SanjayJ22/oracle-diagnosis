# LOOCV re-evaluation at 45 incidents (phase 1 scaling)

Evaluation only — no feature or model-structure change. Re-ran `src/models.py` (deterministic
baseline, in-sample) and `src/loocv_validation.py` (Naive Bayes, Bayesian network, both under
leave-one-incident-out) against the current `features.parquet`, unmodified. Dataset: 12
manipulation, 3 malfunction, 30 volatility (45 total), vs. the prior 5/3/12 (20 total).

## Headline comparison

| Metric | 20 incidents | 45 incidents | Change |
|---|---|---|---|
| Deterministic accuracy | 55% (11/20) | **71% (32/45)** | +16pp — see caveat below |
| NB LOOCV accuracy | 75% (15/20) | **80% (36/45)** | +5pp |
| BN LOOCV accuracy | 85% (17/20) | **87% (39/45)** | +2pp |
| NB Brier score | 0.500 | **0.324** | improved |
| BN Brier score | 0.267 | **0.199** | improved |

**Both probabilistic models improved on both accuracy and calibration.** The deterministic
baseline's jump is real but not what it looks like — see below.

## Per-class recall

| Class | Model | 20 incidents | 45 incidents |
|---|---|---|---|
| Manipulation | NB | 80% (4/5) | **67% (8/12)** |
| Manipulation | BN | 100% (5/5) | **100% (12/12)** |
| Malfunction | NB | 67% (2/3) | **33% (1/3)** |
| Malfunction | BN | 33% (1/3) | **0% (0/3)** |
| Volatility | NB | 75% (9/12) | **90% (27/30)** |
| Volatility | BN | 92% (11/12) | **90% (27/30)** |

## Does the deterministic baseline's 55%→71% mean simple rules work fine at scale? No.

Checked, not assumed: the rule's accuracy gain is a **compositional artifact of how the new
volatility incidents were found**, not evidence the rule generalizes better. The original 12
volatility incidents were hand-picked "famous crashes" (up to -52%); the 18 new ones came from
automated 10%+ threshold sampling and are systematically smaller, calmer moves (11%-35%). Smaller
moves produce smaller `|reserve_skew|`, which crosses the rule's 5% "call it manipulation"
threshold far less often — the gap is large: **7 of the original 12 volatility incidents (58%)
are wrongly called manipulation; only 1 of the 18 new ones (5.6%)**. The rule didn't get smarter;
the new data happens to sit almost entirely below its threshold. This is worth flagging clearly
so the 71% number isn't read as "the deterministic approach holds up at scale" — it's almost
entirely explained by the volatility incidents' magnitude distribution, not the rule's
discriminating power. (The one new false positive, Aug 19 2026 rally at reserve_skew=+5.67%,
barely clears the 5% line.)

## Does manipulation stay cleanly separable? Yes — the strongest result here.

**BN's manipulation recall is 100% at both n=5 and n=12**, now across a much more mechanistically
diverse set: MonoX's custom AMM, Conic/Zunami/ResupplyFi's Curve-pool and vault donation attacks,
CompoundUni's Uniswap V3 pool, MEVBOTa47b's plain WETH/USDC pool. Manipulation's **precision** also
improved, not just held steady: 62.5% (5/8 predicted-manipulation calls correct) at n=20 → **75%
(12/16)** at n=45. This is a genuine strengthening, not a coincidence of a small sample — the
class holds together under LOOCV even as its internal diversity roughly doubled.

**NB tells a different story**: manipulation recall *fell* to 67% (8/12), losing Cream Finance,
Inverse Finance, MEVBOTa47b, and Conic Finance 02 — the latter two are phase-1 additions NB gets
wrong with 99-100% (false) confidence, the same overconfidence pattern already documented for
this model. NB's Gaussian-independence assumption appears to strain more, not less, as
manipulation's mechanisms diversify — consistent with it never having been the more suitable
model for this class (BN's structure already captured manipulation better at n=5 too).

## Does BN's calibration advantage over NB persist? Yes, though the gap narrows in relative terms.

Both models' calibration improved in absolute terms — likely because more data per class
means less extreme (near-zero) fitted variances, which were driving NB's original near-total
overconfidence. NB's per-class mean entropy went from ~0.00-0.01 (fully degenerate) to 0.02-0.15
(still very low, no longer literally zero). But BN remains unambiguously better calibrated:

| | Brier | BN as % of NB's Brier |
|---|---|---|
| 20 incidents | NB 0.500, BN 0.267 | 53% |
| 45 incidents | NB 0.324, BN 0.199 | 61% |

BN is still clearly the better-calibrated model, but the relative gap narrowed slightly (53%→61%)
because NB improved somewhat faster in absolute terms. Read this as "the advantage holds, and its
size is itself uncertain at this n" rather than "the advantage is shrinking" — one class flip in
either model moves these ratios by several points at this scale.

## Malfunction: n=3 caveat is not decoration, it's load-bearing here

**BN's malfunction recall went from 1/3 to 0/3.** UST/USD — the single correct call BN made at
n=20, itself only at 43-51% confidence, essentially a coin flip that happened to land right — now
flips to wrong (69% confidence, still far from decisive) as the model refits on more data.
Malfunction's mean entropy remains the highest of any class in both runs (0.92 → 0.82) — still
the least confidently classified class, unchanged in kind. **This is not a finding that
malfunction "got worse" at scale — it's the same n=3 class, still too small to support any
LOOCV number meaning something more precise than "somewhere between clearly-hard and
coin-flip."** One incident's classification flipping moves this recall by 33 percentage points.
Phase 1's malfunction search (see `reports/malfunction_candidates_phase1.md`) added zero new
malfunction incidents, so this class's fundamental data-scarcity problem is unchanged and remains
the single biggest limitation of the whole model, at either dataset size.

## New confusions surfaced only by the larger dataset

Some of the new volatility incidents (found via automated sampling, not hand-picked) are
genuinely harder to separate from manipulation than the original 12 — a sign the scaling effort
surfaced real ambiguous cases, not just more of the same:
- **Dec 4 2021 selloff** and **Nov 21 2025 selloff**: new BN errors (called manipulation).
- **June 6 2026 selloff**: low-confidence for both models (45-60%), effectively a toss-up.

This is consistent with `reports/cohesion_findings.md`'s original finding that calm, low-realized-
volatility market moves resemble manipulation's signature — the automated sampler, unlike a
hand-picked "famous crashes" list, naturally includes more of these calmer, more ambiguous moves.

## Bottom line

- **Both probabilistic models improved on accuracy and calibration** at 45 incidents — a
  reassuring sign the original n=20 findings weren't a small-sample fluke in the favorable
  direction.
- **Manipulation separability strengthened for BN** (recall steady at 100%, precision up), the
  single cleanest result in this re-evaluation.
- **BN's calibration edge over NB persists**, though the precise size of that edge should be
  treated as uncertain at this n, not as a stable, well-estimated ratio.
- **Malfunction remains the dataset's central limitation**, unchanged by this phase — n=3 is a
  count too small for any LOOCV metric on this class to mean much more than "clearly the hardest
  class," and phase 1 did not (and structurally could not, per the malfunction search's own
  findings) fix this.
- **The deterministic baseline's improvement is a compositional artifact**, not evidence simple
  thresholds hold up — flagged explicitly so it isn't misread.
