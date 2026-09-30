# Project Summary: Diagnosing Chainlink Oracle Anomalies on Ethereum Mainnet

**SUPERSEDED — see `reports/project_summary_v2.md`.** This document describes the
original 20-incident stage only. The dataset has since grown to 165 incidents
(24 manipulation, 3 malfunction, 138 volatility) across three further scaling
phases, and the Bayesian network's discretization scheme has been revised twice
since this was written. Kept here for historical reference only.

Read-only consolidation of the complete project state. All numbers below were re-pulled
from `data/processed/features.parquet` and by re-running `src/models.py` and
`src/loocv_validation.py` fresh, or read verbatim from the report files cited. No
feature or model changes were made to produce this document.

## 1. Research question and framing

Given an oracle price that looks wrong, classify the most likely **cause** among three
options — **manipulation** (deliberately faked), **malfunction** (stale/frozen/deprecated
feed), or **genuine large volatility** — using only market-observable signals (Chainlink,
CEX, DEX data). The smart contract is treated as a **black box**: this is fault diagnosis
from external symptoms, not code-level vulnerability detection. Scope: Ethereum mainnet
only. Framed throughout as a feasibility demonstration on a small, hand-verified incident
set (20 incidents), not a statistically validated production classifier.

## 2. Final dataset — 20 incidents

Source: `reports/final_incidents.md`. Every block number and (where applicable) transaction
hash below was independently confirmed on-chain, not copied from a post-mortem.

### Manipulation (5) — sourced from SunWeb3Sec/DeFiHackLabs, verified via live `eth_getTransactionReceipt`

| Incident | Date | Block | Label |
|---|---|---|---|
| Harvest Finance | 2020-10-26 | 11,129,474 | manipulation |
| Cream Finance | 2021-10-27 | 13,499,798 | manipulation |
| Indexed Finance | 2021-10-15 | 13,417,949 | manipulation |
| Inverse Finance | 2022-06-16 | 14,972,419 | manipulation |
| UwU Lend | 2024-06-10 | 20,061,319 | manipulation |

Each tx hash confirmed `status: 0x1` on mainnet; Cream and Indexed additionally
cross-checked against their post-mortems' own stated hashes.

### Malfunction (3) — sourced from documented 2022 collapse events + Chainlink Feed Registry lookups, verified via each feed's own on-chain round history

| Incident | Date | Block | Label |
|---|---|---|---|
| stETH/ETH heartbeat lag | 2022-06-18 | 14,984,168 | malfunction |
| FTT/USD pause/deprecation | 2022-11-28 | 16,069,381 | malfunction |
| UST/USD feed freeze (Terra collapse) | 2022-06-11 | 14,942,628 | malfunction |

UST is counted as **one incident** despite two independently-frozen aggregator contracts
on-chain (old aggregator froze 2022-06-11; a replacement took over the registry slot and
froze again 2024-07-09) — same root cause, one label, per explicit direction.

### Large volatility event (12) — sourced from well-known ETH/USD market moves, verified via ETH/USD round history directly on-chain

| # | Incident | Date | Block | Move |
|---|---|---|---|---|
| 1 | May 19 2021 crash | 2021-05-19 | 12,465,029 | -52.1% |
| 2 | June 2022 Celsius deleveraging | 2022-06-15 | 14,966,742 | -43.1% |
| 3 | Nov 2022 FTX collapse | 2022-11-09 | 15,935,789 | -34.3% |
| 4 | March 2023 banking-wobble rally | 2023-03-14 | 16,826,924 | **+29.5%** |
| 5 | Aug 2023 selloff | 2023-08-17 | 17,937,299 | -15.6% |
| 6 | March 2024 cycle-high rally | 2024-03-06 | 19,378,953 | **+18.4%** |
| 7 | Aug 5 2024 carry-trade unwind | 2024-08-05 | 20,460,558 | -32.5% |
| 8 | Dec 2024 breakdown from cycle high | 2024-12-20 | 21,443,591 | -24.4% |
| 9 | April 2025 tariff shock | 2025-04-09 | 22,228,063 | -28.5% |
| 10 | Oct 10-11 2025 flash crash | 2025-10-10 | 23,549,972 | -23.7% |
| 11 | Nov 4 2025 crash | 2025-11-04 | 23,728,675 | -21.4% |
| 12 | Feb 6 2026 crash | 2026-02-06 | 24,394,166 | -42.4% |

