# A10. Power analysis (2026-09-29)

Reproduce with `cd src && ../.venv/bin/python a10_power_analysis.py`. Seed 20260929. No project data
and no models are used: only closed forms and Monte Carlo.

Assumptions and limits: Hanley-McNeil normal approximation for AUC; independent rows (the audit
found mild clustering, 149 clusters in 162 rows); single-test power unless stated; "80% power,
alpha = 0.05 one-sided" unless stated. Numbers are planning guides, not guarantees.

## 1. Current data: precision of a recall estimate

`n_pos = 24`. Wilson 95% intervals: 20/24 = 0.833 -> [0.641, 0.933]; 18/24 = 0.75 -> [0.551, 0.880];
22/24 = 0.917 -> [0.742, 0.977]. Half-width about 0.15 to 0.19. Recall differences smaller than about
0.2 between two models cannot be resolved.

## 2. Minimum detectable effect at current n (24 vs 138)

| Test | Min detectable true AUC (vs 0.5) |
|---|---|
| single test | **0.660** |
| Holm/Bonferroni, m = 2 / 3 / 4 / 6 / 8 | 0.679 / 0.690 / 0.697 / 0.706 / 0.713 |

Under the null the AUC has SE 0.064; a two-sided 95% null band is 0.5 +/- 0.126.

**If A2 leaves only 11 to 15 positives** (see A2 §5):

| n_pos, n_neg | MDE AUC single | MDE AUC Holm m=4 |
|---|---|---|
| 11, 138 | 0.724 | 0.775 |
| 13, 138 | 0.708 | 0.756 |
| 15, 138 | 0.696 | 0.740 |
| 13, 300 | 0.704 | 0.750 |

More negatives barely help; the positive count is the bottleneck.

## 3. What this means for the A5 negative controls

The roadmap gate is "AUC near 0.5". At small n, *failing to find* an effect is not evidence of
chance. Proposed formal criterion: **the one-sided 95% upper bound on the control model's AUC
must be below 0.60** (an equivalence-style test, not "p > 0.05").

Expected upper bound when the true AUC is exactly 0.5:

| n_pos, n_neg | Expected upper bound | Meets `< 0.60`? |
|---|---|---|
| 24, 138 | 0.605 | **no, marginal** |
| 13, 138 | 0.638 | no |
| 30, 150 | 0.595 | barely |
| 40, 200 | 0.582 | yes |
| 50, 250 | 0.574 | yes |
| 80, 400 | 0.558 | yes |

**At current n the gate cannot be cleanly passed even by a null model.** It needs `n_pos >= 40`
(matched negatives at 5:1 or better) to make the gate meaningful, `>= 50` for margin. Reference
point: the audit's ETH-context-only model had AUC 0.906 (fails any criterion).

## 4. Paired model comparisons (exact McNemar)

Observed BN vs RF: 4 BN-only errors, 0 RF-only, p = 0.125.

| Discordant pairs | Power if better model wins 75% | Power if it wins 90% |
|---|---|---|
| 4 | 0.00 | 0.00 |
| 8 | 0.10 | 0.44 |
| 12 | 0.39 | 0.89 |
| 20 | 0.61 | 0.99 |

Discordant pairs for 80% power: **49** (if better model wins 70%), **20** (80%), **12** (90%).
Discordance was about 2.5% (4 of 162). For 20 discordant pairs that needs about **800 units** at
2.5% discordance, **400** at 5%, **200** at 10%. **Static two-model comparisons at this scale are
underpowered by design.** Recommendations: pre-register model comparisons as estimation (paired
bootstrap CIs on Brier and log-loss differences) rather than significance tests; keep inferential
claims for the forward-time comparison; apply Holm across the comparison family.

## 5. Sample-size targets

`n_pos` needed to detect a true AUC vs 0.5 (80% power, alpha = 0.05 one-sided):

| True AUC | negatives : positives 1:1 | 2:1 | 5.75:1 |
|---|---|---|---|
| 0.65 | 45 | 35 | 28 |
| 0.70 | 25 | 19 | 16 |
| 0.75 | 16 | 12 | 10 |
| 0.80 | 11 | 8 | 7 |

`n_pos` for recall half-width <= h: h = 0.20: 25 (worst case) / 13 (p = 0.85); h = 0.15: 43 / 22;
h = 0.10: 97 / 49; h = 0.05: 385 / 196.

**Proposed targets for the rebuilt primary class (`M` only, verified, 2-source):**

| Target | n_pos | Buys |
|---|---|---|
| Minimum | 40 | A5 gate is meaningful; recall half-width about 0.10 at p = 0.85 needs 49 |
| Working | 50 | A5 with margin; MDE AUC 0.61 vs 0.5 |
| Stretch | 80 | Holm-corrected comparisons with m = 4 detect AUC 0.61 |

Negatives at least 5:1 (any more is cheap but helps little).

## 6. Yield of A0's scan, by attack prevalence

Total triggered anomalies needed to contain `n_pos` labeled attacks:

| Prevalence among triggered | 30 | 50 | 80 |
|---|---|---|---|
| 30% | 100 | 167 | 267 |
| 15% | 200 | 334 | 534 |
| 5% | 600 | 1,000 | 1,600 |
| 2% | 1,500 | 2,500 | 4,000 |

Prevalence is unknown until the A0 pilot. **The scan cannot create more attacks than exist**: it
can only tell us how many attacks there are relative to benign anomalies. The number of
qualifying attacks on Ethereum mainnet comes from public exploit databases and is the real
ceiling (the project's own summary already notes the ceiling is close). Counting them by
category and year is a free, non-RPC next step (A0 §7).

## 7. Precision at deployment prevalence (claim hygiene)

For sensitivity 0.83 (the BN's manipulation recall):

| Specificity | prevalence 15% | 5% | 1% | 0.1% |
|---|---|---|---|---|
| 0.97 | 0.830 | 0.593 | 0.218 | 0.027 |
| 0.995 | 0.967 | 0.897 | 0.626 | 0.142 |

With 0 false alarms in 138 (RF's static result) the 95% Wilson upper bound on the false-alarm rate is
**2.7%**: a spec above 0.973 cannot be claimed. A model that looks accurate on a 15%-attack
benchmark can have precision near 0.2 at 1% prevalence; B7 must report precision at the A0-estimated
natural rate, not at benchmark prevalence.

## 8. Implications for the plan

1. `n_pos >= 40` verified positives is the threshold for A5 to be a real gate. If A2 + A0 cannot
   reach it, A5 can only be reported as inconclusive, and modeling should not start.
2. Report model comparisons as estimates with CIs; do not pre-register significance tests that
   have under 20% power.
3. Report precision at natural prevalence, never benchmark prevalence.
4. Re-run this script with the actual counts after the A2 relabel and again after A0's pilot.
