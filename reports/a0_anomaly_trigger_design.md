# A0. Common anomaly trigger design (DRAFT v0.1, 2026-09-29, awaiting review)

Fixes audit C1. Goal: attacks and benign anomalies enter the dataset through **the same door**,
so the class is decided after the trigger, not by how each case was found. Nothing here has been
run. No on-chain data has been pulled for this spec.

## 1. Design principle: the trigger may not use anything the classifier will use

The trigger reads **only the source's own price path** (`p_S`). It does **not** use:

- the deviation of `S` from a reference price `R` (that is feature P1/D2; using it would make
  "oracle disagrees with market" the entry condition and separate genuine moves from manipulation
  by construction);
- any cross-venue spread, ETH-context, congestion, staleness, or victim balance.

So a genuine market move and a manipulation both fire the trigger if `S` itself moved enough. What
separates them is downstream classification, not entry.

## 2. Trigger definition

For each source `S` in the scan universe (§3), at every block `b`:

```
fire(S, b)  iff  max over k in [1, Y] of  abs(p_S(b) - p_S(b-k)) / p_S(b-k)   >=  X[S_type]
```

Episodes are merged: firings within `Y_merge` blocks of each other form one episode; `T` = first
firing block of the episode.

**Proposed parameters (placeholders for review; B11 sweeps them):**

| `S_type` | `X` | Rationale |
|---|---|---|
| `chainlink`, `univ3_spot`, `univ3_twap`, `univ2_spot` on volatile pairs | 5% | matches the lower end of the existing volatility class (3-5%) |
| `curve_spot`, `curve_ema`, `curve_lp`, `vault_rate`, stable or pegged `own_amm` | 0.5% | pegged or slow-moving sources: a 0.5% move is already extreme (UwU pool ratio moved 6.6%, sDOLA rate 13.8%) |
| `custom_oracle` | 5%, review per source | depends on what it wraps |

`Y = 50` blocks (about 10 minutes) primary; `Y_merge = 300`. Chosen by the rule "the shortest
window within which every known attack's `S` moved by at least `X`" **evaluated only after the pilot
in §5 is approved**, and recorded with the date. Until then these numbers are untested.

### Granularity decision (needs your call)

Block-close prices miss atomic round trips that revert inside one block (CurveLlamaLend's sDOLA
rate was inflated 13.79% and restored in the same tx). Options:

| Option | What it catches | Cost |
|---|---|---|
| **G1: block-close only** | multi-block and persisting manipulations | misses all same-block round trips; scope claim limited to "non-atomic" |
| **G2: log-derived intra-block extremum** (Uniswap V3 `Swap` event `sqrtPriceX96` after each swap; Curve `TokenExchange`/`AddLiquidity` events replayed to balances; ERC4626 `Deposit`/`Withdraw` ratios) | most AMM-based atomic manipulations, on the **free** `eth_getLogs` tier | log-replay per source type must be validated; sources with no informative events (custom oracles) still fall back to G1 |
| **G3: paid traces** | everything | needs a paid tier (blocked, see `tracing_feasibility.md`) |

**Recommendation: G2 with G1 as fallback**, flagging each episode `granularity = {G1, G2}` so B8's
atomic-vs-non-atomic scope analysis can use it. Requires your approval before any log pull.

## 3. Scan universe and consumer registry

Only sources that a protocol with material value actually reads (so anomalies matter and the
"price source a protocol consumes" unit in A1 is well-defined).

| Universe slice | Candidate list | Source of list |
|---|---|---|
| Chainlink feeds | all Ethereum mainnet feeds with `>= 1` registered consumer above the TVL floor | Chainlink feed registry + consumer lookup |
| Curve pools used as price sources | pools referenced as oracles by lending markets (LlamaLend, Inverse, Cream-era, etc.), plus top pools by TVL per class (stable, crypto, LSD) | Curve registry + protocol docs |
| ERC4626 / rate-provider sources | vaults or wrappers whose `convertToAssets` / rate is read by a lending market | protocol collateral lists |
| Uniswap V2/V3 pools read as spot or TWAP | pools cited by consumer contracts (e.g. `UniswapAnchoredView`) | consumer code reads |
| Own-AMM sources | protocol AMMs whose price another contract consumes | case by case |

