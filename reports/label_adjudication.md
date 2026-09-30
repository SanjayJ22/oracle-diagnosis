# Label adjudication: 9 disagreements between the A2 sheet and the second labeler

Rule applied: `reports/a2_label_protocol.md` section 2 (M1 source moved by attacker flows, or by an arithmetic flaw in S's own math with a distinct consumer; M2 a **different** contract C reads S; M3 profit comes from C's reliance on the moved value; same-contract tie-break gives A). No models were rerun.
Sheet: `reports/a2_label_sheet.csv` now has two new columns, `adjudicated_category` and `adjudicated_verified_M`. `category` and every other column are unchanged. The 15 incidents both labelers agreed on are carried over, not re-researched.

## Headline

- **Final verified-M count: 9 (unchanged).** Strict (excluding math-enabled and donation-type): 7, also unchanged. Verified-M = Harvest, Cream, Inverse, UwU, Zunami, CurveLlamaLend, ResupplyFi, **Makina**, **BalancerBoostedPool2023**.
- **Incidents whose category changed: none.** On all 9 disagreements the adjudication sides with the A2 sheet's category, not the second labeler's.
- Makina and BalancerBoostedPool2023 were the two that could have removed verified-M rows (second labeler said A and R). Both **stay M**, each with two or more independent post-mortems that describe a distinct consumer reading the moved value and paying out.
- **Limits of this result:** (1) the A2 sheet and this adjudication come from the same model family, so agreement on 9 of 9 is weaker evidence than it looks; a human adjudicator should take Indexed Finance, WiseLending and Conic 02 at least. (2) Six of the nine rest on one source, on search excerpts only, or on no source for the specific incident (Indexed, SecuredFi, DRLVaultV3, USM, WiseLending, Conic 02; see each entry). (3) SecuredFi and DRLVaultV3 are `M` by mechanism but **single-source, so provisional and not verified-M**.

| Incident | Sheet | 2nd labeler | **Adjudicated** | Verified-M | Evidence I could read |
|---|---|---|---|---|---|
| BalancerBoostedPool2023 | M | R | **M** (`math_enabled`) | yes (not strict) | 2 full reads |
| Makina | M | A | **M** | yes (strict) | 3 full reads |
| Indexed Finance | A | M | **A** (medium confidence) | no | search excerpts only; both primary pages returned 403 |
| SecuredFi | M | A | **M, provisional** | no | 1 (PoC catalog, no post-mortem) |
| DRLVaultV3 | M | R | **M, provisional** | no | 1 full read |
| USM | R | M | **R** | no | 1 (incident list) |
| AjnaFinance | A | R | **A** | no | 2 (news-level mechanism) |
| WiseLending | O | A | **O** | no | none for this incident |
| Conic Finance 02 | O | A | **O** | no | 1 page (CertiK, quoting Conic's own post-mortem); Halborn is silent on this exploit |

## 1. BalancerBoostedPool2023 (2023-08-27): M, `math_enabled`

- **(a) S:** the cached token rate of the bb-a-USDC (and USDT, DAI) **linear pool**, `0x9210F1204b5a24742Eba12f710636D76240dF3d0` for USDC. Its rate is balance / BPT supply, and it enters the boosted pool's scaling factor.
- **(b) C and payout:** yes. The **boosted pool bb-a-USD** (a ComposableStablePool) is a different contract; it reads the linear pool's rate and swaps at it. BlockSec: the attacker swapped about 1M bb-a-USDC for about 139M bb-a-DAI (roughly 19:1 instead of 1:1) and 1M for about 248M bb-a-USDT (roughly 12:1), and "these distorted rates existed only because the boosted pool applied the manipulated cached rate". The rate moved about 40x (1.01e9 to 40.24e9 in BlockSec's units) inside one atomic transaction.
- **(c) Category M, `math_enabled`.** The rate was moved by exploiting rounding down in the linear pool's own swap math (amounts under 1e12 round to zero, so liquidity is added with nothing minted, and bptSupply can be driven to zero), but a distinct consumer read it and paid out, which A2 M4 covers. The second labeler's R requires "no distinct consumer reads a manipulated price", which is false here.
- **Sources:** BlockSec https://blocksec.com/blog/tiny-rounding-down-big-fund-losses-an-in-depth-analysis-of-the-recent-balancer-incident (read; it is the August 2023 incident, not the November 2025 one); Immunefi https://immunefi.com/blog/bug-fix-reviews/balancer-rounding-error/ (read; rate = balance/supply drops below 1 through rounding, then the flash-swapped BPT is repaid at the depressed rate). Also seen, not read: Balancer's own report https://medium.com/balancer-protocol/the-balancer-report-the-recent-vulnerability-disclosure-6cbed7fda9c7. SlowMist returned a certificate error; Beethoven X returned 403.

