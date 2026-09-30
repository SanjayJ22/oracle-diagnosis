# A2. Label protocol for "oracle-price manipulation" (DRAFT v0.1, 2026-09-29, awaiting review)

Fixes audit M1 (heterogeneous manipulation class). Provisional relabel of the 24 current
manipulations is in §5; it is **not verified against post-mortems** (see §5 caveat).

## 1. Honest note on independence from model results

This rule was drafted **after** the audit ran `label_sensitivity.py` and `error_sets.py`, so the
author had seen which incidents the models miss. The rule below is built from the mechanism (what
was moved, what read it), not from any model output, but the roadmap's requirement "fixed before
looking at model results" cannot be met in the strict sense for the current 24. Mitigations:
(a) A9 blind second labeler on all incidents, with Cohen's kappa; (b) the rule is committed with
a date before any relabel is applied; (c) for **new** incidents (A0/C2/A7) no model output exists.

## 2. Definition

An incident is **`M`: oracle-price manipulation** iff **all** hold:

- **M1 (source moved):** an attacker action, possibly flash-loan financed, moves the value of a
  price source `S` (spot price, TWAP, LP or vault share price, exchange rate, order-book unit
  price) away from its counterfactual fair value, at or before the exploit transaction.
- **M2 (distinct consumer):** a **different** contract (or protocol) `C` reads `S`, directly or via
  a cached value, and uses it to value collateral, mint, redeem, swap, or liquidate.
- **M3 (dependence):** the attacker's profit comes from `C`'s reliance on the moved value.
- **M4 (flow mechanism):** `S` moved because of attacker-controlled flows into `S`'s state (swaps,
  deposits, donations, mint/burn, self-trades), **or** by exploiting an arithmetic flaw in `S`'s
  own math while a distinct consumer still read the result (sub-flag `math_enabled`).

Other categories, adjudicated in this order when `M` fails:

| Code | Meaning |
|---|---|
| `R` | rounding / precision / invariant-math bug in a pool or curve, no distinct consumer reads a manipulated price |
| `A` | accounting, access-control, or logic bug (share accounting, unchecked callbacks, mint bugs); `S` and its only "consumer" are the same contract |
| `K` | MEV-bot or key/permission exploit unrelated to a consumed price |
| `O` | evidence insufficient to assign |

**Tie-break for same-contract cases:** if `S` and its only consumer are the same contract and the
flaw is in that contract's own share or rate accounting, label `A`, even if the mechanism looks
like manipulation. (A donation to a vault whose rate is read by a *different* lending contract is
`M`.)

**Primary positive class = `M`.** Sensitivity: `M` plus `M`-with-`math_enabled` variants
separately; `M` union `R`.

## 3. Evidence requirements

- `>= 2` independent sources per label: a protocol or auditor post-mortem plus an independent
  analysis (BlockSec, PeckShield, OpenZeppelin, SlowMist, Halborn, etc.).
- The labeler reviews the **call trace** (Etherscan / Phalcon / Tenderly) and records `S`, `C`, the
  read function, the manipulating tx hash(es), and whether the manipulation was atomic.
- A PoC header comment (DeFiHackLabs) alone is a **single-source** claim: label `provisional`,
  excluded from the primary positive class until a second source is recorded.
- The record stores `labeled_at` and `model_results_seen_before_label` (must be `none` for new
  incidents).

## 4. Label sheet schema

`incident_id, T_block, T_tx, S_type, S_address, S_function, C_address, C_function, category (M/R/A/K/O),
subflags (atomic, math_enabled, read_only_reentrancy, donation, twap, share_price), sources[url],
evidence_tier (2-source / single / none), labeler, labeled_at, confidence, notes`

## 5. Provisional relabel of the 24 current manipulations

**Caveat: this is a first-pass reading of each incident's stored `reference_note` (which is
partly copied from PoC headers) plus my own recall of some public post-mortems. I have not fetched
post-mortems for any of them. Some incidents are dated after my ability to check independently.
This is not the A2 relabel, and it cannot serve as the A9 second labeler.**

