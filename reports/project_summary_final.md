# Project Summary (Final): Diagnosing Chainlink Oracle Anomalies on Ethereum Mainnet

This is the single authoritative source of truth for the current state of the
project. It replaces `reports/project_summary_v2.md` (which itself replaced
`reports/project_summary.md`) as the consolidation document. Read-only — no
model, code, or feature was changed to produce this report. Every number below
was either read fresh from `src/models.py`/`data/processed/features.parquet`
in this pass, or pulled from a specific cited report; anything not
independently re-verified in this pass is marked **[not re-verified this
pass]**.

## 0. Supersession map — read this first

| Superseded | Superseded by | Why |
|---|---|---|
| `reports/project_summary.md` | `reports/project_summary_v2.md` | n=20 stage, pre-discretization-fix |
| `reports/project_summary_v2.md` | **this document** | pre-temporal-features, pre-`fixed`-discretization, pre-confusion-analysis |
| `reports/loocv_150_incidents.md` | `reports/loocv_200_incidents.md` | pre-scaling numbers |
| `reports/loocv_200_incidents.md` | `reports/discretization_v2.md` | ran under the failed "global" discretization scheme |
| `reports/discretization_fix.md` | `reports/discretization_v2.md` | "global" scheme, later shown to fail under distribution shift a second time |
| `reports/discretization_v2.md` | `reports/discretization_robustness.md` → `reports/production_baseline_fixed.md` | `class_conditional` (the v2 winner) itself later shown less robust than `fixed` |
| `reports/two_stage_analysis.md` | `reports/two_stage_v2.md` | ~45 incidents, sign-based discretization |
| `reports/two_class_analysis.md` (original) | current `reports/two_class_analysis.md` (rewritten in place) | n=20→165, discretization-mismatch bug fixed, headline finding reversed |
| `reports/ablation_and_audit.md` (original) | current `reports/ablation_and_audit.md` (rewritten in place) | n=20→165, `KeyError` bug fixed, feature attribution changed substantially |
| `reports/cohesion_findings.md`'s "calm markets resemble manipulation" framing | `reports/confusion_analysis.md` §4 | shown to not hold at n=165; corrected below (§3) |
| `reports/confusion_analysis.md`'s exact BN numbers/confusion matrix (11 errors, 93.3% accuracy, Brier 0.1330) | `reports/crash_vs_attack_feature.md` + this document's §1/§3 | `reserve_skew_localization` adopted into production BN after that analysis ran; its mechanism-diagnosis (§3 below) remains valid, its exact error count/numbers do not |

**Not superseded, but flagged as unverified against the current config**:
`reports/structure_learning.md` was run under `class_conditional` discretization
(the production default at the time), never re-run under the current `fixed`
default. Its qualitative verdict (hand-drawn beats both learned structures,
by a wide margin, for a diagnosed mechanistic reason) is highly unlikely to
flip — the mechanism (tree-imposed single-parent constraint on `reserve_skew`,
and Hill-Climbing over-fragmenting its CPD) doesn't depend on which
discretization scheme is active — but its exact percentages (83.6%/12.5% for
Chow-Liu, 87.9%/50.0% for Hill-Climbing) are **not confirmed current**. Treated
as directionally reliable, numerically stale, in §5 below.

## 1. Production configuration and locked numbers

**Dataset**: n=165 incidents — 24 manipulation, 3 malfunction, 138 large
volatility event. **Discretization**: `"fixed"` (current default in both
`fit_bayesian_network` and `loocv_bayesian_network`, `src/models.py`).
**Structure**: hand-drawn Bayesian network — confirmed by direct inspection of
`models.BN_EDGES` in this pass:

```
label_d → price_dev_d, cross_venue_spread_d, dex_oracle_spread_d,
          reserve_skew_d, ref_realized_vol_d, heartbeat_elapsed_d,
          temporal_deviation_persistence_d, temporal_slope_d,
          temporal_step_change_count_d, reserve_skew_localization_d
congestion_d → heartbeat_elapsed_d
```

