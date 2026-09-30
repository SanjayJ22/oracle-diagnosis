# Roadmap (created 2026-09-29)

**Read `reports/research_audit.md` first.** It explains why the current dataset cannot support
the paper's central claim (C1 selection confound, C2 measurement non-equivalence, C3 missingness
artifact) and what is already established. This roadmap is the plan to fix it.

Rule for the whole project: **nothing is modeled or claimed until the rebuilt data passes the
negative controls (A5).** Nothing is submitted until the fresh held-out evaluation (A7) is done.

## Critical path (do in this order)

1. **In parallel, no blockers:** A0, A1, A2, A10, C1, C4, D1, D5
2. A3, A8 (after A0/A1 are drafted)
3. A4 re-measure features (needs A0, A1, A2, A3)
4. A5 negative controls (needs A4) -- **gate**
5. B1 to B12 analyses on development data, A9 label reliability
6. A6 freeze and pre-register (needs A5, B1-B3, B7-B12, A9)
7. A7 fresh held-out evaluation, once (needs A6)
8. D2, D3, D4, C7, D7, then D6 submissions

## A. Rebuild the research (fixes audit C1, C2, C3, M1, M2)

| ID | Task | Blocked by | Fixes |
|---|---|---|---|
| A0 | **Common anomaly trigger.** Pick a set of price sources, scan their history with one fixed trigger (e.g. >X% move within Y blocks), label every flagged anomaly. Both classes pass the same trigger: no selection bias, natural base rates. | none | C1 |
| A1 | **Measurement spec.** Unit of observation = an anomaly at the specific price source a protocol consumes. Identical feature definitions for every class: same instrument, price not balance, last block before the first manipulating tx. Drop ETH/USD fallback features. Write it down before any data pull. | none | C1, C2 |
| A2 | **Label protocol.** Written rule for "oracle-price manipulation", fixed before looking at model results. Re-categorize all 24 current manipulations from post-mortems; confirm TOPBPool, Makina, AjnaFinance, EFLeverVault. | none | M1 |
| A3 | **Matched negatives** where A0's scan is thin: stablecoin depegs (USDC Mar 2023), LSD discounts (stETH Jun 2022), non-ETH lending-market moves, Curve imbalances, plus ETH crashes. | A0 draft | C1 |
| A4 | **Re-measure all features** under A1 with block-level reads (free Alchemy tier). No post-exploit state, no fallback instruments. | A0, A1, A2, A3 | C1-C3 |
| A5 | **Negative controls (gate).** ETH-market-context-only and venue-identity-only models must score near chance (AUC ~0.5); missingness must not predict the label. If any fails, fix before modeling. | A4 | C1, C3 |
| A6 | **Freeze and pre-register**: features, thresholds, structures, metrics, tests; commit with a date. | A5, B1-B3, B7-B12, A9 | M2 |
| A7 | **Fresh held-out set**, collected after the freeze; evaluate once, no further tuning. | A6 | M2 |
| A8 | **Data QA harness**: decimals, inverted pairs, wrapper/rate factors (stETH-type), tx-hash and block verification, value ranges; unit tests per feature. Run on every pull. | A1 draft | data quality |
| A9 | **Label reliability**: independent second labeler applies A2 blind; report Cohen's kappa. | A2 | M1 |
| A10 | **Power analysis**: minimum detectable effect at current n; target sample sizes for expansion. | none | small n |

## B. Analysis on rebuilt data (development phase, before freeze)

