# Cohesion Findings

Read-only. Uses only the existing LOOCV predictions (`src/loocv_validation.py`) and the
existing trajectory writeup (`reports/temporal_trajectories.md`) — no feature or model
changes.

## 1. Bayesian network confusion structure (LOOCV)

Confusion matrix (rows = true, columns = predicted, 20 incidents):

| true \ pred | manipulation | malfunction | large volatility event |
|---|---|---|---|
| manipulation | 5 | 0 | 0 |
| malfunction | 2 | 1 | 0 |
| large volatility event | 1 | 1 | 10 |

**Manipulation has 100% recall but only 62.5% precision (5/8 predicted-manipulation calls
are actually manipulation)** — it behaves as an attractor for uncertain cases rather than a
class that gets missed. All 3 errors in the table land on manipulation or malfunction; none
land on volatility from a non-volatility row.

**Malfunction blurs with manipulation, not volatility.** Both malfunction errors (stETH/ETH,
FTT/USD) are called manipulation; neither is called volatility. Mechanism: the BN discretizes
`heartbeat_elapsed` at a single learned median (265s). Every manipulation incident
(494–3,489s) and every malfunction incident (950–86,428s) falls on the same "high" side of
that split — the binarization erases the very magnitude gap (hundreds of seconds vs tens of
thousands) that would separate "moderately stale" from "extremely stale." With that signal
flattened, and FTT having only `heartbeat_elapsed` and `congestion` observed (its other 4
features are missing), its posterior comes out nearly uniform (53%/24%/23%,
manipulation/malfunction/volatility) — entropy 0.93, the single highest in the dataset. This
is a near-coin-flip that landed wrong, not a confident wrong call. stETH's error is the same
shape (59%/23%/19%, entropy 0.88).

**The two rally-labeled volatility incidents are the model's most manipulation-suspicious
volatility calls, and one of them tips over.** March 2024's posterior is 85% manipulation
(entropy 0.43 — a genuinely confident wrong call, unlike FTT/stETH above); March 2023 stays
correctly classified but still carries an elevated 22% manipulation posterior, the second
highest of any volatility incident (typical crash days: 0–2%). Grounded cause: both rallies
have among the lowest 60-min realized vol of all 12 volatility incidents (March 2024:
0.00106, the lowest of all 12; March 2023: 0.00136, the second lowest) — an unusually calm
CEX backdrop that resembles the calm-market signature shared by all 5 manipulation incidents
(0.00028–0.00134). March 2024 additionally has `heartbeat_elapsed` = 1,200s, which crosses
the same 265s median split into "high," landing it in the same discretized bucket as every
manipulation and malfunction incident. Crashes don't show this pattern — their realized vol
is well above the manipulation range, so they aren't mistaken for it.

**Dec 2024 breakdown → malfunction (not manipulation).** Its `reserve_skew` and
`heartbeat_elapsed` both fall on the same "high" side of their thresholds as UST/USD —
malfunction's only incident with a non-missing `reserve_skew` — consistent with, though not
provably caused by, that shared discretized state pulling its posterior toward malfunction
(67%) over volatility (30%).

**Net read:** the errors cluster in a specific, explainable place (BN's median-split
discretization of `heartbeat_elapsed` flattening a real magnitude difference), not randomly
across the confusion matrix.

## 2. Entropy vs. trajectory

Naive Bayes' LOOCV entropy is degenerate — it returns ≈0 confidence-of-certainty for nearly
all 20 incidents, including ones it gets wrong (e.g. FTT: 100% confidence, wrong). It carries
no discriminating signal here, so this comparison uses the Bayesian network's entropy, which
spans a real range (0.014–0.959).

The 3 malfunction incidents (UST 0.96, FTT 0.93, stETH 0.88) are the **3 highest-entropy
incidents of all 20** — the model is least confident, dataset-wide, on the same class already
flagged as fragile everywhere else in this project.

Cross-referencing the 3 incidents that got trajectory plots:

| incident | class | BN entropy | rank (1=most confident, 20=least) | trajectory description |
|---|---|---|---|---|
| Aug 5 2024 carry-trade unwind | volatility | 0.030 | 4th–5th (tied) | "all three venues move together almost indistinguishably... no lag, no localized divergence" |
| Harvest Finance | manipulation | 0.667 | 15th | "5 distinct step-changes... the failure is entirely localized to the exploited venue" |
| stETH/ETH heartbeat lag | malfunction | 0.876 | 18th (3rd least confident) | "the cleanest of the three" — explicit staircase-vs-continuous lag |

Only 1 of 3 agrees cleanly: Aug 2024's low static entropy matches its unambiguous trajectory.
Harvest is a partial match — a clearly-localized trajectory, but only moderate static
confidence. **stETH is a clear disagreement**: it's described as the cleanest trajectory of
the three, yet its static snapshot is the model's 3rd least confident call of all 20 (and is
actually misclassified). This isn't noise — it's the same mechanism from Section 1: the
temporal view shows the full-magnitude 24h staircase lag, but the static snapshot compresses
`heartbeat_elapsed` down to one binary bit that manipulation incidents also trip, discarding
the exact information that makes the trajectory unambiguous.

**Scope caveat:** all 3 trajectories were deliberately chosen as clean, representative
per-class examples (not a random sample), so there is no built trajectory for a genuinely
ambiguous incident to test the converse. This comparison is limited to 3 data points and
should be read as consistent-with, not a validated correlation.
