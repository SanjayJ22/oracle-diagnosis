# Pilot results (2026-09-30). PILOT, UNDERPOWERED PER A10. NOT A CLASSIFIER RESULT.

Status: **measurement feasibility demo plus ETH-context control.** Full numbers: `reports/pilot_model_results.json`. Data: `data/processed/pilot.parquet`. Locks: `reports/spec_lock_2026-09-30.md`. This file was written under a usage limit; a fuller write-up (per-episode tables, checkpoint note) was not done.

## 1. Attack set (`labels_a2.csv`, `a2_verified_M`, 9 rows)

| Source type (from the sheet's `S`) | Count | Outcome under locked G1 / A1 rules |
|---|---|---|
| Curve | 5 (Harvest, Inverse, UwU, Zunami, Makina) | **3 usable** (Inverse, Zunami, Makina fire). Harvest and UwU are **trigger misses**: price is restored by block close |
| Vault rate | 3 (Cream, CurveLlamaLend, Resupply) | **0 usable**: no independent reference price R (A1 s4 tier none). Cream (D1 = 1.00) and sDOLA (D1 = 0.138) shown descriptively; Resupply reader was fixed afterwards (section 6): the label sheet's address is the crvUSD controller; the vault is `pair.collateral()` |
| Uniswap | 0 | CompoundUni and DRLVaultV3 are single-source, so not verified-M |
| Other | 1 (BalancerBoostedPool2023) | Balancer rate provider; no reader built |

By your rule (fewer than 5 with a Curve/Uniswap/vault source) the count is 8, so the rule does not literally trigger. **The usable count after the locked filters is 3** (n_neg = 35), so this is framed as a feasibility demo. Only 3 of 9 verified-M attacks are visible at block close: G1 has poor sensitivity to atomic manipulations.

## 2. Benign side

68 trigger-fired episodes enumerated from the named events, 35 selected (cap 6 per cell, seed 20260930). **USDT Jun 2023, USDe Oct 2025 and the Nov 2022 LSD windows produced 0 fired episodes.** LP episodes are 12 of 35. Uniswap has no matched episodes. Readers were validated on three attacks with post-mortem numbers before use (sDOLA 1.189 to 1.353, Inverse 979, UwU `get_p` identity); all QA passed on every pull except the Resupply reader.

## 3. Model results (LOOCV AUC; n_pos = 3, n_neg = 35)

| Model | AUC | Bootstrap 95% CI | One-sided 95% upper bound (Hanley-McNeil) |
|---|---|---|---|
| **ETH-context control** (logit) | see JSON | see JSON | **0.795** |
| ETH-context control (RF) | 0.376 | [0.066, 0.857] | **0.635** |
| Price-path (P2,P3,D1,D5), logit | 0.476 | [0.00, 1.00] | 0.761 |
| Price-path, RF | 0.757 | [0.371, 1.00] | 1.00 |
| Full pilot features, logit / RF | 0.562 / 0.700 | [0.09, 1.00] / [0.26, 0.995] | 0.858 / 0.989 |
| Price-path without D5, logit / RF | 0.619 / 0.814 | [0.28, 1.00] / [0.56, 1.00] | 0.916 / 1.00 |

All labeled **pilot, underpowered per A10**. With 3 positives the minimum detectable AUC is above 0.9 and every interval spans most of the range. **Neither the control passing nor the price-path model's point estimates supports any claim.** The ETH-context control is not near chance in any certified sense (upper bounds 0.64 to 0.80, against the 0.60 line A10 proposed), so A5 is **inconclusive**, not passed.

## 4. Caveats found and not resolved

- **Anchor asymmetry:** benign T is a trigger block (D1 is often tiny); attack T is the attack block (D1 is huge for Zunami and Makina). D1 separates the classes partly by construction. Sensitivity with attacks anchored at the trigger block was **not run**.
- D5 uses post-T information (look-ahead), so it is not a real-time feature.
- One benign MIM episode shows D1 = 0.27 (27% in one block). **Checked (section 6): real**, not a reader artifact; kept.
- Benign episodes are 2022-2023, attacks 2020-2026; time and source-type mix are confounded. The `S_type`-only control scored AUC 0.0 (LOOCV artifact from S_type composition).
- Deviations: reverse-quote QA on every 5th block; LP scan stride 20; single labeler; vault-rate excluded by design; Uniswap dropped for lack of a verified attack.

## 5. Not done

Hour-5 checkpoint note; trigger-anchored sensitivity; per-episode tables. (MIM outlier check and Resupply reader: done, section 6.) `models.py` and `features.parquet` were not touched.


## 6. Addendum (tasks 37 and 38)

### 6.1 Task 38 leftovers

**MIM 27% one-block episode (`B-mim3crv_MIM_3CRV-14982127`): real, kept.** In block T the pool's 3CRV balance fell from 12.33M to 1.81M while the MIM balance stayed at 145.2M, so one large single-sided withdrawal moved the price of MIM in 3CRV from 0.969 to 0.705. An independent quote (`get_dy_underlying` MIM to USDC) agrees (0.989 to 0.719), and the displacement persists through T+6 (0.735). No control rerun was needed. Two consequences: (a) a benign-labeled liquidity withdrawal has the same shape as a pool drain such as Makina's, so D1 alone cannot separate them; (b) its `G` label is low-confidence, since I did not verify a documented cause for the withdrawal.

**Resupply reader: fixed (about 20 minutes).** The label sheet's address `0x8970...` is the crvUSD controller. The ERC4626 collateral vault is `pair.collateral()` = `0x01144442fba7adccb5c9dc9cf33dd009d50a9e1d` (empty at T-1; the donation leaves `totalSupply` = 1 wei and `totalAssets` = 2,002 crvUSD). `convertToAssets(1e18)` goes from 1e-3 to 2e18 (degenerate, D1 astronomically large). The row in `pilot.parquet` was replaced and `pilot_build.py` updated. The row stays outside the analysis (vault_rate has no independent R), so no model result changes.

### 6.2 Task 37: intra-block (G2) reconstruction

Method (`src/pilot_g2.py`, `reports/pilot_g2_results.json`, `reports/pilot_g2_scan.json`): `eth_getLogs` for the pool, one block per call (free tier), events replayed in log order against the pre-block state (`balances`, `A`, `fee`, `admin_fee` at T-1); price = fee-free marginal price from the stableswap invariant on the replayed balances (Inverse: the balance-weighted LP value its feed read). End-of-block chain state is used only to validate. A0 trigger on the intra-block path: fires if any post-event state deviates by at least X = 0.5% from the pre-block price.

| Pool (role) | Pre-block price | Peak intra-block deviation | Block-close deviation (chain) | G1 fires | G2 fires |
|---|---|---|---|---|---|
| **Harvest** (miss) | 1.00067 (USDT in USDC) | **0.114%** at a 17.22M USDT to USDC swap | 0.0003% | no | **no** |
| **UwU** (miss) | 1.00057 | **8.57%** at a 27.86M USDC to USDe swap | 0.0087% | no | **yes** |
| Inverse (control) | 979.62 | 189.04% (peak 2,831.5) | 1.196% | yes | yes |
| Zunami (control) | 0.99714 | 27,994% | 99.95% | yes | yes |
| Makina (control) | 1.00101 | 6,188% mid-block | 10,025% | yes | yes |

Note on Harvest's amount: the largest swap in block T sold 17,222,013 USDT (underlying units); the block had 6 pool events.

**Superseded for Harvest by section 7a:** the row above measures the Y pool's marginal USDT/USDC price, which is not what the fUSDC vault read. On the value it did read, G2 fires (-2.14% strategy value, -0.89% share price) while G1 on the price source still misses.

**Neighboring blocks.** Harvest: 30 active blocks from T to T+40. T to T+25 are USDT to USDC swaps of about $17.2-18.1M (peaks 0.114-0.120%); T+26 to T+40 are the reverse direction, USDC to USDT of about $10.6-11.4M (peaks 0.104-0.111%), i.e. the unwind. The peak in every block is **well under the 0.5% trigger**. UwU: 17 active blocks in [T-330, T+30]; only **T and T+3** show a large excursion (8.57%, two ~27.86M USDC swaps), every other block peaks below 0.1%, and block-close deviation never exceeds 0.08%. So G2 turns UwU from a miss into a fire at two blocks, and does **not** rescue Harvest.

**Validation against post-mortems and chain state.**
- Replay fidelity: Harvest, UwU and Inverse reproduce on-chain end-of-block balances to 1e-5 or better (Harvest 1e-11, Inverse 1e-16) and the close price to 1e-7 or better. The price engine matches on-chain prices at T-1 and T to 3e-7 (Harvest, via `get_dy`) and exactly (UwU, via `get_p`).
- **Inverse matches BlockSec's number:** the replayed peak is 2,831.5 against the post-mortem's "979 to 2,831".
- Harvest: per-cycle USDT sold (about $17.2M) matches the post-mortem's "$17 million USDT swapped". The post-mortem's roughly 1% decline in the fUSDC share price is **not** visible in this S: the pool's USDT/USDC price moves about 0.11% per cycle. The vault's valuation amplifies pool state in a way this S does not capture, so **Harvest's S is probably not the quantity its consumer read**; the label sheet's S (yUSDC/yUSDT ratio) is flat at block close as well.
- UwU: post-mortems describe a roughly 4% manipulation of the median oracle built from 5 Curve pools; this single pool moves 8.57% in the opposite direction of trade (USDC in). That is the same kind and scale of event but **not a numerical validation**.
- Zunami: engine vs chain 1.3e-3 at T-1 and 3.1e-4 at T (the pool's dynamic fee is higher than `fee()` when imbalanced; the trigger threshold is 0.5%, so this does not affect any conclusion).
- Makina: replay closes to 1.9e-4 on DUSD but 33% on the USDC balance (about 3.4K USDC on 200M of flows, admin-fee terms) and the drained state (price near 100) is hypersensitive to it, so the final replayed price is unreliable while the peak ordering is sound. The replay shows 200,000,000 USDC added across the block versus the post-mortem's "roughly 170 million", a discrepancy I did not resolve.

**Caveats.** (1) Unexplained: the UwU pool's `price_oracle(0)` EMA moved from 0.999 to 1.068 between T-300 and T-10 with no matching spot excursion in the events (max 0.09%). I did not use the EMA anywhere and did not resolve it. (2) G2 here is per pool event, so it sees extremes between txs and inside a tx at swap granularity; it cannot see state changes from events the pool does not emit. (3) Stableswap-only: no crypto-pool invariant (Inverse uses balances, as its feed did). (4) One attack block per pool was the task; the scan windows above are an extension.


## 7. Loose ends (2026-09-30)

Code: `src/pilot_g2_harvest.py` (new), `src/pilot_g2.py` (added a `RemoveLiquidityImbalance` handler). Results: `reports/pilot_g2_harvest.json`. The earlier `pilot_g2_scan.json` UwU row for T-120 (`ev=0`) predates the handler fix and is stale; no other row in `pilot_g2_results.json` or the scan is affected (no block other than T-120 has an imbalance event).

### 7a. Harvest: the price the fUSDC vault actually read. **RESOLVED**

**Path (verified on chain and in Harvest's `CRVStrategyStable.sol` / `PriceConvertor.sol`):** `fUSDC.getPricePerFullShare = (vault cash + strategy.investedUnderlyingBalance()) / supply`; `investedUnderlyingBalance` = yCRV-vault shares (49.31M) x that vault's price per share (1.0045) = about 49.5M yCRV, converted by `PriceConvertor.yCrvToUnderlying(yCRV, 1)` = the Curve Y zap's `calc_withdraw_one_coin(yCRV, USDC)` (`0xbBC81d23...`). So the quantity read is the USDC value of withdrawing the strategy's whole LP position single-sidedly from the Y pool, fee included. The pool's marginal USDT/USDC price (section 6) and the label sheet's yUSDC/yUSDT ratio are **not** that quantity, which is why they moved only 0.11%.

**Replay.** The engine re-implements `calc_withdraw_one_coin` on the replayed Y-pool balances. It reproduces the zap to 4.5e-5 and the on-chain share price to about 2e-5 at T-1 and T. Blocks replayed: T, T+3, T+4, T+6, T+7 (5 of the 30 attack blocks).

| Quantity | Intra-block peak | Block-close (chain) |
|---|---|---|
| Strategy invested value (the price-source component) | **-2.14%** at the first 17.2M USDT to USDC swap, restored by the reverse swap | **+0.010%** |
| fUSDC share price, vault cash and supply held at their pre-block values | **-0.89%** at T (-0.90 to -0.92% at T+3 to T+7) | -0.77% at T (-0.78 to -0.84% later) |

- **G2 fires** on the value the vault read (-2.14% and -0.89%, against X = 0.5%), in every block replayed. The peak is consistent with the post-mortem's "roughly 1%" decline in the fUSDC share price, which validates the path.
- **G1 on the price source does not fire** (+0.010% at close): each cycle reverts inside the block.
- The chain's block-close share price falls 0.77 to 0.84% per block, but that is the **realized loss** (the vault's PPS falls about 0.8% each cycle as the attacker extracts value), not the price path: the replayed close-state share price is +0.004%. Counting it as a G1 hit would be outcome leakage (audit C2).
- **Consequence for the classification:** Harvest is a G1 miss and a **G2 hit** on its real S, not a miss on both as section 6 said. Section 6's "G2 does not rescue Harvest" holds only for the wrong S.
- **Caveats:** the share-price replay holds the vault's cash and fUSDC supply at pre-block values (mid-block deposits and withdrawals leave the price unchanged at the quoted value but change later sensitivity); validation is at block boundaries only; 5 of 30 blocks replayed.

### 7b. Makina: 200M vs about 170M USDC. **RESOLVED**

Nothing is missing from the replay; the sources are describing different legs of a two-cycle transaction. The attack tx `0x569733b8...` (all three pools, block 24273362) emits, **per cycle and twice**: `AddLiquidity` of **100,000,000 USDC** to the DUSD/USDC pool, **170,000,000 USDC** to the Curve DAI/USDC/USDT 3pool, and 30,000,000 of 3LP to the MIM-3LP3CRV metapool. So the DUSD/USDC pool receives 2 x 100M = **200M** (our replay), the 3pool 2 x 170M = 340M, the metapool 2 x 30M. CertiK's breakdown (100M / 170M / 30M) matches one cycle exactly; the "roughly 170M into the DUSD/USDC pool" in Verichains' summary is the 3pool leg (and the Makina post-mortem says the cycle repeats twice). The flash loan is about 280M (160.6M Morpho + 119.4M Aave per CertiK) and the legs reuse it.
The separate point from section 6, that the final drained-state price is unreliable (33% residual on the USDC balance), stands.

### 7c. UwU: the EMA oracle moving from 0.999 to 1.068 before T. **RESOLVED**

- **What happened:** at block T-120 (20,061,199) a `RemoveLiquidityImbalance` of **399 USDe + 450 USDC (about $850)** was sent to the pool by `0xd033217b...`. That call set the pool's stored `last_price` to **2.0** (`last_price(0)`: 0.9994 to 2.0), while the spot price did not move at all (1/get_p stays at 1.0006 and the balances are unchanged through T-110). `price_oracle(0)` then climbed toward the stored 2.0 (1.013 at T-119, 1.066 at T-115, 1.24 at T-100) until the next trade at T-100 reset `last_price` to 0.9997, after which the EMA decayed back (1.059 at T). The "EMA before T" is a pool-oracle artifact of one dust withdrawal, **not** a price excursion.
- **The missed event:** my replay had **no handler** for `RemoveLiquidityImbalance` (it was in the signature table but skipped), so T-120 showed `ev=0` in the scan. With the handler added, the replay at T-120 matches the chain exactly (balance error 0) and the spot stays at 1.0006. The event list over [T-330, T+5] is complete: 23 `TokenExchange`, 1 `Transfer` (the LP burn) and that one `RemoveLiquidityImbalance`, and **no `AddLiquidity`**. So nothing else was missed and the UwU G2 results at T and T+3 (8.57% peak) are unaffected.
- **Not the attacker:** the sender `0xd033...` differs from the attacker `0x841ddf09...`. That rules out the simplest "poisoning tx" story but not a related address; I found no evidence of a link either way.
- **Why `last_price` = 2.0:** I did not read the pool's Vyper source, so the clamp at 2.0 is inferred from the stored value, not verified.


## 8. Negative control rerun with 5 attacks (2026-09-30). PILOT, UNDERPOWERED PER A10

Model: market-context-only (the seven locked ETH-context features, `pilot_model.ETH`), LOOCV, logit and RF, 35 benign rows. Attacks: the 3 from section 3 (Inverse, Zunami, Makina) plus **Harvest** and **UwU**. Code `src/pilot_control5.py`; results `reports/pilot_control5_results.json`; data `data/processed/pilot_5att.parquet` (`pilot.parquet` is unchanged). Harvest's and UwU's G2 values are stored in the parquet (`g2_peak_dev`: fUSDC share price -0.89% intra-block; UwU pool price +8.57%) but **are not used by this control**, which has no price-path features.

| Model | Attacks | AUC | One-sided 95% upper bound (Hanley-McNeil) | Bootstrap one-sided 95% upper | Bootstrap 95% CI |
|---|---|---|---|---|---|
| Logit | 3 | 0.505 | **0.795** | 0.829 | [0.00, 0.86] |
| RF | 3 | 0.376 | **0.635** | 0.705 | [0.07, 0.86] |
| Logit | 5 | 0.583 | **0.818** | 0.743 | [0.39, 0.77] |
| RF | 5 | 0.606 | **0.841** | 0.760 | [0.42, 0.78] |

The 3-attack rows reproduce section 3 exactly. For logit, the label-permutation null (300 permutations) has a 95th percentile of 0.772 at 3 attacks and 0.789 at 5, and the one-sided permutation p-values are 0.365 and 0.289.

**Is n still too small to conclude? Yes, plainly.**
- At 5 attacks and 35 negatives a model with **no** signal has an expected one-sided upper bound of about **0.73**, and the smallest AUC we could reliably detect is **0.83**. The bar A10 set for certifying "near chance" is an upper bound below 0.60, which needs roughly 40 or more verified positives.
- The observed upper bounds (0.74 to 0.84) are all above that bar. The control therefore neither passes nor fails: the data are consistent with no market-context signal and also with a substantial one. **A5 remains inconclusive.**
- Going from 3 to 5 attacks moved the point estimates up (logit 0.505 to 0.583, RF 0.376 to 0.606). With 5 positives that movement is noise; the earlier RF 0.376 (below chance) was noise too. No claim rests on either.

**Caveats specific to this rerun.**
1. **Different entry doors.** Harvest and UwU are G1 trigger misses that enter through G2 (intra-block replay), while all 35 benign episodes were screened under G1 only; a G2 screen of benign sources was not done.
2. **A possible label leak in one feature.** `eth_gas_util_T` (gas used / limit of block T) is 0.999 (Inverse), 0.999 (Harvest) and 0.997 (UwU), against 0.52 (Zunami) and 0.28 (Makina); the benign median is 0.73 and 20% of benign rows exceed 0.99. Three attack blocks being nearly full is consistent with the attack transaction's own gas (UwU's single tx used 18.1M gas), so this feature may encode the attack itself. Dropping it moves the 5-attack results to logit AUC 0.566 (upper bound 0.800) and RF 0.554 (upper bound 0.788): small changes, and the conclusion is unchanged.
3. Both new attacks occur with no ETH move (`eth_absret_T` = `eth_absret_50` = 0), so the control's ETH-return features carry nothing for them.
4. Five attacks remain very few incidents, and they span 2020 to 2026 while the benign rows are all from 2022 and 2023.
