# DeFiHackLabs price/oracle screen: A2 labels (2026-09-30)

Labels: `reports/dhl_screen_labels.csv` (41 rows). Script: `src/dhl_screen_labels.py`. No models were run. Rule: `reports/a2_label_protocol.md` section 2 (M1 attacker flows or an arithmetic flaw in S's own math move S; M2 a **different** contract C reads S; M3 profit comes from C's reliance; same-contract tie-break gives A; R rounding/invariant bug with no distinct consumer; K MEV or key exploit unrelated to a consumed price; O evidence insufficient).

## The exact screen (reproduces the 41)

1. Universe: `reports/defihacklabs_index.csv` (875 README headings from DeFiHackLabs, built by `src/cjsj_01_a2_labels.py`).
2. **Keyword test**: the heading text `"<name> - <description>"`, lower-cased, matches this regex (the first rule of `CAT_RULES` in that script):
   `price manip|oracle|spot price|twap|slot0|exchange.?rate|share price|donat|inflat|get_?p\b|virtual.?price|price feed|stale.*price|mid-price`
3. **Chain test**: the incident's PoC calls `createSelectFork("mainnet")` (PoC matched to the heading by normalized filename, fuzzy within one month).
4. Result: **41 of 295 mainnet incidents**. One correction to the script's own matching: `bZxProtocol` (2023-12-02) was fuzzily matched to `OnyxProtocol_exp.sol`; I used `src/test/2023-12/bZx_exp.sol`. The two "Circle" headings (2022-08-13 and 2022-08-16) share one PoC file.
5. The screen reads **headings only**, not PoC comments; that is why the recall below is low.

## Results

| | Count |
|---|---|
| Incidents screened | 41 (years: 2021: 1, 2022: 4, 2023: 12, 2024: 6, 2025: 10, 2026: 8) |
| Categories | M 20, A 7, R 1, K 1, O 12 |
| **M total (any evidence)** | **20** |
| **2-source-verified M** (M with `source_count` of 2 or more) | **9** |
| of those, with at least one protocol / security-firm post-mortem | 6 |
| M that are provisional (fewer than 2 sources) | 11 |
| Rows with no independent source at all (PoC or catalog only) | 23 of 41 |

Verified M: Flamincome, FloatProtocol, ArrakisGUNI, edel-xstock, Curve LlamaLend, Makina, ResupplyFi, Peapods Finance, InverseFinance.
Provisional M: DRLVaultV3, PresaleV5, FixedTokenBSwap, AmpKashi, Scorch, CompoundUni, Burntbubba, MetaLend, kTAF, BTC20, RoeFinance.

**Conventions.** `source_count` = independent non-PoC sources that state the mechanism (a protocol post-mortem, a security-firm analysis, or a news article that describes the mechanism rather than only the loss). `strong_sources` = the subset that are protocol statements or security-firm post-mortems. News articles frequently restate the same alert or PoC, so their independence is limited; three of the five newly verified M (Flamincome, Float, Arrakis) rest on news-level sources only. Nine rows reuse `a2_label_sheet.csv` (`origin = a2_sheet`); 32 were labeled in this pass from the PoC comments plus what I could retrieve.

## What this says about the screen and about n

- **Recall is low.** Of the 9 verified-M in `a2_label_sheet.csv`, the screen captures **4** (Inverse, Makina, Resupply, Curve LlamaLend) and **misses 5** (Harvest, Cream, UwU, Zunami, BalancerBoostedPool2023): recall 4/9 = 0.44 (95% Wilson CI 0.19 to 0.73). A concrete miss outside our 24: `OnyxProtocol` (2023-11-01), a CompoundV2 empty-market donation attack, is headed "Precission Loss Vulnerability" and is not flagged. So the 41 are a **lower bound** on price/oracle-type incidents on Ethereum, and extending the screen to PoC comments would likely add more.
- **Union with the existing set.** The verified M here (9) overlap the a2 sheet's 9 in 4 incidents (CurveLlamaLend, Inverse Finance, Makina, ResupplyFi); the union of distinct verified M across both is **14**. That is still well below the 40 A10 set for a meaningful A5 gate, and several of the new ones are news-level.
- **Thin evidence dominates.** 23 of the 41 have no independent source, so most labels outside the 9 verified M are provisional; O (12) is the honest label for incidents whose PoC states no mechanism.

## Judgment calls to review

- **Pre-existing mispricing vs. manipulation.** EnsoFinance and SummerFi are **A** because their sources say the bad valuation already existed and the attacker did not move it (M1 fails). SummerFi is borderline: the attacker donated stale-valued tokens into an Ark, which under a donation reading would be M. Morpho Blue (oracle decimal error) is A on the same logic.
- **Attacker-controlled price source.** FixedTokenBSwap is M by the letter of M1-M4 (fake token and fresh pair supply the quote, a distinct contract pays) but could equally be read as a missing-validation A. PoC-only.
- **Slippage-parameter flaws.** Peapods Finance is M (attacker moves the pool price, the contract swaps at it), the same call as DRLVaultV3.
- **Conflicts I could not resolve.** Burntbubba: the one source says Base, the PoC forks mainnet. SASHAToken: the Shezmu post-mortems found describe the September 2024 open-mint bug, and this entry is dated 2024-10-06, so they may not apply.
- **Naming.** Flamincome appears in news as "FlamingoFinance".
