# DEX-TWAP disagreement feature: implemented, tested, does not earn its place

**Verdict: does not clearly help either model — no change made to
`src/models.py`.** BN gets a negligible accuracy nudge (+1 incident, a
volatility case — zero change to manipulation or malfunction recall) at a real
calibration cost (ECE +18%, log-loss +12%). NB gets strictly worse on every
single metric. Neither of the two still-missed manipulation incidents is
recovered — MEVBOTa47b, the one case this feature can actually reach, is
predicted *more* confidently wrong with it than without. The feature was
evaluated via the same temporary monkey-patch approach already used for
`src/structure_edge_test.py` (never a permanent edit), so there is nothing to
revert — `models.py`'s diff against the last commit is empty, confirmed
directly.

## 1. Feature definition, grounded in the design doc

`dex_twap_spread = (chainlink_price − dex_twap_price) / dex_twap_price`,
computed for each incident from `src/compute_dex_twap_feature.py`, implementing
`reports/richer_features.md` §2's `chainlink_twap_spread` proposal — explicitly
called out there as the one multi-oracle-disagreement signal usable
retroactively (unlike Pyth, whose Ethereum mainnet feeds only went live in
2023, ruling it out for most of this project's pre-2023 incidents).

`dex_twap_price` is the DEX pool's **time-weighted average price** over a
strictly-trailing **1800-second (30 min)** window ending at the incident's own
anchor block, read via Uniswap V3's built-in `observe()` oracle (`src/
fetch_dex.py`'s new `get_v3_twap`) — not a manually-averaged multi-block
sample, and not the instantaneous spot price `cross_venue_spread`/
`dex_oracle_spread` already use. The 1800s window reuses this project's
existing `MAX_CLEAN_HEARTBEAT_SECONDS` convention rather than inventing a new
number. A new ABI fragment for `observe()` was added to `fetch_dex.py`
(previously only `slot0()`/`liquidity()` were wired up).

**A real implementation lesson, documented in code**: `observe()` reverts with
"OLD" when a pool's stored observation history doesn't cover the requested
window — common for pools with low observation-slot cardinality, especially
early in a pool's life. Wrapping this in the project's standard 6-attempt
`_with_retry` would burn ~105s per doomed call (the same mistake already
identified and fixed elsewhere in this project for not-yet-deployed
contracts); `get_v3_twap` instead uses a short, 2-attempt bounded retry and
returns `None` (not raised) on failure, documented explicitly as intentional.

## 2. Coverage, per class

| Class | Coverage |
|---|---|
| Large volatility event | 136/138 |
| Malfunction | 1/3 |
| Manipulation | **1/24** |

**Matches `reports/richer_features.md`'s own predicted coverage gap almost
exactly** — that design doc explicitly flagged this feature as unable to reach
manipulation incidents without an identified DEX pool. Confirmed directly:
only **`MEVBOTa47b`** among the 24 manipulation incidents has a `dex_pool`
configured (the other 23, including the still-missed `CurveLlamaLend`, do not
— `CurveLlamaLend`'s `dex_twap_spread` is genuinely `NaN`, not a computation
failure). The 1 malfunction incident with coverage is `stETH/ETH heartbeat
lag` (its `dex_pool` is the wstETH/WETH V3 pool). The 2 volatility failures
(`May 19 2021 crash`, `May 24 2021 rally`) both date to right around Uniswap
V3's actual mainnet launch (2021-05-04) — genuinely insufficient observation
history at that early point in the pool's life, the expected "OLD" failure
mode, not a bug.

## 3. Leakage / no-lookahead check

Verified directly, not just asserted from `observe()`'s documented behavior:
querying the same pool's TWAP at two different `block_identifier` values (100
blocks apart) produces genuinely different results (`0.000401285...` vs.
`0.000406460...`), confirming the read is properly anchored to each block's
own historical state, not some cached or "current" value independent of the
requested block. `observe()`'s `secondsAgos` parameter counts backward from
whatever block it's queried at, so it is architecturally incapable of
returning data from after that block — the same no-lookahead guarantee every
other point-in-time read in this project already has.

## 4. Full LOOCV comparison and per-model verdict

| Model | Config | Accuracy | Manip. recall | Malf. recall | Vol. recall | Vol.→manip. confusion | Brier | ECE | Log-loss |
|---|---|---|---|---|---|---|---|---|---|
| BN | baseline | 93.3% | 83.3% | 33.3% | 96.4% | 5 | 0.1330 | 0.0450 | 0.3354 |
| BN | **+ dex_twap_spread** | 93.9% | 83.3% | 33.3% | **97.1%** | **4** | 0.1337 | **0.0531** | **0.3752** |
| NB | baseline | 95.2% | 75.0% | 100.0% | 98.6% | 0 | 0.0970 | 0.0482 | 1.2192 |
| NB | **+ dex_twap_spread** | **94.5%** | 75.0% | 100.0% | **97.8%** | 0 | **0.1091** | **0.0545** | **1.3776** |

**BN: marginal, and not worth the cost.** The only movement is +1 correctly-
classified incident overall (a volatility case — `vol_recall` ticks up,
`vol→manip` confusion ticks down by one), with **zero change to manipulation
or malfunction recall**, the two classes this project's whole framing centers
on. In exchange, calibration measurably worsens: ECE +18% relative, log-loss
+12% relative. A one-incident volatility-classification nudge is not a
reasonable trade for a double-digit calibration cost.

**NB: strictly worse, no ambiguity.** Every single metric moves in the wrong
direction — accuracy, volatility recall, Brier, ECE, log-loss. Manipulation
and malfunction recall are unchanged (this feature doesn't reach the
manipulation incidents NB already gets right or wrong, and NB's 100%
malfunction recall was already independent of it). There is no reading of
this result where the feature helps NB.

**Neither model gets an asymmetric win here** — unlike the temporal features,
where `temporal_gap_trend` genuinely helped NB while hurting BN, this feature
does not help either model enough to justify a per-model split. Both results
point the same direction: leave it out.

## 5. Does it help with the volatility-vs-manipulation confusion, or recover MEVBOTa47b/CurveLlamaLend?

**Volatility-vs-manipulation confusion**: a small, genuine improvement for BN
(5 → 4 volatility incidents called manipulation) and no change for NB
(already at 0). Real, but tiny relative to the calibration cost it comes with
(§4) — one fewer misclassification among 138 volatility incidents.

**MEVBOTa47b — not recovered, and more confidently wrong.** This is the one
manipulation incident the feature can actually reach (it has a real
`dex_twap_spread` value, `-0.00127` — a very small disagreement, consistent
with its already-known "calm on the ETH/USD reference feed" signature from
the temporal-features investigation). With the feature added, BN predicts
`large volatility event` for it at **99.87% confidence** — not just still
wrong, but among the most confidently wrong calls in the dataset. The DEX-TWAP
signal, where available for this incident, reinforces the "looks like
ordinary volatility" read rather than correcting it.

**CurveLlamaLend — unaffected, exactly as expected.** Confirmed directly:
`dex_pool` is `None` for this incident (no DEX pool was ever identified for
its manipulated venue), so `dex_twap_spread` is genuinely `NaN` for it, not a
failed computation. This incident was never within reach of this specific
feature, and its prediction (`large volatility event`, 98.84% confidence) is
essentially unchanged from before — this feature simply cannot address it.

## 6. Malfunction n=3 — explicit, and unaffected either way

Malfunction recall is bit-for-bit identical with and without this feature for
both models (BN 1/3, NB 3/3) — unsurprising, since only 1 of the 3 malfunction
incidents (`stETH/ETH heartbeat lag`) has any coverage at all, and that one
incident's classification doesn't flip either way. As with every prior
structural or feature change tested in this project, nothing here moves the
malfunction class's fundamental 3-data-point problem.

## 7. Recommendation

**No change to `src/models.py`.** The feature was evaluated exclusively via a
temporary monkey-patch (the same safe pattern used in `src/
structure_edge_test.py`) and never written into the production file, so there
is nothing to revert — confirmed directly (`git diff --stat src/models.py`
returns empty). The underlying data (`dex_twap_spread` in `data/processed/
features.parquet`) is kept, since it's a legitimate, honestly-computed column
that could be useful for a future investigation even though it doesn't earn a
place in either model's feature set today — consistent with this project's
practice of keeping computed data available rather than deleting it. Per
instruction, this is not flagged for your decision, since the evidence does
not clearly support keeping it for either model — that threshold is reserved
for a genuine win, and this result, read honestly across both models, is not
one.
