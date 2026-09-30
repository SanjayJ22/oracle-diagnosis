"""Build the labeled feature table for the 20 locked incidents in reports/final_incidents.md.

Computes, per incident, at its block:
  price_dev          - (chainlink_price - cex_price) / cex_price, at the incident minute
  cross_venue_spread  - (dex_price - cex_price) / cex_price, at the incident block
  dex_oracle_spread   - (dex_price - chainlink_price) / chainlink_price, at the incident
                         block. Unlike cross_venue_spread, this has no CEX leg, so it's
                         available whenever a dex_pool is configured regardless of whether
                         a CEX reference exists for the asset -- but it requires dex_pool
                         and oracle_feed to quote the SAME asset pair (both already-fetched
                         quantities, no new data source); it is only computed where that
                         holds today (stETH/ETH and the 12 ETH/USD volatility incidents).
                         The 5 manipulation incidents and FTT/USD, UST/USD have no dex_pool
                         configured in INCIDENTS below (their DEX-side data, where it
                         exists at all, lives in fetch_curve.py's balance/share-price
                         reads for a DIFFERENT, unit-incompatible quantity -- e.g. Harvest's
                         yUSDC/yUSDT ratio vs its ETH/USD fallback feed -- so this feature
                         is correctly left missing there, not force-computed across
                         mismatched units).

                         FIXED CAVEAT (stETH/ETH row): _dex_price() originally read the raw
                         wstETH/WETH pool price with no conversion applied, but wstETH is a
                         yield-accruing WRAPPER around stETH (worth an ever-growing amount of
                         stETH over time), not stETH itself -- unlike reserve_skew (a same-
                         venue before/after RATIO over ~1h, where this slow drift cancels out
                         almost entirely), dex_oracle_spread is a LEVEL comparison against the
                         STETH/ETH oracle, so the uncorrected wrapping factor didn't cancel and
                         dominated the result (a first pass measured ~7.53% here, confirmed to
                         match the wstETH/stETH conversion rate itself to 4 decimal places --
                         i.e. almost entirely the wrapping factor, not a genuine DEX-vs-oracle
                         disagreement). Fixed below: _dex_price() now divides the wstETH/WETH
                         pool's raw price by the wstETH contract's own stEthPerToken() rate
                         (read at the same block -- the wstETH ERC20 wrapper contract itself,
                         not a new external data source) whenever it's used, so its output is
                         directly comparable, unit-for-unit, to the STETH/ETH oracle. This also
                         very slightly changes reserve_skew's value for this one row (the
                         correction factor drifts by a negligible amount over the ~1h baseline
                         window, so the effect is far below its previously-reported precision).
  heartbeat_elapsed   - seconds since the oracle's last update, at the incident block
  congestion          - incident block's base fee as a percentile of a trailing sample
                         (blank pre-EIP-1559)
  reserve_skew        - % change in DEX pool price from a trailing baseline block to the
                         incident block (only where a relevant Uniswap V2/V3 pool exists)
  ref_realized_vol    - std of 1-min log returns of the CEX reference price over a
                         trailing window ending at the incident minute

All windows are STRICTLY TRAILING (end at the incident, never extend past it) so the
no-lookahead requirement holds by construction, not by after-the-fact filtering.

Writes data/processed/features.parquet: one row per incident, features + label + provenance.
Does not train anything.
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from web3 import Web3

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_cex import fetch_cex_klines  # noqa: E402
from fetch_chainlink import _with_retry, get_round_data_at_block, get_web3  # noqa: E402
from fetch_dex import get_v2_reserves, get_v3_state  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
LONDON_BLOCK = 12_965_000  # EIP-1559 activation; no baseFeePerGas before this
TRAILING_WINDOW_MINUTES = 60  # for ref_realized_vol and price_dev/cross_venue_spread lookup
BASELINE_LAG_BLOCKS = 300  # ~1h at 12s/block, for reserve_skew's "before" snapshot
CONGESTION_SAMPLE_BLOCKS = 150_000  # trailing range to sample for the base-fee percentile
CONGESTION_SAMPLE_STRIDE = 6_000

# Uniswap pool addresses used below (all verified on-chain before use in this project's
# earlier steps): WETH/USDC V3 0.05%, WETH/USDC V2, wstETH/WETH V3 0.3%.
# Each tuple is (kind, address, invert): "invert" is True when the pool's own
# price_1_per_0 (token1/token0) is quoted as base-per-quote (e.g. ETH per USD for a
# USDC/WETH pool, since token0=USDC by address ordering) and must be flipped to
# quote-per-base (USD per ETH) to match the CEX convention (ETHUSDT = USD per ETH).
WETH_USDC_V3 = ("v3", "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640", True)
WETH_USDC_V2 = ("v2", "0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc", True)
# wstETH/WETH: token0=wstETH, token1=WETH -> price_1_per_0 = WETH per wstETH, which
# already matches Chainlink's STETH/ETH convention (ETH per stETH) -- no inversion.
# (Orientation matches; UNIT does not until _dex_price() applies the wstETH/stETH
# conversion below -- wstETH is a yield-accruing wrapper, not stETH itself.)
WSTETH_WETH_V3 = ("v3", "0xd340b57aacdd10f96fc1cf10e15921936f41e29c", False)

# wstETH token contract: exposes stEthPerToken(), the amount of stETH backing 1 wstETH
# (scaled 1e18) at a given block -- the SAME wrapper contract the pool above trades,
# not a new venue/data source. Needed to convert the wstETH/WETH pool's raw price into
# an ETH-per-stETH-equivalent price directly comparable to the STETH/ETH oracle.
WSTETH_TOKEN = "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0"
WSTETH_ABI = [
    {"inputs": [], "name": "stEthPerToken", "outputs": [{"name": "", "type": "uint256"}],
     "stateMutability": "view", "type": "function"},
]

# Per-incident config: (name, date, block, label, oracle_feed, cex_symbol, dex_pool, reference_note)
# oracle_feed/cex_symbol/dex_pool are None where no clean data source exists for the TRUE
# manipulated/affected asset -- in that case a documented ETH/USD fallback is used for the
# generic freshness/congestion features only, never for reserve_skew (see reference_note).
INCIDENTS = [
    # --- manipulation (5) ---
    dict(name="Harvest Finance", date="2020-10-26", block=11_129_474, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="True asset USDC/USDT has no Chainlink feed yet at this block (checked, reverts) "
                         "and no Binance.US history this early; Curve-based exploit, not Uniswap. "
                         "ETH/USD used as a documented fallback for freshness/congestion only."),
    dict(name="Cream Finance", date="2021-10-27", block=13_499_798, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated asset was yUSD (no Chainlink/CEX pair); ETH was the largest drained "
                         "asset, used as reference. Exploit venue was Curve (4pool), not Uniswap."),
    dict(name="Indexed Finance", date="2021-10-15", block=13_417_949, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="DEFI5 has no Chainlink/CEX pair; ETH/USD used as a documented fallback. DEFI5's "
                         "own pool is a custom weighted-pool contract, not Uniswap V2/V3."),
    dict(name="Inverse Finance", date="2022-06-16", block=14_972_419, label="manipulation",
         oracle_feed="0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c", cex_symbol="BTCUSDT", dex_pool=None,
         reference_note="True asset WBTC/USDT; exploit manipulated Curve's 3Crypto pool "
                         "(WETH-USDT-WBTC), not Uniswap -- confirmed via BlockSec/Halborn analyses."),
    dict(name="UwU Lend", date="2024-06-10", block=20_061_319, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated asset was sUSDe (no Chainlink/CEX pair); ETH/USD used as a "
                         "documented fallback. Exploit venue was a Curve pool, not Uniswap."),
    # --- malfunction (3) ---
    dict(name="stETH/ETH heartbeat lag", date="2022-06-18", block=14_984_168, label="malfunction",
         oracle_feed="0x86392dC19c0b719886221c78AB11eb8Cf5c52812", cex_symbol=None, dex_pool=WSTETH_WETH_V3,
         reference_note="stETH has no Binance.US listing (price_dev left missing); cross_venue_spread "
                         "uses the wstETH/WETH Uniswap V3 pool as a DEX-side check on the Chainlink "
                         "STETH/ETH ratio (wstETH's own appreciation vs ETH was still small in mid-2022, "
                         "so this is a reasonable if imperfect proxy for stETH/ETH)."),
    dict(name="FTT/USD pause/deprecation", date="2022-11-28", block=16_069_381, label="malfunction",
         oracle_feed="0x398381563cc93A0Cd62534D775F2207a307e9aDD", cex_symbol=None, dex_pool=None,
         reference_note="FTT was never listed on Binance.US (confirmed: symbol invalid); no CEX "
                         "reference available. No Uniswap pool identified for this asset either."),
    dict(name="UST/USD feed freeze", date="2022-06-11", block=14_942_628, label="malfunction",
         oracle_feed="0x5EDd5F803b831b47715aD3e11a90dD244F0cD0a9", cex_symbol="USTUSDT", dex_pool=None,
         reference_note="UST/USDT is available on Binance.US (confirmed, closely matches the on-chain "
                         "frozen price). No Uniswap pool identified for UST at this block."),
    # --- large volatility event (12), all ETH/USD ---
    *[
        dict(name=n, date=d, block=b, label="large volatility event",
             oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT",
             dex_pool=WETH_USDC_V3, reference_note="Market-wide ETH/USD move; WETH/USDC V3 0.05% pool "
             "used for cross_venue_spread and reserve_skew as a generic liquidity/DEX-price check.")
        for n, d, b in [
            ("May 19 2021 crash", "2021-05-19", 12_465_029),
            ("June 2022 Celsius deleveraging", "2022-06-15", 14_966_742),
            ("Nov 2022 FTX collapse", "2022-11-09", 15_935_789),
            ("March 2023 banking-wobble rally", "2023-03-14", 16_826_924),
            ("Aug 2023 selloff", "2023-08-17", 17_937_299),
            ("March 2024 cycle-high rally", "2024-03-06", 19_378_953),
            ("Aug 5 2024 carry-trade unwind", "2024-08-05", 20_460_558),
            ("Dec 2024 breakdown from cycle high", "2024-12-20", 21_443_591),
            ("April 2025 tariff shock", "2025-04-09", 22_228_063),
            ("Oct 10-11 2025 flash crash", "2025-10-10", 23_549_972),
            ("Nov 4 2025 crash", "2025-11-04", 23_728_675),
            ("Feb 6 2026 crash", "2026-02-06", 24_394_166),
        ]
    ],
]

ORIGINAL_20_NAMES = [i["name"] for i in INCIDENTS]  # captured before phase-1 additions, for cohort marking

# ============================================================================
# Phase 1 dataset scaling (reports/scaling_plan.md) -- manipulation additions.
# All 8 sourced from SunWeb3Sec/DeFiHackLabs, confirmed mainnet via each PoC's own
# `vm.createSelectFork("mainnet", ...)`, and independently verified via a live
# `eth_getTransactionReceipt` (status 0x1) -- same standard as the original 5, not
# copied from a post-mortem. None has a clean Chainlink/CEX pair for its own true
# manipulated asset (same situation as 4 of the original 5), so all use the
# documented ETH/USD fallback for oracle_feed/cex_symbol (freshness/congestion/
# price_dev only, never for reserve_skew) except MEVBOTa47b, whose exploited pool
# genuinely IS the WETH/USDC pair already used elsewhere in this file.
# reserve_skew for the other 7 is computed separately in
# src/recompute_phase1_manipulation_curve_features.py (same pattern as the
# original 5's src/recompute_manipulation_curve_features.py), via get_coin_balances
# on each incident's actually-exploited venue (identified from its own PoC source).
PHASE1_MANIPULATION_INCIDENTS = [
    dict(name="MonoX Finance", date="2021-11-30", block=13_715_026, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated asset MONO (no Chainlink/CEX pair); ETH/USD used as a documented "
                         "fallback. Monoswap's own custom AMM (MonoXPool, self-hosted vCash pricing, not "
                         "Uniswap) mispriced MONO after liquidity was drained, enabling near-free minting. "
                         "Tx 0x9f14d093a2349de08f02fc0fb018dadb449351d0cdb7d0738ff69cc6fef5f299, verified "
                         "live (status 0x1, block 13,715,026, one block after the PoC's fork block)."),
    dict(name="MEVBOTa47b", date="2022-10-14", block=15_741_333, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT",
         dex_pool=WETH_USDC_V3,
         reference_note="MEV-bot exploit against the same WETH/USDC V3 0.05% pool already used for the "
                         "12 volatility incidents (0x88e6...f5640) via a Balancer flash loan and a Sushi "
                         "V2 pair -- genuinely ETH/USD-comparable, unlike most manipulation incidents, so "
                         "cross_venue_spread/dex_oracle_spread are computed normally here, not left "
                         "missing. Tx 0x35ecf595864400696853c53edf3e3d60096639b6071cadea6076c9c6ceb921c1, "
                         "verified live (status 0x1, block 15,741,333, one block after the PoC's fork)."),
    dict(name="Conic Finance 02", date="2023-07-22", block=17_743_470, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated asset crvUSD/UZD-side Conic omnipool share price (no Chainlink/CEX "
                         "pair); ETH/USD used as a documented fallback. Exploit venue: Curve crvUSD/USDC "
                         "pool (0x4DEcE678ceceb27446b35C672dC7d61F30bAD69E) balances, via a Balancer flash "
                         "loan feeding the ConicPool omnipool and Curve's crvUSD controller. Tx "
                         "0x37acd17a80a5f95728459bfea85cb2e1f64b4c75cf4a4c8dcb61964e26860882, verified "
                         "live (status 0x1, block == the PoC's own fork block, not fork+1 this time)."),
    dict(name="ZunamiProtocol", date="2023-08-14", block=17_908_950, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated asset UZD (Zunami's own USD stable, cached price via cacheAssetPrice(), "
                         "no Chainlink/CEX pair); ETH/USD used as a documented fallback. Exploit venue: "
                         "Curve UZD/crvFRAX pool (0x68934F60758243eafAf4D2cFeD27BF8010bede3a) balances. Tx "
                         "0x0788ba222970c7c68a738b0e08fb197e669e61f9b226ceec4cab9b85abe8cceb, verified live "
                         "(status 0x1, block 17,908,950, one block after the PoC's fork block)."),
    dict(name="CompoundUni", date="2024-02-23", block=19_290_921, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated asset UNI, via Compound's own UniswapAnchoredView price feeder "
                         "(0x50ce56A3239671Ab62f185704Caedf626352741e) -- not Chainlink -- so ETH/USD is "
                         "used as a documented fallback rather than an unverified UNI/USD feed. Exploit "
                         "venue: the UNI/WETH Uniswap V3 pool (0x1d42064Fc4Beb5F8aAF85F4617AE8b3b5B8Bd801) "
                         "the feeder reads, via a Balancer flash loan. Tx "
                         "0xaee0f8d1235584a3212f233b655f87b89f22f1d4890782447c4ef742b37af58d, verified "
                         "live (status 0x1, block 19,290,921, one block after the PoC's fork block)."),
    # MorphoBlue was here, and was DELETED after post-mortem review: two independent
    # write-ups (QuillAudits, SolidityScan) confirm its root cause is a static oracle
    # SCALE_FACTOR misconfiguration (a PAXG/USDC decimals mismatch, wrong from the
    # market's deployment) -- no market was ever manipulated, no venue exists to read
    # from, no market-observable signature of any kind. It does not belong in this
    # project's manipulation class. See reports/manipulation_candidates_phase1.md.
    dict(name="CurveLlamaLend", date="2026-03-02", block=24_566_937, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated asset sDOLA (an ERC4626-style vault share price feeding a Curve "
                         "LlamaLend market, no Chainlink/CEX pair); ETH/USD used as a documented "
                         "fallback. Exploit venue CORRECTED after post-mortem review (gov.curve.finance's "
                         "own sDOLA-long2 post-mortem, darknavy.org's writeup): DolaSavings "
                         "(0xE5f24791E273Cb96A1f8E5B67Bc2397F0AD9B8B4, sDOLA's own vault), whose "
                         "convertToAssets() was atomically inflated 13.79% (1.189->1.353) via a "
                         "stake()/unstake() round-trip within the attack tx -- tracked via its DOLA "
                         "balance. Caveat: since the manipulation reverted within the same block, a "
                         "post-block balance snapshot understates it (same limitation as Inverse "
                         "Finance's atomic exploit in the original 5). Tx "
                         "0xb93506af8f1a39f6a31e2d34f5f6a262c2799fef6e338640f42ab8737ed3d8a4, verified live "
                         "(status 0x1, block == the PoC's own fork block, not fork+1 this time)."),
    dict(name="ResupplyFi", date="2025-06-26", block=22_785_461, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated asset was a newly-deployed, nearly-empty cvcrvUSD vault's exchange-"
                         "rate accounting (no Chainlink/CEX pair); ETH/USD used as a documented fallback. "
                         "Exploit venue CORRECTED after post-mortem review (rekt.news's writeup, and "
                         "independently confirmed by decoding the attack tx's own crvUSD Transfer logs "
                         "directly on-chain): a classic donation attack against the vault's controller "
                         "contract, 0x89707721927d7aaeeee513797A8d6cBbD0e08f41 -- 2,002 crvUSD transferred "
                         "directly to it (confirmed on-chain: balance 0.0 -> 2002.0 crvUSD at this exact "
                         "block), corrupting its price-per-share math via integer-division floor-to-zero. "
                         "Tx 0xffbbd492e0605a8bb6d490c3cd879e87ff60862b0684160d08fd5711e7a872d3, verified "
                         "live (status 0x1, block 22,785,461, one block after the PoC's fork block)."),
]


# ============================================================================
# Phase 1 dataset scaling (reports/scaling_plan.md) -- volatility additions.
# 18 new incidents found via automated sampling of ETHUSDT hourly candles (>=10%
# 24h move, not hand-picked by name), each independently verified on-chain for
# clean cross-venue agreement and heartbeat freshness -- see
# src/mine_volatility_incidents.py and reports/volatility_candidates_phase1.md for
# the full mining/verification methodology and the 2 candidates that failed the
# cleanliness gate and were excluded. Same oracle_feed/cex_symbol/dex_pool as the
# original 12 (all ETH/USD, all the same WETH/USDC V3 pool) since these are the
# same class of incident, just found algorithmically instead of by name.
PHASE1_VOLATILITY_INCIDENTS = [
    dict(name=n, date=d, block=b, label="large volatility event",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT",
         dex_pool=WETH_USDC_V3,
         reference_note=f"Phase-1 automated-sampling find (src/mine_volatility_incidents.py): "
                         f"{move} 24h ETH/USD move, verified clean (cross-venue agreement within "
                         f"5%, no oracle staleness) via live Chainlink/DEX/CEX reads at this block. "
                         f"Same WETH/USDC V3 0.05% pool used for the original 12.")
    for n, d, b, move in [
        ("May 24 2021 rally", "2021-05-24", 12_498_787, "+34.7%"),
        ("Sept 8 2021 selloff", "2021-09-08", 13_183_613, "-16.2%"),
        ("Dec 4 2021 selloff", "2021-12-04", 13_739_429, "-16.1%"),
        ("Jan 21 2022 selloff", "2022-01-21", 14_051_461, "-16.9%"),
        ("June 19 2022 rally", "2022-06-19", 14_992_595, "+26.1%"),
        ("July 18 2022 rally", "2022-07-18", 15_169_419, "+18.2%"),
        ("Oct 26 2022 rally", "2022-10-26", 15_831_508, "+14.3%"),
        ("Nov 9 2023 rally", "2023-11-09", 18_537_528, "+12.3%"),
        ("Jan 11 2024 rally", "2024-01-11", 18_984_139, "+12.3%"),
        ("May 21 2024 rally", "2024-05-21", 19_918_142, "+22.6%"),
        ("July 5 2024 selloff", "2024-07-05", 20_237_777, "-11.4%"),
        ("Nov 7 2024 rally", "2024-11-07", 21_132_351, "+13.1%"),
        ("Feb 3 2025 selloff", "2025-02-03", 21_763_455, "-21.0%"),
        ("May 9 2025 rally", "2025-05-09", 22_444_589, "+24.8%"),
        ("Nov 21 2025 selloff", "2025-11-21", 23_846_950, "-11.2%"),
        ("Jan 31 2026 selloff", "2026-01-31", 24_356_507, "-13.4%"),
        ("June 6 2026 selloff", "2026-06-06", 25_255_813, "-12.9%"),
        ("Aug 19 2026 rally", "2026-08-19", 25_791_702, "+19.5%"),
    ]
]

INCIDENTS = INCIDENTS + PHASE1_MANIPULATION_INCIDENTS + PHASE1_VOLATILITY_INCIDENTS
PHASE1_NAMES = [i["name"] for i in PHASE1_MANIPULATION_INCIDENTS + PHASE1_VOLATILITY_INCIDENTS]

# ============================================================================
# Phase 2 dataset scaling (reports/scaling_plan.md) -- manipulation additions.
# 12 of the 13 sourced from a broader DeFiHackLabs sweep were kept (EnsoFinance
# excluded -- its own research report flagged the exploited pool as not precisely
# pinned, and per this project's "reject rather than guess" standard it is left
# out, not force-included). Each confirmed mainnet via its PoC's own
# `vm.createSelectFork("mainnet", ...)` and independently verified via a live
# `eth_getTransactionReceipt` (status 0x1). See reports/manipulation_candidates_phase2.md
# for full sourcing, the honest "13 confirmed, not 28-38" accounting, and venue-
# identification confidence per incident (4 of the 12 -- BalancerV2, SummerFi,
# Makina, Raft_fi -- were independently corroborated via real post-mortems during
# integration, specifically checking each wasn't a MorphoBlue-style static
# misconfiguration with no real manipulated venue; the remaining 8 are sourced from
# each PoC's own declared contract addresses only, same standard as most of phase
# 1's additions, and use a generic 2-token [WETH, USDC] balance-skew proxy at the
# named venue where the exact drained token isn't independently confirmed -- flagged
# per-incident below, not silently assumed).
PHASE2_MANIPULATION_INCIDENTS = [
    dict(name="BalancerV2", date="2025-11-03", block=23_717_397, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated venue: Balancer V2 osETH/wETH ComposableStablePool "
                         "(0xDACf5Fa19b1f720111609043ac67A9818262850c) -- confirmed via independent "
                         "post-mortems (OpenZeppelin, Check Point Research, SlowMist) as a genuine "
                         "market manipulation: a rounding-error bug in _upscaleArray exploited via real "
                         "batchSwap trades to suppress BPT price and extract value via arbitrage cycles "
                         "-- real swaps, real balance movement, not a static config bug. $120M lost "
                         "across all affected chains; this is the Ethereum mainnet leg specifically. Tx "
                         "0x6ed07db1a9fe5c0794d44cd36081d6a6df103fab868cdd75d581e3bd23bc9742, verified "
                         "live (status 0x1)."),
    # SummerFi: DROPPED during the reserve_skew resolution pass (see
    # reports/manipulation_candidates_phase2.md and
    # src/recompute_phase2_manipulation_curve_features.py). The real exploit tx (305
    # logs) is a genuine, independently-confirmed NAV manipulation, but the extracted
    # value never sits at one venue as a trackable balance -- it's spread across a
    # dozen+ nested vault/Ark tokens (Api3CoreUSDC, AVGUSDCcons, KPK_USDC_Prime,
    # skyMoneyUsdcRiskCapital, LVUSDC, sUSDS, sUSDC, USDS, DAI), and the configured
    # FleetCommander address does not appear in the attack transaction's logs at all.
    # No single-venue balance can represent this incident's manipulation signal, so
    # per instruction it's dropped rather than kept with a misleading NaN.
    dict(name="Makina", date="2026-01-20", block=24_273_362, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated venue: Makina Caliber/Machine DUSD/USDC Curve pool "
                         "(0x32e616f4f17d43f9a5cd9be0e294727187064cb3), tracked via its USDC balance "
                         "only (DUSD's exact token address not independently confirmed during "
                         "integration, so left out of the tracked coin list rather than guessed) -- "
                         "confirmed via independent post-mortems (QuillAudits, Makina's own post-mortem) "
                         "as a real flash-loan-driven manipulation of AUM/sharePrice calculations via "
                         "this Curve pool, not a static bug. Loss corrected to ~$4.1M during integration "
                         "(multiple independent sources; the research pass's initial ~$5.1M figure did "
                         "not match). Tx "
                         "0x569733b8016ef9418f0b6bde8c14224d9e759e79301499908ecbcd956a0651f5, verified "
                         "live (status 0x1)."),
    # Raft_fi: DROPPED during the reserve_skew resolution pass. The configured venue
    # and token (cbETH at 0x9ab6b21cdf116f611110b048987e58894786c244) are correct --
    # confirmed via direct transaction-log decoding, a real 6001.45 cbETH inflow is
    # visible -- but the position/collateral contract's cbETH balance returns to
    # baseline within the same transaction (a precision/rounding exploit during
    # R-token minting, not a persisting balance drain). Genuinely architecturally
    # invisible to a before/after balance-ratio metric at this venue, regardless of
    # which correct address is used -- dropped per instruction rather than kept as a
    # misleading 0.0/NaN.
    dict(name="TOPBPool", date="2026-06-09", block=25_279_892, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated venue CORRECTED during the reserve_skew resolution pass: the "
                         "PoC's originally-configured address (0xb935c3d80229d5d92f3761b17cd81dc2610e3a45) "
                         "does not appear in the attack tx's logs at all. Direct transaction-log decoding "
                         "identified the real drained pool as 0x0fa3e014fa2e751f78e53dca766fac2223327329 "
                         "(a bonding-curve-style AMM: attacker mints 10B TOP governance tokens, then "
                         "repeatedly dumps them into this pool for ever-shrinking WETH amounts), tracked "
                         "via [TOP, WETH] balances (max abs skew) -- this is a persisting drain, not an "
                         "atomic round-trip: WETH falls from 281.34 to ~0 and stays there past the "
                         "incident block. Sourced from the PoC's own header comments only (not "
                         "independently post-mortem-corroborated, size ~944.20 WETH did not clear this "
                         "integration pass's bar for a second-source check). Tx "
                         "0x967aa34c69b7775c718545c7f94d92e965eb5fc553c0f27f6f1a9c65c93ac156, verified "
                         "live (status 0x1)."),
    dict(name="WiseLending", date="2023-10-13", block=18_342_121, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated venue: WiseLending pool contract "
                         "(0x84524baa1951247b3a2617a843e6ece915bb9674), a donate-inflate exchange-rate "
                         "exploit -- tracked via [WETH, USDC] balances (max abs skew), a generic 2-token "
                         "proxy since the exact donated token wasn't independently confirmed during "
                         "integration, same treatment as MonoX Finance in phase 1. ~$260K lost, sourced "
                         "from the PoC's own header comments. Tx "
                         "0x7ac4a98599596adbf12fffa2bd23e2a2d2ac7e8989b6ea043fcc412a29126555, verified "
                         "live (status 0x1)."),
    # bZxProtocol: DROPPED during the reserve_skew resolution pass. The configured
    # venue is correct (0x7f3fe9d492a9a60aebb06d82cba23c6f32cad10b, confirmed via
    # direct log decoding), but the exploit mechanism is an iYFI exchange-rate
    # manipulation -- 19.36 YFI flows in, excess iYFI shares get minted against a
    # manipulated rate, then the same 19.36+ YFI flows back out within the same
    # transaction. The vault's real YFI holding returns to ~baseline by end of block
    # regardless of venue choice -- architecturally invisible to a balance-ratio
    # metric, not a wrong-address problem. Dropped per instruction.
    # edel-xstock: DROPPED during the reserve_skew resolution pass. The configured
    # address does not meaningfully appear in the 502-log attack transaction, which
    # spans a dozen+ wrapped tokenized-stock collateral/debt tokens (wGOOGLx, wSPYx,
    # wQQQx, wMSTRx, wNVDAx, wTSLAx) across an Aave-fork-style lending market -- a
    # genuinely diffuse multi-asset exploit with no single venue balance that
    # represents it, the same problem as SummerFi. Dropped per instruction.
    dict(name="BalancerV1BPool", date="2026-08-31", block=25_872_274, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated venue: Balancer V1 BPool, DPI/USDC/WETH/WBTC "
                         "(0x2257aaac34bcb27900291f7b84ee2565a6cbac57), a calcSingleInGivenPoolOut "
                         "rounding exploit -- tracked via [WETH, USDC] balances (max abs skew) at this "
                         "specific pool (one of 5 similarly-exploited pools per the PoC; only this one's "
                         "tx/block was precisely documented). ~$110,839 lost at this pool (~$234K "
                         "aggregate across all 5, not otherwise included here). Tx "
                         "0x72510b257cc09bde8435b83ac1636f9498ffc353583330600b5b8da43d0d1aff, verified "
                         "live (status 0x1)."),
    # CompounderFinance: DROPPED during the reserve_skew resolution pass. The
    # configured venue is active in the attack tx's logs (real DAI in/out visible),
    # but this vault is a Yearn-integrated auto-compounder that holds ~0 idle DAI by
    # design -- it immediately routes deposits into yDAI -- both before and after
    # the incident. The actual exploit is a yDAI/yUSDC/yTUSD exchange-rate
    # manipulation, not a balance drain: the metric type is fundamentally mismatched
    # to this venue's architecture, not a wrong-address problem. Dropped per
    # instruction.
    # MetaPool: DROPPED during the reserve_skew resolution pass. The configured
    # address (0x48afbbd342f64ef8a9ab1c143719b63c2ad81710) turned out to be the
    # mpETH token contract itself, not a holding venue; the real venue was found via
    # log decoding to be 0xc3d10bd8e051a2be6408d18be8464654f699a25a (confirmed real
    # flows: 200 WETH borrowed from the Balancer Vault, 9682.72 mpETH minted/moved),
    # but this venue's WETH/mpETH balances return to baseline within the same
    # transaction -- a flash-loan round-trip, not a persisting drain. Architecturally
    # invisible to a before/after balance-ratio metric regardless of venue choice.
    # Dropped per instruction.
    # MahaLend: DROPPED during the reserve_skew resolution pass. The configured
    # address does not appear in the 625-log attack transaction. Log decoding found
    # the real venue (0xf5836e292f716a7979f9bc5c2d3ed59913e07962, an mUSDC vault) --
    # a 13.9M USDC Balancer flash loan is used to repeatedly round-trip deposits/
    # redemptions against the mUSDC vault to inflate its exchange rate (a donation-
    # style attack), then the flash loan is fully repaid within the same
    # transaction. USDC balance returns to ~0 by end of block regardless of venue
    # choice. Dropped per instruction.
]

# ============================================================================
# Phase 2 dataset scaling -- volatility additions. 55 new incidents found via
# automated sampling of ETHUSDT hourly candles (>=5% 24h move, lowered from phase
# 1's 10% specifically to reach this phase's larger target -- these are, on
# average, smaller/calmer moves than both the original 12 and phase 1's 18; see
# reports/volatility_candidates_phase2.md for full methodology and the 10 rejected
# candidates). Same oracle_feed/cex_symbol/dex_pool as the original 12 and phase 1's
# 18 (all ETH/USD, all the same WETH/USDC V3 pool).
PHASE2_VOLATILITY_INCIDENTS = [
    dict(name=n, date=d, block=b, label="large volatility event",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT",
         dex_pool=WETH_USDC_V3,
         reference_note=f"Phase-2 automated-sampling find (src/mine_volatility_incidents.py, 5% "
                         f"threshold): {move} 24h ETH/USD move, verified clean (cross-venue agreement "
                         f"within 5%, no oracle staleness) via live Chainlink/DEX/CEX reads at this "
                         f"block. Same WETH/USDC V3 0.05% pool used for the original 12 and phase 1.")
    for n, d, b, move in [
        ("Jul 13 2021 selloff (p2)", "2021-07-13", 12_816_800, "-7.8%"),
        ("Aug 7 2021 rally (p2)", "2021-08-07", 12_977_500, "+13.6%"),
        ("Sep 22 2021 rally (p2)", "2021-09-22", 13_278_142, "+12.9%"),
        ("Oct 21 2021 rally (p2)", "2021-10-21", 13_460_310, "+11.8%"),
        ("Nov 16 2021 selloff (p2)", "2021-11-16", 13_626_469, "-10.9%"),
        ("Dec 16 2021 rally (p2)", "2021-12-16", 13_816_855, "+11.7%"),
        ("Jan 6 2022 selloff (p2)", "2022-01-06", 13_950_924, "-13.8%"),
        ("Feb 4 2022 rally (p2)", "2022-02-04", 14_141_575, "+13.9%"),
        ("Mar 1 2022 rally (p2)", "2022-03-01", 14_301_275, "+15.2%"),
        ("Apr 11 2022 selloff (p2)", "2022-04-11", 14_566_646, "-9.3%"),
        ("May 12 2022 selloff (p2)", "2022-05-12", 14_759_154, "-22.9%"),
        ("May 30 2022 rally (p2)", "2022-05-30", 14_875_056, "+10.4%"),
        ("Jul 5 2022 rally (p2)", "2022-07-05", 15_080_762, "+11.2%"),
        ("Aug 19 2022 selloff (p2)", "2022-08-19", 15_373_781, "-13.6%"),
        ("Sep 19 2022 selloff (p2)", "2022-09-19", 15_566_235, "-11.1%"),
        ("Oct 14 2022 rally (p2)", "2022-10-14", 15_746_207, "+9.9%"),
        ("Nov 23 2022 rally (p2)", "2022-11-23", 16_032_256, "+8.2%"),
        ("Nov 30 2022 rally (p2)", "2022-11-30", 16_079_083, "+9.3%"),
        ("Jan 14 2023 rally (p2)", "2023-01-14", 16_403_709, "+10.9%"),
        ("Feb 16 2023 rally (p2)", "2023-02-16", 16_638_769, "+9.6%"),
        ("Mar 23 2023 rally (p2)", "2023-03-23", 16_892_175, "+6.1%"),
        ("Apr 14 2023 rally (p2)", "2023-04-14", 17_042_061, "+11.1%"),
        ("Apr 26 2023 rally (p2)", "2023-04-26", 17_131_155, "+7.7%"),
        ("Jun 21 2023 rally (p2)", "2023-06-21", 17_529_084, "+7.4%"),
        ("Jul 14 2023 rally (p2)", "2023-07-14", 17_688_002, "+7.9%"),
        ("Aug 29 2023 rally (p2)", "2023-08-29", 18_022_215, "+5.4%"),
        ("Oct 24 2023 rally (p2)", "2023-10-24", 18_419_681, "+10.0%"),
        ("Dec 11 2023 selloff (p2)", "2023-12-11", 18_765_202, "-7.3%"),
        ("Dec 28 2023 rally (p2)", "2023-12-28", 18_880_407, "+9.2%"),
        ("Jan 23 2024 selloff (p2)", "2024-01-23", 19_069_529, "-7.9%"),
        ("Feb 27 2024 rally (p2)", "2024-02-27", 19_317_855, "+7.1%"),
        ("Mar 21 2024 rally (p2)", "2024-03-21", 19_480_823, "+12.5%"),
        ("May 1 2024 selloff (p2)", "2024-05-01", 19_773_648, "-9.1%"),
        ("Jun 11 2024 selloff (p2)", "2024-06-11", 20_069_341, "-7.1%"),
        ("Jul 15 2024 rally (p2)", "2024-07-15", 20_314_157, "+7.3%"),
        ("Jul 25 2024 selloff (p2)", "2024-07-25", 20_382_827, "-8.7%"),
        ("Aug 28 2024 selloff (p2)", "2024-08-28", 20_625_454, "-9.0%"),
        ("Oct 14 2024 rally (p2)", "2024-10-14", 20_964_557, "+7.8%"),
        ("Oct 29 2024 rally (p2)", "2024-10-29", 21_072_346, "+6.2%"),
        ("Jan 8 2025 selloff (p2)", "2025-01-08", 21_577_822, "-9.7%"),
        ("Jan 27 2025 selloff (p2)", "2025-01-27", 21_717_510, "-8.6%"),
        ("Mar 4 2025 selloff (p2)", "2025-03-04", 21_970_101, "-16.5%"),
        ("Apr 23 2025 rally (p2)", "2025-04-23", 22_329_179, "+15.1%"),
        ("May 13 2025 rally (p2)", "2025-05-13", 22_476_233, "+9.4%"),
        ("Jun 24 2025 rally (p2)", "2025-06-24", 22_775_341, "+11.8%"),
        ("Jul 16 2025 rally (p2)", "2025-07-16", 22_934_001, "+11.1%"),
        ("Sep 25 2025 selloff (p2)", "2025-09-25", 23_441_403, "-8.2%"),
        ("Oct 17 2025 selloff (p2)", "2025-10-17", 23_596_644, "-8.1%"),
        ("Nov 14 2025 selloff (p2)", "2025-11-14", 23_797_286, "-10.7%"),
        ("Jan 20 2026 selloff (p2)", "2026-01-20", 24_279_137, "-7.8%"),
        ("Feb 25 2026 rally (p2)", "2026-02-25", 24_536_469, "+13.3%"),
        ("Mar 16 2026 rally (p2)", "2026-03-16", 24_671_711, "+10.6%"),
        ("Apr 14 2026 rally (p2)", "2026-04-14", 24_876_697, "+9.4%"),
        ("Jun 15 2026 rally (p2)", "2026-06-15", 25_323_959, "+11.0%"),
        ("Sep 11 2026 rally (p2)", "2026-09-11", 25_954_321, "+7.9%"),
    ]
]

INCIDENTS = INCIDENTS + PHASE2_MANIPULATION_INCIDENTS + PHASE2_VOLATILITY_INCIDENTS
PHASE2_NAMES = [i["name"] for i in PHASE2_MANIPULATION_INCIDENTS + PHASE2_VOLATILITY_INCIDENTS]

# ============================================================================
# Phase 3 dataset scaling (reports/scaling_plan.md): 105 -> ~200 incidents.
# Manipulation: 7 new, independently found via a wider DeFiHackLabs keyword sweep
# (vault/share-price/collateral/liquidation/rounding/precision/donation/inflation,
# terms phase 1/2 hadn't tried) and pre-screened for the atomic-round-trip/diffuse-
# venue failure mode BEFORE integration this time (not after, as in phase 2) --
# see reports/manipulation_candidates_phase3.md for full per-incident before/after
# balance evidence, independently spot-verified against 4 of the 7 (AjnaFinance,
# DRLVaultV3, USM, BalancerBoostedPool2023) via direct on-chain reads matching the
# report's numbers exactly. 5 candidates were found and dropped (2 atomic-round-trip,
# 1 diffuse-multi-venue, 2 too-small-despite-clean-signal) -- reported honestly, not
# silently absorbed. oracle_feed uses the ETH/USD fallback per this project's
# established convention for non-ETH-denominated manipulation incidents; the real
# signal is each incident's own venue-specific reserve_skew, computed by
# src/recompute_phase3_manipulation_curve_features.py.
PHASE3_MANIPULATION_INCIDENTS = [
    dict(name="AjnaFinance", date="2026-08-28", block=25_854_888, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated venue: Ajna ERC20Pool, cbETH/WETH "
                         "(0xad24FC773e125Edb223C38a39657cB64bc7C178e) -- tracked via [cbETH, WETH] "
                         "balances (max abs skew). ~$124.8K lost at this pool (~$775K aggregate across "
                         "7 Ajna pools hit the same day, only this one's tx/block precisely documented). "
                         "Tx 0x12dfde527ef62882bfabb64362c9ae0e6bfb628363bd298d0d0956c9a114e4f5, "
                         "verified live (status 0x1)."),
    dict(name="BalancerBoostedPool2023", date="2023-08-27", block=18_004_652, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated venue: Balancer V2 bb-a-USDC Linear Pool "
                         "(0x9210F1204b5a24742Eba12f710636D76240dF3d0) -- precision-loss rate "
                         "manipulation, tracked via the Balancer V2 Vault method (getPoolId + "
                         "getPoolTokens), USDC balance only (the pool's aUSDC buffer reading is dust at "
                         "both blocks, a degenerate value explicitly excluded from the skew pick, not "
                         "silently used). ~$2M lost. Tx "
                         "0x2a027c8b915c3737942f512fc5d26fd15752d0332353b3059de771a35a606c2d, verified "
                         "live (status 0x1)."),
    dict(name="DRLVaultV3", date="2025-11-10", block=23_769_387, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated venue: DRL leveraged vault "
                         "(0x6A06707ab339BEE00C6663db17DdB422301ff5e8) -- thin-pool slippage/valuation "
                         "exploit, tracked via USDC balance (a clean, full drain, 100,000 -> 0). $100K "
                         "lost. Tx 0xe3eab35b288c086afa9b86a97ab93c7bb61d21b1951a156d2a8f6f5d5715c475, "
                         "verified live (status 0x1)."),
    dict(name="EFLeverVault", date="2022-10-14", block=15_746_342, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated venue CORRECTED after the PoC's own declared WETH/EF_LEVER_TOKEN "
                         "pair came back all-zero at both blocks (phase 2's exact failure signature, "
                         "caught by re-decoding Transfer logs before integration this time): the real "
                         "value path is the vault's Aave V1 aSTETH position "
                         "(0x1982b2F5814301d4e9a8b0201555376e62F82428) at the vault address "
                         "(0xe39fd820B58f83205Db1D9225f28105971c3D309), which drops -99.98% "
                         "(2,321.57 -> 0.39). ~750 ETH reported loss (the PoC's own figure may reflect "
                         "only the final attacker's net take after a frontrunner intercepted part of the "
                         "value; the balance read captures the vault's full ~1,933 stETH-equivalent "
                         "outflow). Tx "
                         "0x160c5950a01b88953648ba90ec0a29b0c5383e055d35a7835d905c53a3dda01e, verified "
                         "live (status 0x1)."),
    dict(name="SecuredFi", date="2026-09-05", block=25_914_192, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated venue: Secured Finance TokenVault "
                         "(0xb74749b2213916b1da3b869e41c7c57f1db69393) -- same-block self-trade "
                         "manipulates getMarketUnitPrice(), tracked via WBTC balance (-98.60%, "
                         "0.91171 -> 0.01272). ~$72K lost at this drain (~$104K aggregate across "
                         "copycat drains). Tx "
                         "0xcd6159860783d8d481cc4bf4dceddc88acdca6bb08f6445525b2904cfd75b1da, verified "
                         "live (status 0x1)."),
    dict(name="ThetanutsIndexVault", date="2026-06-15", block=25_323_329, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated venue CORRECTED after the PoC's own declared INDEX_VAULT "
                         "(0xC2C3AE0a7b405058558C9b4a63b373486CB86Ac7, a pure share-accounting contract "
                         "holding 0.0 USDC at both blocks) came back all-zero -- the real source, found "
                         "by decoding all 429 Transfer logs, is two underlying component vaults: "
                         "BTC_USD_VAULT (0x3BA337F3167eA35910E6979D5BC3b0AeE60E7d59, -97.67%, "
                         "71,995.54 -> 1,679.98 USDC) and ETH_USD_VAULT "
                         "(0xE1c93dE547cc85CBD568295f6CC322B1dbBCf8Ae, -99.84%, 35,212.16 -> 56.23 "
                         "USDC); the two outflows sum to exactly $105,471.50, matching the reported loss "
                         "precisely -- strong independent confirmation of the corrected venue pair. "
                         "Tracked via [BTC_USD_VAULT-USDC] as the primary (larger) venue. Tx "
                         "0xbba9f138fe39503bfd1aa62932dbd6ab35d37d23d48e4b7bf2988a9d5dc39fec, verified "
                         "live (status 0x1)."),
    dict(name="USM", date="2026-08-09", block=25_716_150, label="manipulation",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT", dex_pool=None,
         reference_note="Manipulated venue: USM stablecoin contract "
                         "(0x2a7FFf44C19f39468064ab5e5c304De01D591675) -- split-invariant defund() "
                         "redemption curve, tracked via NATIVE ETH balance (eth_getBalance, not "
                         "balanceOf -- this drains ETH directly, not WETH), -53.42% (132.59 -> 61.76 "
                         "ETH). Boundary case for this project's class definition: the PoC's own header "
                         "states this is a pure rounding-logic bug, not a literal price-feed attack -- "
                         "included per precedent (WiseLending/TOPBPool/BalancerV1BPool are all "
                         "rounding/accounting exploits producing a persisting reserve_skew, tracked the "
                         "same way). ~70.8 ETH (~$135.8K) lost. Tx "
                         "0xfae5e751b8ce01457cbb6b529839f24a0cff50faaabcbd0fd02ca0cf559b050e, verified "
                         "live (status 0x1)."),
]

# Phase 3 volatility additions: 53 new candidates found via automated sampling of
# ETHUSDT hourly candles (>=3% 24h move, lowered from phase 2's 5% specifically to
# reach a larger target on top of the 85 already locked -- see
# reports/volatility_candidates_phase3.md for full methodology and the 13 rejected
# candidates). Same oracle_feed/cex_symbol/dex_pool as every prior phase (all ETH/USD,
# all the same WETH/USDC V3 pool).
PHASE3_VOLATILITY_INCIDENTS = [
    dict(name=n, date=d, block=b, label="large volatility event",
         oracle_feed="0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", cex_symbol="ETHUSDT",
         dex_pool=WETH_USDC_V3,
         reference_note=f"Phase-3 automated-sampling find (src/mine_volatility_incidents_phase3.py, 3% "
                         f"threshold): {move} 24h ETH/USD move, verified clean (cross-venue agreement "
                         f"within 5%, no oracle staleness) via live Chainlink/DEX/CEX reads at this "
                         f"block. Same WETH/USDC V3 0.05% pool used for every prior phase.")
    for n, d, b, move in [
        ("Sep 1 2021 rally (p3)", "2021-09-01", 13_142_610, "+11.6%"),
        ("Dec 28 2021 selloff (p3)", "2021-12-28", 13_895_214, "-7.2%"),
        ("Mar 28 2022 rally (p3)", "2022-03-28", 14_475_066, "+7.7%"),
        ("Apr 2 2022 rally (p3)", "2022-04-02", 14_504_004, "+7.6%"),
        ("Apr 26 2022 rally (p3)", "2022-04-26", 14_658_733, "+6.8%"),
        ("Oct 4 2022 rally (p3)", "2022-10-04", 15_673_143, "+4.5%"),
        ("Dec 8 2022 rally (p3)", "2022-12-08", 16_141_642, "+4.6%"),
        ("Dec 17 2022 selloff (p3)", "2022-12-17", 16_200_694, "-7.9%"),
        ("Jan 4 2023 rally (p3)", "2023-01-04", 16_335_075, "+4.4%"),
        ("Jan 21 2023 rally (p3)", "2023-01-21", 16_454_138, "+7.0%"),
        ("Feb 2 2023 rally (p3)", "2023-02-02", 16_542_765, "+7.6%"),
        ("Feb 9 2023 selloff (p3)", "2023-02-09", 16_594_034, "-6.9%"),
        ("Apr 5 2023 rally (p3)", "2023-04-05", 16_978_915, "+6.0%"),
        ("Apr 19 2023 selloff (p3)", "2023-04-19", 17_083_754, "-8.1%"),
        ("May 6 2023 rally (p3)", "2023-05-06", 17_197_859, "+6.5%"),
        ("May 12 2023 selloff (p3)", "2023-05-12", 17_241_928, "-4.6%"),
        ("Jun 5 2023 selloff (p3)", "2023-06-05", 17_416_542, "-5.2%"),
        ("Jun 15 2023 selloff (p3)", "2023-06-15", 17_484_552, "-6.4%"),
        ("Jul 7 2023 selloff (p3)", "2023-07-07", 17_640_602, "-4.8%"),
        ("Aug 22 2023 selloff (p3)", "2023-08-22", 17_972_799, "-4.1%"),
        ("Sep 11 2023 selloff (p3)", "2023-09-11", 18_115_656, "-4.9%"),
        ("Oct 3 2023 selloff (p3)", "2023-10-03", 18_269_871, "-4.3%"),
        ("Oct 20 2023 rally (p3)", "2023-10-20", 18_390_503, "+4.2%"),
        ("Nov 3 2023 selloff (p3)", "2023-11-03", 18_488_121, "-3.6%"),
        ("Nov 14 2023 selloff (p3)", "2023-11-14", 18_571_793, "-6.0%"),
        ("Nov 22 2023 rally (p3)", "2023-11-22", 18_630_417, "+6.5%"),
        ("Jan 3 2024 selloff (p3)", "2024-01-03", 18_927_286, "-7.2%"),
        ("Jan 31 2024 selloff (p3)", "2024-01-31", 19_129_001, "-4.4%"),
        ("Feb 13 2024 rally (p3)", "2024-02-13", 19_218_062, "+7.9%"),
        ("Mar 12 2024 rally (p3)", "2024-03-12", 19_415_580, "+6.3%"),
        ("Apr 2 2024 selloff (p3)", "2024-04-02", 19_568_270, "-8.0%"),
        ("Apr 13 2024 selloff (p3)", "2024-04-13", 19_643_247, "-10.0%"),
        ("Apr 25 2024 selloff (p3)", "2024-04-25", 19_731_644, "-5.6%"),
        ("May 27 2024 rally (p3)", "2024-05-27", 19_958_680, "+4.5%"),
        ("Jun 24 2024 selloff (p3)", "2024-06-24", 20_162_596, "-5.9%"),
        ("Jul 29 2024 rally (p3)", "2024-07-29", 20_411_182, "+4.9%"),
        ("Aug 23 2024 rally (p3)", "2024-08-23", 20_593_847, "+5.7%"),
        ("Sep 6 2024 selloff (p3)", "2024-09-06", 20_693_799, "-8.3%"),
        ("Sep 19 2024 rally (p3)", "2024-09-19", 20_785_695, "+7.2%"),
        ("Oct 2 2024 selloff (p3)", "2024-10-02", 20_876_777, "-6.9%"),
        ("Oct 23 2024 selloff (p3)", "2024-10-23", 21_029_941, "-5.0%"),
        ("Jan 3 2025 rally (p3)", "2025-01-03", 21_546_800, "+5.1%"),
        ("Jun 13 2025 selloff (p3)", "2025-06-13", 22_692_519, "-10.3%"),
        ("Jul 11 2025 rally (p3)", "2025-07-11", 22_894_901, "+8.6%"),
        ("Aug 9 2025 rally (p3)", "2025-08-09", 23_102_762, "+8.2%"),
        ("Sep 12 2025 rally (p3)", "2025-09-12", 23_349_233, "+5.8%"),
        ("Dec 1 2025 selloff (p3)", "2025-12-01", 23_919_683, "-10.4%"),
        ("Jan 2 2026 rally (p3)", "2026-01-02", 24_148_004, "+5.1%"),
        ("Jan 14 2026 rally (p3)", "2026-01-14", 24_229_520, "+7.6%"),
        ("Feb 19 2026 selloff (p3)", "2026-02-19", 24_491_649, "-3.2%"),
        ("Apr 8 2026 rally (p3)", "2026-04-08", 24_834_849, "+8.1%"),
        ("Apr 28 2026 selloff (p3)", "2026-04-28", 24_975_428, "-4.5%"),
        ("Jul 2 2026 rally (p3)", "2026-07-02", 25_444_986, "+7.2%"),
    ]
]

INCIDENTS = INCIDENTS + PHASE3_MANIPULATION_INCIDENTS + PHASE3_VOLATILITY_INCIDENTS
PHASE3_NAMES = [i["name"] for i in PHASE3_MANIPULATION_INCIDENTS + PHASE3_VOLATILITY_INCIDENTS]


def _cohort_for(name: str) -> str:
    """4-tier lookup, extend with more `elif name in PHASEN_NAMES` blocks as later
    phases are added -- ORIGINAL_20_NAMES, PHASE1_NAMES, and PHASE2_NAMES are
    captured at the point each phase's incidents were added to INCIDENTS, so this
    stays correct regardless of how many more phases follow."""
    if name in ORIGINAL_20_NAMES:
        return "original_20"
    if name in PHASE1_NAMES:
        return "phase1"
    if name in PHASE2_NAMES:
        return "phase2"
    return "phase3"


_BLOCK_CACHE_DIR = REPO_ROOT / "data" / "raw"


def _get_block_cached(w3, block_number):
    """w3.eth.get_block with a disk cache, so reruns (e.g. after a bug fix) don't
    re-spend RPC budget on the congestion-sampling loop's ~500 lookups."""
    _BLOCK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _BLOCK_CACHE_DIR / f"block_meta_{block_number}.csv"
    if cache_file.exists():
        row = pd.read_csv(cache_file).iloc[0]
        return {"timestamp": int(row["timestamp"]), "baseFeePerGas": None if pd.isna(row["baseFeePerGas"]) else int(row["baseFeePerGas"])}
    block = _with_retry(lambda: w3.eth.get_block(block_number))
    result = {"timestamp": block["timestamp"], "baseFeePerGas": block.get("baseFeePerGas")}
    pd.DataFrame([result]).to_csv(cache_file, index=False)
    return result


