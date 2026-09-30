# Manipulation Incident Candidates — Phase 3 additions

Sourced from [SunWeb3Sec/DeFiHackLabs](https://github.com/SunWeb3Sec/DeFiHackLabs). Unlike phase 1/2,
which fetched each `past/{year}/README.md` separately, this pass discovered that the **main
`README.md`'s table of contents alone is the master index of all 854 incidents ever recorded**
(2017–2026-09-11), each entry's link-anchor text carrying the same short vulnerability description
that lives in the per-year body pages. That let this pass grep one 3,356-line file for keyword hits
across the *entire* corpus at once, rather than re-running keyword passes six times across six
year-files. Every incident below was independently verified via a live `eth_getTransactionReceipt`
call against Ethereum mainnet (status `0x1`, real block — not copied from the PoC's own comments),
using the project's `get_web3()` helper from `src/fetch_chainlink.py`.

## Honest result: 7 confirmed, out of 12 mainnet-confirmed candidates found

**Part 1 (sourcing)** found 12 new, real, mainnet-confirmed, plausible candidates beyond the 17
already in the dataset (see keyword list below). **Part 2 (pre-screening, done for every one of the
12 before finalizing anything)** decoded each attack transaction's own Transfer logs and ran a
before/after balance check (attack block vs. ~300 blocks / ~1h earlier), exactly the check that burned
8 of phase 2's 12 originally-integrated incidents. Of the 12:

- **7 survived** with a clean, nonzero, persisting balance signal at a correctly-identified venue.
- **5 were dropped**: 2 for the same atomic-round-trip/diffuse-venue failure signature phase 2 hit
  (BaoCommunity, EFVault), 1 for a clearly diffuse multi-token venue (DeFiPlaza), and 2 for being
  too small/thin-sourced despite an otherwise-clean signal (ArrakisGUNI 2026-08, ThetanutsVaultShareRounding)
  — consistent with the size/documentation bar phase 1/2 already applied elsewhere.

This confirms phase 2's own prediction: DeFiHackLabs mainnet coverage is thinning out, but **it is
not dry** — a wider keyword net (vault/share-price/collateral/liquidation/rounding/precision/donation/
inflation, rather than just oracle/TWAP/spot-price) still surfaces real, usable incidents. 7 clean new
mainnet manipulation incidents is the honest number this pass found — not padded up or down.

## Selection process

Extracted all 854 TOC entries from the main README in one pass (`grep -oP '^\[\d{8}[^\]]*\]\([^\)]*\)'`)
and keyword-filtered the description text for terms phase 1/2 had **not** yet tried: `vault`,
`share-price`, `pps`, `collateral`, `liquidat`, `rounding`, `precision`, `donation`, `inflat` (phase
1/2 had used `oracle`, `TWAP`, `spot price`, `exchange rate`, `vault inflation`/`vault exploit`,
`donation` narrowly, protocol names, and `LP token`/`ERC4626`). This surfaced ~30 hit candidates;
after excluding already-integrated incidents (17), already-dropped incidents (MorphoBlue, EnsoFinance,
the 7 from phase 2's addendum), and titles that were obviously tiny memecoin/tax-token noise, 19
distinct new candidates remained worth checking on-chain.

**`vm.createSelectFork(...)` network check (from each PoC's own source, not assumed)** immediately
removed 7 of the 19 for being on the wrong chain:

| Incident | Date | Chain (from PoC fork call) | Lost |
|---|---|---|---|
| DualPools | 2024-02-15 | `bsc` | ~$42K |
| HundredFinance (2023-04-15 variant) | 2023-04-15 | `optimism` | $7M (re-confirms phase 2's note — same protocol, different chain instance) |
| MidasCapitalXYZ | 2023-06-17 | `bsc` | ~$600K |
| RadiantCapital | 2024-01-02 | `arbitrum` | ~$4.5M |
| Sonne Finance | 2024-05-14 | `optimism` | $20M |
| Univ3CollateralToken | 2026-03-24 | `optimism` | $57K |
| Vault4626 | 2026-06-29 | `base` | 13.53 WETH |

**Re-confirmed already-excluded**: GMX (2025-07-09, "share price manipulation", $41M) forks
`arbitrum` (`355878385 - 1`) — the same incident phase 1 already excluded by this figure; re-verified
here rather than assumed, since this pass's keyword ("share-price") surfaced it independently.

**Excluded for size (mainnet-confirmed but below the existing bar)**: kTAF ($8K), MetaLend ($4K),
AmpKashi ($572.31) — all mainnet, all real, all well below the size floor phase 1/2 already applied
(smallest kept-for-size incident in the dataset is ~$105K; smallest previously-*excluded*-for-size
was ElevateFi at $16K).

**Excluded for wrong-chain + size (BNB/BUSD-denominated, confirmed `bsc` fork)**: CCV (~3.2K BUSD),
DominoTT (~5 WBNB), BigBangSwap (~$5K BUSD), BNBX (~75 BNB), P719Token (547 BNB / ~$312K but BSC).

**Excluded as out-of-category**: KyberSwap (2023-11-22, ~$48M) — a genuine large incident, but its
root cause is a concentrated-liquidity tick/precision bug exploited identically across 6 chains in
17 transactions, not an oracle/price-feed manipulation; pinning one clean mainnet-only tx and venue
for a bug whose whole nature is "spread across chains" didn't fit this project's per-incident,
single-venue model, and it was not pursued further.

That leaves **12 mainnet-confirmed candidates that went through pre-screening (Part 2)**.

## Pre-screening (Part 2): Transfer-log decoding + before/after balance check

Same method as the project's established resolution passes
(`src/recompute_phase1_manipulation_curve_features.py`, `src/recompute_phase2_manipulation_curve_features.py`):
`get_coin_balances()` (raw `balanceOf()`) at the attack block vs. 300 blocks (~1h) earlier, with the
Balancer V2 vault-based method (`getPoolId()` + `getPoolTokens()`) used instead of raw `balanceOf()`
wherever a Balancer V2/Linear-pool architecture was involved, and native `eth_getBalance` used for
the one incident (USM) where the drained asset was native ETH rather than an ERC20.

### Survived (7)

| # | Incident | Date | Tx Hash | Block | Lost | Manipulated Venue |
|---|---|---|---|---|---|---|
| 1 | AjnaFinance | 2026-08-28 | `0x12dfde527ef62882bfabb64362c9ae0e6bfb628363bd298d0d0956c9a114e4f5` | 25,854,888 | ~$124.8K (this pool; ~$775K aggregate across 7 Ajna pools hit the same day) | Ajna ERC20Pool, cbETH/WETH (`0xad24FC773e125Edb223C38a39657cB64bc7C178e`) |
| 2 | BalancerBoostedPool2023 | 2023-08-27 | `0x2a027c8b915c3737942f512fc5d26fd15752d0332353b3059de771a35a606c2d` | 18,004,652 | ~$2M | Balancer V2 bb-a-USDC Linear Pool (`0x9210F1204b5a24742Eba12f710636D76240dF3d0`) — precision-loss rate manipulation |
| 3 | DRLVaultV3 | 2025-11-10 | `0xe3eab35b288c086afa9b86a97ab93c7bb61d21b1951a156d2a8f6f5d5715c475` | 23,769,387 | $100K (USDT/USDC) | DRL leveraged vault (`0x6A06707ab339BEE00C6663db17DdB422301ff5e8`) — thin-pool slippage/valuation exploit |
| 4 | EFLeverVault | 2022-10-14 | `0x160c5950a01b88953648ba90ec0a29b0c5383e055d35a7835d905c53a3dda01e` | 15,746,342 | ~750 ETH (~$995K, this tx's reported figure) | EF Lever Vault (`0xe39fd820B58f83205Db1D9225f28105971c3D309`) — unverified flashloan callback, Aave-oracle-priced leveraged stETH position |
| 5 | SecuredFi | 2026-09-05 | `0xcd6159860783d8d481cc4bf4dceddc88acdca6bb08f6445525b2904cfd75b1da` | 25,914,192 | ~$72K (this drain; ~$104K aggregate across copycat drains) | Secured Finance TokenVault (`0xb74749b2213916b1da3b869e41c7c57f1db69393`) — same-block self-trade manipulates `getMarketUnitPrice()` |
| 6 | ThetanutsIndexVault | 2026-06-15 | `0xbba9f138fe39503bfd1aa62932dbd6ab35d37d23d48e4b7bf2988a9d5dc39fec` | 25,323,329 | $105,471.50 USDC | Thetanuts BTC/USD component vault (`0x3BA337F3167eA35910E6979D5BC3b0AeE60E7d59`); ETH/USD component vault (`0xE1c93dE547cc85CBD568295f6CC322B1dbBCf8Ae`) also drained same tx |
| 7 | USM | 2026-08-09 | `0xfae5e751b8ce01457cbb6b529839f24a0cff50faaabcbd0fd02ca0cf559b050e` | 25,716,150 | ~70.8 ETH (~$135.8K @ $1,917.46 ETH/USD at block) | USM stablecoin contract (`0x2a7FFf44C19f39468064ab5e5c304De01D591675`) — split-invariant `defund()` redemption curve, drains native ETH |

### Before/after balance numbers (the actual evidence, not just "looks good")

All at `BASELINE_LAG_BLOCKS = 300` (~1h), same convention as every other recompute pass in this
project.

**1. AjnaFinance** — `get_coin_balances(0xad24FC773e125Edb223C38a39657cB64bc7C178e, [cbETH, WETH])`
- cbETH (`0xBe9895146f7AF43049ca1c1AE358B0541Ea49704`): baseline `48.7855`, now `0.6582` → **-98.65%**
- WETH: baseline `1.0365`, now `4.5105` → **+335.18%**
- `reserve_skew` (max abs skew) = **+3.3518** (WETH); cbETH's -0.9865 is the more intuitive read of
  "the pool got drained," WETH's spike is the counterparty inflow — both are real, both are shown.

**2. BalancerBoostedPool2023** — Balancer V2 Vault method: `getPoolId()` on the bb-a-USDC pool, then
`getPoolTokens(poolId)` on the shared Vault (`0xBA12222222228d8Ba445958a75a0704d566BF2C8`), same
architecture-aware method already used for `BalancerV2` in the existing dataset.
- USDC (`0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48`): baseline `108,375.77`, now `134,894.31` →
  **+24.47%** — the real, meaningful, persisting signal.
- aUSDC (`0xd093fA4Fb80D09bB30817FDcd442d4d02eD3E5de`, Aave V1-style aToken, 18 decimals): baseline
  `9.7×10⁻¹³`, now `0.0` → nominally -100%, but this is **dust at both ends, not a meaningful skew**
  (the pool's wrapped-asset buffer was already ~empty 300 blocks before the attack; the PoC's own
  "drain all aUSDC from target pool" step is real but was draining a near-zero balance). Recommend
  using **USDC's +0.2447** as `reserve_skew`, not the degenerate aUSDC value a naive max-abs-skew
  pick would surface — flagged explicitly so this isn't silently miscomputed the way phase 2's 8
  failures were.

**3. DRLVaultV3** — `get_coin_balances(0x6A06707ab339BEE00C6663db17DdB422301ff5e8, [USDC, WETH])`
- USDC: baseline `100,000.0`, now `0.0` → **-100%** — a full, clean drain, matching the reported
  "$100K USDT" loss almost exactly.
- WETH: baseline `0.0`, now `0.00012` (dust) → +inf, not meaningful.
- `reserve_skew` = **-1.0** (USDC).

**4. EFLeverVault** — **venue/token corrected after the first check came back all-zero.** The PoC's
own declared WETH/EF_LEVER_TOKEN pair showed `baseline=0.0, now=0.0` for both — the exact "wrong
guess" failure signature from phase 2. Decoding the attack tx's Transfer logs directly (57 logs)
showed the real value path: the vault's Aave V1 aSTETH position gets burned (`aSTETH` Transfer,
vault → `0x0`, exactly `833.566724`) and the underlying stETH is forwarded out to
`0xDC24316b9AE028F1497c275EB9192a3Ea0f67022` (the Curve stETH pool) in the same tx. Re-ran the
balance check on the correct token, aSTETH (`0x1982b2F5814301d4e9a8b0201555376e62F82428`):
- aSTETH: baseline `2,321.5660`, now `0.3882` → **-99.98%** — clean, real, persisting.
- `reserve_skew` = **-0.9998**. (Note: this represents ~1,933 stETH of value leaving the vault's
  Aave collateral position, larger than the "~750 ETH" figure in the PoC's own header — the PoC
  documents two attack transactions, a frontrun-bot tx and this exploiter tx; the reported figure
  may reflect only the final attacker's net take after the frontrunner intercepted part of the
  value, while the balance read captures the vault's full outflow in this tx.)

**5. SecuredFi** — `get_coin_balances(0xb74749b2213916b1da3b869e41c7c57f1db69393, [WBTC])`
- WBTC (`0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599`, 8 decimals): baseline `0.91171`, now `0.01272`
  → **-98.60%** — clean, real, persisting.
- `reserve_skew` = **-0.9860**.

**6. ThetanutsIndexVault** — **venue/token corrected after the first check came back all-zero.**
The PoC's own declared `INDEX_VAULT` (`0xC2C3AE0a7b405058558C9b4a63b373486CB86Ac7`) held `0.0` USDC
at both blocks — the vault itself is a pure share-accounting contract, not where the USDC lives.
Decoding the attack tx's Transfer logs (429 logs total) found the real source: USDC flows out of
**two** underlying Thetanuts component vaults directly to the attack contract, in amounts that sum
to exactly the reported $105,471.50 loss:
- BTC_USD_VAULT (`0x3BA337F3167eA35910E6979D5BC3b0AeE60E7d59`): baseline `71,995.54`, now `1,679.98`
  USDC → **-97.67%** (this tx moved $70,315.56 USDC out).
- ETH_USD_VAULT (`0xE1c93dE547cc85CBD568295f6CC322B1dbBCf8Ae`): baseline `35,212.16`, now `56.23`
  USDC → **-99.84%** (this tx moved $35,155.94 USDC out).
- `70,315.56 + 35,155.94 = 105,471.50` — exact match to the PoC's own reported loss, strong
  independent confirmation this is the real venue pair, not a guess. `reserve_skew` = **-0.9767**
  (BTC_USD_VAULT, the larger and primary venue) with ETH_USD_VAULT as a secondary confirming venue.

**7. USM** — native ETH via `eth_getBalance`, not `balanceOf()` (this attack drains ETH directly,
not WETH — the PoC's own header explicitly notes "The Chainlink/Uniswap TWAP oracle reads are
identical before and during the attack... nothing about the ETH/USD price is moved," i.e., a
split-invariance rounding exploit, not literally an oracle-price attack, but it does drain the
protocol's real ETH reserve, the same way donation/rounding attacks elsewhere in this dataset do):
- Native ETH balance of `0x2a7FFf44C19f39468064ab5e5c304De01D591675`: baseline `132.5889`, now
  `61.7580` → **-53.42%** — clean, real, persisting.
- `reserve_skew` = **-0.5342**.

### Dropped after pre-screening (5)

- **BaoCommunity** (2023-07-04, ~$46K, tx `0xdd7dd68cd879d07cfc2cb74606baa2a5bf18df0e3bda9f6b43f904f4f7bbdfc1`,
  block 17,620,871): classic donate-inflate exchange-rate attack against Bao Finance's `bdbSTBL`
  market (`0xb0f8Fe96b4880adBdEDE0dDF446bd1e7EF122C4e`) — bSTBL is donated to inflate the exchange
  rate, borrowed against, then **redeemed back out almost entirely within the same transaction**
  (the PoC's own comment: "redeem almost all underlyingtoken"). Balance check confirms:
  `bSTBL` (`0x5ee08f40b637417bcC9d2C51B62F4820ec9cF5D8`) balance at the venue is `baseline=0.0,
  now=1×10⁻¹⁸` (dust) — the exact all-zero/atomic-round-trip failure signature already found for
  Raft_fi/bZxProtocol/CompounderFinance/MetaPool/MahaLend in phase 2's addendum. Same category,
  same reason. Dropped.
- **DeFiPlaza** (2024-07-05, ~$200K, tx `0xa245deda8553c6e4c575baff9b50ef35abf4c8f990f8f36897696f896f240e3a`,
  block 20,240,539): a single Balancer flashloan of **9 different tokens simultaneously**
  (WBTC, LINK, DAI, AAVE, MKR, USDC, WETH, CRV, USDT) manipulates the DeFiPlaza multi-asset AMM pool
  (`0x00C409001C1900DdCdA20000008E112417DB003b`) across all of them at once, with attacker-balance
  bookkeeping tracked across 14+ separate tokens in the PoC itself. No single venue balance
  represents this incident — the same diffuse-multi-venue category that dropped SummerFi and
  edel-xstock in phase 2. Dropped without forcing a single-token guess.
- **EFVault** (2023-02-24, ~$5.1M, tx `0x1fe5a53405d00ce2f3e15b214c7486c69cbc5bf165cf9596e86f797f62e81914`,
  block 16,696,240): root cause is a storage-collision bug in an Enzyme-Finance-style fund
  (`ENF`, `0xBDB515028A6fA6CD1634B5A9651184494aBfD336`) redeemed for far more USDC than it should be
  worth. `ENF` itself holds `baseline=0.0, now=0.0` USDC (it's a pure share/accounting contract, not
  the asset custodian). Decoding the attack tx's Transfer logs (41 logs) traced the real USDC/cUSDC/
  DAI/cDAI/NOTE flow through **5+ intermediary contracts** (Compound-style cToken redemptions routed
  through what appears to be the fund's Comptroller/Vault-split architecture) before reaching the
  exploiter — a diffuse multi-hop flow with no single, confidently-identifiable venue address, and a
  root cause (storage collision, no market price ever moves) categorically similar to MorphoBlue's
  phase-1 exclusion ("a shaky venue is grounds to drop rather than guess"). Dropped.
- **ArrakisGUNI** (2026-08-23, ~2.94 ETH / ~$10K net, tx
  `0x6ae3af4b2f25a56594de99cfb31369150dd9ac059c49efe04b9e3e0163dbc672`, block 25,817,966): the
  balance signal here is actually **clean** — the Arrakis V1 G-UNI ENS/WETH vault
  (`0x7c687f775A3b73BBAb0E15832F24caaB5D53bDDe`) shows WETH baseline `6.234` → now `0.744`
  (**-88.06%**) and ENS baseline `924.33` → now `993.77` (**+7.51%**), a real, persisting mint/burn
  mispricing loss, not an atomic round-trip. It's dropped purely for **size**: ~$10K net profit is
  below the size floor phase 1 already applied when it excluded a different, earlier ArrakisGUNI
  incident at ~$8K for the same reason. Kept out for consistency, not because the signal is bad —
  flagged in case the coordinator wants to reconsider given the dataset's smallest current entries
  (MahaLend-scale, ~$20K) aren't dramatically larger.
- **ThetanutsVaultShareRounding** (2026-04-20, 0.15 WBTC / ~$15-17K, tx
  `0x1bc83899060c27106b6fb4257b208925085794e83b21c444854442fd3554862c`, block 24,923,219): also a
  **clean** signal — WBTC balance at the Thetanuts BTC/USD covered-call vault
  (`0x80b8EEb34A2Ba5dd90c61e02a12eA30515dCa6f5`) goes from baseline `0.15180` to now `0.000024`
  (**-99.98%**), matching the reported "0.15 WBTC" loss almost exactly. Dropped for size and
  sourcing thinness (single Telegram-alert source, `t.me/defimon_alerts/2933`, no independent
  corroboration) — the same profile phase 1 used to exclude SharwaMarginTrading ($32.85K),
  ElevateFi ($16K), and PeapodsFinance ($3.5K). Numbers shown here for transparency in case the
  coordinator judges the clean signal outweighs the size/sourcing concern.

## Honest caveats

- **BalancerBoostedPool2023's aUSDC dust reading is a real methodological wrinkle, not an error**:
  do not let an automated "max abs skew" picker select the degenerate -100%-from-dust aUSDC value
  over the meaningful +24.47% USDC value if this gets integrated — call it out explicitly the way
  this report does, or the resulting `reserve_skew` will be a misleadingly large number computed
  from noise.
- **EFLeverVault and ThetanutsIndexVault both required venue correction after the first check came
  back all-zero** — exactly phase 2's failure mode, caught this time by re-decoding Transfer logs
  before finalizing rather than after integration. This is the entire point of doing Part 2 before
  writing anything down as "confirmed."
- **USM is arguably a boundary case for the "manipulation" class**: its own PoC header explicitly
  states "this is a pure pricing/rounding logic bug, NOT price manipulation... nothing about the
  ETH/USD price is moved." It's included here because it fits this project's *operational*
  definition of the class as established by precedent (WiseLending, TOPBPool, BalancerV1BPool, etc.
  are all rounding/accounting exploits producing a persisting reserve_skew, not literal price-feed
  attacks) — flagged so the coordinator can exclude it if a stricter definition is wanted.
- **Only 19 of DeFiHackLabs' ~854 total incidents were keyword-hit and checked this pass** — this is
  still not an exhaustive scan (a systematic pass through every "Flashloan Attack"/"Access Control"-
  titled entry was not attempted, same scope limitation phase 2 noted). A future pass with a
  different keyword set (e.g. "index price," "peg," "redeem," "slippage," "reward") could plausibly
  find a handful more, but given this pass's hit rate (7 kept out of ~30 initial keyword hits, most
  of the loss coming from wrong-chain and size exclusions, same pattern as phase 2), the well is
  visibly getting shallower, not dry.
- **Sourcing outside DeFiHackLabs (Rekt.news, Immunefi, SlowMist) was not attempted this pass** —
  DeFiHackLabs' own master-README-as-full-index discovery (see top of this report) made it clearly
  the higher-leverage next step to exhaust before switching sources, and it was not yet exhausted
  (only ~30 of 854 entries keyword-matched and checked).

## Summary for integration

**7 new manipulation incidents**, sizes from ~$72K to ~$2M (median ~$105K): AjnaFinance,
BalancerBoostedPool2023, DRLVaultV3, EFLeverVault, SecuredFi, ThetanutsIndexVault, USM. All 7 have a
confirmed, nonzero, persisting `reserve_skew` at a correctly-identified (and in 2 cases,
log-decoding-corrected) venue, with before/after numbers shown above rather than asserted. If
integrated, this would take the dataset from 17 to 24 manipulation incidents (105 to 112 total),
short of the ~200-incident aspirational target but consistent with this project's standing rule to
report the true number rather than pad it. `price_dev` should be left `None` for all 7, same
reasoning as every non-ETH/BTC-peg incident already in the dataset (none has a single clean "implied
price vs. a peg" number — `reserve_skew` is the signal).
