# A1. Measurement spec (DRAFT v0.1, 2026-09-29, awaiting review)

Fixes audit C1 (selection confound), C2 (per-class feature definitions), C3 (missingness as source
signal). Written before any data pull. Depends on A0 (trigger) and A2 (labels) for definitions of `T`
and the class labels, but not for anything below except where marked.

Status: **nothing here has been implemented or tested.** Every threshold is a proposal for review.

## 1. Unit of observation

One row = **one anomaly episode at one price source `S` that a named consumer contract reads.**

| Field | Definition |
|---|---|
| `episode_id` | stable id, `YYYYMMDD-<source_addr[:8]>-<T block>` |
| `S` | the on-chain value the consumer actually reads, identified by (contract, function, args). Examples: Chainlink aggregator `latestRoundData`, Curve pool `get_dy`/`price_oracle`/`get_virtual_price`, ERC4626 `convertToAssets`, Uniswap V3 `slot0` or TWAP `observe`, a protocol's own oracle contract |
| `S_type` | `chainlink`, `curve_spot`, `curve_ema`, `curve_lp`, `vault_rate`, `univ2_spot`, `univ3_spot`, `univ3_twap`, `own_amm`, `custom_oracle` |
| `C` | consumer contract + function that reads `S` (from post-mortem and verified code read; for benign anomalies, from the consumer registry in A0 §3) |
| `T` | anchor block, defined in §3 |
| `cluster_id` | (calendar date, protocol family). Used for grouped CV. The audit found 149 clusters in 162 rows, so dependence is mild but must stay controlled |
| `label` | from A2 only. Never inferred from any feature |

The unit is **not** "an ETH/USD move" and **not** "a victim contract's balance". A protocol attacked
through a Curve pool is observed at that Curve pool. A benign USDC depeg is observed at the USDC
pricing sources that lending markets consume.

## 2. Feature families and identical definitions across classes

All features are computed from block-level reads of `S` and of a reference price `R` (§4). No feature
may be defined differently for two classes, and no feature may read a victim contract's token balance.

**Tier P: pre-event state, measured at block `a = T - 1`** (primary feature set; the audit's required
"last block before the first manipulating tx").

| ID | Feature | Definition |
|---|---|---|
| P1 | `s_dev_ref` | `abs(p_S(a) - p_R(a)) / p_R(a)` |
| P2 | `s_ret_pre` | log return of `p_S` over `[a - W, a]`, `W` = 300 blocks (about 1 hour) |
| P3 | `s_vol_pre` | realized volatility of per-block `p_S` returns over the same window |
| P4 | `s_stale` | blocks since `S` last changed value |
| P5 | `s_depth` | notional needed to move `p_S` by 1% at `a`, from reserves or `totalAssets` (for pools that do not expose reserves, from the source's own quoting function) |
| P6 | `s_venue_spread` | max pairwise spread of `p` across `>= 2` independent on-chain venues quoting the same asset pair, excluding `S` and excluding any venue sharing the attacked contract |
| P7 | `s_imbalance` | for multi-asset pools, the pool's own reserve-ratio deviation from its balanced or peg state at `a` (**source-internal, pre-event**; never the victim's balance) |

**Tier D: trigger-observable, measured at end of block `T`, price path only.** Both classes have a
trigger block by construction (A0). These are the quantities a monitor could see at detection time.

| ID | Feature | Definition |
|---|---|---|
| D1 | `move_size` | `abs(p_S(T) - p_S(a)) / p_S(a)` |
| D2 | `move_ref_gap` | `abs(p_S(T) - p_R(T)) / p_R(T)` |
| D3 | `ref_move` | `abs(p_R(T) - p_R(a)) / p_R(a)` (did the outside market move too?) |
| D4 | `move_speed` | blocks from first departure of `p_S` to peak within the episode window |
| D5 | `revert_blocks` | blocks until `p_S` returns within 0.5% of `p_S(a)`, capped at `Y_max` |

Rules:

1. **Two feature sets, evaluated separately**: Tier P alone (early-warning claim) and Tier P + D
   (diagnosis claim). No claim about Tier D may be made from Tier P results or vice versa.
