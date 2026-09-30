# Manipulation Incident Candidates — Phase 1 additions

Sourced from [SunWeb3Sec/DeFiHackLabs](https://github.com/SunWeb3Sec/DeFiHackLabs) (all `past/{year}/README.md`
archives plus the current-year main README, fetched directly via the GitHub API/raw content —
not from memory). Every incident below was cross-checked against its own Foundry PoC source for
`vm.createSelectFork("mainnet", ...)` (excluding non-mainnet forks the same way the original 5's
candidate search did), then independently verified via a live `eth_getTransactionReceipt` call
against Ethereum mainnet — status `0x1`, real block, not copied from a post-mortem.

**Update after venue-verification pass**: 3 of the original 8 (MorphoBlue, CurveLlamaLend,
ResupplyFi) had uncertain venue identification when first added — flagged honestly at the time
rather than silently trusted. Each was re-investigated against its actual post-mortem.
**MorphoBlue is dropped** (root cause has no manipulated venue at all — see below).
**CurveLlamaLend and ResupplyFi are corrected** to their real venues, both confirmed against a
dedicated post-mortem and, for ResupplyFi, independently re-confirmed by decoding the attack
transaction's own logs on-chain. **Confirmed count: 7**, not 8.

## Selection process

Two of the original 8 (MonoX Finance, and Conic Finance 02 renamed from the original search's
"Conic Finance") were already surfaced as backup candidates in `reports/manipulation_candidates.md`
(that pass found 7 total, locked 5, left MonoX and Conic Finance as documented-but-unused
candidates, plus CompoundUni and MorphoBlue noted as available backups). This pass re-verified
all 4 on-chain and searched the DeFiHackLabs index further (all "oracle" and "price manipulation"
titled incidents, 2021–2026) for additional mainnet-confirmed, well-documented, meaningful-size
candidates, applying the same size/documentation bar the original search used (excluded LUSD at
$9,464 as "too thin" — this pass excluded a much larger set of sub-$50K, Telegram-alert-only-sourced
incidents on the same basis: GradientMakerPool $5K, FixedTokenBSwap $2.2K, Scorch $0.14 ETH,
ArrakisGUNI ~$8K, SharwaMarginTrading $32.85K, ElevateFi $16K, PeapodsFinance $3.5K,
StrategyLlamaLendConvex $563 — all real, all mainnet-confirmed, all rejected purely for size/
sourcing thinness, consistent with existing precedent).

Also checked and excluded for being on the wrong chain (confirmed via each PoC's own fork call,
not assumed): 0vix (polygon, $2M), NeutraFinance (arbitrum), LavaLending (arbitrum, $130K), GMX
(arbitrum, $41M — by far the largest single exclusion, purely a chain mismatch), BXH (bsc),
NXUSD (avalanche), Discover (bsc), RodeoFinance (arbitrum), HYDT (bsc), ImpermaxV3 (base),
Paribus (arbitrum). NOVO Protocol, DEUS DAO, ElephantMoney, and OneRingFinance were listed in
the README index but their PoC files 404'd at the expected path — not pursued further given the
8 initially found already met the phase-1 target.

## Confirmed (7)

