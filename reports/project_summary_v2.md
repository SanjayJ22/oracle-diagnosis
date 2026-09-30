# Project Summary v2: Diagnosing Chainlink Oracle Anomalies on Ethereum Mainnet

**SUPERSEDED by `reports/project_summary_final.md`.** This document predates
temporal features, the switch to `fixed` discretization, and the confusion-
matrix analysis that corrected this project's central-thesis framing. Kept
for historical reference only — do not cite its numbers as current.

Read-only consolidation of the complete current project state, replacing
`reports/project_summary.md` (now outdated — it describes the original 20-incident
stage). Every number below was pulled from `data/processed/features.parquet`,
`src/models.py`, and the report files cited, as they stand today. Where a report is
superseded by a later one, that is stated explicitly rather than silently ignored.
**Superseded and not used for any number in this document**: `reports/
loocv_150_incidents.md` (112/105-incident numbers, pre-discretization-fix),
`reports/loocv_200_incidents.md` (165-incident numbers under the failed "global"
discretization scheme), and `reports/discretization_fix.md`'s n=105 "post-fix"
numbers (superseded by the class-conditional scheme now in place). The current,
authoritative model numbers are in `reports/discretization_v2.md` and are restated
here.

## 1. Research question and framing

Given an oracle price that looks wrong, classify the most likely **cause** among
three options — **manipulation** (deliberately faked), **malfunction** (stale/
frozen/deprecated feed), or **genuine large volatility** — using only
market-observable signals (Chainlink, CEX, DEX data). The smart contract is treated
as a **black box**: this is fault diagnosis from external symptoms, not code-level
vulnerability detection. Scope: Ethereum mainnet only, Chainlink `AggregatorV3`/Feed
Registry feeds specifically. Framed throughout as a research feasibility study on a
hand-verified, incrementally-scaled incident set, not a statistically validated
production classifier at any point so far.

## 2. Final dataset — 165 incidents

**24 manipulation, 3 malfunction, 138 large volatility event.** Built incrementally
across four phases (`reports/scaling_plan.md`), each phase's incidents cohort-marked
in `features.parquet` and never removed once verified — only individually-reviewed
and explicitly dropped incidents are absent, never silently excluded.

| Cohort | Manipulation | Malfunction | Volatility | Total |
|---|---|---|---|---|
| original_20 | 5 | 3 | 12 | 20 |
| phase1 | 7 | 0 | 18 | 25 |
| phase2 | 5 | 0 | 55 | 60 |
| phase3 | 7 | 0 | 53 | 60 |
| **Total** | **24** | **3** | **138** | **165** |

### 2a. Manipulation (24) — sourced from SunWeb3Sec/DeFiHackLabs, every one independently verified via live `eth_getTransactionReceipt` (status `0x1`, real block)

- **original_20 (5)**: Harvest Finance, Cream Finance, Indexed Finance, Inverse
  Finance, UwU Lend — the original hand-picked, most-documented incidents.
- **phase1 (7)**: Conic Finance 02, MEVBOTa47b, CompoundUni, CurveLlamaLend,
  ResupplyFi, MonoX Finance, ZunamiProtocol.
- **phase2 (5)**: BalancerV2, Makina, TOPBPool, WiseLending, BalancerV1BPool.
- **phase3 (7)**: AjnaFinance, BalancerBoostedPool2023, DRLVaultV3, EFLeverVault,
  SecuredFi, ThetanutsIndexVault, USM.

**13 additional candidates were found, integrated at some point, and then
explicitly dropped** rather than kept with a misleading signal — reported here for
full transparency, not glossed over:

