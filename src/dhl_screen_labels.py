"""Apply the A2 written rule (reports/a2_label_protocol.md s2) to the 41 DeFiHackLabs Ethereum incidents flagged by the keyword screen.
Screen = the README-heading regex of src/cjsj_01_a2_labels.py CAT_RULES[0] on 'name - description', chain == mainnet via PoC createSelectFork.
Labels are hand-assigned from PoC comments + retrieved post-mortems (recorded per row); 9 rows reuse the a2 sheet / adjudication. No models are run.
"""
import json, re
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IDX = pd.read_csv(ROOT / "reports/defihacklabs_index.csv")
SCREEN_RE = r"price manip|oracle|spot price|twap|slot0|exchange.?rate|share price|donat|inflat|get_?p\b|virtual.?price|price feed|stale.*price|mid-price"
scr = IDX[(IDX.category == "price/oracle/rate manipulation") & (IDX.chain == "mainnet")].copy()
assert len(scr) == 41
POC = {x["name"] + str(x["date"]): x["poc"] for x in json.load(open("/private/tmp/claude-501/-Users-sanjayjillellamudi/47c45126-8620-49c8-ac56-1f12b71acaf1/scratchpad/dhl41.json"))}
POC["bZxProtocol20231202"] = "src/test/2023-12/bZx_exp.sol"      # fuzzy match had picked OnyxProtocol_exp.sol

