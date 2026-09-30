# Crash-vs-attack discriminating feature: build, test, and adopt

Targets the dominant error mode found in `reports/confusion_analysis.md`: all 11
current LOOCV errors trace to `reserve_skew` crossing the fixed 0.05 threshold,
because both violent market-wide crashes and localized single-venue attacks
produce large DEX-vs-Chainlink reserve deviations that one magnitude threshold
cannot tell apart. **Verdict**: one of the two candidate features
(`reserve_skew_localization`) earned a small, clean, well-explained place for the
Bayesian network only; the other (`skew_vol_ratio`) did not earn its place for
either model; neither earned a place for Naive Bayes.

## 0. Production update — ADOPTED (BN-only)

**`reserve_skew_localization` is now part of the production Bayesian network**,
added to `BN_RAW_TO_DISCRETE`/`BN_EDGES`/`BN_STATE_NAMES`/`FIXED_THRESHOLDS` in
`src/models.py` (threshold 0.05, reusing the existing spread/skew convention),
via the same per-model asymmetric-split precedent already established for
`temporal_gap_trend` (NB-only) — this is the mirror case, BN-only. **NB's
`FEATURE_COLS`, the discretization scheme (`"fixed"`), and the rest of the
hand-drawn structure are unchanged**, exactly as instructed.

Re-ran the full production LOOCV evaluation against the updated `src/models.py`
(not the monkey-patch harness) to confirm the numbers below are what production
now actually produces, not just what the test harness predicted:

| | Accuracy | Manip. recall | Malf. recall | Vol. recall | Brier | ECE | Log-loss |
|---|---|---|---|---|---|---|---|
| BN, **previous production** | 93.3% (154/165) | 83.3% | 33.3% | 96.4% | 0.1330 | 0.0450 | 0.3354 |
| BN, **current production** | **93.9%** (155/165) | 83.3% | 33.3% | **97.1%** | **0.1061** | 0.0465 | 0.3496 |
| NB (unchanged, reconfirmed identical) | 95.2% (157/165) | 75.0% | 100.0% | 98.6% | 0.0970 | 0.0482 | 1.2192 |

Matches the projected numbers from the monkey-patch harness exactly (Brier
0.1061, accuracy 93.9%). NB's numbers are bit-for-bit identical to before,
confirming it was not touched.

**Confusion matrix, current production BN:**

| True \ Predicted | manipulation | malfunction | volatility |
|---|---|---|---|
| manipulation (24) | 20 | 0 | 4 |
| malfunction (3) | 0 | 1 | 2 |
| large volatility event (138) | 3 | 1 | 134 |

**April 2025 tariff shock is now correctly classified** as large volatility
event (82.7% confidence, was misclassified as manipulation before).

**No other incident regressed** — verified directly by reconstructing the
pre-change BN (temporarily removing `reserve_skew_localization` via monkey-
patch, for comparison only, not applied to the file) and diffing predictions
across all 165 incidents against the new production model. **Exactly 2
predictions differ anywhere in the dataset**:

| Incident | Before | After | |
|---|---|---|---|
| April 2025 tariff shock | manipulation (wrong) | large volatility event (**correct**) | genuine fix |
| May 19 2021 crash | manipulation (wrong) | malfunction (still wrong) | lateral shift, not a fix |

11 → 10 errors, zero regressions (zero previously-correct incidents became
incorrect).

## Key finding — this result sits at the information ceiling of block-level diagnosis, not a solvable feature-engineering gap

**The 9 boundary-region incidents (the manipulation and volatility incidents
nearest this decision) fully interleave on `reserve_skew_localization`'s own
scale (§6 below has the exact ranked list) — manipulation and volatility
alternate with no gap, across every reference-basket-based signal tried.** This
is not a threshold-tuning problem: no cutoff on this feature, at any value,
separates these specific 9 incidents, and the mechanism for *why* is understood
directly (§6) rather than just observed as a negative number.