`congestion_d` has **zero parents of its own** (it is a root node, and a
*parent* of `heartbeat_elapsed_d`, not a child of `label_d`) — this was
verified directly via `model.get_parents('congestion_d')` during the
structure-edge-test task and is restated here since it corrects an earlier
in-project assumption.

**Feature sets** (deliberately asymmetric, confirmed by direct inspection):
NB uses 11 features (7 static + all 4 temporal, including `temporal_gap_trend`).
BN uses 11 features (7 static + 3 temporal, excluding `temporal_gap_trend` —
an ablation showed it helps NB and hurts BN — **plus `reserve_skew_localization`,
BN-only**, `reports/crash_vs_attack_feature.md`: a same-venue `|reserve_skew|`
minus a fixed reference-pool basket's own median skew, adopted after an
ablation showed it helps BN's Brier ~20% and hurts NB's manipulation recall to
as low as 0% via the same NB-Gaussian-extreme-value sensitivity already
documented for raw `reserve_skew` — see §4 item 3 below).

**`FIXED_THRESHOLDS`** (confirmed by direct inspection of `models.py` in this
pass), with domain motivation:

| Feature | Threshold | Motivation |
|---|---|---|
| price_dev, cross_venue_spread, dex_oracle_spread, reserve_skew, ref_realized_vol, temporal_slope, **reserve_skew_localization** | 0.05 | matches this project's own `RESERVE_SKEW_THRESHOLD`/`CROSS_VENUE_TOLERANCE` conventions used elsewhere in the pipeline |
| heartbeat_elapsed, temporal_deviation_persistence | 3600 (seconds) | matches `HEARTBEAT_STALE_THRESHOLD_SECONDS`, the same staleness convention Chainlink feeds themselves typically use |
| congestion | 0.5 | matches EIP-1559's target gas ratio (network at exactly its long-run target) |
| temporal_step_change_count | 1 | more than one discrete step within the trailing window is the "high" bucket |

### Locked model numbers (LOOCV, re-run fresh in this pass against the current `src/models.py`, including `reserve_skew_localization`)

| Model | Accuracy | Manip. recall | Malf. recall | Vol. recall | Brier | ECE | Log-loss |
|---|---|---|---|---|---|---|---|
| Deterministic (in-sample; **not LOOCV, not comparable across dataset scales — flagged every time it's cited**) | 92% (151/165) | 83% (20/24) | 67% (2/3) | 93% (129/138) | — | — | — |
| Naive Bayes (LOOCV, unchanged by this update) | 95.2% (157/165) | 75.0% (18/24) | 100.0% (3/3) | 98.6% (136/138) | 0.0970 | 0.0482 | 1.2192 |
| **Bayesian Network (LOOCV, `fixed`, +`reserve_skew_localization`) — production** | **93.9% (155/165)** | 83.3% (20/24) | 33.3% (1/3) | **97.1% (134/138)** | **0.1061** | 0.0465 | 0.3496 |

**Supersedes `reports/confusion_analysis.md`'s exact numbers** (93.3%
accuracy, 11 errors, Brier 0.1330), which described the BN *before*
`reserve_skew_localization` was added (`reports/crash_vs_attack_feature.md`).
The mechanism that analysis diagnosed (§3 below) is still the right
explanation for the remaining 10 errors; only the exact counts moved. All
seven BN numbers and all six NB numbers were reproduced from a fresh
`loocv_naive_bayes(df)` / `loocv_bayesian_network(df)` run in this pass
against the current `src/models.py` — no drift from `reports/
crash_vs_attack_feature.md`'s own reported numbers.

## 2. The central finding: the hard boundary is genuine-market-move vs. manipulation, not attack vs. malfunction

Earlier in this project's history (`reports/cohesion_findings.md`, n=20-era),
the working hypothesis was that **manipulation and malfunction are hard to
tell apart from each other** — both look like "the oracle disagrees with the
market," and the natural third class (ordinary volatility) looked like the
easy exit case. That framing has now been checked directly against the
current 165-incident production model, independently, twice — once via
`reports/two_class_analysis.md`'s explicit oracle-failure/volatility collapse,
and again via `reports/confusion_analysis.md`'s full per-incident error audit
of the unmodified 3-class model — and **it does not hold**.