Label is deliberately direction-agnostic — #4 and #6 are rallies, not crashes. No tx hash
recorded for this class (a volatility label attaches to a price level, not a triggering
transaction); each move's max update gap was checked against the feed's own median for
that window to rule out malfunction contamination (all stayed under ~62 minutes absolute).

## 3. Features and their reliability

Six features per incident, all strictly trailing (no lookahead by construction):
`price_dev`, `cross_venue_spread`, `heartbeat_elapsed`, `congestion`, `reserve_skew`,
`ref_realized_vol`.

**reserve_skew is the reliable manipulation signal.** Values for the 5 manipulation
incidents (from `features.parquet`): Harvest -0.1297, Cream +inf (clipped to +3.0),
Indexed -0.9861, Inverse +0.0238, UwU +0.0705. Cream's is a real infinite jump (vault went
from ~0 to ~1.0 backing — this *is* the exploit). Inverse's (+2.4%) is a known
**understatement**: the flash-loan deposit and its self-reversal land in the same block,
so the post-block balance partially nets out the attacker's own deposit — it overlaps with
ordinary volatility-day DEX moves.

**price_dev is noisy specifically on the Curve-based manipulation incidents.** Harvest's
price_dev (+24.4%) assumes a 1.0 peg for the raw yUSDC/yUSDT balance ratio, but the
temporal trajectory data (Section 5) shows this ratio sits at ~1.24–1.32 throughout the
entire window regardless of the attack (yToken yield-accrual drift, unrelated to the
exploit) — the reference point is wrong for this incident. reserve_skew is unaffected
(same-venue before/after comparison over ~1h, where yield drift is negligible), which is
why reserve_skew, not price_dev, is the feature actually relied on for manipulation.

**heartbeat_elapsed anchoring artifact (found and fixed).** Originally computed by reading
the oracle round *at* the incident's own anchor block — which for malfunction/volatility
incidents (anchored to an oracle-update transaction itself) trivially returned 0 for all 15
non-manipulation incidents, and a real nonzero gap only for the 5 manipulation incidents
(anchored to an unrelated exploit tx). This was a structural artifact, not a real freshness
signal — models were exploiting it. Fixed in `src/recompute_heartbeat_elapsed.py` by always
reading the round at `block_number - 1` (strictly before the anchor), applied uniformly
across all 20 incidents. Manipulation values were confirmed essentially unchanged by the
fix (494–3,489s); malfunction/volatility values became real (malfunction: 950–86,428s;
volatility: 12–1,200s).

Missingness (from `features.parquet`, counts of NaN per class):

| feature | manipulation (n=5) | malfunction (n=3) | volatility (n=12) |
|---|---|---|---|
| price_dev | 2 | 2 | 0 |
| cross_venue_spread | 5 | 3 | 0 |
| heartbeat_elapsed | 0 | 0 | 0 |
| congestion | 1 | 0 | 1 |
| reserve_skew | 0 | 2 | 0 |
| ref_realized_vol | 0 | 2 | 0 |

`cross_venue_spread` is missing for every manipulation and malfunction incident (8/8) and
present for every volatility incident (12/12) — a real availability asymmetry (see
Section 6 audit), not a fabricated signal, since both models skip missing features rather
than encoding absence as a value.

## 4. Models — exact numbers

### 4a. Deterministic baseline
Rule: `heartbeat_elapsed > 3600s → malfunction`, `elif |reserve_skew| > 0.05 → manipulation`,
`else → large volatility event`.

Overall accuracy: **11/20 = 55%**. Per-class recall: manipulation 4/5 = 80%, malfunction
2/3 = 67%, volatility 5/12 = 42%. Misses UST (freeze *starts* after the anchor, no
preceding stale gap to catch) and 7 of 12 volatility incidents (their `|reserve_skew|`
overlaps the 5% threshold and gets called manipulation).

### 4b. Naive Bayes (Gaussian, independent features)

**In-sample** (fit and scored on the same 20 points): **20/20 = 100%**, precision/recall
100% in every class. Explicitly not a validated result — flagged as such in the model's own
output.

**LOOCV** (honest, held-out): **15/20 = 75%** overall. Manipulation 4/5 = 80%, malfunction
2/3 = 67%, volatility 9/12 = 75%. Misclassified when held out: Cream Finance (→malfunction),
FTT/USD (→manipulation), May 19 2021 crash (→malfunction), March 2023 rally
(→manipulation), March 2024 rally (→manipulation).