| Incident | Provisional | Basis in the stored note | To confirm |
|---|---|---|---|
| Harvest Finance | M | Curve Y pool spot manipulated, vault priced from it | 2 sources |
| Cream Finance (2021-10) | M | yUSD vault rate inflated by LP donation, read by Cream | consumer read path |
| Inverse Finance | M | Curve tricrypto price manipulated (BlockSec/Halborn cited) | atomic flag |
| UwU Lend | M | Curve USDe pool ratio 1.06 to 1.14 feeding oracle | S/C addresses |
| Conic Finance 02 | M (`read_only_reentrancy`) | Curve pool state read mid-tx | confirm mechanism |
| ZunamiProtocol | M | UZD cached price from manipulated Curve pool | S/C addresses |
| CompoundUni | M | UNI/WETH V3 pool read by `UniswapAnchoredView` | none likely |
| CurveLlamaLend | M (`atomic`) | sDOLA rate inflated 13.79% in-tx, read by LlamaLend | atomic; needs G2 |
| ResupplyFi | M (`donation`) | controller reads vault exchange rate after donation | none likely |
| Makina | M | Curve pool state read for AUM/sharePrice, 2 post-mortems cited | tx-level trace |
| SecuredFi | M | same-block self-trade moves `getMarketUnitPrice()` read by vault | 2nd source |
| Indexed Finance | M? | DEFI5 own pool; note does not state the consumed price | mechanism unclear |
| DRLVaultV3 | M? | "thin-pool slippage/valuation exploit"; single PoC source | mechanism, 2nd source |
| BalancerBoostedPool2023 | boundary (`M` `math_enabled` vs `R`) | linear-pool rate manipulated by precision loss | does a distinct pool read the rate? |
| MonoX Finance | boundary (`A` vs `M`) | own-AMM price mis-updated; consumer is the same AMM | rule tie-break applies -> `A` unless another contract read it |
| BalancerV2 (2025-11) | R | pool's own math; no external consumer | confirm no consumer |
| BalancerV1BPool | R | `calcSingleInGivenPoolOut` rounding | confirm |
| USM | R | redemption-curve rounding; note itself says "not a literal price-feed attack" | confirm |
| TOPBPool | A | mint-and-dump into bonding-curve AMM; PoC-header sourced only | single-source |
| WiseLending | A | donate-inflate on own share accounting | same-contract tie-break |
| EFLeverVault | A | vault callback / accounting path (from note; not post-mortem confirmed) | verify mechanism |
| ThetanutsIndexVault | A | share accounting; PoC-header sourced | single-source |
| MEVBOTa47b | K | MEV-bot exploit | none |
| AjnaFinance | O | note gives no mechanism; 7 pools hit same day | needs post-mortem |

**Counts, provisional:** `M` 11 confident + 2 uncertain (`M?`) ; 2 boundary; `R` 3; `A` 4;
`K` 1; `O` 1. So the primary positive class could be as small as 11 to 15 of the current 24.
Roadmap items asked to confirm: TOPBPool (`A`, single-source), Makina (`M`, 2 post-mortems cited),
AjnaFinance (`O`), EFLeverVault (`A`, unverified). Consequence for power: A10 §4.

## 6. Decisions needed from you

1. **`math_enabled` manipulations** (BalancerBoostedPool2023-type, a distinct pool reads a rate
   that an arithmetic flaw distorted): include in primary `M` with a sub-flag (recommended, pre-registered
   sensitivity run) or exclude?
2. **Same-contract tie-break** (`A`): accept? It moves WiseLending and MonoX out of the positive class.
3. **Second labeler for A9**: who? Needs to be independent of this project and blind to the
   provisional table above.
4. Should incidents with only a single (PoC-header) source stay in the development set as
   `provisional` or be dropped until a second source is found?