The current production BN's confusion matrix (n=165, LOOCV, current production
including `reserve_skew_localization` — see §1):

| True \ Predicted | manipulation | malfunction | volatility |
|---|---|---|---|
| manipulation (24) | 20 | 0 | 4 |
| malfunction (3) | 0 | 1 | 2 |
| volatility (138) | 3 | 1 | 134 |

**10 total errors** (down from the 11 `reports/confusion_analysis.md`
originally found — `reports/crash_vs_attack_feature.md` fixed one incident,
April 2025 tariff shock, net). **All 10 still cross the manipulation/
malfunction-vs-volatility boundary. Zero are manipulation↔malfunction
confusions in either direction** — this remains true after the update; one
volatility incident (May 19 2021 crash) now lands on malfunction instead of
manipulation, which is still a boundary-crossing error, not a manipulation↔
malfunction one.

**This is stated here as an honest, scaling-enabled reversal, not as evidence
the original n=20 analysis was wrong to say what it said.** At n=20, with 4-5
incidents per class, a genuine pattern and a small-sample artifact are
difficult to distinguish, and the manipulation/malfunction resemblance
observed then was real *for that sample* — it simply did not generalize once
the dataset grew enough (particularly the manipulation class, 24 incidents
now vs. ~5 then) to separate signal from sampling noise. The actual hard
boundary, at the scale this project can currently support, is **telling a
genuine large market move apart from a deliberately faked one** — not
distinguishing two different kinds of oracle failure from each other.

## 3. The precise mechanism — corrected

The n=20-era explanation for this kind of confusion (`reports/
cohesion_findings.md`) was that **calm markets** resemble manipulation's
"quiet, thin-volume" signature (via low `ref_realized_vol`). This project
explicitly checked that explanation against the current data and it is
**not** what's happening. **The actual driver is `reserve_skew` crossing the
fixed 0.05 threshold during violent, fast, real market moves — not calm
ones.**

**Direction 1 — 4 manipulation incidents missed, misread as volatility**
(MEVBOTa47b, CurveLlamaLend, Conic Finance 02, Inverse Finance): these are
**exactly** the 4 lowest `|reserve_skew|` values among all 24 manipulation
incidents in the dataset, with zero exceptions in the full ranking — every
manipulation incident below the 0.05 threshold is missed, every one at or
above it (starting at UwU Lend, 0.0705) is caught.

**Direction 2 — originally 5 volatility incidents missed, misread as
manipulation; now 4** (Aug 2023 selloff, Aug 5 2024 carry-trade unwind, and
Oct 10-11 2025 flash crash are still misread as manipulation; May 19 2021
crash is now misread as malfunction instead; April 2025 tariff shock is now
**correctly classified**, per `reports/crash_vs_attack_feature.md`). All 4
remaining misses have `|reserve_skew| > 0.05`, and **all are crashes or
selloffs (negative reserve_skew) — never rallies**. Of 9 total volatility
incidents that cross the ±0.05 threshold in either direction, the single
positive/rally case (Aug 19 2026 rally, +0.0567) was correctly classified;
correctly-classified threshold-crossers are also negative but smaller in
magnitude or otherwise outweighed by the model's other evidence.

**The calm-market explanation was checked directly and refuted**: `ref_
realized_vol` for the originally-misclassified volatility incidents ranges
0.0024 to 0.0244 — not uniformly low. `May 19 2021 crash` sits at 0.0244,
essentially the top of the entire volatility class's observed range
(`[0.0003, 0.0244]`). These are not quiet markets that happen to look
suspicious; they are unusually large, fast, real market moves that happen to
push a DEX-vs-Chainlink deviation proxy past the same fixed threshold a
genuine attack would.

