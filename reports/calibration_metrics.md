# Calibration metrics: ECE and log-loss, alongside Brier score

Evaluation only — no feature or model-structure change. Computed via `src/calibration_metrics.py`,
which imports and calls `loocv_validation.py`'s `loocv_naive_bayes()` / `loocv_bayesian_network()`
unmodified (same LOOCV posteriors already used for the existing Brier-score reporting), on the
current 45-incident dataset (12 manipulation, 3 malfunction, 30 volatility).

## Headline: all three metrics agree, and they don't agree by the same margin

| Metric | Naive Bayes | Bayesian Network | BN as % of NB |
|---|---|---|---|
| Brier score | 0.324 | 0.199 | 61% |
| **ECE** | **0.166** | **0.058** | 35% |
| **Log-loss** | **2.576** | **0.367** | 14% |

**Yes, this confirms the Bayesian network is better-calibrated than Naive Bayes** — on every
metric computed, in both this evaluation and the pre-existing Brier-score comparison. But the
three metrics disagree sharply on *how much* better: Brier says ~1.6×, ECE says ~2.9×, log-loss
says ~7×. This spread is itself informative, not noise to average away — see below for why.

## Why log-loss shows the largest gap: it punishes confident wrong answers exponentially harder

Log-loss is `-log(p_true_class)`, so a wrong prediction where the true class was assigned a
posterior near zero contributes a very large penalty — Brier's squared-error penalty for the same
mistake is bounded (at most 2 for a maximally wrong 3-class call), but log-loss is unbounded as
p_true → 0. Naive Bayes' calibration problem, already documented elsewhere in this project, is
exactly this: it doesn't just get some calls wrong, it gets them wrong with the true class's
posterior often collapsing to (or numerically underflowing to) near-zero. Log-loss is the metric
most sensitive to that specific failure mode, which is why it shows the starkest gap.

## ECE bucket breakdown — the actual "is an 80%-confidence call right 80% of the time" test

Same 4 confidence buckets `loocv_validation.py`'s own calibration reporting already uses
(>90%, 70–90%, 50–70%, <50%) — not equal-width bins; kept for consistency with the rest of this
project's calibration reporting and because it keeps bin populations as large as n=45 allows (see
the small-sample caveat below for what a textbook equal-width binning would look like instead).

**Naive Bayes:**

| Bucket | n | Avg. confidence | Actual accuracy | Gap |
|---|---|---|---|---|
| very high (>90%) | 41 | 0.999 | 0.854 | 0.145 |
| high (70–90%) | 0 | — | — | — |
| medium (50–70%) | 4 | 0.630 | 0.250 | 0.380 |
| low (<50%) | 0 | — | — | — |

**ECE = 0.166.** Two things stand out beyond the headline number. First, **NB never lands in the
70–90% bucket at all** — 41 of 45 held-out predictions are >90% confident, the remaining 4 are in
the 50–70% range, and nothing in between. This is the degenerate-confidence pattern already
documented elsewhere in this project made concrete: NB doesn't express graduated uncertainty, it's
either nearly certain or it's a coin-flip-ish outlier. Second, the medium bucket is badly
miscalibrated on its own terms — 63.0% average confidence against 25.0% actual accuracy, a 38-point
gap, on the 4 incidents where NB doesn't collapse to near-100%.

**Bayesian network:**

| Bucket | n | Avg. confidence | Actual accuracy | Gap |
|---|---|---|---|---|
| very high (>90%) | 25 | 0.972 | 1.000 | 0.028 |
| high (70–90%) | 13 | 0.791 | 0.846 | 0.055 |
| medium (50–70%) | 5 | 0.607 | 0.400 | 0.207 |
| low (<50%) | 2 | 0.417 | 0.500 | 0.083 |

**ECE = 0.058.** All 4 buckets are populated (unlike NB), and the top two buckets — covering
38 of 45 incidents — are both well-calibrated (gaps of 0.028 and 0.055). The medium bucket is the
weak point (0.207 gap, overconfident: 60.7% average confidence vs. only 40% actual accuracy) —
this is the same n=5 zone where malfunction's fragility and the volatility/manipulation boundary
cases concentrate, not a new finding on its own.

## Honest small-sample caveat, made concrete rather than just asserted

At n=45, ECE is inherently noisy, and this is easy to demonstrate directly rather than take on
faith: a textbook **equal-width 10-bin** ECE (instead of the 4 decision-relevant buckets used
above) would produce these per-bin counts:

- **Naive Bayes**: `[0, 0, 0, 1, 2, 1, 0, 0, 0, 41]` — 9 of 10 bins have ≤2 points; one bin alone
  (the top one) holds 41 of the 45 incidents. A per-bin accuracy computed from n=1 or n=2 is not a
  meaningful estimate of anything.
- **Bayesian network**: `[1, 1, 1, 1, 2, 5, 3, 4, 5, 22]` — better distributed, but still 5 of 10
  bins have ≤2 points.

This is why the 4-bucket scheme (already used elsewhere in this project) is reported as the
headline ECE rather than a finer equal-width binning — not because it's the only valid choice, but
because it's the coarsest reasonable one that still keeps most buckets above single digits at this
n. **Treat the exact ECE values (0.166 / 0.058) as directionally reliable, not precisely estimated**
— a handful of incidents landing in different buckets would move these numbers by several hundredths,
same caveat already attached to the Brier-score comparison in `reports/loocv_45_incidents.md`.

## Bottom line

All three calibration metrics — Brier, ECE, and log-loss — agree: **the Bayesian network is
better-calibrated than Naive Bayes**, at both the original n=20 and the current n=45. Log-loss
shows this most dramatically because it's the metric most sensitive to NB's specific failure mode
(confidently-wrong posteriors collapsing the true class's probability near zero), while ECE and
Brier show smaller but still clear and directionally consistent gaps. None of the three should be
read as a precise, stable estimate at this sample size — the *direction* of the finding is solid
across three different mathematical definitions of calibration; the *exact magnitude* of BN's
advantage is not.