**This connects directly to `reports/tracing_feasibility.md`'s finding, and
together they form one coherent limitation, not two separate ones.** Both
reports independently arrive at the same underlying fact: **the features this
model can compute are all derived from block-boundary state reads** (a pool's
reserves/price at specific blocks) or CEX/DEX signals aggregated over a
trailing window. Neither kind of signal can see *why* a given block-to-block
price change happened — whether it reflects a real, broad market move or a
transaction-scoped, engineered one. `tracing_feasibility.md` showed this
gap directly for the *fully atomic* case (an exploit that is invisible at both
block boundaries because it's constructed and unwound within one transaction);
this report shows the same gap exists for the *boundary-magnitude* case even
when the deviation IS visible at the block level (it survives past the
transaction, so `reserve_skew` captures it) — the problem isn't visibility,
it's that block-level reads cannot distinguish a market-wide cause from a
localized one once the magnitude is ambiguous. **Both point to the same fix:
intra-transaction (trace-level) data — which transactions moved the price,
whether they also moved correlated venues in the same block, and whether the
flow pattern matches a market-wide arbitrage cascade or a self-contained
attack — not a better block-level feature.** This project has now tried three
different block-level angles at this exact boundary (the raw `reserve_skew`
threshold itself, `skew_vol_ratio`, and `reserve_skew_localization`) and each
one narrows the problem marginally without resolving it, which is itself
evidence for an information ceiling rather than a features-not-yet-tried gap.
**Flagged explicitly for `reports/project_summary_final.md`** — see that
document's updated §3/§4 for how this reframes the project's leading
limitation as one coherent block-level-vs-trace-level information boundary.

## 1. Feasibility check: reading multiple reference pools per incident

**Yes, feasible on the current free Alchemy tier — but only with an explicit
deployment-existence precheck, which was not obvious in advance and is worth
documenting.**

A first, naive attempt — calling `fetch_dex.py`'s existing `get_v2_reserves`/
`get_v3_state` directly on a small basket of 3 reference pools (WETH/USDC V3
0.05%, WETH/USDC V2, wstETH/WETH V3 — all three already defined constants in
`build_features.py`, reused unchanged) for a few test incidents — was killed
after 2+ minutes of complete silence. Diagnosed directly: Uniswap V3 did not
exist before ~May 2021 (its factory deployed at block ~12,369,621), so for any
incident before that (e.g. Harvest Finance, Oct 2020, block 11,129,474), calling
`token0()`/`slot0()`/etc. on the not-yet-deployed V3 pool addresses reverts on
every sub-call, and `fetch_dex.py`'s `_with_retry` retries each one
`MAX_RETRIES=6` times with backoff (5, 10, 15, 20, 25s) — tens of minutes of
pure sleep for a single incident, confirmed as the actual cause once isolated.

**Fixed by prechecking pool existence with `w3.eth.get_code(pool_address,
block_identifier=block)`** — a single, near-instant call — before attempting
any expensive multi-call read; empty bytecode means "not deployed yet," skip
with zero retries burned. Verified directly: at Harvest's block, `get_code`
returns non-empty only for WETH/USDC V2 (deployed 2020); both V3 pools return
empty. By Cream Finance's block (Oct 2021) all three are deployed. This precheck
made the full run cheap: **~1-7 seconds per incident** for a full 3-pool,
2-block read (measured directly), and the full 165-incident run completed in
about 14 minutes with zero failures or rate-limit errors. **Reading several
independent reference pools per incident is feasible on the free tier — the
real cost is the retry-storm trap for pre-deployment blocks, not the RPC access
itself, and that trap is avoidable with one cheap precheck call.**

Given this worked, the design below uses the multi-pool approach (option (a) in
the original request) rather than falling back to the CEX-realized-vol-only
proxy — but the CEX-vol-ratio idea (option (b)) was *also* implemented, at
essentially zero extra cost (it reuses `ref_realized_vol`, already computed for
every incident, no new RPC calls), so both candidate features got a real test
rather than treating them as mutually exclusive.

## 2. Feature design

Implemented in `src/compute_crash_attack_feature.py` (new file, does not modify
`models.py` or `build_features.py`).

**`market_basket_skew`** (intermediate quantity, not itself a model feature):
median `|% price change|`, using the *same* before/after ratio convention as
`build_features.py`'s own `reserve_skew` (baseline block = incident block −
`BASELINE_LAG_BLOCKS` (300, ~1h)), across the 3-pool reference basket —
**excluding whichever basket pool happens to be the incident's own observed/
manipulated venue**, to avoid circularity. This matters concretely: all 138
volatility incidents and MEVBOTa47b use WETH/USDC V3 as their own `dex_pool`
(confirmed by direct inspection of `build_features.INCIDENTS`), and stETH/ETH
heartbeat lag uses wstETH/WETH V3 as its own — for those 140 incidents the
matching basket pool is dropped, leaving 2 (or, rarely, 1) independent basket
members.