2. **Post-exploit quantities are banned as features**: victim token balances, loss size, tx count
   after `T`, any `reserve_skew` computed on the victim. (Audit C2: 16/24 old skew values were the
   loss itself.)
3. **ETH/USD is not a fallback for anything.** ETH-context quantities (gas congestion, ETH
   realized vol, Chainlink ETH/USD heartbeat, ETH trajectory) are excluded from classifier inputs.
   They are kept **only** as the control features in the A5 negative-control model.
4. **Atomic in-block round trips are observable only through logs.** Block-close reads miss them
   (the CurveLlamaLend caveat). See A0 §2 for the log-derived intra-block extremum option. Until
   that decision is made, D1/D5 are defined on block-close prices and the episode is flagged
   `intra_block_only = true` if the block-close move is below trigger but the log-derived extremum
   is above it.

## 3. Anchor block `T`

- **Attacks:** `T` = block of the first tx labeled manipulating in A2's evidence (verified from the
  call trace, not from a PoC fork block). Record `T_evidence` (tx hash + source).
- **Benign anomalies:** `T` = first block at which A0's trigger fires for `S`.
- **Same-definition check:** for attacks, also record `T_trigger` (first block A0's trigger would
  fire on `S`). If `T_trigger != T` (e.g. multi-block attacks whose price moves later), the episode
  is still anchored on `T` for features but the gap `T_trigger - T` is logged and analysed in B8.
  A0's trigger applied identically to both classes is what removes the selection asymmetry.

## 4. Reference price `R` (hierarchy, applied identically to both classes)

| Tier | Source | Used when |
|---|---|---|
| R1 | CEX mid (Binance/Coinbase kline, 1-minute aligned to block timestamp) | liquid CEX pair exists |
| R2 | An independent oracle feed for the same pair (e.g. Chainlink when `S` is not Chainlink) | R1 unavailable |
| R3 | Median of `>= 2` deep on-chain venues, none sharing the attacked contract, none equal to `S` | R1, R2 unavailable |
| R4 | Fundamental parity: peg = 1, or on-chain redemption value (e.g. wstETH rate) | pegged or wrapped assets |
| none | no defensible `R` | episode **excluded from the primary analysis**, counted and reported by class |

- `R_tier` is recorded per episode. It is a covariate in the A5 negative control (venue-identity /
  sourcing model), so any dependence of the label on `R_tier` shows up as a gate failure.
- Excluded episodes are **not** silently dropped: the exclusion table (count by class and `S_type`)
  is part of the paper. Many long-tail attacks will have no `R`; the scope claim must say so.

## 5. Missingness policy (fixes C3)

- Every included episode has every P and D feature defined. If a feature cannot be defined for an
  episode, the episode is excluded (see `none` above), not imputed and not left NaN.
- No feature may be structurally undefined for one class (the old `price_dev` was missing for 83%
  of manipulations and 0% of volatility).
- A5 includes the required check: a model given only missingness / `R_tier` / `S_type` indicators
  must score near chance.

## 6. Quality gates (A8 hooks)

Per pull, before any feature is written: decimals, inverted pair (`token0/token1` order), wrapper
or rate factor (stETH/wstETH-type), block and tx-hash verification, value-range sanity, unit test
per feature on a synthetic fixture. Specified in A8; A1 requires that no feature is computed
without passing them.

## 7. What is deliberately not specified yet

- Trigger thresholds `X`, `Y`: A0.
- Whether intra-block log-derived prices replace block-close prices: A0 §2 (decision for review).
- Consumer registry contents and TVL floor: A0 §3.
- Labels: A2.

## 8. Decisions needed from you

1. **Two anchors (Tier P at `T-1`, Tier D at `T`) or Tier P only?** Tier P alone is the strictest
   reading of the audit but for atomic attacks it carries almost no price signal; the spec keeps
   both, evaluated separately. Confirm.
2. **Exclude episodes with no defensible `R`** (recommended) vs. keep them with an explicit
   "no reference" category. Excluding shrinks the attack class the most.
3. **`W` = 300 blocks and the 0.5% revert band** are placeholders; B11 sweeps them.
