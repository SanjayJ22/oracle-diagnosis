# Temporal features: from a standalone side analysis to real model inputs

**Bottom line: this is a genuine, substantial capability gain, and it is now
integrated into `src/models.py`'s actual production defaults — not left as a
side experiment.** Naive Bayes improves dramatically (accuracy 84.2% → 95.2%,
manipulation recall 8.3% → 75%, malfunction recall 66.7% → 100%). The Bayesian
network's calibration improves meaningfully (log-loss 0.290 → 0.215) while its
accuracy and manipulation recall hold flat (93.3%, 83.3%) — a real, if smaller,
win. **Not all 4 proposed temporal features earned their place equally**: a
leave-one-out ablation shows one of them (`temporal_gap_trend`) measurably helps
NB but measurably hurts BN, and — honoring the ablation rather than forcing a
single compromise set — the two models now use deliberately different feature
sets, exploiting an architectural decoupling that already existed in
`models.py`. 3 of the 5 previously-missed manipulation incidents were already
recovered by the earlier class-conditional discretization fix; temporal features
do not additionally recover the remaining 2 (MEVBOTa47b, CurveLlamaLend) —
reported honestly, not oversold.

## 1. Feature definitions, and one honest substitution

Implemented in `src/compute_temporal_features.py`, using each incident's own
`oracle_feed` (from `build_features.py`'s `INCIDENTS` list — every incident has
one) and the existing `get_feed_update_history()` helper (same function, same
on-disk cache, already used by `reports/temporal_trajectories.md`'s standalone
analysis and `src/mine_malfunctions_phase1.py`). Walks backward from each
incident's own anchor round across a fixed **24-hour trailing window** — long
enough to see at least one round even for a daily-heartbeat feed, strictly
trailing by construction (see §4).

- **`temporal_deviation_persistence`** (seconds): how long, counting backward
  contiguously from the incident's own anchor round, price stayed beyond a 5%
  deviation from the window's own median (this project's established "meaningful
  deviation" convention, shared with `RESERVE_SKEW_THRESHOLD` and
  `CROSS_VENUE_TOLERANCE`). 0 if not currently deviated.
- **`temporal_slope`** (fractional change/hour): net directional rate of price
  change from the first to the last round in the window.
- **`temporal_step_change_count`** (count): number of round-to-round price moves
  exceeding 1% within the window — a change-point-count proxy, directly
  targeting the standalone analysis's finding that manipulation shows multiple
  distinct step-changes while volatility tends toward smoother, single moves.
- **`temporal_gap_trend`** (seconds/round, signed): linear-regression slope of
  consecutive update gaps against round order — positive means the oracle is
  updating progressively *slower* leading up to the incident (matching stETH's
  documented staircase-lag signature), negative means it's tightening (matching
  Aug 2024's documented "gap tightens right at the crash trough" signature).

