# Final Incident List — Ethereum Mainnet

Combined incident set for the diagnostic model: **20 incidents total** across all three label classes —
5 `manipulation`, 3 `malfunction`, 12 `large volatility event`. Manipulation/malfunction transaction
hashes have been verified against a live Ethereum mainnet `eth_getTransactionReceipt`/
`eth_getTransactionByHash` call (status `0x1`, correct chain), not just copied from a post-mortem.
Volatility events are verified by block number + on-chain price move instead (see that section for why).

## Manipulation (5, locked)

| Incident | Date | Transaction Hash | Block Number | Affected Asset | Label |
|---|---|---|---|---|---|
| Harvest Finance | 2020-10-26 | `0x35f8d2f572fceaac9288e5d462117850ef2694786992a8c3f6d02612277b0877` | 11,129,474 | USDC / USDT (Curve Y-pool arbitrage against FARM_USDC / FARM_USDT vaults) | manipulation |
| Cream Finance | 2021-10-27 | `0x0fe2542079644e107cbf13690eb9c2c65963ccb79089ff96bfaf8dced2331c92` | 13,499,798 | yUSD / Yearn 4Curve LP (oracle input); ETH, DAI, USDC, USDT drained | manipulation |
| Indexed Finance | 2021-10-15 | `0x44aad3b853866468161735496a5d9cc961ce5aa872924c5d78673076b1cd95aa` | 13,417,949 | DEFI5 index pool | manipulation |
| Inverse Finance | 2022-06-16 | `0x958236266991bc3fe3b77feaacea120f172c0708ad01c7a715b255f218f9313c` | 14,972,419 | WBTC / USDT | manipulation |
| UwU Lend | 2024-06-10 | `0x242a0fb4fde9de0dc2fd42e8db743cbc197ffa2bf6a036ba0bba303df296408b` | 20,061,319 | sUSDe (Curve-sourced oracle input) | manipulation |

Notes:
- Harvest, Inverse, and UwU Lend block numbers were pulled directly from `eth_getTransactionByHash`
  (not previously recorded) — all three land exactly one block after their DeFiHackLabs PoC's fork
  block, consistent with the fork-then-attack convention already confirmed for Cream and Indexed.
- The UwU Lend transaction is a contract-creation call (`to: null`) — the exploit executed inside
  the deployed contract's constructor, a common pattern for atomic flash-loan attacks.

## Malfunction (3, locked)

| Incident | Date | Transaction Hash | Block Number | Affected Asset | Label |
|---|---|---|---|---|---|
| stETH/ETH heartbeat lag | 2022-06-18 | `0x258ede91fce37c1423e9e5ff80abb461d1b36276625cc1b43b9b3951a3e45bd9` | 14,984,168 | stETH (ETH-denominated) | malfunction |
| FTT/USD pause/deprecation | 2022-11-28 | `0x4b8a4759444d602084c9d308df0ed0c8d4459263574154e25d31ca807021e75f` | 16,069,381 | FTT | malfunction |
| UST/USD feed freeze (Terra collapse) | 2022-06-11 | `0xe25b50733b4e241d9429fd9de178de18b02c37f1c5e4725448ffc80e34b423b5` | 14,942,628 | UST (Terra USD, Wormhole-bridged) | malfunction |

Notes:
- Each transaction hash is the actual on-chain `transmit`/update call that set the recorded round —
  found by matching the block's transaction list against the feed's underlying phase aggregator (for
  stETH/ETH, a phase-1 proxy) or the aggregator contract directly (FTT/USD, UST/USD — both older,
  non-phase-encoded contracts). Each block had exactly one matching transaction.
- **stETH/ETH**: not a stall — the feed's ~24h heartbeat with a wide deviation threshold meant the
  genuine June 2022 depeg (price fell from 0.979 on June 5 to a 0.935 trough on June 18) was reflected
  on-chain with up to a full day of lag versus real-time Curve spot. The listed block/tx is the trough
  update; full round-by-round detail is in `reports/malfunction_candidates.md`.
- **FTT/USD**: a hard stop, not a lag. The tx above is FTT/USD's *final* update (round 1825); round 1826
  is confirmed empty and no update has occurred since — frozen at $1.289601 for ~3.6 years and counting.
- **UST/USD**: counted as **one incident** despite two independently frozen contracts (per your
  direction — same root cause, not two unrelated malfunctions). The block/tx listed is the *first*
  freeze: the original aggregator's last update, price $0.010007, on 2022-06-11. A *second* aggregator
  took over the Chainlink Feed Registry's UST/USD slot mid-collapse (block 14,769,103, 2022-05-13) and
  continued tracking Terra Classic's residual value for two more years before it, too, froze permanently
  on 2024-07-09 (block 20,267,648, final price $0.015519). Both freezes are independently verified
  on-chain (separate addresses, separate empty-next-round confirmations); full detail in
  `reports/malfunction_candidates.md`.