| # | Incident | Date | Tx Hash | Block | Lost | Manipulated Asset / Venue |
|---|---|---|---|---|---|---|
| 1 | MonoX Finance | 2021-11-30 | `0x9f14d093a2349de08f02fc0fb018dadb449351d0cdb7d0738ff69cc6fef5f299` | 13,715,026 | $31M | MONO via Monoswap's own MonoXPool (custom AMM, vCash pricing corrupted after liquidity drain) |
| 2 | MEVBOTa47b | 2022-10-14 | `0x35ecf595864400696853c53edf3e3d60096639b6071cadea6076c9c6ceb921c1` | 15,741,333 | ~188 WETH (~$244K) | WETH/USDC — the SAME V3 0.05% pool (`0x88e6...f5640`) already used for the 12 volatility incidents |
| 3 | Conic Finance 02 | 2023-07-22 | `0x37acd17a80a5f95728459bfea85cb2e1f64b4c75cf4a4c8dcb61964e26860882` | 17,743,470 | ~$934K | crvUSD/UZD Conic omnipool share price, via Curve crvUSD/USDC pool |
| 4 | ZunamiProtocol | 2023-08-14 | `0x0788ba222970c7c68a738b0e08fb197e669e61f9b226ceec4cab9b85abe8cceb` | 17,908,950 | ~$2M | UZD (Zunami's cached stable price), via Curve UZD/crvFRAX pool |
| 5 | CompoundUni | 2024-02-23 | `0xaee0f8d1235584a3212f233b655f87b89f22f1d4890782447c4ef742b37af58d` | 19,290,921 | $439,537 | UNI, via Compound's own UniswapAnchoredView reading the UNI/WETH V3 pool |
| 6 | CurveLlamaLend | 2026-03-02 | `0xb93506af8f1a39f6a31e2d34f5f6a262c2799fef6e338640f42ab8737ed3d8a4` | 24,566,937 | ~$240K (attacker); ~$822K borrower losses | sDOLA's own vault (DolaSavings), atomically manipulated exchange rate |
| 7 | ResupplyFi | 2025-06-26 | `0xffbbd492e0605a8bb6d490c3cd879e87ff60862b0684160d08fd5711e7a872d3` | 22,785,461 | $9.6M | A newly-deployed, nearly-empty cvcrvUSD vault, donation-attacked |

Note on block numbers: 5 of the 7 land exactly one block after the PoC's own fork block — the
same convention already documented for 3 of the original 5 (Harvest, Inverse, UwU Lend). Conic
Finance 02 and CurveLlamaLend are the two exceptions — their PoCs fork at the exact attack block
itself, confirmed by the receipt's block number matching the fork block precisely, not assumed.

## Dropped: MorphoBlue

**Root cause has no manipulated venue at all — this incident does not belong in the manipulation
class.** Confirmed independently by two separate write-ups
([QuillAudits](https://medium.com/coinmonks/decoding-morphoblues-230k-exploit-6296565ced40),
[SolidityScan](https://blog.solidityscan.com/morphoblue-hack-analysis-638b685f8bf2/)): the PAXG/USDC
market's oracle had a static `SCALE_FACTOR` misconfiguration — a 12-decimal mismatch between
PAXG (18 decimals) and USDC (6 decimals) that priced PAXG at **$2.6 trillion**, wrong from the
moment the market was deployed. The attacker deposited $351 of PAXG and borrowed $230K — no
trade, no pool interaction, no market price movement of any kind was needed or occurred. My
original venue guess (the PAXG/WETH Uniswap V2 pair) was never actually touched by the exploit,
which is exactly why it showed near-zero reserve_skew (0.085%) — not because the signal was weak,
but because there was no manipulated venue to measure in the first place.

This is categorically different from every other incident in this dataset, including the 7 above:
manipulation, malfunction, and volatility are all defined as *market-observable* phenomena in this
project — a real price, somewhere, that diverges from truth. MorphoBlue's failure has zero
market signature: no feature this project computes (or could compute) would ever show anything
for it, not because the attack was well-hidden, but because nothing in the market moved. Including
it would mislabel a pure code/configuration bug as a market manipulation incident. Dropped, not
patched — per instruction, a shaky venue is grounds to drop rather than guess.

## CurveLlamaLend and ResupplyFi: corrected venues, confirmed against post-mortems

**CurveLlamaLend** — original guess (a Curve DOLA/sDOLA pool, `0x76A96...f4F50`) held zero raw
DOLA at both the incident block and baseline; wrong venue. Real target, confirmed via
[Curve's own governance post-mortem](https://gov.curve.finance/t/llamalend-sdola-long2-post-mortem/11020)
and [darknavy.org's technical writeup](https://www.darknavy.org/web3/exploits/sdola-llamalend-oracle-manipulation/):
**DolaSavings** (sDOLA's own vault), `0xE5f24791E273Cb96A1f8E5B67Bc2397F0AD9B8B4`. The attacker
flash-loaned ~10M USDC + 15,986 WETH from Morpho Blue, forced LLAMMA positions into
soft-liquidation, then called `DolaSavings.stake()` to atomically inflate sDOLA's
`convertToAssets()` price by 13.79% (1.189 → 1.353) within the same transaction, making the
soft-liquidated positions instantly unhealthy for hard liquidation. Corrected `reserve_skew`
(DOLA balance at DolaSavings, incident block vs. ~1h earlier): **-0.0162** (-1.6%).

*Caveat, not a further error*: this is real but visibly muted — the manipulation was atomic
(inflate, then the position was unwound within the same transaction), so a post-block balance
snapshot 300 blocks apart cannot see the in-transaction peak distortion. Same limitation
category as Inverse Finance's understated `reserve_skew` in the original 5. The venue is now
correct; the feature's sensitivity to atomic, same-block manipulations is a separate, known
limitation of the before/after-snapshot approach itself.

**ResupplyFi** — original guess (the Curve reUSD StableSwap pool, `0xc522A...B6F4F50`) held zero
raw crvUSD at both the incident block and baseline; wrong venue. Real target, confirmed via
[rekt.news's writeup](https://rekt.news/resupplyfi-rekt) **and independently re-confirmed by
decoding the attack transaction's own logs directly on-chain** (not just trusting the secondary
source — one web summary reported the vault's address with 64 hex characters, which is a
transaction-hash length, not a valid 40-character address, so it was verified from the primary
data instead): a classic donation attack against a newly-deployed, nearly-empty cvcrvUSD vault
controller, `0x89707721927d7aaeeee513797A8d6cBbD0e08f41`. Decoding the attack tx's crvUSD
`Transfer` events shows exactly 2,000 + 2 = 2,002 crvUSD sent directly to this address via a raw
`transfer()` call (not a deposit function) — a classic donation attack, corrupting the vault's
price-per-share math via an integer-division floor-to-zero. Corrected `reserve_skew` (crvUSD
balance, 0.0 → 2,002.0): **+inf** — a genuine, on-chain-confirmed "from zero" jump, the same
category as Cream Finance's +inf reserve_skew in the original 5.

## Alignment probe, re-run on all 3 reviewed incidents

| Incident | price_dev | cross_venue_spread | reserve_skew | Naive-feature spike? |
|---|---|---|---|---|
| MorphoBlue (dropped) | — | — | — | N/A — no venue exists to probe |
| CurveLlamaLend | NaN | NaN | **-0.0162** | No |
| ResupplyFi | NaN | NaN | **+inf** | No |

Both kept incidents show the same pattern as the rest of the dataset: the naive, ETH/USD-anchored
feature set shows nothing (both `price_dev` and `cross_venue_spread` are `NaN` — no clean
Chainlink/CEX pair for the true asset), and the manipulation signal is visible **only** at the
correctly-identified venue's `reserve_skew`. ResupplyFi's spike is now unambiguous (+inf, up from
a much weaker and wrongly-sourced +13.6% before correction); CurveLlamaLend's is real but modest
(-1.6%) for the atomicity reason explained above, not because the venue is still wrong.

## Reserve_skew results, final (7 confirmed incidents)

| Incident | reserve_skew (max abs balance skew) | Reading |
|---|---|---|
| MonoX Finance | -0.9997 | MONO balance -99.97%, USDC balance -99.7% — a near-total liquidity drain, consistent with the $31M scale |
| MEVBOTa47b | +0.0094 | via the standard WETH/USDC V3 path (no bespoke venue needed) |
| Conic Finance 02 | -0.0257 | modest skew in a large pool (~$934K exploit against ~$80M+ pooled) |
| ZunamiProtocol | +2.4652 | UZD balance +246.5% (large inflow), crvFRAX balance -99.8% (drained) — a dramatic, clearly-attack-shaped skew |
| CompoundUni | +2.1679 | WETH balance +216.8%, UNI balance -36.7% — large skew in a small pool, consistent with a flash-loan-sized trade |
| CurveLlamaLend | -0.0162 | DolaSavings' DOLA balance — real but muted by the atomic revert (see above) |
| ResupplyFi | +inf | cvcrvUSD vault controller's crvUSD balance, 0 → 2,002 — a genuine donation attack, cleanly captured |

## Reserve_skew methodology

Each incident's `reserve_skew` is computed as the largest absolute before/after balance change
(incident block vs. 300 blocks / ~1h earlier) across the actually-exploited venue's constituent
tokens, via the same generic `get_coin_balances()` helper (raw `balanceOf()` reads) already used
for 4 of the original 5 — see `src/recompute_phase1_manipulation_curve_features.py` for exact
venue addresses and token lists per incident. `price_dev` is left `None` for all 6 of these
(MonoX, Conic Finance 02, ZunamiProtocol, CompoundUni, CurveLlamaLend, ResupplyFi) — same
reasoning as Indexed/Inverse Finance in the original 5: none has a single clean "implied price
vs. a peg" number. MEVBOTa47b is the one exception: its exploited pool is literally the WETH/USDC
V3 pool already wired into this project's standard pipeline, so it gets `reserve_skew`,
`cross_venue_spread`, and `dex_oracle_spread` all computed the normal way — no bespoke code
needed.

## Honest caveats

- **Venue identification for the remaining 5 (MonoX, Conic Finance 02, ZunamiProtocol,
  CompoundUni, MEVBOTa47b) is still sourced from each PoC's own declared contract addresses,
  not a dedicated post-mortem cross-check** the way MorphoBlue/CurveLlamaLend/ResupplyFi and the
  original 5 now have. Their reserve_skew values look sensible (large, directionally consistent
  with each exploit's described scale), which is reassuring but not equivalent to independent
  confirmation — a reasonable next target if this dataset gets another review pass.
- **MonoX's reserve_skew is a raw balance-skew proxy**, not a faithful model of Monoswap's own
  internal vCash/vPrice accounting (which isn't a standard AMM invariant) — same caveat already
  applied to Indexed Finance in the original 5.
- **CompoundUni's true manipulated asset (UNI) has a real Chainlink feed on mainnet** that wasn't
  used here — ETH/USD was used as the documented fallback for consistency with the rest of the
  dataset and to avoid introducing an unverified feed address, the same tradeoff already made for
  the original 5's non-ETH/BTC incidents.