S = "https://"
# name -> (category, n_sources, n_strong, evidence, reason, sources, notes)
L = {
"Flamincome": ("M", 2, 0, "PoC + 2 news", "Strategy NAV priced at Convex position x spot metapool virtual price; permissionless stakeFor and flash-loaned LP mint inflate it; VaultYUSDT (distinct) overpays on withdrawAll.", f"{S}www.cryptotimes.io/2026/09/16/blockaid-flags-flamingofinance-contract-exploit-345-9k-stolen/ | {S}cryptorank.io/news/feed/815dc-flamingofinance-loses-346000-in-defi-exploit-using-18m", "news calls the protocol 'FlamingoFinance'; mechanism detail in news may derive from the PoC PR"),
"EnsoFinance": ("A", 2, 0, "PoC + 2 news", "Oracle misconfiguration (fee tier passed as TWAP window) on an already-imbalanced V3 pool; attacker did not move S, so M1 fails.", f"{S}www.kucoin.com/news/flash/enso-finance-vault-loses-5-6-eth-due-to-oracle-price-error | {S}www.thecryptoupdates.com/enso-finance-loses-5-6-eth-in-oracle-price-error/", "flips to M if a trace shows the attacker moved the V3 pool"),
"FloatProtocol": ("M", 3, 0, "PoC + 3 news (SlowMist root cause quoted)", "Hypervisor prices LP shares off Uniswap V3 slot0; flash-loan swap moves the tick, deposit/withdraw (distinct contract) at the skewed value.", f"{S}crypto.news/float-protocol-hit-by-28k-flash-loan-attack-through-uniswap-v3-manipulation/ | {S}www.cryptotimes.io/2026/08/31/float-protocol-losses-10-71-eth-after-uniswap-v3-spot-price-manipulation/ | {S}coinspectator.com/cryptonews/2026/08/31/float-protocol-hit-by-28k-flash-loan-attack-through-uniswap-v3-manipulation/", "SlowMist attribution is second-hand (via Cryptotimes)"),
"ArrakisGUNI": ("M", 2, 0, "PoC + 2 news", "G-UNI mint/burn size off live Uniswap V3 slot0; atomic swap moves price, mint then burn against the pool (distinct) at the skewed value.", f"{S}pro.edgex.exchange/en-US/news/article/arrakis-finance-weth-exploit-uniswap-v3 | {S}coinfomania.com/uniswap-v3-exploit-costs-arrakisfinance-2-94-weth-details/", ""),
"SummerFi": ("A", 3, 1, "PoC + protocol retrospective + 2 news", "Retrospective says the stale-value misvaluation pre-existed and the attacker exploited it (capped-but-active Arks stayed in NAV); S not created by attacker flows.", f"{S}forum.summer.fi/t/lazy-summer-protocol-exploit-july-6-2026-ba-labs-risk-curator-retrospective/856 | {S}www.theblock.co/post/407198/summer-finance-exploited | {S}ambcrypto.com/summer-fi-reveals-months-long-preparation-behind-6m-defi-exploit/", "borderline: attacker donated stale-valued vault tokens into an Ark (would be M under a donation reading)"),
"edel-xstock": ("M", 4, 1, "PoC + protocol statement + 3 news/explainers", "Attacker's redeem/donate loop inflated the wGOOGLx ERC-4626 rate about 6 to 79; Edel Lending (distinct) valued the collateral at the inflated rate and lent.", f"{S}x.com/edeldotfinance/status/2072154468058022033 | {S}www.coindesk.com/tech/2026/07/01/tokenized-google-stock-inflated-7-700-in-rare-defi-lending-exploit | {S}crypto-economy.com/attacker-manipulates-tokenized-google-shares-to-drain-defi-lending-protocol/ | {S}coinsbit.io/news/how-tokenized-stocks-fail-as-collateral-edel-exploit/", "tokenized-stock vault rate: same class as Resupply/Cream (vault rate, no independent reference price)"),
"Circle@20220816": ("O", 0, 0, "PoC only", "PoC links only a BlockSec trace; victim is a plain Uniswap V2 DAI/USDC pair and the PoC calls Maker vault functions, but no mechanism is stated and no post-mortem was found.", "", "two README entries (0813, 0816) share one PoC; the name 'Circle' is not explained"),
"Circle@20220813": ("O", 0, 0, "PoC only", "Same PoC as the 2022-08-16 entry; no mechanism stated, no post-mortem found.", "", "see 2022-08-16"),
"GoodCompound": ("O", 0, 0, "PoC only", "PoC shows flashLoan/borrow/swap against Compound markets but states no mechanism; web results for the incident returned only unrelated Compound governance news.", "", ""),
"bZxProtocol": ("A", 0, 0, "PoC only", "PoC (bZx_exp.sol): iYFI empty-pool first-depositor inflation (burn shares, mint 5 wei, donate, borrow); share price moved and read inside the same iToken contract, so same-contract tie-break.", "", "provisional; fuzzy PoC match had picked Onyx; no post-mortem found (search returned only the 2020 bZx incidents)"),
"Burntbubba": ("M", 1, 0, "PoC + 1 analysis (DarkNavy, via search summary)", "FarmingLPToken mints shares off a spot price that the attacker moves through attacker-created routing pools; the wrapper (distinct from the pair) pays.", f"{S}www.darknavy.org/web3/exploits/movie-token-burn-manipulation/", "CHAIN CONFLICT: the source places it on Base, the PoC forks mainnet; unresolved. Provisional (1 source)"),
"MetaLend": ("M", 0, 0, "PoC only (donateAndBorrow)", "PoC donates to an empty CompoundV2-fork market to inflate the exchange rate and borrows against it; the Comptroller (distinct) reads the inflated rate.", "", "provisional; mechanism from PoC function names plus README heading; no post-mortem found"),
"kTAF": ("M", 0, 0, "PoC only (mint/borrow/redeem/liquidate)", "Same CompoundV2 empty-market inflation pattern per README heading and PoC calls; distinct Comptroller reads the inflated rate.", "", "provisional; generic Onyx-class post-mortems describe the pattern, not this incident"),
"MahaLend": ("O", 0, 0, "PoC only (recoverDonatedFund)", "README heading says donate-inflation plus rounding but the PoC states no read path, so M2 cannot be established.", "", "same gap as WiseLending 2023-10"),
"Raft_fi": ("R", 2, 1, "PoC + CoinDesk + MetaTrust", "Precision flaw (divUp) in Raft's own share minting let the attacker mint unbacked R; no distinct consumer of a moved price.", f"{S}www.coindesk.com/tech/2023/11/10/defi-platform-raft-suffers-33m-exploit-but-hacker-likely-takes-a-loss-on-the-attack | {S}metatrust.io/blogs/post/when-hacking-goes-haywire-rafts-1570-eth-loss-takes-a-cosmic-detour-to-the-black-hole", "README heading also says donate-inflation"),
"BTC20": ("M", 0, 0, "PoC + catalog description only", "Presale buyWithEthDynamic priced off a spot AMM price the attacker moved (catalog description); presale contract (distinct) pays.", f"{S}crypto.training/hacks/", "provisional; the only mechanism text is a PoC catalog entry (SlowMist cited for the loss)"),
"VINU": ("O", 0, 0, "PoC only", "PoC comment says 'fake Router, manipulating the price of VINU' but no consumer of a moved price is identified; no post-mortem found.", "", ""),
"ERC20TokenBank": ("O", 0, 0, "PoC only", "README heading only; PoC calls Curve exchange_underlying but states no mechanism; no post-mortem found.", "", ""),
"RoeFinance": ("M", 1, 1, "PoC + QuillAudits (via search summary)", "Flash loan plus UNI-V2 sync moved the LP price that ROE's oracle read (34.59e12 to 43.21e12); borrowing against it drained the pool.", f"{S}quillaudits.medium.com/decoding-roe-finances-flash-loan-exploit-quillaudits-df8494e2090f", "provisional (1 source)"),
"MorphoBlue": ("A", 5, 3, "PoC + Verichains + SolidityScan + 3 more", "Market oracle misconfigured (decimal scale factor, PAXG priced about 1e12 too high); attacker did not move S, so M1 fails.", f"{S}blog.verichains.io/p/morpho-protocol-market-oracle-price | {S}blog.solidityscan.com/morphoblue-hack-analysis-638b685f8bf2/ | {S}thedefiant.io/news/defi/morpho-user-exploits-oracle-error-to-turn-usd350-into-usd230k | {S}www.bitget.com/news/detail/12560604270503 | {S}medium.com/coinmonks/decoding-morphoblues-230k-exploit-6296565ced40", ""),
"SASHAToken": ("O", 0, 0, "PoC only", "PoC is attributed to 'Shezmu Attacker 3'; the Shezmu post-mortems found (QuillAudits, BlockApex, Rekt) describe the Sept 2024 open-mint bug, not price manipulation, and may be a different incident (this entry is dated 2024-10-06).", f"{S}www.quillaudits.com/blog/hack-analysis/shezmu-exploit | {S}blockapex.io/shezmu-hack-analysis/ | {S}rekt.news/shezmu-rekt", "sources listed are for the Sept 2024 Shezmu incident, NOT confirmed to be this entry"),
"PestoToken": ("O", 0, 0, "PoC only", "No mechanism in the PoC (TenArmor tweet link only); no post-mortem found.", "", ""),
"HANAToken": ("O", 0, 0, "PoC only", "No mechanism in the PoC (TenArmor tweet link only); no post-mortem found.", "", ""),
"MINER": ("O", 0, 0, "PoC only", "No mechanism in the PoC (Phalcon tweet link only); no post-mortem found.", "", "README lists the loss in WBNB, PoC header in ETH"),
"PresaleV5": ("M", 0, 0, "PoC only (explicit root cause)", "PoC: presale buyWithEth priced from the slot0 of a V3 pool the flash-loaned attacker moves; presale contract (distinct) sells at the skewed price.", "", "provisional; no retrievable post-mortem (Defimon Telegram link only)"),
"StrategyLlamaLendConvex": ("A", 0, 0, "PoC only (explicit root cause)", "PoC root cause: permissionless strategy deposit/redeem accepts the realized withdrawal loss from the underlying Curve Lend vault; no price source is moved by the attacker.", "", "provisional; README heading says 'share price manipulation' but the PoC describes a loss-acceptance logic flaw"),
"GradientMakerPool": ("O", 0, 0, "PoC only", "README heading only; PoC states no mechanism; no post-mortem found.", "", ""),
"FixedTokenBSwap": ("M", 0, 0, "PoC only (explicit root cause)", "PoC: swap trusts getAmountsIn on a user-supplied path; attacker's fake token and fresh pair supply an expensive quote and the contract (distinct) pays RTV.", "", "provisional; attacker-controlled source (could also be read as a missing-validation A)"),
"AmpKashi": ("M", 0, 0, "PoC only (explicit description)", "PoC: flash-loaned WETH buys AMP through three pools; Kashi (distinct) values the inflated AMP collateral and issues a USDC borrow.", "", "provisional; no post-mortem found"),
"SBR Token": ("A", 0, 0, "PoC + catalog description only", "Catalog: skim() plus a broken token transfer zeroed a Uniswap V2 reserve and drained the WETH side; token logic bug, no consumed price moved.", f"{S}crypto.training/hacks/", "provisional"),
"Scorch": ("M", 0, 0, "PoC only (explicit description)", "PoC: Scorch.scorch() paid ETH off a live getAmountsOut quote of the OTC/WETH pool that the attacker inflated with a WETH to OTC swap.", "", "provisional; no post-mortem found"),
"Peapods Finance": ("M", 3, 1, "PoC + SolidityScan + 2 more", "Attacker moves the Uniswap V3 pool price, calls depositFromPairedLpToken with _slippageOverride = 999, the reward contract (distinct) swaps at the skewed price, then back-runs.", f"{S}blog.solidityscan.com/peapods-finance-hack-analysis-bdc5432107a5 | {S}thedefiant.io/news/defi/peapods-finance-token-slips-5-percent-on-reported-oracle-issue | {S}getfailsafe.com/peapods-finance-hack-200k-exploit-what-happened-and-and-how-to-stay-safe/", "SolidityScan frames it as a slippage front-run; same class as DRLVaultV3"),
}
SHEET = pd.read_csv(ROOT / "reports/a2_label_sheet.csv")
NAMEMAP = {"InverseFinance": "Inverse Finance", "Curve LlamaLend": "CurveLlamaLend"}
OLD = {  # already adjudicated: name -> (n_sources, n_strong, evidence, reason override)
    "Indexed Finance": (2, 0, "sheet '2-source' (excerpt-level only; both primary pages 403)", "Flash-swap re-index distorted the pool's own weights/balances, minted at the moved valuation in the same pool (same-contract tie-break); medium confidence."),
    "InverseFinance": (2, 2, "a2 sheet 2-source (BlockSec read in this project; Halborn, CertiK cited)", "Attacker's 27k WBTC swap moved the tricrypto2 balance-weighted LP price (979 to 2,831) read by Inverse Frontier's oracle; distinct market paid out."),
    "WiseLending": (0, 0, "adjudicated: no source for this incident", "No post-mortem found for the 2023-10-13 incident (web results are the Jan-2024 one)."),
    "CompoundUni": (0, 0, "PoC + stored note only; no independent post-mortem found in 4 searches", "UNI/WETH V3 price moved through a flash loan and read by UniswapAnchoredView; provisional, unverifiable."),
    "Makina": (3, 3, "adjudicated: Makina post-mortem, CertiK, Verichains", "Flash-loaned liquidity inflated the Curve MIM/3CRV calc_withdraw_one_coin valuation read by Caliber/Machine, which paid out via the DUSD pool."),
    "MEVBOTa47b": (1, 0, "a2 sheet 'single'", "MEV-bot exploit of a WETH/USDC pool; not a consumed-price manipulation."),
    "ResupplyFi": (2, 2, "a2 sheet 2-source (BlockSec, Halborn, QuillAudits read)", "Donation left totalSupply at 1 wei so the vault rate read by the pair's solvency check went to 0."),
    "DRLVaultV3": (1, 1, "adjudicated: Verichains only", "Flash-loaned buy moved a V3 pool quote the vault read for amountOutMinimum; vault swapped at the moved price."),
    "Curve LlamaLend": (2, 2, "a2 sheet 2-source (LlamaRisk post-mortem, Curve governance)", "Donation via stake() inflated sDOLA convertToAssets 1.189 to 1.353, read by the LlamaLend oracle."),
}
rows = []
for _, r in scr.iterrows():
    n = r["name"]; d = str(r["date"])
    key = n + "@" + d if n == "Circle" else n
    poc = POC.get(n + d)
    if n in OLD:
        sname = NAMEMAP.get(n, n)
        s = SHEET[SHEET.incident_id == sname].iloc[0]
        ns, nst, ev, reason = OLD[n]
        rows.append(dict(date=d, name=n, poc=poc, lost=r.lost, dhl_desc=r.desc, category=s.adjudicated_category, source_count=ns, strong_sources=nst,
                         evidence=ev, verified_M_2src=(s.adjudicated_category == "M" and ns >= 2), reason=reason, sources=s.sources, notes="reuses reports/a2_label_sheet.csv adjudicated_category", origin="a2_sheet"))
        continue
    cat, ns, nst, ev, reason, srcs, notes = L[key]
    rows.append(dict(date=d, name=n, poc=poc, lost=r.lost, dhl_desc=r.desc, category=cat, source_count=ns, strong_sources=nst, evidence=ev,
                     verified_M_2src=(cat == "M" and ns >= 2), reason=reason, sources=srcs, notes=notes, origin="this_pass"))
out = pd.DataFrame(rows).sort_values("date", ascending=False).reset_index(drop=True)
out.to_csv(ROOT / "reports/dhl_screen_labels.csv", index=False)
print(len(out), out.category.value_counts().to_dict())
m = out[out.category == "M"]
print("M:", len(m), "| 2-source-verified M:", int(m.verified_M_2src.sum()), "| of which >=1 strong:", int((m.verified_M_2src & (m.strong_sources >= 1)).sum()))
print("M list (verified):", list(m[m.verified_M_2src].name)); print("M provisional:", list(m[~m.verified_M_2src].name))