**Calibration**: Brier score **0.500** (reference: always-uniform 1/3-1/3-1/3 scores
~0.667). All 20 LOOCV predictions land in the ">90% confidence" bucket, which is only
75% (15/20) accurate at that confidence level — i.e. the model is **overconfident**: it
outputs ≈100%-confidence, entropy≈0 posteriors for nearly every incident, including wrong
ones (e.g. FTT/USD: 100% confidence, wrong). Mean entropy by true class: manipulation 0.01,
malfunction 0.00, volatility 0.02 (n=5/3/12) — essentially degenerate, carrying no
discriminating uncertainty signal.

### 4c. Bayesian network (pgmpy; `heartbeat_elapsed` conditioned on `congestion`, not independent)

**In-sample**: **16/20 = 80%**. Manipulation precision 62% (5/8), recall 100% (5/5);
malfunction precision 50% (1/2), recall 33% (1/3); volatility precision 100% (10/10),
recall 83% (10/12).

**LOOCV**: **16/20 = 80%** overall. Manipulation 5/5 = 100%, malfunction 1/3 = 33%,
volatility 10/12 = 83%. Misclassified when held out: stETH/ETH (→manipulation, 59%
confidence), FTT/USD (→manipulation, 53%), March 2024 rally (→manipulation, 85%), Dec 2024
breakdown (→malfunction, 67%).

**Calibration**: Brier score **0.296** (better-calibrated than NB). Confidence buckets:
>90% → 9/9 = 100% correct; 70–90% → 4/5 = 80% correct; 50–70% → 2/5 = 40% correct; <50% →
1/1 = 100% correct (this is the only sub-50%-confidence call: UST/USD, correct at 43%
confidence — essentially a coin-flip that landed right). Mean entropy by true class:
manipulation 0.70, malfunction **0.92**, volatility 0.18 (n=5/3/12) — malfunction is by far
the least confidently-classified class.

## 5. Temporal trajectory findings (`reports/temporal_trajectories.md`)

Separate, standalone trajectory analysis on 3 representative incidents (one per class) —
does not feed into `features.parquet` or the models above.

- **Manipulation (Harvest Finance)**: Curve Y-pool yUSDC/yUSDT ratio sampled every ~10
  blocks across ±1h. Revealed **5 distinct step-changes over ~2 hours**
  (1.316 → 1.271 → 1.247 [anchor block] → 1.236 → 1.290), matching the post-mortem's
  description of a repeated multi-cycle attack, not a single atomic flash loan. ETH/USD
  (unrelated venue) shows no corresponding move ($408–411, ordinary noise) and normal
  update cadence throughout (750–2,250s gaps) — the failure is entirely localized to the
  exploited venue.
- **Malfunction (stETH/ETH)**: Chainlink STETH/ETH (~24h updates) vs. the wstETH/WETH
  Uniswap V3 pool as a continuous reference (corrected for wstETH's own ~7.5% staking-yield
  accrual). Described as **"the cleanest of the three"** — a continuously-wiggling DEX line
  against a staircase-stepping Chainlink line that visibly lags at each flat segment. The
  heartbeat itself is visible: mostly pinned at 24h, occasionally 12–20h when a deviation
  threshold triggers an early update.
- **Volatility (Aug 5 2024 crash)**: Chainlink ETH/USD, Binance.US ETHUSDT, and WETH/USDC
  Uniswap V3, overlaid across ~6 days. All three venues move together almost
  indistinguishably through the entire crash ($3,200 → $2,200, partial recovery to ~$2,500)
  — no lag, no localized divergence. The freshness panel shows the update gap *tightening*
  right at the crash trough versus calmer days before/after — the oracle updates *more*
  often exactly when the price moves fastest, the opposite of the malfunction signature.

**HMM regime-fitting: attempted, not usable, for three different reasons** — reported
honestly rather than forced:

| Trajectory | Points | Result |
|---|---|---|
| Harvest Y-pool ratio | 56 | Converged, but 55/56 state switches with means only 0.07 pooled-std apart — flip-flopping on noise, not a regime split. |
| stETH DEX-vs-oracle spread | 77 | Converged but degenerate (one state collapsed to near-zero variance). |
| Aug 2024 1-min log returns | 8,579 | Converged cleanly (no excessive switching), but state means only 0.04 pooled-std apart — no real 2-state structure exists to find. |

The explicit state-transition descriptions above (not the HMM) are the trustworthy version
of this analysis on sequences this short (56–77 points for two of the three).

## 6. Ablation result (`reports/ablation_and_audit.md`)

