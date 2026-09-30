# Design proposal: richer features

This is a **plan, not an implementation**. It does not change `models.py`,
`build_features.py`, `features.parquet`, or the current 6-feature, 3-model,
20-incident pipeline in any way. Two small experimental prototypes are included at
the end (§6) purely to check feasibility on already-cached data; they are not wired
into the pipeline and are not validated features.

## 1. Why this is needed

The current feature set (`price_dev`, `cross_venue_spread`, `heartbeat_elapsed`,
`congestion`, `reserve_skew`, `ref_realized_vol`) is low-dimensional by design, and
`reports/ablation_and_audit.md` already shows the cost of that: feature attribution
is model-dependent and unstable (NB and BN rely on different features for the same
class), and no feature comes close to being a clean separator on its own. Some of
this instability is a real property of the problem; some of it is simply that 6
features leave little room to describe *how* a price went wrong, only *that* it did.
The proposals below aim at that second part — more informative, not just more,
features — while being explicit that most of them should not be added to the
modeled set until the incident count grows well past 20 (§5).

## 2. Multi-oracle disagreement

**`chainlink_pyth_spread`** — `(chainlink_price − pyth_price) / pyth_price` at the
incident block.

- Targets: manipulation typically forces a single price source (the exploited venue,
  or the one oracle reading it) away from an independent second oracle that wasn't
  touched — a genuine disagreement between two *oracles*, not just oracle-vs-market.
  Malfunction should show the same disagreement, but persistently and without a
  triggering transaction. Volatility should show close agreement, since both oracles
  are tracking the same real move.
- Data source: **new.** Pyth is not currently fetched anywhere in this repo; would
  need Pyth's Hermes API or its on-chain price feed contract on Ethereum mainnet.
- **Coverage gap to flag now, not discover later:** Pyth's Ethereum mainnet feeds
  went live in 2023. Of the 8 manipulation/malfunction incidents, only UwU Lend
  (2024) postdates that — Harvest (2020), Cream/Indexed (2021), Inverse and the
  stETH/FTT/UST malfunctions (all 2022) predate Pyth on Ethereum entirely. This
  feature would be usable for essentially none of the incidents where it's most
  wanted, only for newer volatility incidents (2023 onward) and UwU Lend. Historical
  coverage, not implementation effort, is the real blocker here.

**`chainlink_twap_spread`** — `(chainlink_price − dex_TWAP_price) / dex_TWAP_price`,
using the DEX pool's own time-weighted average (Uniswap V3's built-in `observe()`),
not the instantaneous spot price `cross_venue_spread` already uses.

- Targets: an instantaneous spot price can itself be the manipulated quantity (that's
  the entire premise of a spot-price oracle attack); a TWAP over the preceding
  window is specifically resistant to a single-block manipulation, so a spread
  between Chainlink and a DEX TWAP should isolate "the pool itself is being actively
  distorted right now" from ordinary tracking error.
- Data source: **not new** for the incidents that already have a V3 pool identified
  (`WSTETH_WETH_V3` for stETH, `WETH_USDC_V3` for all 12 volatility incidents) — both
  are Uniswap V3 pools, which expose `observe()` for any historical block via the
  same Alchemy archive connection already in use. This is an additional on-chain
  read against a contract already being queried, not a new source. It does not reach
  the 4 manipulation incidents with no identified DEX pool at all (Harvest, Cream,
  Indexed, UwU) or FTT/USD — those need §4 first.

## 3. Trajectory-derived features, made static

`reports/temporal_trajectories.md` already describes three qualitatively distinct
signatures (multi-step manipulation, staircase-lag malfunction, tight co-movement
under volatility) for one incident per class. The proposal is to turn those
descriptions into scalar features computed the same way for **all 20** incidents,
not just the 3 case studies.

| Feature | Definition (proposed) | What it targets | New data source? |
|---|---|---|---|
| `step_change_count` | Number of distinct plateau-to-plateau jumps in the reference/oracle deviation over a fixed pre-incident window, via a real change-point method (not a fixed threshold — see §6) | Manipulation-by-repeated-cycles (Harvest) vs. malfunction's single per-update staircase step vs. volatility's continuous drift | No — reuses round-history / DEX-price-history already fetched for the trajectory analysis, generalized to all 20 |
| `deviation_persistence` | Cumulative time the oracle-vs-reference deviation stays above a threshold | Malfunction should persist for hours/days; manipulation for one exploit window; volatility should rarely cross the threshold at all since both sides move together | No, same as above |
| `deviation_slope` | Rate of change of the deviation immediately before the incident block | Gradual drift (staleness accumulating) vs. a discrete jump (an exploit transaction) vs. near-zero slope (co-moving venues) | No, same as above |
| `recovery_time` | Time from peak deviation back under a threshold | Manipulation/atomic exploits often revert within the same or a few blocks; a genuine freeze does not recover until the feed is fixed or replaced; volatility has no "recovery" in this sense because there's no divergence to recover from | No, same as above |

