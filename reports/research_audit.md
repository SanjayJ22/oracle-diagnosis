# Research audit: threats to validity (2026-09-29)

Scope: the manipulation vs. large-volatility task (n=162; malfunction excluded as a case study).
Every number below was produced by a script in `src/` against `data/processed/features.parquet`.
Status key: **CONFIRMED** (evidence shows the flaw is real), **RULED OUT** (tested, not a problem).

## Bottom line

Within this dataset, the Bayesian network (BN) is statistically indistinguishable from a strong
random forest (RF) on the static benchmark, and it holds up far better when trained on older, smaller
data and tested forward in time. Naive Bayes is unreliable.

However, the dataset cannot yet support the paper's central claim, that market-observable
signals diagnose oracle manipulation vs. genuine volatility in general. Three confirmed
construction flaws (C1 to C3) mean a large part of the class separation is explained by **how
each class was sourced and measured**, not by the attack itself. Fixing them requires rebuilding
the negative class and re-measuring features, not more modeling.

## Critical flaws

### C1. The volatility class is selected by the same signals used to classify it. CONFIRMED
- All 138 volatility incidents: venue `WETH_USDC_V3`, oracle Chainlink ETH/USD, selected
  *because* ETH/USD moved by 3 to 5% or more.
- 23 of 24 manipulations: oracle field is ETH/USD as a "documented fallback" (per each
  incident's own `reference_note`); the attacked asset is usually something else (Curve stable
  pools, vault shares, long-tail tokens).
- So `heartbeat_elapsed`, `congestion`, `ref_realized_vol` and all four temporal features describe
  **the ETH market at that block**, not the attacked asset. For volatility they describe the
  ETH move that defined the label.
- Evidence (`confound_ablation.py`, RF, LOOCV):

  | Features | Accuracy | AUC | Manip caught | False alarms |
  |---|---|---|---|---|
  | Majority class | 0.852 | | 0/24 | 0/138 |
  | ETH-market context only (7 features) | 0.907 | **0.906** | 11/24 | 2/138 |
  | Temporal features only | 0.907 | 0.851 | 13/24 | 4/138 |
  | Venue + localization (the "real" signal) | 0.963 | 0.901 | 18/24 | 0/138 |

  Features that carry no information about the attacked asset for 23/24 attacks separate the
  classes as well as the venue features do. Holds on the oracle-only label subset (AUC 0.896).
- `reserve_skew_localization` inherits the problem: for volatility it compares an ETH pool
  against an ETH basket (near zero by construction); for attacks it compares a different asset
  against an ETH basket. (`n_basket_pools` 2 vs. 3 is a mechanical side effect of excluding
  WETH_USDC_V3 from its own basket; benign.)
- Consequence: an attack during an ETH crash, or a crash on a non-ETH pool, is unrepresented,
  and the model's behavior on either is unknown.

### C2. `reserve_skew` is a different quantity per class, often measured after the theft. CONFIRMED
- Volatility: price change on WETH/USDC V3.
- Many manipulations (phase 2/3): change in the victim contract's **token balance**
  ("tracked via USDC balance", "tracked via native ETH balance").
- 16/24 manipulation values have |skew| of 0.9 or more (10 near -1, i.e. full drains; 2 infinite;
  1 at about 6.7e5; 3 between 1 and 10). No volatility incident exceeds 0.19. The feature
  partly measures the loss itself, at a block after the exploit executed. For a diagnosis
  meant to trigger a halt, this is outcome leakage.

### C3. Feature missingness encodes the data source. CONFIRMED
- `price_dev` missing for 83% of manipulations, `cross_venue_spread` and `dex_oracle_spread`
  for 96%; all three missing for 0% of volatility (volatility is ETH/USD, which always has
  exchange and oracle prices).
- Logistic regression with missingness flags: 99.4% accuracy. Without: 88.9%, manipulation
  recall 0.958 to 0.375 (`baseline_leakcheck.py`).
- RF is not exploiting this: using only never-missing features it still scores 97.5%, 20/24
  (`missingness_check.py`). The BN omits missing evidence, so it does not use missingness.

## Major flaws

### M1. The manipulation class is heterogeneous. CONFIRMED, results robust
- Per their own notes, 7/24 are not oracle-price manipulation: rounding/precision
  (BalancerV2, BalancerV1BPool, BalancerBoostedPool2023), share accounting (WiseLending,
  ThetanutsIndexVault), redemption-curve design (USM), MEV-bot exploit (MEVBOTa47b).
  TOPBPool, Makina, AjnaFinance, EFLeverVault need post-mortem confirmation.
- Sensitivity (`label_sensitivity.py`), oracle-only subset (17 manipulations): RF 14/17, BN 14/17,
  BN 4 false alarms, RF 0. Conclusions unchanged; the class definition still needs fixing.

### M2. Every design choice was tuned on the evaluation data. CONFIRMED
Fixed thresholds, BN-only and NB-only feature splits, the discretization default, the localization
feature, and excluding `temporal_gap_trend` from the BN were all chosen after seeing results on
these same incidents. No untouched test set exists. Forward-in-time splits reduce model-fitting
optimism, not design-choice optimism. The size of the bias cannot be measured without new data.