- **Consumer TVL floor:** proposed `>= $1M` consumer TVL at `T` (from DeFiLlama historical TVL).
  Placeholder.
- **Scan window:** 2020-10 to 2026-09 (the current incident range). Full window for each source
  from the block it first has a registered consumer.
- The universe list, not the anomalies, is what gets pulled first (metadata only). Universe
  completeness is the largest threat to "natural base rates" and is reported as a limitation.

## 4. Labelling every flagged episode

Every episode gets an A2 label. Label sources are external documents only (post-mortems, exploit
databases), **never** model features (see A2 §2 for the evidence rules).

| Label | Meaning |
|---|---|
| `M` | oracle / price-source manipulation, per A2 |
| `G` | genuine market move (documented external cause, no exploit touching a consumer of `S` in the window) |
| `F` | oracle malfunction or feed failure (stale, paused, wrong feed, deprecated) |
| `X` | other exploit (rounding, accounting, access control, MEV); excluded from the primary task |
| `U` | unresolved; excluded from primary, counted |

`U` and low-confidence `G` are reported and used in sensitivity analysis. **Absence of a documented
exploit is not proof of benign**: undiscovered small attacks are a source of label noise in `G`.
Two-tier confidence for `G` (documented cause vs. merely no exploit found) makes this measurable.

## 5. Sampling and base rates

Enumerating and labeling every flagged episode may be thousands of rows (A10 §6). Plan:

1. **Attacks:** all known manipulation incidents from exploit databases (DeFiHackLabs, DeFiLlama
   hacks, rekt) on Ethereum mainnet that (a) qualify as `M` under A2 and (b) have a source in the
   universe. Each is passed through the **same trigger** on its own `S`; an attack whose `S` never
   fires the trigger is recorded as a **trigger miss** (a result about the trigger, not something
   to drop quietly).
2. **Benign / all others:** full enumeration where affordable; otherwise stratified sampling by
   (`S_type`, trigger magnitude decile, year) with **recorded inclusion probabilities** so prior
   shift can be corrected (B7).
3. **Natural base rate estimate** = (attacks that fire the trigger) / (all episodes fired). It is a
   **lower bound** on true prevalence (unknown attacks, incomplete database) and is stated as such.

## 6. Known threats to this design

| Threat | Handling |
|---|---|
| Trigger threshold indirectly favors one class | sweep in B11; report class balance vs. `X`,`Y` |
| Attack database completeness | state as limitation; base rate is a lower bound |
| Consumer registry incomplete | report; sensitivity on TVL floor |
| Trigger misses (esp. G1) | recorded per attack, reported with granularity flag |
| Episodes cluster on the same day | `cluster_id` grouped CV in B1 |

## 7. Proposed gate before any data pull (for your approval)

Everything in §2-§5 stays on paper until you approve a **pilot** with exactly this scope:

- Build the universe list (metadata reads and public repo reads only, no per-block scans).
- **Free public data only**: count attack candidates in DeFiHackLabs by type and year; no RPC.
- Then, if approved, one small RPC pilot on 3-5 known attacks to test whether G2 log-replay
  reproduces the known manipulated price, and whether the trigger fires on each.

## 8. Decisions needed from you

1. Approve the trigger principle (§1): source-price-only, no reference deviation.
2. Granularity G1 vs **G2 (recommended)**.
3. Approve the placeholder thresholds and TVL floor as the *starting point* for the pilot.
4. Universe scope for the first pass: all slices in §3, or start with Curve + vault rates + Uniswap
   only (where most attacks live) and add Chainlink after.