## 2. Makina (2026-01-20): M

- **(a) S:** the valuation of Makina's Curve **MIM/3CRV** position, computed through `calc_withdraw_one_coin()` (which depends on the pool's balances), flowing position, to Caliber AUM, to Machine AUM, to the exchange rate / share price (`MachineShareOracle`), which the DUSD/USDC Curve pool used as its oracle. **The label sheet's S (the DUSD/USDC pool spot) is the payout venue, not the price source**; this matters for the pilot (section 7 of `pilot_results.md`).
- **(b) C and payout:** yes. Caliber and Machine (distinct contracts from the Curve pool being read) consumed the inflated position value; the attacker bought DUSD at fair value, triggered revaluation, and sold DUSD at the inflated price, so the DUSD/USDC pool's LPs paid (about 1,299 ETH, about $4.13M, mostly taken by an MEV builder that front-ran the tx). CertiK: AUM 51.58M to 67.89M, share price 1.011771 to 1.331577.
- **(c) Category M** (attacker-controlled flash-loan flows into the pools move S; distinct consumers read it and pay out). The second labeler's A needs S and its only consumer to be the same contract; they are not (Curve pool function vs Caliber/Machine vs the DUSD pool).
- **Sources:** Makina post-mortem https://makinafi.substack.com/p/post-mortem-january-20th-2026-incident ; CertiK https://www.certik.com/blog/makina-incident-analysis ; Verichains https://blog.verichains.io/p/analyzing-the-4m-makina-finance-exploit (all read).

## 3. Indexed Finance (2021-10-14): A, medium confidence, unresolved between A and M

- **(a) S:** the DEFI5/CC10 pool's own token balances and weights. At re-index the controller used a Uniswap oracle only to size the new token's minimum balance; the excerpts do not say the oracle price was moved.
- **(b) C and payout:** not established. Excerpts say the attacker flash-swapped about $156M of pool tokens, bought UNI from the pool in chunks, added SUSHI to take majority weight, removed UNI so it was "calculated in SUSHI", then minted DEFI5 at an inflated valuation. The payout contract is the same pool whose state was moved.
- **(c) Category A** by the same-contract tie-break (own pool accounting / re-index logic). **It flips to M** if a call trace shows the controller or an external oracle read a flash-swap-moved value to set the minimum balance.
- **Sources (excerpts via search only; both primary pages returned 403):** BlockSec https://blocksecteam.medium.com/the-analysis-of-indexed-finance-security-incident-8a62b9799836 ; Indexed post-mortem https://ndxfi.medium.com/indexed-attack-post-mortem-b006094f0bdc ; news: https://decrypt.co/83681/defi-protocol-indexed-finance-hacked-for-16-million-team-finds-hacker

## 4. SecuredFi (2026-09-05): M, provisional (single source)

- **(a) S:** `getMarketUnitPrice()` of the Secured Finance order book.
- **(b) C and payout:** the **TokenVault** values lending-order-book collateral from it and releases WBTC; a same-block self-trade pins the price at par. About $104K across copycat bots; the PoC drained 0.899 WBTC (about $72K).
- **(c) Category M by mechanism:** S and the paying contract are distinct (order book vs TokenVault), so the second labeler's A does not fit. **Evidence tier single**: the only source is the crypto.training PoC catalog, which cites no post-mortem, so it cannot be verified-M.
- **Source:** https://crypto.training/hacks/

## 5. DRLVaultV3 (2025-11-10): M, provisional (single source)

- **(a) S:** a Uniswap V3 USDC/WETH pool quote read **in the same transaction** by the vault (`getQuoteForUSDC`) to set `amountOutMinimum`.
- **(b) C and payout:** yes. The attacker borrowed about 14M USDC from Morpho Blue, bought WETH to spike the pool price, triggered `swapToWETH`, and the vault bought WETH at the manipulated price; the attacker then sold back. Tx `0xe3eab35b...c475`.
- **(c) Category M:** S moved by attacker flows, a distinct contract (the vault) read it and paid out. Verichains calls it a "slippage design flaw" because the slippage baseline is mutable; that is how the flaw is framed, not a different mechanism. The second labeler's R (rounding) has no support; no rounding is involved. **Single mechanism-level source**, so provisional.
- **Source:** https://blog.verichains.io/p/the-drlvaultv3-exploit-a-slippage (read). Other hits were restatements of the same summary; none was independent technical analysis.

## 6. USM (2026-08-10): R (single source)