| ID | Task | Blocked by |
|---|---|---|
| B1 | Full model comparison: NB, BN(fixed), RF, RF(balanced), LogReg(balanced). LOOCV, event-grouped CV, forward-time at multiple cutoffs; McNemar + bootstrap CIs, Holm correction. Reuse `n162_experiments.py`, `dependence_significance.py`, `forward_time.py`. | A5 |
| B2 | Robustness and calibration under shift: 30+ seed simulated shift, forward-time; Brier, log-loss, reliability diagrams with CIs. Check whether the BN's forward-time edge survives without the drifting ETH-context features. | A5 |
| B3 | Fix the BN's coarse discretization (crash false alarms) by a rule stated before seeing results; validate on held-out only. | A5 |
| B4 | Structure learning under `fixed` discretization (open gap, project_summary_final.md section 0) and at larger scale. | A5 |
| B5 | Interpretability demo: per-incident evidence contributions to the BN posterior vs RF's single score. | A5 |
| B6 | Malfunction case study (n=3, qualitative). | none |
| B7 | Realistic base rates: attack prevalence among triggered anomalies (from A0); precision at deployment prevalence; likelihood ratios; prior sensitivity. | A5 |
| B8 | Atomic vs non-atomic attacks; blocks-before-loss time-to-diagnosis; scope claims to detectable attacks. | A5 |
| B9 | Cost-sensitive decision analysis with DeFiHackLabs dollar losses; thresholds by expected loss. | A5 |
| B10 | Practitioner baselines (deviation checks, TWAP guards, circuit breakers / OSM-style delay) and XGBoost (TOAD-ML's family), all nested-CV tuned. | A5 |
| B11 | Sensitivity analysis / specification curve over thresholds, windows, lag blocks, BDeu ESS, trigger parameters. | A5 |
| B12 | Threat model and adaptive-attacker simulation (cross-venue spreading, slow multi-block manipulation). | A5 |

## C. Carried-over and supporting work

| ID | Task | Blocked by |
|---|---|---|
| C1 | Tracing pilot: Etherscan free `txlistinternal` on 2-3 incidents (from project_summary_final.md section 7 and `tracing_feasibility.md`). Informs A1 timing. | none |
| C2 | Expand manipulation data under A2 and A1. | A1, A2 |
| C3 | Temporal model from the original plan: GMM label-gap closure, then GMM-HMM / dynamic Bayesian network. | A5 |
| C4 | Re-verify novelty (section 6 marked not re-verified); confirm TOAD-ML is nearest neighbor; verify and cite Chockalingam et al. | none |
| C5 | Update `project_summary_final.md` supersession map with the audit; mark invalid claims (information ceiling; "BN leads NB on all three calibration metrics"); commit new scripts to git. | none |
| C6 | Multi-chain expansion (BSC, Arbitrum, Base); cross-chain generalization test. | A4 |
| C7 | Reproducibility package: frozen dataset + datasheet, pinned requirements, seeds, one-command reproduce, RPC cache, git tag. | A7 |

## D. Paper and submissions

| ID | Task | Blocked by |
|---|---|---|
| D1 | **CJSJ decision (deadline 2026-09-30).** Rebuild cannot finish in time: skip this cycle, or submit a narrowly scoped version stating the confounds as limitations. | none |
| D2 | Rewrite the paper around validated results only. | A7 |
| D3 | References: DeFiTrace authors (ACM TOPS, doi 10.1145/3817054), Chockalingam et al., re-verify all. | none |
| D4 | Figures deck from final data (structure diagrams `nb_model.png`, `bn_model.png` exist). | D2 |
| D5 | Permission-to-publish form signed by Prof. Ricks. | none |
| D6 | Submissions: SSRN preprint, SCCUR (2026-10-09), Regeneron STS (2026-11-05), IJHSR. Only claims that survive the audit. | D2, D7 |
| D7 | Pre-submission review: Prof. Ricks; ideally a DeFi security researcher red-teams threat model and labels. | D2 |

## Already established (do not redo)

See `research_audit.md`: dependence ruled out; static BN vs RF not significantly different
(McNemar p=0.125); BN more robust forward-in-time when training data is small (p=0.0044 at
the 2024 cutoff); NB unreliable; missingness is a sourcing artifact; label heterogeneity does not
change conclusions. All of these must be re-checked on the rebuilt data (B1, B2).