### M3. The BN's four false alarms are crashes, from coarse discretization. CONFIRMED
BN and RF miss the identical 4 manipulations (Inverse Finance, MEVBOTa47b, Conic Finance 02,
CurveLlamaLend; all |skew| under 3%). The BN also calls 4 crashes manipulation (May 2021,
Aug 2023, Aug 2024, Oct 2025; two at 97 to 100% confidence); RF calls none (`error_sets.py`).
RF separates them mainly via `reserve_skew_localization` and step-change counts, which the BN's
single 5% cutoff discards. Given C1, part of that separation is itself confounded.

### M4. Malfunction (n=3) is not learnable. CONFIRMED
Production 3-class BN: FTT correct (0.62); stETH lag and UST freeze called volatility (0.93, 0.99).
Treat as a qualitative case study only.

## Tested and ruled out / resolved

- **Incident dependence.** 162 incidents form 149 date clusters (at most 3 per cluster);
  leave-one-event-cluster-out CV is identical to LOOCV. RULED OUT (`dependence_significance.py`).
- **Static model differences are not significant.** BN vs. RF: McNemar exact p = 0.125
  (4 BN-only errors, 0 RF-only); Brier difference 95% CI [-0.001, 0.077]; identical
  manipulation sets. Do not claim either is better on the static benchmark.
- **Forward-in-time generalization** (`forward_time.py`; train before cutoff, test after):

  | Cutoff | Train n (manip) | RF false alarms | BN false alarms | McNemar p |
  |---|---|---|---|---|
  | 2022-07 | 29 (5) | 0/114 | 2/114 | 1.0 |
  | 2023-01 | 43 (7) | 12/102 | 3/102 | 0.049 |
  | 2023-07 | 60 (7) | 10/85 | 3/85 | 0.049 |
  | 2024-01 | 79 (11) | 16/70 | 2/70 | **0.0044** |
  | 2024-07 | 98 (13) | 0/53 | 2/53 | 0.50 |
  | 2025-01 | 113 (13) | 0/38 | 1/38 | 1.0 |
  | 2025-07 | 125 (14) | 0/27 | 1/27 | 1.0 |

  BN is more robust when training data is limited and older; only the 2024-01 result survives a
  correction for seven cutoffs (Holm). Mechanism: volatility `heartbeat_elapsed` drifts over time
  (median 264s to 300s, Mann-Whitney p = 8e-7); RF learned cutoffs on it, while the BN's fixed
  3600s threshold makes it inert. Note that heartbeat is a C1 (ETH-context) feature.
  Naive Bayes: 37 to 55% forward accuracy.
- **Simulated shift, 10 seeds** (`n162_experiments.py`): BN manipulation recall 20/24 on every seed;
  RF 17 to 20; NB accuracy collapses to 43 to 49% on 3 of 10 seeds. Phase-3 holdout (real
  collection shift): BN and RF 60/60, NB 80%, LogReg 83%.

## What the evidence currently supports

Supported: within this dataset, the BN matches the best black-box baseline statistically, is
interpretable, and generalizes forward in time more reliably when data is scarce. NB is unreliable.
A missingness artifact can inflate naive baselines to 99%.

Not supported: that any of these models diagnoses oracle manipulation vs. genuine volatility in
general. C1 to C3 explain a large share of the separation through sourcing and measurement.

## Required fixes (in order)

1. **Redefine the unit of observation.** An anomaly at a specific price source a protocol consumes
   (Curve pool price, vault share price, TWAP, Chainlink feed). Measure every feature on that same
   source for both classes. Drop ETH/USD "fallback" features entirely.
2. **Rebuild the negative class on matched venues.** Benign large moves on the same kinds of
   sources the attacks hit: stablecoin depegs (e.g. USDC, March 2023), LSD discounts (stETH, June
   2022), non-ETH lending-market price moves, plus ETH crashes. Aim for venue and asset types
   distributed similarly across classes.
3. **Fix measurement timing and quantity.** Price (not balance) at the last block *before* the first
   manipulating transaction, identically defined for both classes. No post-exploit state.
4. **Pre-specify negative controls that must pass.** On the rebuilt data, an ETH-market-context-only
   model and a venue-identity-only model should score near chance (AUC about 0.5). If not, the
   confound persists.
5. **Label protocol.** Categorize each exploit from post-mortems; include only price-source
   manipulation under a written rule decided before looking at model results.
6. **Freeze and hold out.** Lock features, thresholds, and model; evaluate once on incidents
   collected after the freeze, plus forward-in-time splits. Report McNemar and bootstrap CIs for
   every model comparison.
7. **Malfunction** stays a case study.

Fixes 1 to 3 need new on-chain reads (block-level state is available on the free RPC tier;
intra-transaction state needs paid tracing).

## Scripts

`confound_ablation.py`, `missingness_check.py`, `baseline_leakcheck.py`, `error_sets.py`,
`label_sensitivity.py`, `dependence_significance.py`, `forward_time.py`, `n162_experiments.py`,
`analysis_extras.py`. Run from `src/` with the project `.venv`.
