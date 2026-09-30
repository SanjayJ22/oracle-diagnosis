# Manipulation Incident Candidates — Phase 2 additions

Sourced from [SunWeb3Sec/DeFiHackLabs](https://github.com/SunWeb3Sec/DeFiHackLabs) (all `past/{year}/README.md`
archives 2021-2025 plus the current-year main README, fetched directly via GitHub's raw content —
not from memory). Every incident below was cross-checked against its own Foundry PoC source for
`vm.createSelectFork("mainnet", ...)`, then independently verified via a live `eth_getTransactionReceipt`
call against Ethereum mainnet — status `0x1`, real block — not copied from a post-mortem.

## Honest result: 13 confirmed, not 28-38

**Target was not reached, and this is reported plainly rather than padded.** Mainnet-confirmed,
well-documented, meaningful-size Ethereum oracle/price-manipulation incidents are a genuinely
scarcer resource than the phase-1 search's early hit rate suggested — phase 1 picked much of the
accessible, well-documented "low-hanging fruit" already. This pass found real, additional
incidents (including some large ones — see below), but repeated search rounds showed clearly
diminishing returns: **the large majority of candidates surfaced by title-keyword search
("oracle", "price manipulation", "TWAP", "inflation", "donation", "LP token", etc.) turned out to
be on the wrong chain** (BSC, Arbitrum, Base, Polygon, Optimism, Fantom, Linea, zkSync all
appeared repeatedly) or too small/thin to meet this project's documentation bar. This chain
distribution is itself worth noting: recent large, well-documented DeFi exploits increasingly
happen on L2s/altchains rather than Ethereum mainnet specifically, which directly constrains how
many more mainnet-only incidents this sourcing method can supply.

## Confirmed (13)