Drop-one-feature, re-run under LOOCV. **Feature attribution is model-dependent** — the
"obvious" story (reserve_skew carries manipulation, heartbeat_elapsed carries malfunction)
holds only partially:

| feature dropped | NB overall Δ | NB manip Δ | NB malf Δ | BN overall Δ | BN manip Δ | BN malf Δ |
|---|---|---|---|---|---|---|
| price_dev | +0% | +0% | +0% | -5% | +0% | **-33%** |
| cross_venue_spread | +0% | +0% | +0% | +0% | +0% | +0% |
| heartbeat_elapsed | +0%* | +0%* | +0%* | **-20%** | **-60%** | **-33%** |
| congestion | +0%* | +0% | +0%* | +0% | +0% | +0% |
| reserve_skew | **-5%** | **-20%** | +0% | +0% | +0% | +0% |
| ref_realized_vol | **-5%** | +0% | **-33%** | **-25%** | **-80%** | **-33%** |

(`*` = net-zero hides real flips that cancel, e.g. NB dropping heartbeat_elapsed flips
March 2024 rally wrong→correct *and* Oct 2025 flash crash correct→wrong.)

- **NB manipulation**: carried by reserve_skew, as hypothesized (loses Indexed Finance
  when dropped).
- **BN manipulation**: NOT carried by reserve_skew (0% change, zero flips) — actually
  carried by **ref_realized_vol** (-80%, loses 4/5) more than heartbeat_elapsed (-60%,
  loses 3/5). Contradicts the hypothesis for BN specifically.
- **NB malfunction**: NOT carried by heartbeat_elapsed (0% net, no flips at all) — carried
  by ref_realized_vol (-33%, loses UST/USD). Contradicts the hypothesis for NB.
- **BN malfunction**: heartbeat_elapsed and price_dev both show -33%, but it's the **same**
  single incident (UST/USD) lost both times — one incident correctly called via two
  redundant signals, not two independent confirmations; with n=3 and only 1 ever right
  under LOOCV, this is a description of these 20 points, not a validated pattern.

Leakage/robustness audit on the same pass: **zero perfect single-feature separators**
found; **no remaining lookahead** (every read is a point-in-time EVM state query, verified
architecturally impossible to see future blocks); the only structural asymmetry is
`cross_venue_spread`'s availability pattern (Section 3), not exploitable as a disguised
zero.

## 7. Cohesion findings (`reports/cohesion_findings.md`)

**Confusion structure (BN, LOOCV)**: manipulation has 100% recall but only 62.5% precision
(5/8 predicted-manipulation calls are actually manipulation) — it acts as an attractor for
uncertain cases, not a class that gets missed. **Malfunction blurs with manipulation, not
volatility** — both malfunction errors (stETH, FTT) are called manipulation, none are
called volatility.

**Root cause, traced to a single mechanism**: the BN discretizes `heartbeat_elapsed` at one
learned median (**265s**). Every manipulation incident (494–3,489s) and every malfunction
incident (950–86,428s) falls on the same "high" side of that split, erasing the magnitude
gap that would separate "moderately stale" from "extremely stale." FTT additionally has
only `heartbeat_elapsed` and `congestion` observed (its other 4 features are missing), so
with that signal flattened its posterior is nearly uniform (53%/24%/23%) — entropy 0.93,
the single highest in the dataset: a near-coin-flip that landed wrong, not a confident wrong
call. The two rally-labeled volatility incidents are the model's most
manipulation-suspicious volatility calls (March 2024: 85% manipulation posterior, a
confident wrong call; March 2023: 22% manipulation posterior, correct but elevated vs.
crash days' 0–2%) because both have among the lowest realized vol of all 12 volatility
incidents, resembling manipulation's calm-market signature.

**Entropy-trajectory link**: NB's LOOCV entropy is degenerate (near 0 for nearly all 20
incidents, including wrong ones) and was excluded; BN's entropy (real spread, 0.014–0.959)
was used instead. The 3 malfunction incidents are the **3 highest-entropy incidents of all
20**. Cross-referencing the 3 trajectory incidents: Aug 2024 agrees (entropy 0.030, rank
4th–5th most confident, and an unambiguous trajectory); Harvest partially agrees (entropy
0.667, rank 15th of 20, despite a clearly-localized trajectory); **stETH disagrees clearly**
— described as the cleanest trajectory of the three, yet its static entropy (0.876) is the
3rd-least-confident of all 20, and it's misclassified. Same mechanism as above: the
temporal view shows the full-magnitude 24h staircase lag; the static snapshot compresses it
to one binary bit that manipulation incidents also trip. Scope caveat: all 3 trajectories
were deliberately chosen as clean per-class examples, so this is 3 data points, not a
validated correlation.