**The core limitation, refined after testing a direct fix**: `reserve_skew`
measures how far a reference pool's implied price has drifted from
Chainlink's reported price, with no way to distinguish *why* that drift
happened — a market-wide crash moves every pool's price in the same
direction at once, while a localized attack moves one pool in isolation.
`reports/crash_vs_attack_feature.md` built and tested a feature aimed
directly at this (`reserve_skew_localization`: this venue's own skew minus a
fixed reference-pool basket's own skew) and it produced a small, real,
adopted improvement — but **the 9 boundary-region incidents (the ones this
limitation is actually about) fully interleave on that feature's own scale
too, with zero separating threshold at any value.** This was tested
directly, not assumed, and reframes the limitation: it is not simply "a
missing feature," it is that **every signal derivable from block-boundary
state reads — the only kind of signal this model has access to — runs into
the same wall at this exact boundary.** See §4 item 1 below, which merges
this with the tracing-feasibility finding into one coherent limitation.

## 4. Limitations, ordered by actual dominance (not historical order)

1. **The block-level information ceiling at the crash-vs-attack boundary is
   the dominant, load-bearing limitation of the current model — and it is
   now understood as ONE coherent limitation, not two separate ones.**
   Originally diagnosed as `reserve_skew` crossing a fixed 0.05 threshold
   during both violent crashes and localized attacks (§3), this project then
   built and tested a feature aimed directly at resolving it
   (`reserve_skew_localization`, `reports/crash_vs_attack_feature.md`) —
   adopted into production, and it helped (11 → 10 errors, Brier improved
   ~20%), but the 9 incidents actually at this boundary still fully
   interleave on that feature's own scale, with no cutoff separating them.
   Three different block-level angles have now been tried at this exact
   boundary (raw `reserve_skew`, a market-vol-ratio variant, and the
   localization variant) and each narrows the problem marginally without
   resolving it. Independently, `reports/tracing_feasibility.md` found the
   same underlying fact from a different angle: this model's features are
   all derived from block-boundary state reads, which are structurally blind
   to *why* a price moved (market-wide vs. localized) and, in the extreme
   case, blind entirely to manipulation fully constructed and unwound within
   a single transaction (RPC trace access needed to see that is gated behind
   a paid Alchemy tier, confirmed directly; 7 of 165 candidate incidents were
   dropped from this dataset for exactly this reason). **Both findings point
   to the same conclusion: resolving this boundary further most plausibly
   requires intra-transaction (trace-level) data — which transactions moved
   the price, whether correlated venues moved together in the same block —
   not additional block-level feature engineering.** This is not a
   diffuse, hard-to-pin-down weakness — it is one specific boundary, three
   tested angles, one consistent conclusion about where the ceiling is.
2. **Malfunction, n=3, is real but secondary.** `reports/
   malfunction_search_coverage.md` documents a systematic search — 27 feeds,
   3 passes, 4 methods, 216 candidates evaluated, zero new incidents found —
   confirming this is a structural data-scarcity problem (a feed has to
   completely and catastrophically stop updating, which requires the
   underlying asset or exchange to cease to exist, not merely have an
   unusual day), not a search-effort problem. Every malfunction number in
   this project, including malfunction's 33.3% (1/3) BN recall above, is a
   statement about exactly 3 incidents.
3. **Feature attribution is model-dependent, and this project treats that as
   a real limitation, not just a footnote.** `reports/ablation_and_audit.md`
   (refreshed at n=165) shows `reserve_skew` is BN's single most load-bearing
   feature for manipulation recall (-75 points if dropped) while
   simultaneously *hurting* NB's manipulation recall when kept (+12 points if
   dropped) — a documented consequence of NB's unclipped Gaussian fit being
   distorted by `reserve_skew`'s legitimately extreme raw values (e.g.
   TOPBPool's +670,679.59). `reserve_skew_localization` reproduces and
   amplifies the exact same asymmetry (BN Brier improves ~20%, NB
   manipulation recall collapses to as low as 0%), which is part of why it
   was adopted BN-only rather than for both models. Any claim about "what
   drives this model's manipulation detection" has to specify which model.