**The real cost here is not code, it's data collection.** Only 3 of 20 incidents
currently have a pulled multi-hour trajectory window (Harvest, stETH, Aug 2024);
the other 17 would each need their own DEX/CEX/Chainlink history pulled around their
anchor block — the same kind of archive-RPC work `temporal_trajectories.py` already
does per-incident, just repeated 17 more times. That is a real, non-trivial data
pull, not a formula change.

## 4. Finer-grained liquidity and depth measures

Current liquidity signal is coarse: `reserve_skew` is a single before/after
balance-ratio snapshot, and `congestion` is base-fee level, not pool-specific at all.

| Feature | Definition (proposed) | What it targets | New data source? |
|---|---|---|---|
| `depth_within_band` | DEX liquidity available within ±X% of the current price (Uniswap V3 concentrated-liquidity distribution near the active tick) | Thin, easily-moved pools are a precondition for spot-price manipulation; would help explain *why* some incidents (e.g. Indexed Finance's custom weighted pool) show extreme `reserve_skew` while others (Inverse Finance's atomic flash-loan case) show an understated one, per `project_summary.md` §3/§9 | New reads (tick/position data), but against pools already being queried for `reserve_skew` — not a new venue |
| `pool_tvl_trend` | Change in total pool value over the hours/days preceding the incident | A liquidity withdrawal shortly before an attack is a documented precursor pattern in some of these post-mortems; would need to be checked per-incident, not assumed | Reuses existing balance-reading code (`fetch_curve.get_coin_balances`, `fetch_dex`), applied over a longer window than currently pulled |
| `slippage_to_move_x_pct` | Estimated trade size needed to move the pool price by a fixed percentage, from the pool's own state | A direct, venue-agnostic manipulability measure, more informative than `reserve_skew` alone since it doesn't require an exploit to have already happened to be meaningful | New computation from existing pool-state reads (V3 tick liquidity or V2 constant-product math) — no new venue, but new logic |

## 5. Cross-venue features for the incidents that currently have none

> **Status: implemented** (`src/build_features.py`, `dex_oracle_spread` column). Actual
> outcome differs from the estimate below in one important way, corrected here rather
> than left stale: it recovers **1 of 8** previously-missing incidents (stETH), not 4.
> Harvest/Inverse/UwU's Curve-derived quantities (a peg ratio, a raw WBTC balance) turned
> out NOT to share units with those incidents' Chainlink feed (ETH/USD or BTC/USD
> fallbacks for an unrelated asset) — computing a spread against them would have been a
> fabricated comparison, so it was correctly left missing there instead, per §6's
> overfitting/artifact discipline. Full before/after numbers were reported directly in
> conversation, not duplicated into this file. One caveat found during implementation:
> stETH's recovered value is dominated by an uncorrected wstETH-wrapping factor (see the
> comment in `build_features.py`) — flagged as unreliable for that one row, not fixed
> (would need a new on-chain read, out of scope for this change).

This is the one item worth doing regardless of the dataset-scaling question, because
it targets a gap in the **existing** feature, not a new dimension.

`project_summary.md` §3 documents that `cross_venue_spread` is missing for **8/8**
manipulation and malfunction incidents (all 5 manipulation, all 3 malfunction),
while present for all 12 volatility incidents. Reading `build_features.py`'s
formula directly explains why:

```
cross_venue_spread = (dex_price − cex_price) / cex_price
```

This is **CEX-anchored** — it goes missing whenever `cex_symbol` is `None`, which is
true for the true manipulated asset in 4 of 5 manipulation incidents and for both
stETH and FTT in the malfunction class (none of these have a Binance.US listing).
Critically, this is true **even for stETH, which already has a DEX price series
fetched** (`WSTETH_WETH_V3`, used throughout the trajectory analysis) — the data
exists, the formula just routes it through a CEX leg that doesn't exist for this
asset, so it's discarded.

**Proposed addition: `dex_oracle_spread = (dex_price − chainlink_price) /
chainlink_price`** — compares the DEX price directly against the same Chainlink feed
being diagnosed, with no CEX leg at all.