## Large Volatility Event (12, locked)

Label is deliberately **direction-agnostic** ("large volatility event", not "crash") — #4 and #6 below
are rallies, not crashes, and the label needs to cover both. All 12 verified on ETH/USD
(`0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419`) directly from on-chain round history via
`fetch_chainlink.py` — same tool used for the manipulation and malfunction classes. For each, the block/
date is the peak-or-trough moment of the move; "Move" is peak-to-trough (or trough-to-peak, noted)
within the checked window. "Gap check" is the feed's max update gap in that window as a multiple of its
own median for the window — every one stayed well within normal responsive behavior (no candidate here
shows the kind of multi-hour/day stall that would indicate malfunction contamination). No transaction
hash is recorded for this class, per your direction — a volatility label attaches to a price level, not
a discrete triggering transaction, so block number + date is the verifiable anchor.

| # | Incident | Date | Block Number | Affected Asset | Move | Gap Check | Label |
|---|---|---|---|---|---|---|---|
| 1 | May 19 2021 crash | 2021-05-19 | 12,465,029 | ETH/USD | -52.1% ($4,128.28 → $1,976.54) | max 3,642s (13.4x median) | large volatility event |
| 2 | June 2022 Celsius deleveraging | 2022-06-15 | 14,966,742 | ETH/USD | -43.1% ($1,794.67 → $1,020.41) | max 3,630s (10.1x median) | large volatility event |
| 3 | Nov 2022 FTX collapse | 2022-11-09 | 15,935,789 | ETH/USD | -34.3% ($1,634.07 → $1,073.89) | max 3,660s (13.9x median) | large volatility event |
| 4 | March 2023 banking-wobble rally | 2023-03-14 | 16,826,924 | ETH/USD | **+29.5% rally** ($1,373.40 → $1,779.15) — SVB crisis drove flight *into* crypto, not a crash | max 3,660s (4.2x median) | large volatility event |
| 5 | Aug 2023 selloff | 2023-08-17 | 17,937,299 | ETH/USD | -15.6% ($1,844.92 → $1,558.00) | max 3,696s (1.4x median) | large volatility event |
| 6 | March 2024 cycle-high rally | 2024-03-06 | 19,378,953 | ETH/USD | **+18.4% single-day rally** ($3,253.45 → $3,853.26 in ~24h) | max 3,696s (3.8x median) | large volatility event |
| 7 | Aug 5 2024 carry-trade unwind | 2024-08-05 | 20,460,558 | ETH/USD | -32.5% ($3,228.83 → $2,177.85) | max 3,660s (10.2x median) | large volatility event |
| 8 | Dec 2024 breakdown from cycle high | 2024-12-20 | 21,443,591 | ETH/USD | -24.4% ($4,106.92 → $3,106.77) | max 3,696s (2.5x median) | large volatility event |
| 9 | April 2025 tariff shock | 2025-04-09 | 22,228,063 | ETH/USD | -28.5% ($1,949.67 → $1,394.62) | max 3,708s (6.9x median) | large volatility event |
| 10 | Oct 10-11 2025 flash crash | 2025-10-10 | 23,549,972 | ETH/USD | -23.7% ($4,542.39 → $3,464.40) | max 3,696s (5.9x median) | large volatility event |
| 11 | Nov 4 2025 crash | 2025-11-04 | 23,728,675 | ETH/USD | -21.4% ($3,904.44 → $3,070.42) | max 3,696s (5.0x median) | large volatility event |
| 12 | Feb 6 2026 crash | 2026-02-06 | 24,394,166 | ETH/USD | -42.4% ($3,038.34 → $1,751.55) | max 3,672s (7.7x median) | large volatility event |

Notes:
- All 12 kept, no trimming, per your direction.
- #1-7 were the specifically requested candidates, all confirmed as-described. #4 and #6 turned out to
  be **rallies, not crashes** (flagged inline) — still large, clean, market-wide moves, just not in the
  direction their "crash"-sounding window names implied; reported honestly rather than reframed to fit.
  This is exactly why the label itself is direction-agnostic.
- #8, #10, #11, #12 were self-identified from real 2024-2026 market history (via search, then verified
  on-chain) rather than recalled from training data, since anything this recent needs verification
  regardless of source. #12 in particular resolved a genuine inconsistency in press coverage (one
  source implied Feb 23 2026, another Feb 6) — the on-chain data confirms Feb 6 as the real trough.
- Every gap-check multiple corresponds to an absolute max gap under ~62 minutes — during high volatility
  the feed's update *frequency increases* (median gaps drop to single-digit minutes), so even a 13-14x
  multiple here is a brief lull, not a stall. None of these 12 are anywhere near the malfunction
  thresholds used elsewhere in this project (hours-to-permanent).