4. **Access, not engineering, is now the binding constraint on further
   progress at the dominant boundary.** Following directly from item 1: the
   concrete next step is not another block-level feature (three have now
   been tried) but the trace-level access `reports/tracing_feasibility.md`
   already scoped — pilot Etherscan's free `txlistinternal` API before
   considering a paid Alchemy tier upgrade (§7 below).

## 5. The full arc, as findings

**Discretization** (4 schemes tested, 2 distinct failure modes, robustness-
tested endpoint): sign-based (original) → `global` (magnitude-aware,
population-median split) failed under distribution shift **twice**, first
noted in `reports/loocv_200_incidents.md` at the 105→165 scaling step and
confirmed in `reports/discretization_v2.md` → `class_conditional` (per-class
geometric-mean thresholds) initially won head-to-head against `global`
(`reports/discretization_v2.md`) but was then shown in `reports/
discretization_robustness.md` to move its thresholds up to **7-8x more**
than `fixed` under simulated distribution shift (oversampling calm
volatility, varying the manipulation:volatility ratio, holding out
high-magnitude incidents) → **`fixed`** (hardcoded, training-invariant
constants, §1 above) is the current production default, switched by explicit
instruction after the robustness comparison, confirmed in `reports/
production_baseline_fixed.md` to reproduce the robustness report's baseline
exactly.

**Structure validation**: hand-drawn beat both learned structures under
per-fold LOOCV structure learning (`reports/structure_learning.md`, **run
under `class_conditional`, not re-verified under `fixed` — §0**).
Chow-Liu's tree constraint forces a single parent per non-root node, routing
`reserve_skew`'s signal through `price_dev` instead of keeping a direct
`label→reserve_skew` edge, and was diagnosed (not just observed) as the
mechanism behind its catastrophic 12.5% manipulation recall. Hill-Climbing
was less catastrophic (50.0% manipulation recall) but still worse than
hand-drawn on every metric but ECE, from over-fragmenting `reserve_skew`'s
CPD across too many learned parents. The one plausible, non-missingness-
explained learned edge (`price_dev_d → congestion_d`, present in 99% of
Chow-Liu folds) was explicitly tested as an addition to the hand-drawn
structure (`reports/structure_edge_test.md`) and found to do essentially
nothing (bit-for-bit identical accuracy) because requiring both features
non-missing collapses the contributing sample to 3 manipulation and 1
malfunction row — exactly the data-thinning risk flagged in advance.

