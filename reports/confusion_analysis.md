# Confusion matrix analysis: current production Bayesian network (n=165, fixed discretization)

Read-only analysis — no model or code changed. LOOCV re-run fresh via
`loocv_validation.py`'s unmodified `loocv_bayesian_network(df)` (default
`"fixed"` discretization, current production).

## 1. Full 3×3 confusion matrix (raw counts)

| True \ Predicted | manipulation | malfunction | large volatility event |
|---|---|---|---|
| **manipulation** (24) | 20 | 0 | 4 |
| **malfunction** (3) | 0 | 1 | 2 |
| **large volatility event** (138) | 5 | 0 | 133 |

Overall: 154/165 = 93.3%. Per-class recall: manipulation 83.3% (20/24),
malfunction 33.3% (1/3), volatility 96.4% (133/138). **11 total errors.**

## 2. Every error, precisely characterized

### Group A — volatility → manipulation (5 errors)

| Incident | Confidence | reserve_skew | Other notable feature values |
|---|---|---|---|
| Oct 10-11 2025 flash crash | 98.8% | -0.1405 | congestion=1.0, temporal_gap_trend=-43.6 |
| Aug 2023 selloff | 95.4% | -0.0706 | congestion=1.0, temporal_step_change_count=6 |
| Aug 5 2024 carry-trade unwind | 87.2% | -0.0790 | congestion=1.0, temporal_step_change_count=24 |
| May 19 2021 crash | 73.1% | -0.1932 | congestion=NaN, ref_realized_vol=0.0244 (near the class max) |
| April 2025 tariff shock | 54.0% (near coin-flip) | -0.0558 | temporal_step_change_count=1 (lowest of the 5) |

**Every single one of these 5 has `reserve_skew` more negative than -0.05** —
the fixed discretization threshold. **Every single one is a selloff/crash
(negative reserve_skew), never a rally** — of the 9 volatility incidents that
cross the ±0.05 threshold in either direction (§4), the one positive
(rally) case was *not* misclassified. `congestion=1.0` (fully saturated) on
3 of the 5 is notable but not universal (May 19 2021 crash has it missing
entirely, yet is still misclassified) — `reserve_skew` alone is the
consistent driver, not a congestion co-factor.

### Group B — manipulation → volatility (4 errors)

| Incident | Confidence | reserve_skew | Other notable feature values |
|---|---|---|---|
| MEVBOTa47b | 99.8% | +0.0094 | temporal_deviation_persistence=0.0, all spread features near-zero |
| CurveLlamaLend | 98.8% | -0.0162 | price_dev/cross_venue_spread/dex_oracle_spread all NaN (no dex_pool) |
| Conic Finance 02 | 96.5% | -0.0257 | same missingness pattern as CurveLlamaLend |
| Inverse Finance | 97.9% | +0.0238 | same missingness pattern |

**These are exactly the 4 lowest `|reserve_skew|` values in the entire
24-incident manipulation class** — confirmed by ranking all 24 (§5): every
manipulation incident with `|reserve_skew| < 0.05` is misclassified, **with
zero exceptions**; every one with `|reserve_skew| ≥ 0.05` (starting at UwU
Lend, 0.0705) is correctly classified, **also with zero exceptions**. This is
a perfectly clean single-feature threshold effect in both directions — Group
A and Group B are mirror images of the same boundary.

### Group C — malfunction → volatility (2 errors)

| Incident | Confidence | heartbeat_elapsed | reserve_skew |
|---|---|---|---|
| UST/USD feed freeze | 99.5% | 950 (below the 3600s fixed threshold) | NaN |
| stETH/ETH heartbeat lag | 83.1% | 86,428 (far above threshold) | -0.0043 (near-zero, "near" bucket) |

UST's miss is the same, already-documented failure mode as the deterministic
baseline's own known UST error: its freeze *starts* at this point rather than
building up a preceding stale gap, so `heartbeat_elapsed` doesn't clear the
threshold. stETH's miss is different and more interesting: its
`heartbeat_elapsed` clears the threshold easily (86,428s ≫ 3600s), but its
posterior still swings to volatility at 83.1% confidence — `reserve_skew`
being solidly in the "near" (unremarkable) bucket, plus 5 of stETH's other
features being genuinely missing (`price_dev`, `cross_venue_spread`,
`ref_realized_vol`, all 4 temporal features), leaves the model with
comparatively little evidence to work with, and what it has doesn't clearly
say malfunction.