- Recovers a genuine cross-venue check for exactly the incidents with the least
  current evidence, using data **already fetched for other purposes**:
  - stETH: the `WSTETH_WETH_V3` pool (already queried).
  - Harvest, Inverse, UwU Lend: their Curve pool balances (already queried in
    `fetch_curve.py` for `reserve_skew`) can also yield an implied pool price.
  - Cream Finance: no natural DEX price exists (the exploit was against vault
    share-price accounting, not a swap pool) — would remain missing.
  - Indexed Finance: DEFI5's pool is a custom weighted-pool contract, not Uniswap
    V2/V3 — `fetch_dex.py` doesn't support it; would need new pool-math, not just a
    new formula.
  - FTT/USD: no DEX pool has been identified for FTT at all — still missing, this
    needs discovery work, not a formula fix.
- Net effect: recovers the feature for **4 of 8** currently-missing incidents
  (stETH, Harvest, Inverse, UwU) from data already on disk or already one function
  call away; the remaining 4 (Cream, Indexed, FTT, and UST which also has no DEX
  pool identified) still need either new venue discovery or genuinely don't have
  one.

## 6. Overfitting caveat — most of this should wait for a larger dataset

At 6 features and 20 incidents (one class with n=3), the feature-to-incident ratio
is already thin. `reports/ablation_and_audit.md`'s central finding — that feature
attribution flips between models and that no single feature is a clean separator —
is itself partly a symptom of not having enough data to pin down which features
actually matter, not only a statement about the features themselves.

Adding §2's 2 features + §3's 4 features + §4's 3 features on top of the current 6
would produce a **15-feature model on 20 points**, close to one feature per
incident. At that ratio, LOOCV becomes close to meaningless (each fold is fitting
a high-dimensional model to 19 points), ablation results would be dominated by noise
rather than signal, and near-perfect in-sample separation would become almost
guaranteed without being evidence of anything — the same failure mode the ablation
report already went out of its way to check for and rule out (`"zero perfect
single-feature separators found"`) would become far more likely to appear
spuriously with more dimensions.

**Recommendation:**
- **Do now, independent of scale:** §5's `dex_oracle_spread`. It fixes a coverage
  gap in an existing feature dimension for incidents that currently contribute
  almost no evidence to `cross_venue_spread` at all, rather than adding a new one —
  lower marginal overfitting risk than the rest.
- **Gate behind a substantially larger incident set** (order of 50–100+, not 20):
  §2 (multi-oracle disagreement), §3 (trajectory-as-features), §4 (liquidity/depth).
  These should not be added to the modeled feature set on the current 20 incidents
  even once they're technically implemented — collect them, but don't feed them to
  `models.py` until there's enough data for LOOCV and ablation on the *expanded*
  set to mean the same thing they currently mean on the 6-feature set.
- Before any of the gated features join the modeled set: re-run the same discipline
  already applied to the current 6 (`loocv_validation.py`'s LOOCV + calibration,
  `ablation_and_audit.py`'s drop-one-feature ablation) on the larger incident count,
  not on n=20.

## 7. Experimental prototypes (not part of the pipeline)

Two of §3's proposed metrics were quick enough to sanity-check directly against data
`temporal_trajectories.py` already cached — no new RPC calls, no changes to
`build_features.py`/`features.parquet`/`models.py`. Code:
`src/experimental_trajectory_features_prototype.py`. **These are feasibility checks
on n=1–2 incidents each, not validated features** — they exist to surface real
implementation questions, not to demonstrate that either metric would help a
classifier.

**`step_change_count` on Harvest's Curve Y-pool ratio** (56 cached samples): a naive
fixed-threshold counter (>0.5% consecutive-sample jump) found **11** step-changes,
against the **5** an eyeball read of the same series described in
`temporal_trajectories.md`. They disagree because a fixed relative-jump threshold
also fires on small noisy wiggles that a manual read collapsed into one plateau.
This is exactly why §3 specifies a real change-point method (e.g. `ruptures`/PELT)
rather than a threshold rule — the naive version isn't a usable feature definition
yet, even though the underlying data is available.

**`deviation_persistence` on stETH's Chainlink-vs-DEX deviation** (77 aligned
samples over a ~447-hour window): cumulative time with `|deviation| > threshold`
came out to 1,212s / 999s / 298s at thresholds of 0.001 / 0.002 / 0.005
respectively (raw exchange-rate units, stETH/ETH terms) — small relative to the
447-hour window. This shows the metric is highly sensitive to the threshold and unit
chosen (absolute rate difference vs. a relative percentage), which needs a
deliberate choice before this becomes a real feature definition, not something to
assume works out of the box.

Neither prototype should be read as "this feature works" or "this feature doesn't
work" — n=1 and n=2 respectively prove nothing about classifier usefulness. They
confirm the raw data supports computing something in this family, and surface the
specific design decisions (change-point method, threshold/units) that a real
implementation would need to make explicitly.