## 8. Malfunction hunt result

No dedicated report file was produced for this pass (timeboxed, 90 minutes, read-only
research); the numbers below were verified on-chain directly in that session and are
recorded here for the first time.

**Result: zero new incidents found**, across two techniques:

- **Registry-lookup for frozen/deprecated feeds**: CEL/USD, LUNA/USD, renBTC, SRM have no
  Ethereum mainnet Chainlink feed at all (checked via ENS `<pair>.data.eth` resolution).
  FEI/USD and BUSD/USD do exist and are now dead, but both show a **clean deprecation**
  pattern, not a freeze: FEI/USD updated normally (~1h cadence) right up to block
  17,990,373 (2023-08-25), then the whole proxy started reverting 12 seconds later.
  BUSD/USD did the same up to block 24,994,113 (2026-04-30), price pinned near $1.00 the
  whole time. Neither shows staleness building up before removal — a fundamentally
  different (and safer) failure mode than FTT/UST, which are **still queryable today**,
  silently returning their frozen 2022 price with no revert.
- **Heartbeat-lag on liquid-staking/wrapped assets during depegs**: WBTC/BTC during the
  Aug 2024 BitGo/Justin Sun custody dispute showed a rigid ~24h heartbeat with max
  deviation 0.35% — the confidence crisis never produced a price move large enough to
  trigger anything. ezETH/ETH during its real, sharp April 24 2024 depeg (to ~0.82 ETH)
  updated every 12–600 seconds *during* the crash — the oracle tracked it correctly in
  near-real time, the opposite of a lag. cbETH/ETH shows no reaction to the Jun 2023
  Coinbase SEC lawsuit window at all, consistent with it being an internal NAV-style
  calculation rather than a market price.

**Finding**: the silent-freeze-at-last-price failure mode (FTT, UST) appears structurally
rare — it required the underlying asset or exchange to **catastrophically cease to exist
entirely** (no possible price source remained at all), not merely a protocol wind-down,
temporary panic, or custody dispute. Every milder stress event checked either got a clean
deprecation (feed removed while still functioning normally) or was tracked correctly by a
modern deviation-threshold feed. This is consistent with, and helps explain, why only 3
malfunction incidents exist in this dataset after an extensive search.

## 9. Honest limitations

- **Feature attribution is model-dependent, not a fixed ground truth.** Section 6's
  ablation shows NB and BN rely on different features for the same class. Any claim of the
  form "feature X is what identifies class Y" should be read as true for one specific
  model, not as a general property of the signal.
- **Malfunction is an n=3 class throughout.** Every LOOCV, calibration, and ablation result
  for malfunction is a statement about 3 points (2 of which are usually wrong under BN
  LOOCV). Its mean entropy (0.92) is the highest of any class specifically because there is
  too little data to pin down a stable pattern, not because malfunction is inherently
  harder to detect.
- **Inverse Finance's manipulation signal is understated because the exploit was atomic.**
  Its reserve_skew (+2.4%) nets out most of the true deposit because the flash-loan deposit
  and its self-reversal occur in the same block — the feature is measuring a partially
  self-cancelled snapshot, not the full magnitude of the attack.
- **BN's median-split discretization is coarse enough to erase real magnitude differences.**
  The single root cause identified in Section 7 (heartbeat_elapsed's 265s threshold
  collapsing 494s and 86,428s into the same bucket) likely affects other continuous
  features discretized the same way; it was only explicitly traced for heartbeat_elapsed.
- **Harvest's price_dev uses a demonstrably wrong reference point** (an assumed 1.0 peg for
  a ratio that sits at ~1.24–1.32 even when healthy) — flagged in Section 3, not corrected,
  since reserve_skew (unaffected) is the feature actually used for manipulation.
- **cross_venue_spread's availability is asymmetric by class** (Section 3) — an artifact of
  which venues got mapped to which feature, not fixed, though not exploitable as a
  disguised zero the way the original heartbeat_elapsed bug was.
- **20 incidents total is a feasibility demonstration, not a validated production
  classifier** — stated at the outset and true throughout; every in-sample number in this
  document (NB 100%, BN in-sample 80%) is explicitly flagged in the model outputs
  themselves as not a held-out result.