- **(a) S:** USM's own mean-price / redemption curve (`ethFromDefund`, not split-invariant).
- **(b) C and payout:** same contract. A flash loan moved the price through `fund()`, then 64 small `defund()` calls extracted more than one large redemption: about 70.83 ETH (about $136K). No external oracle is involved.
- **(c) Category R:** an invariant / curve-design flaw with no distinct consumer, so the second labeler's M fails M2. **Evidence tier single.**
- **Source:** Nominis August 2026 report https://www.nominis.io/insights/nominis-monthly-report (read). No protocol statement was found.

## 7. AjnaFinance (2026-08-28/29): A

- **(a) S:** none external; Ajna's internal liquidation and bucket pricing.
- **(b) C and payout:** same contract. Per Cryptotimes: `bucketTake` can mint LP to the taker, `removeCollateral` pulls against that LP, and `settle` moves leftover collateral out when `quoteRepaid` is zero; in the documented cbETH pool 48.13 cbETH ($133K) left for 3.47 WETH. "The drain did not require a fake Chainlink or Pyth price." About $775K across seven pools.
- **(c) Category A:** a state-transition / accounting flaw in one contract, not rounding or precision, so the second labeler's R is the weaker fit. Bitget's article is a restatement, so independence is limited.
- **Sources:** https://www.cryptotimes.io/2026/08/29/ajna-v2-loses-775k-on-ethereum-after-attacker-exploits-liquidation-math/ ; https://www.bitget.com/news/detail/12560605753354 ; also listed: https://cryptoticker.io/en/ajna-defi-lending-exploit-immutable-contract/

## 8. WiseLending (2023-10-13): O

- **(a)-(b):** I could not establish either. Every post-mortem found (Astra, SolidityScan, Code4rena, Cointelegraph) is the **January 2024** exploit. For 13 October 2023 I found only that the attack tx was front-run by c0ffeebabe.eth (about $260K); one search-result summary describes a donate-to-inflate-shares step and a precision-loss `withdrawShares` returning 0, but I could not trace that text to a page I fetched. The sheet's two cited sources are tweets.
- **(c) Category O.** If the donation/precision description holds, the same-contract tie-break gives A, which is what the second labeler chose; that is a probable outcome, not an established one.
- **Sources:** none adequate. Seen: BlockSec explorer tx page https://app.blocksec.com/explorer/tx/eth/0x7ac4a98599596adbf12fffa2bd23e2a2d2ac7e8989b6ea043fcc412a29126555

## 9. Conic Finance 02 (2023-07-22): O

- **(a) S:** the Curve crvUSD/USDC pool state that the Conic crvUSD omnipool used to value deposits and withdrawals.
- **(b) C and payout:** the crvUSD omnipool paid out. CertiK's page, quoting the Conic team, characterizes this second loss (about $300K, not the $3.2M read-only reentrancy on the ETH omnipool) as **MEV arbitrage** of an imbalance left by the first exploit (Halborn does not cover it, so this is one source): swap crvUSD to USDC on Curve, deposit into Conic, reverse, withdraw, repeat. Whether the swaps moved S **away from** fair value (M1) or toward it is not stated, and nothing I read traces the read path.
- **(c) Category O.** A is unsupported (nothing suggests an accounting bug). It would be M only if the swaps are shown to push S away from fair value; if they restore it, the event is arbitrage and outside the positive class either way.
- **Sources:** CertiK https://www.certik.com/skynet-report/5FZAakbsUVg1EyHLNw9Qnm-conic-finance-incident-analysis (read, including the team's MEV-arbitrage characterization); Halborn https://www.halborn.com/blog/post/explained-the-conic-finance-hack-july-2023 (read; covers only the ETH omnipool). Conic's own post-mortem https://medium.com/@ConicFinance/post-mortem-eth-and-crvusd-omnipool-exploits-c9c7fa213a3d was not fetched.

## Other sheet corrections found while reading (no column edited)

- **Makina `S`:** should be the MIM/3CRV `calc_withdraw_one_coin` valuation feeding Machine AUM, not the DUSD/USDC pool spot (section 2).
- **Harvest `S`:** the sheet's yUSDC/yUSDT ratio is flat at block close; the value the fUSDC vault read is `zap.calc_withdraw_one_coin` via `PriceConvertor` (`pilot_results.md` section 7a).
- **ResupplyFi `S`:** the listed address `0x8970...` is the crvUSD controller; the ERC4626 vault is `pair.collateral()` = `0x01144442fba7adccb5c9dc9cf33dd009d50a9e1d`.
- Evidence-tier wording: Indexed Finance is marked "2-source" in the sheet but I could not read either source page.