**Honest substitution, not a silent drop**: the task proposed "recovery time
(how fast it returns to baseline)" as a fourth candidate. Taken literally, this
requires looking *past* the incident block to see when price returns to
baseline — exactly the lookahead this task explicitly prohibited ("compute them
with strictly trailing windows, no lookahead"). Rather than violate one
instruction to satisfy the letter of another, `temporal_gap_trend` was
substituted: the closest strictly-trailing analog (cadence-dynamics momentum
going *into* the incident, rather than price-dynamics recovery coming *out* of
it), independently motivated by the standalone analysis's own documented
findings, not invented for this purpose.

## 2. Coverage, per class

| Feature | Manipulation (24) | Malfunction (3) | Volatility (138) |
|---|---|---|---|
| All 4 temporal features | 24/24 | **2/3** | 138/138 |

**Remarkably clean coverage overall** — manipulation and volatility are both
100% covered, because even manipulation incidents whose `reserve_skew` comes
from a venue-specific DeFi pool still have an `oracle_feed` (usually the ETH/USD
fallback) with a normal update cadence to compute temporal features from.

**The one gap is exactly where you'd expect it, and it's structural, not a bug**:
`stETH/ETH heartbeat lag` — one of only 3 malfunction incidents — has just
**1 round** in its 24h trailing window (its own ~24h heartbeat means a 24h window
usually contains at most 1-2 rounds). With fewer than 2 points, no trajectory
statistic (slope, persistence-span, step-count, gap-regression) can be computed
at all — reported as genuine `NaN`, not a forced 0 or an imputed value. This is
a structural irony worth stating plainly: malfunction is precisely the class
where a *slow* update cadence is often part of the diagnosis, and that same slow
cadence is what starves a fixed-length trailing window of enough data points to
describe it.

## 3. Full LOOCV comparison, n=165, class-conditional discretization, hand-drawn structure

| Model | Accuracy | Manip. recall | Malf. recall | Vol. recall | Brier | ECE | Log-loss |
|---|---|---|---|---|---|---|---|
| Deterministic (unchanged, doesn't use temporal features) | 92% (151/165) | 83% | 67% | 93% | — | — | — |
| NB, **before** (7 features) | 84.2% | 8.3% | 66.7% | 97.8% | 0.229 | 0.124 | 1.478 |
| **NB, after (11 features, all 4 temporal)** | **95.2% (157/165)** | **75.0%** | **100.0%** | 98.6% | **0.097** | **0.048** | **1.219** |
| BN, **before** (7 features) | 93.3% | 83.3% | 0/3 | 97.1% | 0.129 | 0.053 | 0.290 |
| **BN, after (10 features, 3 of 4 temporal — see §4)** | **93.3% (154/165)** | **83.3%** | 0/3 | 97.1% | 0.115 | 0.054 | **0.215** |

**NB's transformation is the headline result.** Its manipulation recall — which
was essentially non-functional (8.3%) due to an unclipped Gaussian fit blowing up
on `reserve_skew`'s extreme values (`reports/loocv_150_incidents.md` §4) — jumps
to 75%, and its malfunction recall reaches a perfect 3/3 for the first time in
this project's history. This makes mechanistic sense: NB multiplies per-feature
likelihoods independently, so 4 new, well-behaved (non-extreme-outlier-prone)
features can out-vote `reserve_skew`'s poisoned contribution rather than being
drowned by it. Every calibration metric improves substantially too.

**BN's raw numbers look flat but the composition changed, and calibration
genuinely improved.** With all 4 temporal features, BN's manipulation recall
actually *drops* slightly (79.2%) while volatility recall rises (97.8%) — a
lateral trade, net zero on the overall count. Dropping `temporal_gap_trend`
specifically (§4) restores manipulation recall to 83.3% (matching the
no-temporal baseline exactly) while still improving log-loss substantially
(0.290 → 0.215) — the configuration now in production.

## 4. Ablation: which temporal features earn their place? (BN, leave-one-out)

| Configuration | Accuracy | Manip. recall | Brier | ECE | Log-loss |
|---|---|---|---|---|---|
| All 4 (full) | 93.3% | 79.2% | 0.114 | 0.049 | 0.230 |
| Drop `temporal_deviation_persistence` | 92.7% | 79.2% | 0.116 | 0.048 | 0.232 |
| Drop `temporal_slope` | 93.3% | 83.3% | 0.121 | 0.061 | 0.255 |
| Drop `temporal_step_change_count` | 92.7% | 79.2% | 0.135 | 0.062 | 0.272 |
| **Drop `temporal_gap_trend` (adopted)** | **93.3%** | **83.3%** | **0.115** | 0.054 | **0.215** |
| 0 temporal (original baseline) | 93.3% | 83.3% | 0.129 | 0.053 | 0.290 |

**Verdict per feature, for BN:**
- **`temporal_deviation_persistence` earns its place**: dropping it costs
  accuracy (93.3% → 92.7%) and worsens Brier. **Kept.**
- **`temporal_step_change_count` earns its place most strongly**: dropping it
  costs accuracy (92.7%) and produces the *worst* Brier of any configuration
  tested (0.135, worse even than the 0-temporal baseline). **Kept.**
- **`temporal_slope` is mildly beneficial**: dropping it doesn't cost accuracy
  or manipulation recall, but does cost calibration (Brier 0.121 vs. 0.115,
  log-loss 0.255 vs. 0.215 relative to keeping it). **Kept.**
- **`temporal_gap_trend` does not earn its place for BN**: the configuration
  *without* it beats the full 4-feature configuration on manipulation recall
  (83.3% vs. 79.2%) and log-loss (0.215 vs. 0.230, the best result of any
  configuration tested), while tying it on accuracy. **Dropped from BN.**

**But the same feature earns its place clearly for NB** — checked directly, not
assumed symmetric: NB with the 3-feature set (no `gap_trend`) scores 94.5%
accuracy, 66.7% malfunction recall (down from 100%), Brier 0.111, log-loss 1.428
— every metric measurably worse than NB's full 4-feature result. **This is an
honest, model-dependent split, not an oversight**: it directly echoes this
project's own earlier documented finding that feature attribution is
model-dependent (`reports/project_summary.md` §6), now shown to apply to a
*newly added* feature too, not just the original 7.

**Production decision, already implemented**: `src/models.py`'s `FEATURE_COLS`
(used by NB) includes all 4 temporal features; `BN_RAW_TO_DISCRETE`/`BN_EDGES`
(used by BN) include 3, excluding `temporal_gap_trend`. This was straightforward
because NB's feature list and BN's edge/discretization structure were already
architecturally decoupled in `models.py` — no new plumbing was needed, just two
different, evidence-backed choices using existing infrastructure.

## 5. Do temporal features recover the 5 previously-missed manipulation incidents?

Checked directly against BN's production configuration (3 temporal features),
not just the full 4-feature version:

| Incident | Before (class-conditional, no temporal) | After (+ temporal) | Recovered? |
|---|---|---|---|
| Cream Finance | manipulation ✓ (already recovered by discretization fix) | manipulation ✓ (96.2%) | No change — already fixed |
| MonoX Finance | manipulation ✓ (already recovered) | manipulation ✓ (58.1%, near-coin-flip) | No change — already fixed |
| ResupplyFi | manipulation ✓ (already recovered) | manipulation ✓ (97.9%) | No change — already fixed |
| **MEVBOTa47b** | large volatility event ✗ | large volatility event ✗ (93.1% confidence — *confidently* wrong) | **No** |
| **CurveLlamaLend** | large volatility event ✗ | large volatility event ✗ (99.0% confidence — *confidently* wrong) | **No** |

**Honest answer: temporal features do not additionally recover any incident
beyond what the class-conditional discretization fix (`reports/
discretization_v2.md`) had already recovered.** The 3 incidents shown "already
fixed" were fixed by that earlier change, not by this one — verified by checking
their status is identical with and without temporal features. The 2 that remain
missed are missed *more* confidently with temporal features present (93-99%
confidence vs. lower before), not less — worth noting as a real, unresolved
limitation rather than glossing past it.

**Why not, mechanistically**: the 3 already-recovered incidents' raw temporal
values are `temporal_step_change_count=0` and `temporal_deviation_persistence=0`
— their ETH/USD reference feed was quiet during the window, consistent with
"this was a localized venue event, not broad market movement," reinforcing an
already-correct call rather than flipping a wrong one. MEVBOTa47b and
CurveLlamaLend show *non-zero* step counts (2 and 3) and larger `|gap_trend|`
values on their own ETH/USD reference — enough residual market-like activity on
the broad reference feed that the model still reads them as ordinary volatility,
even with the new evidence. Temporal features add real signal, but not enough to
overturn these two specific, already-hard cases.

## 6. Leakage / no-lookahead check

Verified directly for 3 incidents (`Harvest Finance`, `TOPBPool`, `FTT/USD
pause/deprecation`): in every case, the maximum `updated_at` timestamp among all
rounds returned by `get_feed_update_history` for the 24h trailing window
**exactly equals** the incident's own anchor round's `updated_at` — never
exceeds it. This holds by construction (`get_feed_update_history` walks
*backward* from `start_round_id`, the round in effect at the incident block, and
stops at a `min_timestamp` floor — there is no code path that could return a
later round), and was confirmed empirically rather than only asserted from
reading the code.

## 7. Malfunction n=3 — explicit, and structurally the hardest class for this feature type

Unimproved, as expected: BN's malfunction recall is still 0/3 with temporal
features (unchanged from before). NB's malfunction recall reaches 3/3 — but this
is 3 *incidents*, not a stable rate, and one of those 3 (`stETH/ETH heartbeat
lag`) has **no computable temporal features at all** (§2) — its correct
classification, if any, is not coming from the new features for that specific
incident, since they're simply absent for it. Every temporal-feature number for
this class should be read with the same "3 data points" caveat that has applied
throughout this project — this feature addition does not, and structurally
mostly cannot, change that.

## 8. Downstream reports now stale for their BN/NB numbers, flagged not silently left

`src/two_stage_analysis.py` and `src/two_class_analysis.py` both import
`BN_EDGES`/`BN_RAW_TO_DISCRETE`/`BN_STATE_NAMES`/`FEATURE_COLS` directly and
generically — they will pick up the new temporal features automatically on
their next run, without needing code changes. `src/ablation_audit.py` similarly
iterates `FEATURE_COLS` generically. Their **previously-reported** numbers
(`reports/two_stage_analysis.md`, `reports/two_class_analysis.md`,
`reports/ablation_and_audit.md`) describe the pre-temporal-features model and
are now stale in the same sense every prior structural change in this project
has made earlier reports stale — flagged here, not proactively re-run, since
none was requested this pass.