def _get_wsteth_rate_cached(w3, block_number: int) -> float:
    """stETH backing 1 wstETH at `block_number`, via the wstETH contract's own
    stEthPerToken() -- an on-chain read against the same wrapper token the pool
    already trades, not a new data source. Cached on disk like every other
    per-block/per-contract read in this file."""
    _BLOCK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _BLOCK_CACHE_DIR / f"wsteth_rate_{block_number}.csv"
    if cache_file.exists():
        return float(pd.read_csv(cache_file).iloc[0]["rate"])
    contract = w3.eth.contract(address=Web3.to_checksum_address(WSTETH_TOKEN), abi=WSTETH_ABI)
    raw = _with_retry(lambda: contract.functions.stEthPerToken().call(block_identifier=block_number))
    rate = raw / 1e18
    pd.DataFrame([{"rate": rate}]).to_csv(cache_file, index=False)
    return rate


def _dex_price(w3, dex_pool, block_number):
    """Return the pool's price, normalized to quote-per-base (matching CEX convention).
    For the wstETH/WETH pool specifically, also divides out wstETH's yield-accruing
    wrapper factor (see _get_wsteth_rate_cached) so the result is a genuine ETH-per-
    stETH-equivalent price, comparable unit-for-unit to the STETH/ETH oracle -- not
    just internally consistent with itself across time (which is all the raw pool
    price guarantees)."""
    kind, addr, invert = dex_pool
    if kind == "v2":
        state = get_v2_reserves(w3, addr, block_number)
    else:
        state = get_v3_state(w3, addr, block_number)
    price = float(state["price_1_per_0"])
    price = (1.0 / price) if invert else price
    if addr.lower() == WSTETH_WETH_V3[1].lower():
        price = price / _get_wsteth_rate_cached(w3, block_number)
    return price