**Feature (a) — `reserve_skew_localization`** = `|reserve_skew| −
market_basket_skew`. High positive: this venue moved much more than the
reference-pool basket (localized/attack signature). Near zero or negative: this
venue moved about as much as the general reference market (market-wide/crash
signature).

**Feature (b) — `skew_vol_ratio`** = `|reserve_skew| / (ref_realized_vol +
0.001)`. The 0.001 epsilon is on the same order as the smallest observed
`ref_realized_vol` values (~0.0003-0.0024) — chosen to prevent divide-by-near-
zero blowup without materially changing the ratio at typical magnitudes, not
fit to the class labels. A real crash should have both a large `reserve_skew`
and elevated CEX-measured `ref_realized_vol` (ratio stays moderate); a
localized attack should have a large `reserve_skew` while the broader market
(and CEX vol) stays calm (ratio blows up).

Both strictly trailing, no lookahead by construction: every block read in
`compute_crash_attack_feature.py` uses `block_identifier ∈
{incident_block − 300, incident_block}`, never a later block — the same
guarantee every other feature in this project already carries.

## 3. Coverage, per class

| Feature | Volatility (138) | Malfunction (3) | Manipulation (24) |
|---|---|---|---|
| market_basket_skew | 138/138 | 3/3 | 24/24 |
| reserve_skew_localization | 138/138 | **1/3** | 24/24 |
| skew_vol_ratio | 138/138 | **0/3** | 24/24 |