**Calibration**: stated honestly, not as a blanket claim. Historically, BN
beat NB on all three calibration metrics for most of this project's scaling
history; that stopped being a blanket-true statement once temporal features
specifically improved NB's Brier and accuracy (NB was 84.2% accuracy / 0.229
Brier before temporal features — `reports/temporal_features.md`) without a
matching improvement to BN. **At the current exact production state (§1,
post-`reserve_skew_localization`)**: NB's Brier (0.0970) is still slightly
better than BN's (0.1061), but the gap narrowed substantially from before
that feature was adopted (BN's Brier was 0.1330, a 37% relative gap vs. NB;
now a 9% relative gap). **BN now leads on ECE too** (0.0465 vs NB's 0.0482,
where before this update they were already close, 0.0450 vs 0.0482), and
log-loss still clearly favors BN (0.3496 vs 1.2192). The honest current
statement is: **BN leads on log-loss, ECE, and manipulation recall, and is
far more consistent under distribution-shift discretization stress-testing
(§ discretization above); NB holds a real, if now narrower, Brier edge and a
real recall advantage on malfunction (100% vs 33.3%, though this is an n=3
statement).** Neither model dominates the other outright at the current
scale, though BN's position improved on net from `reserve_skew_
localization`'s adoption.

**Malfunction rarity**: `reports/malfunction_search_coverage.md` — 27 feeds
searched, 3 passes, 4 methods, 216 candidates evaluated, zero new incidents
found. Structurally requires the underlying asset or exchange to
catastrophically and completely cease to exist, not just behave unusually.

**Crash-vs-attack feature test** (`reports/crash_vs_attack_feature.md`):
built and tested a feature aimed directly at the dominant error mode —
`reserve_skew_localization` (a venue's own skew minus a fixed reference-pool
basket's median skew) and `skew_vol_ratio` (skew relative to CEX-measured
market volatility). A feasibility check first found and fixed a real cost
trap (reading pools not yet deployed at old block heights triggers a retry-
storm without a cheap `get_code` deployment precheck). `skew_vol_ratio` was
refuted mechanistically (DEX-liquidity slippage during real crashes inflates
it too, not just localized attacks) and dropped. `reserve_skew_localization`
was adopted BN-only (§1) after earning a small, clean, well-explained win —
but the exercise's more important output was diagnostic: the 9 incidents at
this boundary interleave on every block-level signal tried, pointing at an
information ceiling rather than a remaining feature-engineering gap (§4 item
1).

## 6. Novelty and positioning

Verified via live web search during `reports/project_summary_v2.md`'s
original consolidation pass, restated here as still the best available
positioning (not re-searched in this pass — **[not re-verified this pass]**):
no existing published work does market-observable, cause-level (manipulation
vs. malfunction vs. volatility) diagnosis of Chainlink oracle anomalies
treating the contract as a black box. The closest neighbors:

- **TOAD-ML** (Frontiers in Blockchain, 2026) — nearest neighbor in problem
  space, but outputs a binary trust score via XGBoost, not a multi-class
  cause diagnosis. Different output type, not a competing solution to this
  project's specific question.
- **Chockalingam et al.** (systematic review, Bayesian Network models in
  cyber security) — the closest methodological precedent for the general
  idea of "Bayesian attack-vs-failure diagnosis," applied to general
  cyber-physical/industrial-control settings. The user's own characterization
  of this precedent, not independently re-verified to this level of
  specificity in this pass: **"Bayesian attack-vs-failure diagnosis on
  floodgates, ported to DeFi."** This project is best positioned as applying
  that general methodological pattern to a new, unaddressed domain (DeFi
  oracle feeds) with a 3-way rather than 2-way outcome space.

## 7. Open next steps (all lab-phase, none started)

1. **More manipulation data.** Bounded by how many clean, verifiable,
   non-atomic mainnet manipulation cases actually exist — this project has
   already run 3 scaling passes (`manipulation_candidates_phase1/2/3.md`) and
   is likely close to the practical ceiling of what's findable without the
   trace-level access described in item 2.
2. **Transaction tracing**, per `reports/tracing_feasibility.md`'s
   recommendation: pilot Etherscan's free `txlistinternal` API on 2-3
   incidents before considering any paid Alchemy tier upgrade. Confirmed
   partial payoff even if fully built — recovers balance-based atomic
   exploits (MetaPool-like) with one general algorithm, but not
   accounting/exchange-rate-based ones (MahaLend-like) without bespoke
   per-protocol work. **Now the single highest-priority next step** (§4 item
   1/4): the crash-vs-attack boundary has already absorbed three block-level
   feature attempts (`reports/crash_vs_attack_feature.md`) with only
   marginal gains, and that report's own diagnosis points at trace-level
   data, not further block-level engineering, as the next lever with real
   headroom.
3. **Structure learning at larger scale** — worth re-running once the
   manipulation class grows further (item 1), since Hill-Climbing's
   weaknesses were partly attributed to data-thinning at the current n=165,
   and to close the `class_conditional`-vs-`fixed` verification gap flagged
   in §0.

---

*Every number in §1-§5 was cross-checked against a fresh LOOCV run or direct
source-file inspection performed in this pass, except where explicitly
marked `[not re-verified this pass]` (§6) or flagged as stale-but-
directionally-reliable (`reports/structure_learning.md`'s exact percentages,
§0/§5). Updated after `reports/crash_vs_attack_feature.md` (`reserve_skew_
localization` adopted into production BN) — §1's production numbers, §2/§3's
confusion matrix and mechanism, and §4's limitations ordering were all
re-verified against the current `src/models.py` and a fresh LOOCV run in this
pass, not carried forward from the pre-update version of this document.*
