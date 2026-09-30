# Manipulation Incident Candidates — Ethereum Mainnet

Source: [SunWeb3Sec/DeFiHackLabs](https://github.com/SunWeb3Sec/DeFiHackLabs) (README + `past/{year}/README.md` archives), cross-checked
against each incident's own PoC file (`vm.createSelectFork(...)` chain alias) and the linked
post-mortems. 7 candidates surfaced — all confirmed forking `"mainnet"` in their Foundry PoC.

| # | Incident | Date | Affected Asset | Protocol | Tx Hash | Source |
|---|----------|------|-----------------|----------|---------|--------|
| 1 | Harvest Finance | 2020-10-26 | USDC / USDT (Curve Y-pool arbitrage against FARM_USDC / FARM_USDT vaults) | Harvest Finance | `0x35f8d2f572fceaac9288e5d462117850ef2694786992a8c3f6d02612277b0877` | [rekt.news](https://rekt.news/harvest-finance-rekt/) |
| 2 | Cream Finance | 2021-10-27 | yUSD / Yearn 4Curve LP (oracle input); ETH, DAI, USDC, USDT drained | Cream Finance (Iron Bank) | `0x0fe2542079644e107cbf13690eb9c2c65963ccb79089ff96bfaf8dced2331c92` (block 13,499,798) | [Immunefi analysis](https://medium.com/immunefi/hack-analysis-cream-finance-oct-2021-fc222d913fc5) |
| 3 | Indexed Finance | 2021-10-15 | DEFI5 index pool | Indexed Finance | `0x44aad3b853866468161735496a5d9cc961ce5aa872924c5d78673076b1cd95aa` (block 13,417,949) | [BlockSec analysis](https://blocksecteam.medium.com/the-analysis-of-indexed-finance-security-incident-8a62b9799836) |
| 4 | MonoX Finance | 2021-11-30 | MONO token (self-swap price inflation); WETH, WMATIC, WBTC, USDC, USDT, LINK drained | MonoX | `0x9f14d093a2349de08f02fc0fb018dadb449351d0cdb7d0738ff69cc6fef5f299` (mainnet leg) | [SlowMist analysis](https://slowmist.medium.com/detailed-analysis-of-the-31-million-monox-protocol-hack-574d8c44a9c8) |
| 5 | Inverse Finance | 2022-06-16 | WBTC / USDT | Inverse Finance | `0x958236266991bc3fe3b77feaacea120f172c0708ad01c7a715b255f218f9313c` | [BlockSec analysis](https://blocksecteam.medium.com/price-oracle-manipulation-attack-on-inverse-finance-a5544218ea91) |
| 6 | Conic Finance | 2023-07-22 | crvUSD / USDC (crvUSD Omnipool) | Conic Finance | Not given in source | [Official post-mortem](https://medium.com/@ConicFinance/post-mortem-eth-and-crvusd-omnipool-exploits-c9c7fa213a3d) |
| 7 | UwU Lend | 2024-06-10 | sUSDe (Curve-sourced oracle input) | UwU Lend | `0x242a0fb4fde9de0dc2fd42e8db743cbc197ffa2bf6a036ba0bba303df296408b` (first of 5 related txs) | [rekt.news](https://rekt.news/uwulend-rekt) |

## Notes and flags

- **bZx — checked, not included.** DeFiHackLabs does *not* contain the famous Feb 2020 bZx
  oracle-manipulation incidents. It only lists two unrelated bZx entries: `20200912 bzx - Incorrect
  transfer` and `20231202 bZxProtocol - Inflation Attack`, neither of which is oracle/price-manipulation.
  Per your instruction to pull from the actual repo rather than assume, bZx is excluded.
- **MonoX Finance — dual-chain, flagged.** The same MONO self-swap bug was exploited on Ethereum
  mainnet *and* Polygon in the same incident (repo lists both an `etherscan.io` and a `polygonscan.io`
  tx). Included because a genuine mainnet leg exists, but note the loss total ($31M) spans both chains.
- Every included incident was verified directly against its Foundry PoC source (`src/test/.../*.sol`),
  confirming `vm.createSelectFork("mainnet", <block>)` — not inferred from the README text alone.
- **Cream Finance and Indexed Finance tx hashes — verified on-chain.** Both hashes were pulled from
  the PoC source comments (`@TX` / `Attack tx:`), cross-checked against the post-mortems (Immunefi
  calls the Cream hash "the attack transaction" verbatim; BlockSec's Indexed Finance article lists
  the same hash), and confirmed via a live `eth_getTransactionReceipt` call against Ethereum mainnet:
  both succeeded (`status: 0x1`), both landed exactly one block after their PoC's fork block, and
  their logs touch the exact token/pool addresses named in the post-mortems (DAI/USDC/USDT/WETH for
  Cream; the DEFI5 pool contract for Indexed). Indexed Finance was a two-pool incident (DEFI5 + CC10);
  the hash here is the DEFI5 transaction the repo's own PoC reproduces. A second, CC10-side tx
  (`0xbde4521c5ac08d0033019993b0e7e1d29b1457e80e7743d318a3c27649ca4417`) is mentioned in BlockSec's
  article but has not been independently verified against a receipt.

## Excluded (checked, wrong chain or too small/thin)

| Incident | Date | Reason excluded |
|---|---|---|
| Fortress Loans | 2022-05-08 | Confirmed BSC fork, not mainnet |
| BonqDAO | 2023-02-02 | Confirmed Polygon fork, not mainnet |
| Woofi | 2024-03-05 | Confirmed Arbitrum fork, not mainnet |
| Themis | 2023-06-28 | Confirmed Arbitrum fork, not mainnet |
| CompoundUni | 2024-02-23 | Mainnet-confirmed, but only $439K lost and a single tweet as documentation — weaker than the 7 above |
| MorphoBlue | 2024-10-13 | Mainnet-confirmed, but only $230K lost and a single tweet as documentation — weaker than the 7 above |
| LUSD | 2023-07-07 | Mainnet, but only ~$9,464 lost and a single tweet — too thin to be "well-documented" |

CompoundUni and MorphoBlue are mainnet-confirmed and available as backups if you want 8 instead of 7.