**Zero manipulation ↔ malfunction confusions in either direction** — no
incident in either class was ever predicted as the other.

## 3. Where errors concentrate: confirms the two-class refresh finding exactly

| Error type | Count | Crosses oracle-failure/volatility boundary? |
|---|---|---|
| volatility → manipulation | 5 | Yes |
| manipulation → volatility | 4 | Yes |
| malfunction → volatility | 2 | Yes |
| manipulation → malfunction | 0 | — |
| malfunction → manipulation | 0 | — |

**11/11 errors cross the oracle-failure/volatility boundary. 0/11 are
manipulation↔malfunction confusions.** This is not a rough match to
`reports/two_class_analysis.md`'s finding (11/11 boundary-crossing, 0/11
manip↔malfunction, computed independently via a full LOOCV re-run rather
than reused) — it is the exact same set of 11 incidents, confirming that
result precisely rather than approximately. **For this model, at this scale,
the entire error surface is the oracle-failure-vs-volatility distinction.
None of it is about telling manipulation and malfunction apart from each
other.**

## 4. The calm-volatility confusion, quantified precisely — and one correction to an earlier framing

**9 of 138 volatility incidents (6.5%) have `|reserve_skew|` crossing the
fixed 0.05 threshold; 5 of those 9 (56%) are actually misclassified**, the
other 4 correctly held as volatility by the rest of the model's evidence
despite `reserve_skew` alone pointing the wrong way:

| Incident | reserve_skew | Misclassified? |
|---|---|---|
| May 19 2021 crash | -0.1932 | Yes |
| Oct 10-11 2025 flash crash | -0.1405 | Yes |
| Aug 5 2024 carry-trade unwind | -0.0790 | Yes |
| Feb 6 2026 crash | -0.0756 | No (correctly volatility, 72.1% confidence) |
| Aug 2023 selloff | -0.0708 | Yes |
| June 2022 Celsius deleveraging | -0.0662 | No (correctly volatility, 90.4% confidence) |
| May 12 2022 selloff (p2) | -0.0593 | No (correctly volatility, 94.3% confidence) |
| Aug 19 2026 rally | **+0.0567** (the only positive case) | No (correctly volatility, 94.3% confidence) |
| April 2025 tariff shock | -0.0558 | Yes |

**Is it specifically the low-magnitude/calm ones? No — the opposite, and this
corrects an earlier framing from this project's much earlier history**
(`reports/cohesion_findings.md`, n=20-era, characterized similar confusions
as resembling "manipulation's calm-market signature" via low
`ref_realized_vol`). Checked directly against the current data: the 5
misclassified incidents' `ref_realized_vol` values (0.0024–0.0244) are **not**
uniformly low — `May 19 2021 crash` sits at 0.0244, essentially the top of the
entire volatility class's range (`[0.0003, 0.0244]` per `reports/
ablation_and_audit.md`'s separation check). **The actual driver is `reserve_
skew` specifically — a DEX-vs-Chainlink price-deviation proxy on the standard
reference pool — crossing the fixed 5% threshold during unusually large,
fast, real market moves (every one of the 5 is a crash/selloff/unwind, named
as such), not "calm" markets in any general sense.** The `ref_realized_vol`-
based "calm market" explanation from the original n=20 analysis does not hold
up as the driver at the current scale and feature set; `reserve_skew`
magnitude does, cleanly and consistently, in both directions (§2).

## 5. Malfunction n=3 — explicit caveat

Malfunction's row in the confusion matrix (1 correct, 2 wrong) is a
statement about exactly 3 incidents — the same caveat that has applied
throughout this project's entire history, unaffected by any of this
analysis's other findings. `reports/refresh_summary.md` and every prior
report already establish this is a data-scarcity problem, not something this
confusion-matrix breakdown adds new information about.