`market_basket_skew` itself has full coverage (every incident found at least
one deployed, readable basket pool). The two derived features inherit
`reserve_skew`'s and `ref_realized_vol`'s own pre-existing missingness for
malfunction — `reserve_skew_localization` needs `reserve_skew` (missing for
FTT/USD and UST/USD, present for stETH), `skew_vol_ratio` needs *both*
`reserve_skew` and `ref_realized_vol` (stETH has `reserve_skew` but not
`ref_realized_vol`, so it's 0/3). **This is not a new missingness problem** —
it's the same pre-existing malfunction-class scarcity (`reports/
ablation_and_audit.md` §3(a)) propagating through, unchanged in kind.

## 4. Full production evaluation (LOOCV, `fixed` discretization, hand-drawn structure)

| Variant | Accuracy | Manip. recall | Malf. recall | Vol. recall | Brier | ECE | Log-loss | vol→manip errors | manip→vol errors |
|---|---|---|---|---|---|---|---|---|---|
| **BN baseline (production)** | 93.3% | 83.3% | 33.3% | 96.4% | 0.1330 | 0.0450 | 0.3354 | 5 | 4 |
| BN +localization | **93.9%** | 83.3% | 33.3% | **97.1%** | **0.1061** | 0.0465 | 0.3496 | **3** | 4 |
| BN +skew_vol_ratio | 92.1% | 83.3% | 33.3% | 94.9% | 0.1325 | 0.0564 | 0.3702 | 6 | 4 |
| BN +both | 93.3% | 83.3% | 33.3% | 96.4% | 0.1248 | 0.0630 | 0.4031 | 4 | 4 |
| **NB baseline (production)** | 95.2% | 75.0% | 100.0% | 98.6% | 0.0970 | 0.0482 | 1.2192 | 0 | 4 |
| NB +localization | 89.1% | **33.3%** | 100.0% | 98.6% | 0.1965 | 0.0926 | 1.7595 | 0 | — |
| NB +skew_vol_ratio | 84.2% | **4.2%** | 100.0% | 97.8% | 0.3019 | 0.1505 | 2.3130 | 0 | — |
| NB +both | 83.6% | **0.0%** | 100.0% | 97.8% | 0.3277 | 0.1648 | 3.8172 | 0 | — |

## 5. The specific test: does this reduce the two targeted error groups?

**Group A (volatility → manipulation, 5 baseline errors): partially, and only
via `reserve_skew_localization`.** Traced the exact incident-level prediction
diff between BN baseline and BN +localization across all 165 incidents (not
just the 11-incident watchlist) — **only 2 predictions change anywhere in the
dataset**:

| Incident | Baseline | +localization | Net effect |
|---|---|---|---|
| April 2025 tariff shock | manipulation (wrong) | large volatility event (**correct**) | **Genuine fix** |
| May 19 2021 crash | manipulation (wrong) | malfunction (still wrong) | Lateral shift, not a fix |

Net: 11 → 10 errors. One incident is genuinely corrected. One shifts from one
wrong answer to a different wrong answer (still miscounted, arguably a less
severe mistake in kind but not in the recall/accuracy numbers). **Aug 2023
selloff, Aug 5 2024 carry-trade unwind, and Oct 10-11 2025 flash crash are
still misclassified as manipulation, unchanged.** `skew_vol_ratio` alone makes
Group A *worse* (5 → 6 errors) — see §6 for why.

**Group B (manipulation → volatility, 4 baseline errors): no.** MEVBOTa47b,
CurveLlamaLend, Conic Finance 02, and Inverse Finance are still all
misclassified as volatility under every variant tested (localization alone,
ratio alone, both together). Zero recovery.

## 6. Why the win is small: the interleaving problem, diagnosed directly

Ranked the 9 "boundary-region" incidents (the 4 missed manipulation + 5 missed
volatility incidents) by `reserve_skew_localization` directly:

| Incident | True label | reserve_skew_localization |
|---|---|---|
| MEVBOTa47b | manipulation | 0.0032 |
| CurveLlamaLend | manipulation | 0.0141 |
| Inverse Finance | manipulation | 0.0188 |
| May 19 2021 crash | volatility | 0.0237 |
| Conic Finance 02 | manipulation | 0.0257 |
| April 2025 tariff shock | volatility | 0.0265 |
| Aug 2023 selloff | volatility | 0.0313 |
| Aug 5 2024 carry-trade unwind | volatility | 0.0400 |
| Oct 10-11 2025 flash crash | volatility | 0.0596 |

**These fully interleave — manipulation and volatility incidents alternate
across this range with no gap.** No single threshold on this feature, at any
value, could cleanly separate this specific 9-incident group; the hypothesis
("localized attacks show high localization, crashes show low") holds cleanly
for the *rest* of the manipulation class (median localization for the other 15
manipulation incidents is ~0.97-1.0, far above anything in this table) but
**not** for exactly the ambiguous cases the confusion analysis flagged — these
9 are ambiguous on this axis too, not just on raw `reserve_skew`. A further,
compounding reason the fixed 0.05 threshold captures almost none of this
region: 8 of these 9 incidents fall *below* 0.05 (only Oct 10-11 2025 clears
it), so the BN's discretized evidence treats 8 of the 9 as the same "low"
bucket — nearly all of the observed 1-fix improvement comes from the model's
probabilistic combination of this feature with the other 9, not from this
feature single-handedly resolving the threshold-crossing problem it was built
to fix.

**Why `skew_vol_ratio` doesn't hold up**: raw values for the same 9 incidents
also interleave (MEVBOTa47b 3.99, CurveLlamaLend 6.17, May19 7.61, Inverse
11.64, April2025 15.57, ConicFinance 17.20, Aug2023 20.04, Aug2024 23.13,
Oct2025 25.31) — and here the *crash* incidents actually skew *higher* than 3
of the 4 manipulation incidents, the opposite of the hypothesis. Mechanism:
`reserve_skew` (a DEX-pool price change) reflects DEX-specific liquidity/
slippage effects during a violent, fast crash that the CEX-measured 1-minute
`ref_realized_vol` doesn't capture at the same magnitude — a real crash's DEX
pool moves *more*, proportionally, than its own CEX realized vol would predict,
inflating the ratio in a way that mimics a localized attack rather than
distinguishing from one. This is a genuine, mechanistic refutation of half the
original hypothesis, not just a negative number.

## 7. Per-model verdict — ablation, ties directly to the NB Gaussian-extreme-value issue already on record

**BN + `reserve_skew_localization`: marginally earns its place.** Small, clean,
mechanistically explained gain (+1 correct incident net, Brier improves 20%
relatively, 0.1330 → 0.1061, ECE and log-loss essentially flat), touches
exactly 2 of 165 predictions and breaks nothing else. **BN +
`skew_vol_ratio`: does not earn its place** — makes Group A strictly worse (5 →
6 errors) and ECE worse, for the mechanistic reason in §6. **BN + both: worse
than localization alone** on every calibration metric (ECE 0.063 vs 0.047,
log-loss 0.403 vs 0.350) — `skew_vol_ratio`'s noise partially cancels
`localization`'s gain even in combination.

**Neither feature earns a place in NB, and by a wide margin.** NB's
manipulation recall collapses from 75.0% to 33.3% (+localization), 4.2%
(+skew_vol_ratio), and 0.0% (+both). This is the same, already-documented
mechanism from `reports/ablation_and_audit.md` §2 — NB's unclipped Gaussian
fit is distorted by `reserve_skew`'s legitimately extreme raw values (TOPBPool
+670,679.59; Cream Finance and ResupplyFi literal `+inf`) — **except worse
here**, because both derived features amplify that extremity rather than
damping it: `reserve_skew_localization` inherits the same `inf` values
directly (`|inf| − finite = inf`), and `skew_vol_ratio` for TOPBPool alone is
~3.47×10⁸ (an already-extreme raw skew divided by a small realized-vol
denominator). This is a strict escalation of a known, on-record NB
vulnerability, not a new independent problem.

## 8. Leakage / no-lookahead re-check

**No lookahead**: re-read `compute_crash_attack_feature.py` fresh — every block
read (`get_code`, `get_v2_reserves`, `get_v3_state`) uses `block_identifier ∈
{incident_block, incident_block − BASELINE_LAG_BLOCKS}`, both `≤` the incident
block, architecturally incapable of seeing a future block. Same guarantee as
every other feature in this project.

**Perfect single-feature separation**: checked fresh for both new columns —
**none found**. `reserve_skew_localization`'s manipulation range
`[0.0032, inf]` overlaps volatility's `[-0.0018, 0.0596]`; `skew_vol_ratio`'s
manipulation range `[3.99, inf]` overlaps volatility's `[0.072, 25.31]`.
(Malfunction's single non-missing `reserve_skew_localization` value, stETH's
-0.0134, technically falls outside both other classes' ranges, but this is one
point at n=1 — not a meaningful separation, and consistent with malfunction's
pre-existing n=3 data-scarcity caveat, not a new finding.)

## 9. Malfunction n=3 — unchanged, and this feature adds essentially nothing here

Malfunction's BN recall is unchanged at 33.3% (1/3) in every variant tested.
This isn't a null result about the feature's quality for malfunction so much
as a coverage ceiling: `reserve_skew_localization` has a real value for only 1
of 3 malfunction incidents (stETH), `skew_vol_ratio` for none. No assessment
of this feature's effect on malfunction detection is possible from 1 (or 0)
data points — this is the same n=3 caveat that applies to every finding in
this project involving that class, not a new problem this feature introduces.

## 10. Final status

**`reserve_skew_localization`, BN-only: ADOPTED into production** (§0) —
explained mechanism, minimal footprint (2 of 165 predictions change, zero
regressions), real Brier improvement, and it directly targets — and partially
reduces — the exact dominant error mode `confusion_analysis.md` identified.
It does not solve that error mode (§6/Key finding above: the specific
ambiguous incidents interleave on this feature too, diagnosed as an
information-ceiling problem, not a missing-feature problem), and it doesn't
touch Group B (the 4 manipulation→volatility misses) at all.

**`skew_vol_ratio` was dropped, not adopted** — it does not earn its place for
either model, and §6 gives a real mechanistic reason (DEX-liquidity slippage
during genuine crashes, not just localized attacks, inflates this ratio)
rather than just a negative number. It is not part of `src/models.py`.

**Residual limitation, now understood precisely rather than open**: the
dominant error mode (§3-4 of `reports/confusion_analysis.md`) is now partially
mitigated (11 → 10 errors) but not resolved, and the reason it can't be fully
resolved with block-level features is itself the headline finding of this
report (Key finding, above) — reaching further into this specific boundary
region most plausibly requires trace-level data, connecting directly to
`reports/tracing_feasibility.md`'s already-documented access blocker (paid
Alchemy tier) rather than more block-level feature engineering.