| # | Incident | Date | Tx Hash | Block | Lost | Manipulated Venue |
|---|---|---|---|---|---|---|
| 1 | BalancerV2 | 2025-11-03 | `0x6ed07db1a9fe5c0794d44cd36081d6a6df103fab868cdd75d581e3bd23bc9742` | 23,717,397 | **$120M** | Balancer V2 stable pools osETH/wETH (`0xDACf5Fa19b1f720111609043ac67A9818262850c`) and wstETH/wETH (`0x93d199263632a4EF4Bb438F1feB99e57b4b5f0BD`) — a stable-pool invariant precision-loss bug |
| 2 | SummerFi | 2026-07-06 | `0x0db528c44f23fc7fa4544684a2fab81096450a14aae8bc89f42cd0592d43da12` | 25,471,348 | ~$6.02M (DAI) | Summer.fi / Lazy Summer FleetCommander (`0x98c49e13bf99d7cad8069faa2a370933ec9ecf17`) — NAV inflation via a depegged xUSD |
| 3 | Makina | 2026-01-20/21 | `0x569733b8016ef9418f0b6bde8c14224d9e759e79301499908ecbcd956a0651f5` | 24,273,362 | ~$5.1M | Makina Caliber/Machine + DUSD/USDC pool (`0x32e616f4f17d43f9a5cd9be0e294727187064cb3`) |
| 4 | Raft_fi | 2023-11-10 | `0xfeedbf51b4e2338e38171f6e19501327294ab1907ab44cfd2d7e7336c975ace7` | 18,543,486 | ~$3.2M | Raft Finance position/collateral contract (`0x9ab6b21cdf116f611110b048987e58894786c244`) — donate-inflate exchange-rate/rounding |
| 5 | TOPBPool | 2026-06-09 | `0x967aa34c69b7775c718545c7f94d92e965eb5fc553c0f27f6f1a9c65c93ac156` | 25,279,892 | 944.20 WETH | Governance token-mint + Balancer BPool drain (voting impl. `0xb935c3d80229d5d92f3761b17cd81dc2610e3a45`) |
| 6 | WiseLending | 2023-10-13 | `0x7ac4a98599596adbf12fffa2bd23e2a2d2ac7e8989b6ea043fcc412a29126555` | 18,342,121 | ~$260K | WiseLending pool contract (`0x84524baa1951247b3a2617a843e6ece915bb9674`) — donate-inflate exchange-rate/rounding |
| 7 | bZxProtocol | 2023-12-02 | `0x0fc5c0d41e5506fdb9434fab4815a4ff671afc834e47a533b3bed7182ece73b0` | 18,695,729 | ~$208K | bZx vault contract (`0x7f3fe9d492a9a60aebb06d82cba23c6f32cad10b`) — inflation attack |
| 8 | edel-xstock | 2026-07-01 | `0xe2320086b2815d21b0927839bd0e306466c29a68d38d5361e99dd21ec5472612` | 25,434,062 | ~$204K | `0xBd497eE429D9D3E46446339286271b3714a83B29` — price oracle manipulation |
| 9 | BalancerV1BPool | 2026-08-31 | `0x72510b257cc09bde8435b83ac1636f9498ffc353583330600b5b8da43d0d1aff` | 25,872,274 | ~$110,839 (this pool; ~$234K across 5 pools total, only this one dated/blocked precisely) | Balancer V1 BPool, DPI/USDC/WETH/WBTC (`0x2257aaac34bcb27900291f7b84ee2565a6cbac57`) — `calcSingleInGivenPoolOut` rounding exploit |
| 10 | CompounderFinance | 2023-06-07 | `0xcff84cc137c92e427f720ca1f2b36fbad793f34ec5117eed127060686e6797b1` | 17,426,065 | ~$27,174 | Compounder cDAI-style vault (`0xaf274e912243b19b882f02d731dacd7cd13072d0`) — exchangeable-asset-ratio manipulation |
| 11 | MetaPool | 2025-06-17 | `0x57ee419a001d85085478d04dd2a73daa91175b1d7c11d8a8fb5622c56fd1fa69` | 22,722,911 | ~$25K | `0x48afbbd342f64ef8a9ab1c143719b63c2ad81710` — infinite mint via unvalidated ERC4626 mint |
| 12 | MahaLend | 2023-11-11 | `0x2881e839d4d562fad5356183e4f6a9d427ba6f475614ce8ef64dbfe557a4a2cc` | 18,544,605 | ~$20K | `0xfd11aba71c06061f446ade4eec057179f19c23c4` — donate-inflate exchange-rate/rounding |
| 13 | EnsoFinance | 2026-09-09 | `0x63fbfc4b47e810d604dbdab0db35b17366f421337d8c60955eb81cd5d6071ad3` | 25,934,827 | ~$15-20K (5.6 ETH) | Enso StrategyController + a thin FARM/WETH Uniswap V3 TWAP pool (exact pool address not pinned — see caveats) |

## Selection process

Systematically searched DeFiHackLabs' README index across multiple keyword passes: "oracle",
"price manipulation" (repeating and extending phase 1's search), then broader passes for "TWAP",
"spot price", "exchange rate", "vault inflation", "donation", "Curve/Compound/Aave/Balancer/Maker/
Yearn/Convex/Frax/Lido/Uniswap" (mainnet-native blue-chip protocol names, on the theory that
exploits against protocols that are themselves mainnet-native are more likely to be mainnet
incidents), and "LP token"/"liquidity manipulation"/"ERC4626"/"vault exploit".

**Confirmed wrong-chain, checked via each PoC's own fork call (not assumed)**: Lodestar
(arbitrum, $4M), Allbridge (bsc, $550K), Fortress Loans (bsc — already known from phase 1),
Rikkei Finance (bsc, $1.1M), Moonwell ×2 (base, $1M and $1.78M), WhalebitOracleManipulation
(polygon, $824K), SingularityDynaVault (base, $413K), DLMC (bsc, $222K), CozyFinance (optimism,
$160K), CookFinanceIssuance (bsc, $50K), Nmbplatform (bsc, $76K), ZoomproFinance (bsc, $61K),
BeatXswap (bsc, ~$70K), PolterFinance (fantom, $7M), CompoundFork (base, $1M), Venus_ZKSync
(zksync), Venus THE (bsc), PerpPair (linea, $165K), Gamma (arbitrum, $6.3M), ChannelsFinance
(bsc, $320K), HundredFinance (optimism — at least this PoC variant), ATM (bsc, denominated in
WBNB), MONA LisaVault (bsc, $60.95K). That's a striking number of otherwise well-documented,
sometimes very large incidents ($7M, $6.3M, $4M) excluded purely for chain.