def compute_features(w3, incident: dict) -> dict:
    name = incident["name"]
    block_number = incident["block"]
    print(f"--- {name} (block {block_number:,}) ---", flush=True)

    block = _get_block_cached(w3, block_number)
    block_ts = block["timestamp"]
    base_fee = block.get("baseFeePerGas")

    row = {
        "incident": name,
        "date": incident["date"],
        "block": block_number,
        "label": incident["label"],
        "chain": "ethereum-mainnet",
        "cohort": _cohort_for(name),
        "reference_note": incident["reference_note"],
        "price_dev": np.nan,
        "cross_venue_spread": np.nan,
        "dex_oracle_spread": np.nan,
        "heartbeat_elapsed": np.nan,
        "congestion": np.nan,
        "reserve_skew": np.nan,
        "ref_realized_vol": np.nan,
    }

    # --- oracle price + heartbeat_elapsed ---
    oracle_price = None
    if incident["oracle_feed"]:
        oracle_round = get_round_data_at_block(w3, incident["oracle_feed"], block_number)
        oracle_price = float(oracle_round["answer"])
        row["heartbeat_elapsed"] = block_ts - int(oracle_round["updated_at"])

    # --- CEX reference price + realized vol (trailing window, ending at block_ts) ---
    cex_price_at_time = None
    if incident["cex_symbol"]:
        window_start = pd.Timestamp(block_ts, unit="s", tz="UTC") - pd.Timedelta(minutes=TRAILING_WINDOW_MINUTES)
        window_end = pd.Timestamp(block_ts, unit="s", tz="UTC")
        cex = fetch_cex_klines(incident["cex_symbol"], window_start, window_end)
        if not cex.empty:
            # nearest candle at or before block_ts (never after -- no lookahead)
            cex_before = cex[cex["timestamp"] <= window_end]
            if not cex_before.empty:
                cex_price_at_time = float(cex_before.iloc[-1]["close"])
                log_ret = np.log(cex_before["close"]).diff().dropna()
                if len(log_ret) > 1:
                    row["ref_realized_vol"] = float(log_ret.std())

    # --- price_dev ---
    if oracle_price is not None and cex_price_at_time is not None:
        row["price_dev"] = (oracle_price - cex_price_at_time) / cex_price_at_time

    # --- DEX price, cross_venue_spread, reserve_skew ---
    if incident["dex_pool"]:
        dex_price_now = _dex_price(w3, incident["dex_pool"], block_number)
        if cex_price_at_time is not None:
            row["cross_venue_spread"] = (dex_price_now - cex_price_at_time) / cex_price_at_time
        if oracle_price is not None:
            row["dex_oracle_spread"] = (dex_price_now - oracle_price) / oracle_price
        time.sleep(0.15)
        baseline_block = block_number - BASELINE_LAG_BLOCKS
        dex_price_baseline = _dex_price(w3, incident["dex_pool"], baseline_block)
        if dex_price_baseline:
            row["reserve_skew"] = (dex_price_now - dex_price_baseline) / dex_price_baseline

    # --- congestion: percentile of base fee vs a trailing sample (blank pre-EIP-1559) ---
    if base_fee is not None:
        sample_fees = []
        start_block = max(LONDON_BLOCK, block_number - CONGESTION_SAMPLE_BLOCKS)
        for b in range(start_block, block_number, CONGESTION_SAMPLE_STRIDE):
            blk = _get_block_cached(w3, b)
            time.sleep(0.15)
            if blk.get("baseFeePerGas") is not None:
                sample_fees.append(blk["baseFeePerGas"])
        if sample_fees:
            row["congestion"] = float(sum(f <= base_fee for f in sample_fees)) / len(sample_fees)

    return row


def main():
    w3 = get_web3()
    rows = [compute_features(w3, incident) for incident in INCIDENTS]
    df = pd.DataFrame(rows)

    out_dir = REPO_ROOT / "data" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "features.parquet"
    df.to_parquet(out_path, index=False)
    print(f"\nWrote {len(df)} rows to {out_path}", flush=True)
    return df


if __name__ == "__main__":
    df = main()
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    print(df[["incident", "label", "block", "price_dev", "cross_venue_spread", "dex_oracle_spread",
              "heartbeat_elapsed", "congestion", "reserve_skew", "ref_realized_vol"]].to_string(index=False))