| Incident | Phase | Reason dropped |
|---|---|---|
| MorphoBlue | 1 | Root cause is a static `SCALE_FACTOR` decimal misconfiguration pricing PAXG at $2.6 trillion from deployment — no trade, no pool interaction, no manipulated venue exists at all. Categorically not a market-observable manipulation. |
| SummerFi, Raft_fi, bZxProtocol, edel-xstock, CompounderFinance, MetaPool, MahaLend | 2 | Each showed `baseline=0, now=0` at every candidate venue tried. Root cause found via direct transaction-log decoding: 2 are diffuse multi-venue exploits (no single trackable balance), 5 are exchange-rate/accounting exploits where the token balance returns to baseline *within the same transaction* — architecturally invisible to a before/after balance-ratio metric regardless of which correct venue is used. |
| BaoCommunity, DeFiPlaza, EFVault, ArrakisGUNI, ThetanutsVaultShareRounding | 3 | 2 atomic round-trips (same failure mode as phase 2's drops, this time caught *before* integration via pre-screening), 1 diffuse 9-token flashloan with no single venue, 2 with genuinely clean signals dropped purely for being below this project's established size floor (~$10-17K vs. the smallest kept incident, ~$20K). |

Full per-incident evidence in `reports/manipulation_candidates_phase1.md`,
`reports/manipulation_candidates_phase2.md` (addendum), and `reports/
manipulation_candidates_phase3.md`.

### 2b. Malfunction (3) — held constant since the original 20, searched three separate times and confirmed structurally rare

FTT/USD pause/deprecation, stETH/ETH heartbeat lag, UST/USD feed freeze (Terra
collapse) — all sourced from documented 2022 collapse events, verified via each
feed's own on-chain round history.

**Why it stays at 3**: `reports/malfunction_search_coverage.md` consolidates three
separate search passes covering **27 distinct feeds** (23 USD-quoted, 4 ETH-quoted
liquid-staking derivatives) via **4 detection methods** (full-history global
mining, event-specific spot-checks, per-window local-median mining, a live
still-frozen check) and **216 individually-reviewed candidates**. **Zero new
incidents survived verification** — every flagged signal resolved to an
explainable, non-anomalous cause (normal stablecoin heartbeat, actively-tracking
updates during a crash, a clean deprecation rather than a freeze, or a real depeg
that the oracle tracked correctly in near-real time). The one repeating pattern
behind all 3 confirmed cases: the underlying asset or exchange **catastrophically
ceased to exist entirely**, leaving no possible price source — a milder stress
event (a custody dispute, a temporary depeg, a protocol wind-down) was never
observed to produce a genuine freeze. A handful of feeds (LDO, sUSD, osETH,
sfrxETH) remain genuinely unchecked due to repeated RPC failures — stated plainly
as a real gap, not silently absorbed into "confirmed clean."

### 2c. Large volatility event (138) — 12 hand-picked + 126 automated-sampling finds, all verified via live cross-venue reads

| Cohort | Method | Threshold | Count |
|---|---|---|---|
| original_20 | Hand-picked, well-known ETH/USD market moves | — | 12 |
| phase1 | Automated sampling, ETHUSDT hourly candles | ≥10% / 24h | 18 |
| phase2 | Automated sampling | ≥5% / 24h | 55 |
| phase3 | Automated sampling | ≥3% / 24h | 53 |

Every incident (all cohorts) verified clean via live Chainlink/DEX/CEX reads at its
block: cross-venue agreement within 5%, no oracle staleness (heartbeat_elapsed ≤
1800s for automated finds). The progressively lower threshold per phase is a
deliberate scaling choice, not a methodology drift — it directly means later-phase
volatility incidents are, on average, calmer moves than earlier ones, a fact that
matters for interpreting the deterministic baseline (§5) and is flagged wherever
relevant.

## 3. Features and reserve_skew venue-resolution work

Seven features per incident, all strictly trailing (no lookahead by construction —
every state read uses `block_identifier=<=incident_block`, verified architecturally
impossible to see future blocks):

`price_dev`, `cross_venue_spread`, `dex_oracle_spread`, `heartbeat_elapsed`,
`congestion`, `reserve_skew`, `ref_realized_vol`.

The first six were the original feature set; **`dex_oracle_spread`** (DEX price vs.
Chainlink price, independent of the CEX reference) was added later specifically to
recover a DEX-side signal for incidents where the CEX comparison alone was
uninformative — it is now used identically to the other six throughout.

**`reserve_skew` (before/after balance ratio at the actually-manipulated venue,
~300 blocks / ~1h apart) is the primary, most reliable manipulation signal**, but
getting it right required substantial venue-resolution work across every phase,
not a one-time computation:

- **Architecture-specific bugs found and fixed**: Balancer V2 pools do not hold
  their own tokens — a shared Vault contract (`0xBA12222222228d8Ba445958a75a0704d566BF2C8`)
  holds everything, indexed by `poolId`. Missing this initially made `BalancerV2`'s
  (and later `BalancerBoostedPool2023`'s) `reserve_skew` read as zero; fixed via a
  `getPoolId()` + `getPoolTokens()` reader, verified against real post-mortem numbers.
- **13 candidates dropped after direct venue re-investigation** (§2a) — the single
  largest source of lost candidates in this project, and the reason phase 3's
  research explicitly pre-screened every new candidate for this exact failure mode
  *before* integration (catching 2 of its own candidates, EFLeverVault and
  ThetanutsIndexVault, needing a venue correction during that pre-screening rather
  than after).
- **TOPBPool's originally-configured venue was simply wrong** (absent from the
  attack transaction's own logs) — found and corrected via direct Transfer-log
  decoding to the real venue, a bonding-curve AMM now showing a clean, extreme,
  persisting `reserve_skew` of **+670,679.59** (the single largest-magnitude value
  in the dataset, and the incident that ultimately motivated the entire
  discretization investigation in §4).
- **`RESERVE_SKEW_CLIP = 3.0`** clips *literal* `±inf` values (e.g. Cream Finance,
  ResupplyFi — a vault going from exactly 0 to nonzero backing) to a finite
  sentinel for arithmetic that can't handle inf directly; it does **not** clip
  large-but-finite values like TOPBPool's, which turned out to matter (§4, §5).

## 4. The discretization arc: a methodological contribution, not a footnote

This project's Bayesian network discretizes every continuous feature into a binary
low/high split before fitting discrete CPDs. **The exact rule for that split was
revised twice**, each time in response to a concretely diagnosed failure, and this
arc is presented here as a first-class finding: getting a "simple" discretization
choice right for a 2-class-imbalanced, small-n, magnitude-heterogeneous dataset is
genuinely hard, and each fix that looked complete at one scale failed at the next
for a *different*, non-obvious reason.

**Stage 1 — sign-based median split (original, n=20 through n=105-uncorrected).**
`value > median(value) → high, else low`. For a feature whose median sits near zero
and is meaningfully bidirectional (a large deviation in *either* direction is the
anomalous signal), this reduces to "is the value positive or negative" — any
manipulation incident with a strongly *negative* deviation lands in the same bucket
as an ordinary small negative reading from a calm volatility incident. Diagnosed at
n=112 in the now-superseded `reports/loocv_150_incidents.md`: BN's manipulation
recall was already collapsing (100% → 50%) as more sign-heterogeneous manipulation
incidents were added.

**Stage 2 — magnitude-aware global threshold (`reports/discretization_fix.md`,
applied at n=105).** `abs(value) > median(abs(value)) → high, else low`, with the
median computed across the *whole* population. This was a genuine, verified fix at
the time: BN's manipulation recall jumped from 35% to 71% at n=105. **It then
failed at n=165** (`reports/loocv_200_incidents.md`): manipulation recall fell to
37.5%, *worse* than the pre-fix n=105 number. Diagnosed directly, not just
observed: because the threshold is a population-wide statistic, it is implicitly
dominated by whichever class has the most incidents (volatility, 138 of 165) — as
phase 3 added 53 more, calmer volatility incidents, the population median drifted
down (0.013478 → 0.008425 for `reserve_skew`), letting **41.3% of all volatility
incidents** cross into the same "far" bucket manipulation occupies (up from an
implied ~4-13% at n=105). This is a genuinely different failure mode from Stage 1's
sign conflation — a **distribution-shift failure of global thresholding** under
class-size imbalance, not a reappearance of the original bug.

**Stage 3 — class-conditional and fixed thresholds (`reports/discretization_v2.md`,
current, n=165).** Two replacements were implemented and compared head-to-head:

- **`class_conditional`**: threshold = geometric mean of the largest and smallest
  per-class median absolute value (training data only). Insulates the threshold
  from population-size imbalance — verified directly, its `reserve_skew` threshold
  moved by only **0.13%** between two LOOCV folds with/without TOPBPool, versus
  Stage 2's **38%** shift when 53 new same-class incidents were added.
- **`fixed`**: a constant per feature, reused from conventions this project already
  established for independent reasons (deterministic baseline's own thresholds,
  the volatility-mining cleanliness gate's 5% cross-venue tolerance, EIP-1559's
  real 50% target gas ratio) — never fit from incident data at all, so it cannot
  drift with the sample **by construction**.

**Both recovered manipulation recall (83.3% and 79.2% respectively) *and* reduced
volatility-called-manipulation confusion (9/138 → 4/138 for both)** — resolving the
tension Stage 2's failure exposed, not trading one failure mode for the other.
`class_conditional` is now the default (better on 5 of 7 metrics); `fixed` remains
available and is the theoretically more shift-proof alternative — see §7 for the
honest tradeoff between the two.

## 5. Models — current numbers at n=165, LOOCV, class-conditional discretization

Source: `reports/discretization_v2.md`, re-verified against `data/processed/
features.parquet` and `src/models.py` directly in this consolidation pass.

### 5a. Deterministic baseline

Rule: `heartbeat_elapsed > 3600s → malfunction`, `elif |reserve_skew| > 0.05 →
manipulation`, `else → large volatility event`. **In-sample only, not LOOCV, and
explicitly flagged as not comparable across dataset scales** (its accuracy is a
compositional artifact of how calm the automatically-sampled volatility incidents
happen to be at each phase's threshold, not a property of the rule improving).

Overall accuracy: **92% (151/165)**. Per-class: manipulation 83% (20/24),
malfunction 67% (2/3), volatility 93% (129/138).

### 5b. Naive Bayes (Gaussian, independent features) — LOOCV

Overall accuracy: **84.2% (139/165)**. Manipulation recall **8.3% (2/24)** —
effectively non-functional for this class, root cause diagnosed in
`reports/loocv_150_incidents.md` §4 and confirmed still active here: NB's Gaussian
fit clips literal infinities but not large finite values, so TOPBPool's real
+670,679.59 `reserve_skew` (and now several other large-magnitude phase-3
incidents) blows up manipulation's fitted variance, drowning the signal for every
other manipulation incident. Malfunction recall **66.7% (2/3)**, volatility recall
**97.8% (135/138)**.

Calibration: **Brier 0.229, ECE 0.124, log-loss 1.478.**

### 5c. Bayesian network (pgmpy; `heartbeat_elapsed` conditioned on `congestion`) — LOOCV, class-conditional discretization

Overall accuracy: **93.3% (154/165)**. Manipulation recall **83.3% (20/24)**,
malfunction recall **0/3**, volatility recall **97.1% (134/138)**.
Volatility-called-manipulation confusion: **4/138 (2.9%)**.

Calibration: **Brier 0.129, ECE 0.053, log-loss 0.290** — beats NB on all three.

**BN is the better model on every axis except malfunction recall**, where neither
model is currently reliable (NB 2/3, BN 0/3 — §7).

## 6. What held across scales: BN's calibration edge, and the manipulation-separability recovery story

| Scale / scheme | NB Brier | BN Brier | NB ECE | BN ECE | NB log-loss | BN log-loss | BN manip. recall |
|---|---|---|---|---|---|---|---|
| n=20 (sign-based) | 0.500 | 0.267 | — | — | — | — | 100% (5/5) |
| n=45 (sign-based) | 0.324 | 0.199 | 0.166 | 0.058 | 2.576 | 0.367 | 100% (12/12) |
| n=105, corrected, sign-based (superseded) | 0.312 | 0.224 | 0.171 | 0.042 | 2.234 | 0.397 | 35% (6/17) |
| n=105, magnitude-aware global (superseded) | 0.312 | 0.151 | 0.171 | 0.047 | 2.234 | 0.302 | 71% (12/17) |
| n=165, magnitude-aware global (superseded, failed) | 0.229 | 0.195 | 0.124 | 0.038 | 1.478 | 0.347 | 37.5% (9/24) |
| **n=165, class-conditional (current)** | **0.229** | **0.129** | **0.124** | **0.053** | **1.478** | **0.290** | **83.3% (20/24)** |

**BN's calibration edge over NB holds on Brier and log-loss at every point shown
in this table, with no exceptions.** ECE is the one metric that occasionally
narrows or ties (both models' ECE is close at several points, and BN's ECE is
marginally worse than global's at n=165 under class-conditional specifically) —
stated plainly rather than rounded up to "holds on all three at every scale,"
since it would not survive a literal reading of the ECE column at every row.

**One honest exception exists outside this table and must be named, not
omitted**: at the intermediate, since-corrected **n=112** state (the
uncorrected version of n=105, before the 8-incident `reserve_skew` resolution
pass — `reports/loocv_150_incidents.md`, itself explicitly superseded), **NB
actually beat BN on Brier (0.150 vs. 0.276)** — the one point in this project's
entire history where that happened. It occurred specifically because 8 of that
snapshot's manipulation incidents had an unresolved (missing-venue) `reserve_skew`,
which is itself the reason that state was corrected down to n=105 rather than
trusted. With that data gap closed, the reversal disappeared at n=105 and never
reappeared. Excluded from the main table above because it is a superseded,
incomplete-data artifact, not a valid independent scale — but named here so the
"BN wins on Brier/log-loss at every scale" claim is not quietly rounding away a
real, once-true counterexample.

**Manipulation separability: a genuine U-shaped recovery, not a monotonic trend.**
100% (n=20, tiny/easy sample) → declining as mechanistic diversity increased and
scale grew (35% at n=105, 37.5% at n=165 under the schemes active at each point) →
recovered to 83.3% once the discretization mechanism itself was fixed for the
*current* scale. The lesson this project draws from its own history: a recall
number at any one snapshot says as much about which discretization/data-coverage
regime was active as it does about whether manipulation is "hard" in some fixed
sense — three of the four major recall swings in this table were caused by fixing
or breaking a thresholding scheme, not by the underlying incidents changing.

## 7. Honest limitations

- **Malfunction is an n=3 class throughout the entire project, unimproved by any
  fix so far.** Three independent search passes across 27 feeds found zero new
  candidates (§2b) — this is a **data-scarcity problem, not a method problem**.
  Neither the discretization fixes in §4 nor any feature change has moved or could
  move this number; BN's malfunction recall is 0/3 under the current default
  scheme, NB's is 2/3, and every number for this class should be read as a
  statement about these exact 3 points, not a stable estimate.
- **The "5 stubbornly-missed" manipulation incidents are not a fixed, immutable
  set — 3 of the 5 were actually recovered by the class-conditional fix, but the
  set of errors shifted rather than shrinking to zero.** Under the failed global
  scheme at n=165, Cream Finance, MonoX Finance, MEVBOTa47b, CurveLlamaLend, and
  ResupplyFi were all misclassified as volatility. Under the current
  class-conditional default, **Cream Finance, MonoX Finance, and ResupplyFi are
  now correctly classified as manipulation** (confidence 95.3%, 74.4%, 74.4%
  respectively); **MEVBOTa47b and CurveLlamaLend remain misclassified** (as
  volatility, at 99.6% and 97.8% confidence — confidently wrong, not
  borderline). Two incidents that were previously *correct* under the global
  scheme newly become wrong under class-conditional: **Inverse Finance** (was
  manipulation at 55.7%, now volatility at 97.4%) and **Conic Finance 02** (was
  manipulation at 55.7%, now volatility at 97.9%). Net effect is a strict
  improvement (24 → 20 correct, up from 9), but it is a genuine recomposition of
  which specific incidents succeed, not a monotonic recovery of the same fixed
  set — worth remembering before assuming any one incident's classification is
  stable across discretization regimes.
- **13 manipulation candidates across three phases were found, integrated, and
  then dropped** (§2a) because the exploit was an atomic round-trip (opens and
  fully closes within one transaction, invisible to a 300-block-apart balance
  snapshot) or a diffuse multi-venue attack with no single trackable balance. This
  is a structural blind spot of the `reserve_skew` feature's design (a block-level
  before/after balance comparison), not a sourcing failure — a meaningfully large
  fraction (13 of 37 ever-found candidates, 35%) of real, well-documented
  manipulation incidents are architecturally invisible to this project's current
  primary manipulation signal.
- **`class_conditional`'s threshold is not immune to every kind of distribution
  shift, only the specific one diagnosed.** It is far more robust than the failed
  global scheme against population-size-driven drift (adding more of an
  already-represented class barely moves it), but if a *future* phase shifted a
  class's own typical magnitude (not just relative class sizes) — for instance, if
  a wave of new manipulation incidents were systematically smaller or larger in
  `reserve_skew` terms than the current 24 — the threshold would still move with
  it, unlike `fixed`, which cannot move at all by construction. This tradeoff is
  explicit and unresolved: `fixed` is more theoretically robust, `class_conditional`
  currently performs better empirically; neither is a permanent, provably-final
  answer.
- **Feature attribution is model-dependent** (established at n=20 in
  `reports/ablation_and_audit.md`, not re-run at n=165 in this pass) — any claim
  of the form "feature X is what identifies class Y" should be read as true for
  one specific model at one specific point in this project's history, not a fixed
  ground truth.

## 8. Novelty and positioning

Verified via two targeted live web searches during this consolidation session —
**this is not a systematic literature review**, and should be treated as a
confirmed starting point, not an exhaustive survey.

**TOAD-ML** (Frontiers in Blockchain, 2026) is the closest published nearest
neighbor: a trust-aware framework combining DeFiHackLabs, CoinGecko, Chainlink,
Uniswap V3, and DeFiLlama data, using an XGBoost classifier with a trust-calibration
layer to produce a binary anomaly label and a continuous [0,1] trust score. Reports
96.72% accuracy / 0.97 AUC-ROC, trained on 19 months of data covering 4 documented
oracle hacks (~60 attack-days). **Key differences from this project**: (1) TOAD-ML
is a **binary** anomaly detector — it does not distinguish deliberate manipulation
from an accidental oracle malfunction, the exact distinction this project's
3-class framing targets; (2) it uses an opaque gradient-boosted classifier, not an
interpretable probabilistic graphical model with per-incident posterior
probabilities and calibration metrics; (3) its incident diversity (4 hacks) is far
smaller than this project's 24 manipulation + 3 malfunction incidents spanning
2020-2026.

**Chockalingam et al.** (a body of work including "Bayesian Network Models in
Cyber Security: A Systematic Review," with Pieters, Teixeira, and van Gelder) is
the methodological precedent for this project's core idea, applied to a different
domain: using Bayesian networks specifically to **distinguish intentional attacks
from accidental technical failures**, based on contributory factors and
observations, in general cyber-physical/critical-infrastructure security risk
assessment. This project is a direct, domain-specific instantiation of that same
methodological idea — manipulation (intentional) vs. malfunction (accidental) —
applied to blockchain oracle price feeds specifically, with a third class (genuine
volatility) added because, unlike most cyber-physical risk settings, "nothing is
actually wrong, the underlying signal really did move" is a first-class, common
outcome that needs its own explicit category here.

**The confirmed-open gap**: the intersection of (a) a market-observable-only,
black-box-oracle framing, (b) an explicit three-way distinction between
manipulation, malfunction, and genuine volatility (not just binary anomaly-or-not),
and (c) an interpretable, calibration-aware probabilistic model (not an opaque
classifier) — applied specifically to Chainlink-style DeFi oracles — does not
appear to be addressed by either of the two closest works found. This is reported
as a confirmed gap based on the two searches performed, not a claim that no such
work exists anywhere.

## 9. Current open next steps

- **Chow-Liu structure learning**: the Bayesian network's structure (`BN_EDGES` in
  `src/models.py`) is hand-specified — a star topology (label → every feature)
  plus one added edge (`congestion → heartbeat_elapsed`). Chow-Liu is the standard
  algorithm for learning a maximum-likelihood tree-structured dependency graph
  directly from data, and would let the network discover whether other feature
  dependencies (beyond the one hand-added edge) exist and matter, rather than
  relying on manual specification. Not yet attempted at any scale in this project.
- **Temporal features as inputs**: `reports/temporal_trajectories.md`'s standalone
  analysis (3 representative incidents, one per class, never fed into
  `features.parquet`) found that manipulation shows multiple distinct step-changes
  over time (not a single atomic jump), malfunction shows a visible staircase-lag
  pattern against a continuous DEX reference, and volatility shows tightening
  update cadence exactly at the point of fastest price movement — three
  qualitatively distinct temporal signatures that the current *static*,
  single-snapshot feature set cannot see. Promoting trajectory-derived statistics
  (e.g. number of step-changes, staircase-vs-continuous divergence, update-cadence
  response to price movement) from that standalone analysis into real, model-facing
  features is a concretely scoped, well-motivated next step — flagged in
  `reports/richer_features.md` §3 as gated behind a larger dataset to avoid
  overfitting, and now worth revisiting given the dataset has grown from 20 to 165.