**Checked and excluded for size/documentation, consistent with the existing bar**: BoJLeverageMarket
($7.2K), and the large tail of obvious memecoin/deflationary-token/tax-token titles across all
years (BGLD, TIFIToken, MU&MUG, APC, INUKO, Circle ×2, EGD Finance, SpaceGodzilla, and dozens more
— not individually re-verified since the pattern is unambiguous by name and none showed a real
loss amount or credible analysis link).

**DODO (2021-03-08, $700K, mainnet-confirmed, real official post-mortem) was found but NOT
included** — its autogenerated PoC file has no embedded attack-tx comment, and a targeted
block-range scan for a transaction touching its DVM pool contract in the fork block's immediate
vicinity found nothing. Pinning down the exact transaction would need either a wider/costlier
block scan or an external source for the exact tx hash — flagged as a candidate for a future
pass, not force-included without a verified transaction.

## Honest caveats

- **Venue identification depth is uneven across these 13, by necessity given the volume needed.**
  BalancerV2, SummerFi, Makina, and Raft_fi have real corroborating analysis (BlockSec/SlowMist/
  peckshield threads or the protocol's own post-mortem) beyond just the PoC's own claim — treat
  these as high-confidence. The remainder are sourced from each PoC's own `// Vulnerable
  Contract :` comment only, the same standard used for 5 of phase 1's 8 additions — reasonable
  evidence, but not independently cross-checked against a second source the way BalancerV2/
  SummerFi/Makina/Raft_fi were, or the way the original 5's incidents were. A dedicated review
  pass (the kind that caught MorphoBlue's real root cause and CurveLlamaLend/ResupplyFi's wrong
  initial venues in phase 1) has NOT been done for these 13 — recommended before treating their
  `reserve_skew` values as fully trustworthy.
- **EnsoFinance's venue is the least precisely pinned of the 13** — the PoC describes the
  mechanism (a thinly-observed Uniswap V3 pool feeding an EnsoOracle TWAP estimator) in prose but
  doesn't give a single clean pool address the way the others do. Flagged for the coordinator to
  either pin down precisely or treat this one incident's reserve_skew as low-confidence.
- **BalancerV1BPool's $234K aggregate figure spans 5 pools**; only the one pool/tx documented
  above (~$110,839) has a precise block and date. If the coordinator wants the other 4 pools'
  drains as additional incidents, they'd need separate research — not attempted here since the
  PoC's header only detailed this one pool's tx precisely.
- **TOPBPool's loss (944.20 WETH) was not converted to USD** — depends on ETH's price on
  2026-06-09, not looked up here; the coordinator should compute this from already-available
  Chainlink data when integrating.
- This is NOT an exhaustive scan of DeFiHackLabs' full corpus — a systematic pass covering every
  single "Flashloan Attack"-titled entry (hundreds, across years, mostly tiny scam tokens by
  spot-checking) was not performed; only keyword-targeted passes likely to surface real DeFi
  protocol incidents were run. A future pass with more time budget could plausibly find a modest
  number of additional mainnet incidents this way, but based on the hit rate observed here
  (roughly 1 real mainnet find per 3-5 candidates checked, and a large fraction of the "biggest"
  incidents already being on other chains), reaching 40-50 total from this specific source alone
  looks unlikely without either lowering the documentation bar further or drawing from additional
  incident databases beyond DeFiHackLabs (Rekt.news, Immunefi's disclosed reports, SlowMist's
  Hacked database) — not attempted in this pass, out of scope for what was asked.

## Summary for integration

13 new incidents, sizes from ~$15K to $120M (median firmly in the low-hundred-thousands, with two
outliers — BalancerV2 at $120M and SummerFi/Makina/Raft_fi in the $3-6M range). EnsoFinance (#13)
was subsequently excluded during integration (see `reports/loocv_150_incidents.md` §1) because its
own research report flagged the venue as not precisely pinned, leaving **12** integrated into
`build_features.py`'s `PHASE2_MANIPULATION_INCIDENTS`.

## Addendum: reserve_skew resolution pass (8 of the 12 corrected)

Flagged above as a real risk ("recommended before treating their reserve_skew values as fully
trustworthy") — exactly this happened. Of the 12 integrated, **8 came back with `reserve_skew`
unresolved** (zero balance at both the incident and baseline blocks, meaning the guessed venue/
token was wrong, not that nothing happened). A dedicated resolution pass — reading each attack
transaction's own Transfer logs directly via `eth_getTransactionReceipt`, the same standard used
for phase 1's MorphoBlue/CurveLlamaLend/ResupplyFi corrections — found:

- **TOPBPool: FIXED.** The originally-configured address (`0xb935c3d80229d5d92f3761b17cd81dc2610e3a45`,
  taken from the PoC's own header comment) does not appear anywhere in the attack transaction's 154
  logs. Direct log decoding found the real venue: a bonding-curve-style AMM at
  `0x0fa3e014fa2e751f78e53dca766fac2223327329` that the attacker drains by minting 10 billion TOP
  governance tokens and repeatedly dumping them in for ever-shrinking WETH amounts. This is a
  genuine, persisting drain (WETH balance falls from 281.34 to ~0 and stays there), not an atomic
  round-trip — `reserve_skew` now resolves to a clean, extreme signal (+670,679, i.e. TOP's balance
  grew ~670,680x). Confirmed via a fresh alignment-probe check: this is now the single largest-
  magnitude `reserve_skew` value in the entire dataset.
- **7 DROPPED, not kept as a misleading NaN**: SummerFi, Raft_fi, bZxProtocol, edel-xstock,
  CompounderFinance, MetaPool, MahaLend. Each was individually re-investigated via direct
  transaction-log decoding (not re-trusting the PoC's declared address a second time) and falls
  into one of two categories:
  - **Diffuse, no single trackable venue** (SummerFi, edel-xstock): the real exploit spans 300+
    logs across a dozen+ nested vault/collateral/debt tokens (SummerFi: Api3CoreUSDC, AVGUSDCcons,
    KPK_USDC_Prime, skyMoneyUsdcRiskCapital, LVUSDC, sUSDS, sUSDC, USDS, DAI; edel-xstock: an
    Aave-fork tokenized-stock market spanning wGOOGLx, wSPYx, wQQQx, wMSTRx, wNVDAx, wTSLAx). No
    single venue balance represents either incident.
  - **Exchange-rate/accounting exploits, correct venue confirmed but architecturally invisible to
    a balance-ratio metric** (Raft_fi, bZxProtocol, CompounderFinance, MetaPool, MahaLend): in each
    case the real venue and token were identified and confirmed active in the attack tx's own
    logs (real fund flows visible — e.g. MetaPool's real 200 WETH Balancer-flash-loan-funded
    round-trip, MahaLend's real 13.9M USDC donation-attack round-trip), but the underlying token
    balance returns to ~baseline within the *same* transaction (a manipulated exchange-rate/share-
    price is what's actually exploited, not a persisting balance change) — or, for CompounderFinance
    specifically, the vault holds ~0 idle DAI by design at all times (auto-routes into yDAI
    immediately), so a DAI balance was never going to show a meaningful skew regardless of which
    block is checked. All 5 show genuine `baseline=0, now=0` (or ~0) at their now-correctly-
    identified venues — confirmed not a wrong-venue-guess problem, since the same zero-balance
    result held before AND after the correction.

**Net effect: manipulation drops from 12 (phase 2) / 25 (combined) to 5 (phase 2) / 17 (combined,
across original + phase 1 + phase 2) — reported honestly rather than force-keeping weak or
misleading data.** Full updated LOOCV re-evaluation on the resulting 105-incident dataset in
`reports/loocv_150_incidents.md`.
