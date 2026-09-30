"""CJSJ item 1 (A2): label sheet for the 24 current manipulations, DeFiHackLabs counts, A10 power rerun.

Labels are applied under reports/a2_label_protocol.md (M/R/A/K/O). They come from post-mortems / independent
analyses retrieved 2026-09-30 (see `source_access`), NOT from call-trace review: trace RPC is paid-tier
(reports/tracing_feasibility.md), so S/C addresses and the atomic flag are source-derived where marked.
`model_results_seen_before_label` = yes for all 24: the audit's error sets were known to the labeler.

Evidence tiers
  2-source       >=2 independent mechanism-level sources (protocol/auditor post-mortem + independent analysis)
  2-source-weak  >=2 sources but news-level only (no auditor/protocol write-up retrieved)
  single         one mechanism-level source (or PoC header only)  -> 'provisional', excluded from verified M
`VERIFIED_M` = category M AND tier '2-source' (the positive class used by later items).
Outputs: reports/a2_label_sheet.csv, reports/defihacklabs_index.csv, section in reports/cjsj_numbers.md.
"""
import csv, difflib, os, re, subprocess
from collections import Counter
from pathlib import Path
import numpy as np, pandas as pd
from cjsj_common import REPORTS, ROOT, TAG_CONFOUNDED, write_section
import a10_power_analysis as a10

LABELED_AT = "2026-09-30"
DHL = Path(os.environ.get("DEFIHACKLABS_DIR",
           "/private/tmp/claude-501/-Users-sanjayjillellamudi/d1383b8d-c9c6-4c1d-900f-92574fa52ea4/scratchpad/DeFiHackLabs"))

# (incident, T_tx, S, C, category, subflags, atomic, tier, confidence, source_access, sources, notes)
L = [
 ("Harvest Finance", "0x35f8d2f572fceaac9288e5d462117850ef2694786992a8c3f6d02612277b0877",
  "Curve Y pool 0x45F783CCE6B7FF23B2ab2D70e416cdb7D6055f51 (yUSDC/yUSDT ratio)", "Harvest fUSDC vault 0xf0358e8c3CD5Fa238a29301d0bEa3D63A17bEdBE (share price from Curve Y)",
  "M", "share_price", "per-cycle atomic; campaign multi-tx", "2-source", "high", "search-snippet",
  ["https://slowmist.medium.com/slow-mist-analysis-of-harvest-finances-hacked-event-63450b49e6a5", "https://rekt.news/harvest-finance-rekt", "https://blockapex.io/harvest-finance-hack-analysis-poc/"],
  "Repeated ~7 min campaign (many txs); T_tx is first tx in block 11129474 (receipt-verified)."),
 ("Cream Finance", "0x0fe2542079644e107cbf13690eb9c2c65963ccb79089ff96bfaf8dced2331c92",
  "yUSD vault 0x4B5BfD52124784745c1071dcB244C6688d2533d3 (pricePerShare, inflated by direct yToken transfer)", "Cream crYUSD market, Comptroller 0x3d5BC3c8d13dcB8bF317092d84783c2697AE9258",
  "M", "donation;share_price", "Y", "2-source", "high", "search-snippet",
  ["https://immunefi.com/blog/bug-fix-reviews/hack-analysis-cream-finance-oct-2021/", "https://inspexco.medium.com/cream-finances-incident-analysis-yusd-share-price-manipulation-ebd55c56d8eb", "https://www.halborn.com/blog/post/explained-the-cream-finance-hack-october-2021"],
  "Four sources agree on mechanism; second tx by another address also exists (Inspex)."),
 ("Indexed Finance", "0x44aad3b853866468161735496a5d9cc961ce5aa872924c5d78673076b1cd95aa",
  "DEFI5/CC10 pool weights and balances (own pool math)", "same pools (mint/burn against manipulated weights)",
  "A", "own_pool_math", "Y", "2-source", "medium", "search-snippet",
  ["https://ndxfi.medium.com/indexed-attack-post-mortem-b006094f0bdc", "https://blocksecteam.medium.com/the-analysis-of-indexed-finance-security-incident-8a62b9799836"],
  "Provisional M -> A: per snippets, weights were manipulated by adding SUSHI and minting against the same pool (same-contract tie-break). Medium.com pages returned 403, so this rests on search summaries; a distinct external price reader was not found. Re-check with call trace."),
 ("Inverse Finance", "0x958236266991bc3fe3b77feaacea120f172c0708ad01c7a715b255f218f9313c",
  "Curve tricrypto2 0xD51a44d3FaE010294C616388b506AcdA1bfAAE46 (spot moved by 27k WBTC swap; feeds yvcrv3crypto price)", "Inverse Frontier market anYvCrv3CryptoInverse 0x1429a930ec3bcf5Aa32EF298ccc5aB09836EF587 (oracle read)",
  "M", "atomic;twap_oracle", "Y", "2-source", "high", "search-snippet",
  ["https://blocksec.com/blog/our-take-on-the-inverse-finance-security-incident-price-manipulation-attack", "https://www.halborn.com/blog/post/explained-the-inverse-finance-hack-june-2022", "https://github.com/yuichiroaoki/inverse-finance-exploit"],
  "T_tx located by matching Frontier Comptroller logs in block 14972419 (receipt scan); hash not in prior project files."),
 ("UwU Lend", "0x242a0fb4fde9de0dc2fd42e8db743cbc197ffa2bf6a036ba0bba303df296408b",
  "Curve pools (get_p spot) feeding UwU's USDe/sUSDe median oracle", "UwU Lend pool 0x2409af0251dcb89ee3dee572629291f9b087c668",
  "M", "atomic;multi_source_median", "Y", "2-source", "high", "search-snippet",
  ["https://slowmist.medium.com/analysis-of-the-uwu-lend-hack-9502b2c06dbe", "https://www.quillaudits.com/blog/hack-analysis/uwu-lend-hack", "https://rekt.news/uwulend-rekt"],
  "5 of 11 oracle sources were manipulable Curve spot prices."),
 ("MonoX Finance", "0x9f14d093a2349de08f02fc0fb018dadb449351d0cdb7d0738ff69cc6fef5f299",
  "Monoswap vCash/price state for MONO (0xC36a7887786389405EA8DA0B87602Ae3902B88A1)", "same contract (swap with tokenIn == tokenOut overwrote price update)",
  "A", "same_token_swap", "Y", "2-source", "high", "search-snippet",
  ["https://medium.com/monoswap/exploit-post-mortem-33921a779b43", "https://slowmist.medium.com/detailed-analysis-of-the-31-million-monox-protocol-hack-574d8c44a9c8", "https://immunebytes.com/blog/monox-hack-incident-nov-30-2021-detailed-analysis/"],
  "Resolves the boundary case: own-AMM validation bug, S and consumer are the same contract -> A by tie-break."),
 ("MEVBOTa47b", "0x35ecf595864400696853c53edf3e3d60096639b6071cadea6076c9c6ceb921c1",
  "n/a", "MEV bot 0x00000000000A47b1298f18Cf67de547bbE0D723F (unverified contract)",
  "K", "mev_bot", "Y", "single", "medium", "not-retrieved (tweets from PoC header)",
  ["https://twitter.com/BlockSecTeam/status/1580779311862190080", "https://twitter.com/AnciliaInc/status/1580705036400611328"],
  "Two tweets are cited in the DeFiHackLabs header; x.com/twitter fetch not possible here, so counted single."),
 ("Conic Finance 02", "0x37acd17a80a5f95728459bfea85cb2e1f64b4c75cf4a4c8dcb61964e26860882",
  "Curve crvUSD/USDC pool 0x4DEcE678ceceb27446b35C672dC7d61F30bAD69E balances", "Conic crvUSD omnipool (deposit/withdraw valued off Curve pool state)",
  "O", "sandwich;mev_arbitrage", "Y(per tx)", "2-source-weak", "low", "fetched (CertiK, Halborn); Conic post-mortem 403",
  ["https://www.certik.com/skynet-report/5FZAakbsUVg1EyHLNw9Qnm-conic-finance-incident-analysis", "https://www.halborn.com/blog/post/explained-the-conic-finance-hack-july-2023", "https://medium.com/@ConicFinance/post-mortem-eth-and-crvusd-omnipool-exploits-c9c7fa213a3d"],
  "CORRECTS provisional table: this tx (~$934K) is the crvUSD-omnipool exploit, described by CertiK as a swap/deposit/swap/withdraw sandwich cycle on pools left imbalanced by the earlier ETH-omnipool read-only-reentrancy exploit; it is NOT the read-only reentrancy. M1-M4 arguably hold but no source characterizes the read path -> O until traced."),
 ("ZunamiProtocol", "0x0788ba222970c7c68a738b0e08fb197e669e61f9b226ceec4cab9b85abe8cceb",
  "Curve/Sushi pool balances (UZD/crvFRAX 0x68934F60758243eafAf4D2cFeD27BF8010bede3a) donated to skew", "Zunami UZD 0xb40b6608B2743E691C9B54DdBDEe7bf03cd79f1c (cacheAssetPrice)",
  "M", "donation;atomic", "Y", "2-source", "high", "search-snippet",
  ["https://www.certik.com/blog/zunami-protocol-incident-analysis", "https://www.halborn.com/blog/post/explained-the-zunami-protocol-hack-august-2023", "https://neptunemutual.com/blog/how-was-the-zunami-protocol-exploited/"],
  "CertiK: 'price manipulation caused by donations that incorrectly calculate the price'."),
 ("CompoundUni", "0xaee0f8d1235584a3212f233b655f87b89f22f1d4890782447c4ef742b37af58d",
  "UNI/WETH Uniswap V3 pool 0x1d42064Fc4Beb5F8aAF85F4617AE8b3b5B8Bd801", "Compound UniswapAnchoredView 0x50ce56A3239671Ab62f185704Caedf626352741e",
  "M", "atomic;twap", "Y", "single", "medium", "not-retrieved (PoC header + one tweet; 4 searches found no write-up)",
  ["https://x.com/0xLEVI104/status/1762092203894276481"],
  "Mechanism taken from PoC and stored note; no independent post-mortem found -> provisional."),
 ("CurveLlamaLend", "0xb93506af8f1a39f6a31e2d34f5f6a262c2799fef6e338640f42ab8737ed3d8a4",
  "sDOLA vault convertToAssets() (DolaSavings 0xE5f24791E273Cb96A1f8E5B67Bc2397F0AD9B8B4), 1.189->1.353 by donation via stake()", "LlamaLend CryptoFromPoolVaultWAgg oracle 0x88822eE517Bfe9A1b97bf200b0b6D3F356488fF2 (unsmoothed vault-rate read)",
  "M", "donation;atomic;share_price", "Y", "2-source", "high", "fetched (LlamaRisk); search-snippet (Curve gov)",
  ["https://www.llamarisk.com/research/llamalend-sdola-long2-post-mortem", "https://gov.curve.finance/t/llamalend-sdola-long2-post-mortem/11020"],
  "LlamaRisk and Curve governance post-mortem are separate authors; both agree. Net attacker profit ~$245K."),
 ("ResupplyFi", "0xffbbd492e0605a8bb6d490c3cd879e87ff60862b0684160d08fd5711e7a872d3",
  "cvcrvUSD vault (0x89707721927d7aaeeee513797A8d6cBbD0e08f41) exchange-rate after 2,002 crvUSD donation", "Resupply pair 0x6e90c85a495d54c6d7E1f3400FEF1f6e59f86bd6 (exchangeRate solvency check)",
  "M", "donation;math_enabled;atomic", "Y", "2-source", "medium", "search-snippet",
  ["https://www.halborn.com/blog/post/explained-the-resupply-hack-june-2025", "https://ackee.xyz/blog/resupply-hack-analysis/", "https://rekt.news/resupplyfi-rekt"],
  "Donation inflates vault price, then integer division floors exchangeRate to 0 in the consumer's math: math_enabled sub-flag (pre-registered sensitivity)."),
 ("BalancerV2", "0x6ed07db1a9fe5c0794d44cd36081d6a6df103fab868cdd75d581e3bd23bc9742",
  "osETH/wETH ComposableStablePool 0xDACf5Fa19b1f720111609043ac67A9818262850c invariant/BPT price", "same pool (batchSwap in constructor, 65+ micro-swaps)",
  "R", "rounding;atomic", "Y", "2-source", "high", "search-snippet",
  ["https://www.openzeppelin.com/news/understanding-the-balancer-v2-exploit", "https://research.checkpoint.com/2025/how-an-attacker-drained-128m-from-balancer-through-rounding-error-exploitation/", "https://blocksec.com/blog/in-depth-analysis-the-balancer-v2-exploit"],
  "Pool's own _upscaleArray rounding; no distinct consumer of the suppressed BPT price identified."),
 ("Makina", "0x569733b8016ef9418f0b6bde8c14224d9e759e79301499908ecbcd956a0651f5",
  "Curve DUSD/USDC pool 0x32e616f4f17d43f9a5cd9be0e294727187064cb3 (calc_withdraw_one_coin spot)", "Makina Caliber 0xD1A1C248B253f1fc60eACd90777B9A63F8c8c1BC / Machine 0x6b006870C83b1Cd49E766Ac9209f8d68763Df721 (AUM/sharePrice)",
  "M", "atomic;flash_loan_280M", "Y", "2-source", "high", "search-snippet",
  ["https://www.certik.com/blog/makina-incident-analysis", "https://blog.verichains.io/p/analyzing-the-4m-makina-finance-exploit", "https://makinafi.substack.com/p/post-mortem-january-20th-2026-incident"],
  "Tx was front-run by an MEV builder; T_tx is the tx used by the dataset."),
 ("TOPBPool", "0x967aa34c69b7775c718545c7f94d92e965eb5fc553c0f27f6f1a9c65c93ac156",
  "n/a (no price read)", "Aragon voting/TokenManager (no timelock) then Balancer V1 BPool 0x0fa3e014fa2e751f78e53dca766fac2223327329",
  "K", "governance_takeover;mint_and_dump", "Y", "2-source-weak", "high", "fetched (crypto.news); search-snippet (BeInCrypto, CryptoTimes)",
  ["https://crypto.news/token-of-power-exploit-drains-1-58m-from-balancer-pool/", "https://beincrypto.com/millions-vanish-tiny-tokens-governance-top/", "https://www.cryptotimes.io/2026/06/10/one-vote-1-58m-gone-top-token-hit-by-alleged-governance-attack/"],
  "Governance takeover (8,192 TOP > 50% of snapshot supply, vote+execute in one tx, mint 10B TOP, dump into BPool). Blockaid/PeckShield/Cyvers named by crypto.news. Provisional 'A' -> K (permission/governance exploit)."),
 ("WiseLending", "0x7ac4a98599596adbf12fffa2bd23e2a2d2ac7e8989b6ea043fcc412a29126555",
  "unknown", "WiseLending pool 0x84524baa1951247b3a2617a843e6ece915bb9674",
  "O", "", "unknown", "single", "low", "not-retrieved (PoC header tweets)",
  ["https://twitter.com/bbbb/status/1712841315522638034", "https://twitter.com/BlockSecTeam/status/1712871304993689709"],
  "All web coverage found (Cointelegraph, SolidityScan, etc.) is the Jan-2024 WiseLending exploit (Pendle LP donation), a different incident. Nothing retrieved for the 2023-10-13 tx by a whitehat MEV searcher, so the provisional 'A' is unsupported -> O."),
 ("BalancerV1BPool", "0x72510b257cc09bde8435b83ac1636f9498ffc353583330600b5b8da43d0d1aff",
  "BPool 0x2257aaac34bcb27900291f7b84ee2565a6cbac57 join math", "same pool (joinswapPoolAmountOut mints BPT for 1 satoshi)",
  "R", "rounding;flash_loan", "Y", "2-source-weak", "high", "search-snippet",
  ["https://news.bitcoin.com/crypto-news/balancer-v1-pool-exploit-234k-rounding-bug/", "https://blockfence.io/balancer-v1-pool-exploited-for-234k-through-rounding-bug/", "https://www.cryptotimes.io/2026/08/31/balancer-v1-exploit-hits-unmaintained-code-as-forks-remain-exposed/"],
  "SlowMist quoted (missing min effective input/min balance); PoC header root cause consistent. No price consumer."),
 ("AjnaFinance", "0x12dfde527ef62882bfabb64362c9ae0e6bfb628363bd298d0d0956c9a114e4f5",
  "n/a (oracle-free; internal auction/bucket price)", "Ajna ERC20Pool 0xad24FC773e125Edb223C38a39657cB64bc7C178e (bucketTake/removeCollateral/settle)",
  "A", "liquidation_accounting", "Y", "2-source-weak", "high", "fetched (CryptoTimes); search-snippet (CryptoTicker, Bitget)",
  ["https://www.cryptotimes.io/2026/08/29/ajna-v2-loses-775k-on-ethereum-after-attacker-exploits-liquidation-math/", "https://cryptoticker.io/en/ajna-defi-lending-exploit-immutable-contract/", "https://www.bitget.com/news/detail/12560605753354"],
  "Resolves 'O': 'The drain did not require a fake Chainlink or Pyth price'; attacker controlled both sides of an internal liquidation."),
 ("BalancerBoostedPool2023", "0x2a027c8b915c3737942f512fc5d26fd15752d0332353b3059de771a35a606c2d",
  "bb-a-USDC Linear Pool 0x9210F1204b5a24742Eba12f710636D76240dF3d0 (cached token rate)", "Balancer boosted pool (reads linear pool rate)",
  "M", "math_enabled;atomic;flash_swap", "Y", "2-source", "medium", "search-snippet",
  ["https://blocksec.com/blog/tiny-rounding-down-big-fund-losses-an-in-depth-analysis-of-the-recent-balancer-incident", "https://slowmist.medium.com/review-and-recommendations-of-balancer-incident-d2b31b5bd863", "https://medium.com/immunefi/balancer-rounding-error-bugfix-review-cbf69482ee3d"],
  "BlockSec: 'price manipulation caused by rounding down ... improperly affects the cached token rate used by the boosted pool' -> distinct consumer exists; M with math_enabled sub-flag (boundary case)."),
 ("DRLVaultV3", "0xe3eab35b288c086afa9b86a97ab93c7bb61d21b1951a156d2a8f6f5d5715c475",
  "Uniswap V3 USDC-WETH pool spot price", "DRLVaultV3 0x6A06707ab339BEE00C6663db17DdB422301ff5e8 swapToWETH (amountOutMinimum from current pool quote)",
  "M", "atomic;spot_price;flash_loan_14M", "Y", "single", "high", "fetched (Verichains); Nominis monthly report mentions only",
  ["https://blog.verichains.io/p/the-drlvaultv3-exploit-a-slippage"],
  "Mechanism is clear and matches M1-M4 but only one mechanism-level source found (Nominis is a one-line incident-list mention) -> provisional."),
 ("EFLeverVault", "0x160c5950a01b88953648ba90ec0a29b0c5383e055d35a7835d905c53a3dda01e",
  "n/a", "EFLeverVault 0xe39fd820B58f83205Db1D9225f28105971c3D309 (flash-loan callback did not check initiator)",
  "A", "access_control;flash_loan_callback", "Y", "2-source-weak", "high", "search-snippet",
  ["https://www.web3isgoinggreat.com/?id=earningfarm-exploited-for-971000", "https://crypto.news/287000-reportedly-stolen-in-hack-targeting-aaves-earning-farm/"],
  "Resolves 'verify mechanism': missing check that the flash loan was initiated by the protocol (Daniel Von Fange per crypto.news); ~748 ETH, 480 ETH taken by a front-running MEV bot. Not a price manipulation."),
 ("SecuredFi", "0xcd6159860783d8d481cc4bf4dceddc88acdca6bb08f6445525b2904cfd75b1da",
  "Secured Finance order book getMarketUnitPrice() (same-block self-trade to par)", "Secured Finance TokenVault 0xb74749b2213916b1da3b869e41c7c57f1db69393 (collateral valuation)",
  "M", "atomic;self_trade;flash_loan", "Y", "single", "medium", "not-retrieved (PoC header + crypto.training aggregator, which mirrors the PoC)",
  ["https://crypto.training/hacks/"],
  "No independent post-mortem found (two searches) -> provisional. Mechanism (distinct consumer reads manipulated price) matches M1-M4 per PoC."),
 ("ThetanutsIndexVault", "0xbba9f138fe39503bfd1aa62932dbd6ab35d37d23d48e4b7bf2988a9d5dc39fec",
  "n/a", "Thetanuts legacy TN-IDX-USDC-PUT vault 0xC2C3AE0a7b405058558C9b4a63b373486CB86Ac7 (mint() integer-division floor)",
  "A", "rounding;share_accounting", "Y", "2-source", "high", "fetched (DarkNavy); search-snippet (SlowMist, PeckShield via Cryptopolitan)",
  ["https://www.darknavy.org/web3/exploits/thetanuts-legacy-index-vault-zero-cost-remint/", "https://www.cryptopolitan.com/hack-deprecated-thetanuts-vault/"],
  "DarkNavy: 'No price oracles are involved. Purely a logic error involving integer rounding in share calculations.'"),
 ("USM", "0xfae5e751b8ce01457cbb6b529839f24a0cff50faaabcbd0fd02ca0cf559b050e",
  "n/a", "USM 0x2a7FFf44C19f39468064ab5e5c304De01D591675 defund() (mean-price non-split-invariance)",
  "R", "rounding;redemption_curve;flash_loan", "Y", "single", "medium", "fetched (Nominis monthly report); crypto.training mirrors PoC",
  ["https://www.nominis.io/insights/nominis-monthly-report"],
  "Nominis report matches the PoC description; no protocol statement ('USM has not issued a public statement'). Single independent source -> provisional."),
]
COLS = ["incident_id", "T_block", "T_tx", "S", "C", "category", "subflags", "atomic", "evidence_tier", "confidence",
        "source_access", "sources", "notes", "labeler", "labeled_at", "model_results_seen_before_label",
        "provisional_category_a2_protocol_5"]
PROV = {"Harvest Finance": "M", "Cream Finance": "M", "Inverse Finance": "M", "UwU Lend": "M", "Conic Finance 02": "M",
        "ZunamiProtocol": "M", "CompoundUni": "M", "CurveLlamaLend": "M", "ResupplyFi": "M", "Makina": "M",
        "SecuredFi": "M", "Indexed Finance": "M?", "DRLVaultV3": "M?", "BalancerBoostedPool2023": "boundary",
        "MonoX Finance": "boundary", "BalancerV2": "R", "BalancerV1BPool": "R", "USM": "R", "TOPBPool": "A",
        "WiseLending": "A", "EFLeverVault": "A", "ThetanutsIndexVault": "A", "MEVBOTa47b": "K", "AjnaFinance": "O"}
STRICT_EXCLUDE = ("math_enabled",)


def build_sheet():
    df = pd.read_parquet(ROOT / "data/processed/features.parquet")
    blk = df[df.label == "manipulation"].set_index("incident")["block"].to_dict()
    rows = []
    for (inc, tx, S, C, cat, flags, atomic, tier, conf, acc, srcs, note) in L:
        rows.append(dict(incident_id=inc, T_block=blk[inc], T_tx=tx, S=S, C=C, category=cat, subflags=flags, atomic=atomic,
                         evidence_tier=tier, confidence=conf, source_access=acc, sources=" | ".join(srcs), notes=note,
                         labeler="claude (single labeler; A9 blind second labeler still required)", labeled_at=LABELED_AT,
                         model_results_seen_before_label="yes (audit error sets known)",
                         provisional_category_a2_protocol_5=PROV[inc]))
    sheet = pd.DataFrame(rows, columns=COLS)
    assert len(sheet) == 24 and set(sheet.incident_id) == set(blk)
    sheet["verified_M"] = (sheet.category == "M") & (sheet.evidence_tier == "2-source")
    sheet["verified_M_strict"] = sheet.verified_M & ~sheet.subflags.str.contains("math_enabled")
    sheet.to_csv(REPORTS / "a2_label_sheet.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    return sheet


# ---------------- DeFiHackLabs index ----------------
CAT_RULES = [  # ordered; first match wins. Keyword heuristic on the README heading, NOT an A2 label.
    ("price/oracle/rate manipulation", r"price manip|oracle|spot price|twap|slot0|exchange.?rate|share price|donat|inflat|get_?p\b|virtual.?price|price feed|stale.*price|mid-price"),
    ("reentrancy", r"reentran"),
    ("access control / missing check", r"access control|permission|unauthori|missing .*(check|auth|valid|verif)|arbitrary|unprotected|initializ|signature|replay|approval|caller|authoriz|delegatecall|forwarder|bypass"),
    ("rounding / precision / math", r"round|precision|overflow|underflow|unsafe math|truncat|integer|arithmetic|math"),
    ("governance / key / rugpull", r"governance|rug|private key|compromis|phish|backdoor|insider|admin|owner|dao "),
]


def categorize(text):
    t = text.lower()
    for name, pat in CAT_RULES:
        if re.search(pat, t):
            return name
    return "logic / other"


def chain_of(sol):
    m = re.search(r'createSelectFork\(\s*"([A-Za-z0-9_]+)"', sol) or re.search(r'createSelectFork\(\s*([A-Za-z_]+)', sol)
    return m.group(1) if m else "unknown"


def _norm(x):
    return re.sub(r"[^a-z0-9]", "", x.lower())


def parse_dhl():
    """One row per README heading `### YYYYMMDD <name> - <description>` (README.md + past/*/README.md)."""
    heads = []
    for f in [DHL / "README.md"] + sorted((DHL / "past").glob("*/README.md")):
        lines = f.read_text(errors="ignore").splitlines()
        for i, l in enumerate(lines):
            m = re.match(r"^### (\d{8})[ -]+(.*)$", l.strip())
            if not m:
                continue
            rest = m.group(2)
            parts = re.split(r"\s+[-\u2013]\s+|---", rest, maxsplit=1)
            lost = next((x[len("### Lost:"):].strip() for x in lines[i + 1:i + 4] if x.startswith("### Lost:")), "")
            heads.append(dict(date=m.group(1), name=parts[0].strip(), desc=(parts[1] if len(parts) > 1 else "").strip(), lost=lost))
    h = pd.DataFrame(heads).drop_duplicates(["date", "name"]).reset_index(drop=True)
    by_name = {}
    for p in (DHL / "src/test").glob("*/*.sol"):
        if re.match(r"\d{4}-\d{2}$", p.parent.name):
            by_name.setdefault(_norm(p.stem.replace("_exp", "")), []).append(p)
    import difflib
    def near_months(ym):
        y, m = int(ym[:4]), int(ym[5:])
        return {f"{yy}-{mm:02d}" for yy, mm in [(y, m), (y + (m == 12), m % 12 + 1), (y - (m == 1), (m - 2) % 12 + 1)]}
    chains = []
    for _, r in h.iterrows():
        ym = f"{r.date[:4]}-{r.date[4:6]}"
        cands = sorted(by_name.get(_norm(r["name"]), []), key=lambda p: (p.parent.name != ym, p.parent.name))
        if not cands:  # fuzzy: closest PoC filename within +-1 month
            pool = {k: v for k, v in by_name.items() if any(p.parent.name in near_months(ym) for p in v)}
            best = difflib.get_close_matches(_norm(r["name"]), list(pool), n=1, cutoff=0.75)
            cands = pool[best[0]] if best else []
        c = chain_of(cands[0].read_text(errors="ignore")) if cands else "unmatched"
        chains.append({"BSC_ARCHIVE_RPC": "bsc", "vm": "unknown"}.get(c, c))
    h["chain"] = chains
    h["year"] = h.date.str[:4].astype(int)
    h["category"] = (h["name"] + " - " + h["desc"]).map(categorize)
    return h


def main():
    sheet = build_sheet()
    out = []
    P = lambda s="": out.append(s)
    tier = sheet.evidence_tier.value_counts().to_dict()
    P("### 1a. A2 label sheet (24 current manipulations) -> `reports/a2_label_sheet.csv`")
    P("")
    P("Labels are from retrieved post-mortems, not call traces (trace RPC is paid-tier). Single labeler, model results seen: A9 blind second labeler is still required. `provisional_category_a2_protocol_5` keeps the old table for comparison.")
    P("")
    P("| Incident | Provisional (protocol §5) | A2 category | Tier | Subflags | Atomic | Conf |")
    P("|---|---|---|---|---|---|---|")
    for _, r in sheet.iterrows():
        P(f"| {r.incident_id} | {r.provisional_category_a2_protocol_5} | **{r.category}** | {r.evidence_tier} | {r.subflags or '-'} | {r.atomic} | {r.confidence} |")
    P("")
    cc = sheet.category.value_counts().to_dict()
    P(f"- Category counts (n=24): {', '.join(f'{k}={v}' for k, v in sorted(cc.items()))}  [cjsj_01_a2_labels.py]")
    P(f"- Evidence tiers: {', '.join(f'{k}={v}' for k, v in tier.items())}")
    n_m = int((sheet.category == "M").sum()); n_vm = int(sheet.verified_M.sum()); n_vs = int(sheet.verified_M_strict.sum())
    P(f"- **M total (any tier) = {n_m}; verified M (M and 2-source) = {n_vm}; verified M excluding `math_enabled` = {n_vs}**. "
      f"Old audit positive class: 24; protocol §5 provisional M: 11 to 15.")
    P(f"- Verified M: {', '.join(sheet[sheet.verified_M].incident_id)}")
    P(f"- Provisional M (single source, excluded from verified): {', '.join(sheet[(sheet.category == 'M') & ~sheet.verified_M].incident_id)}")
    changed = sheet[sheet.category.map(lambda c: c) != sheet.provisional_category_a2_protocol_5.replace({'M?': 'M'})]
    P("- Changes vs protocol §5 provisional table (labeler's own earlier read): " + "; ".join(
        f"{r.incident_id}: {r.provisional_category_a2_protocol_5} -> {r.category}" for _, r in changed.iterrows()))
    P("")
    P("Labels that overturn earlier notes (flag for review): **Conic Finance 02** is the crvUSD-omnipool sandwich, not the read-only reentrancy; **TOPBPool** is a governance takeover; **Ajna** and **EFLeverVault** are resolved as non-price bugs; **WiseLending (2023-10)** has no retrievable source (web results are for the Jan-2024 incident); **Indexed Finance** moved to A on snippet-level evidence (medium confidence).")
    P("")

    # ---- DeFiHackLabs counts ----
    h = parse_dhl()
    h.to_csv(REPORTS / "defihacklabs_index.csv", index=False)
    commit = subprocess.run(["git", "-C", str(DHL), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    P(f"### 1b. DeFiHackLabs incident counts (repo commit `{commit}`, parsed from README headings; `reports/defihacklabs_index.csv`)")
    P("")
    P(f"- Parsed incidents: {len(h)}  (README banner says 875); chain matched from PoC `createSelectFork` for {(h.chain != 'unmatched').sum()}, unmatched {(h.chain == 'unmatched').sum()}.  [cjsj_01_a2_labels.py]")
    ch = h.chain.value_counts()
    P("- By chain: " + ", ".join(f"{k}={v}" for k, v in ch.items()))
    P("- Chain counts are lower bounds per chain: incidents whose PoC file could not be matched to a README heading stay `unmatched` and are excluded from the Ethereum columns below.")
    P("- By year: " + ", ".join(f"{k}={v}" for k, v in h.year.value_counts().sort_index().items()))
    P("- By category (**keyword heuristic on the heading, not A2 labels**): " + ", ".join(f"{k}={v}" for k, v in h.category.value_counts().items()))
    P("")
    P("| Year | Ethereum (mainnet) all | Ethereum price/oracle/rate-like | All chains price/oracle/rate-like |")
    P("|---|---|---|---|")
    pl = h.category == "price/oracle/rate manipulation"; eth = h.chain == "mainnet"
    for y in sorted(h.year.unique()):
        P(f"| {y} | {int(((h.year == y) & eth).sum())} | {int(((h.year == y) & eth & pl).sum())} | {int(((h.year == y) & pl).sum())} |")
    n_eth_pl = int((eth & pl).sum()); n_all_pl = int(pl.sum())
    P(f"| **total** | {int(eth.sum())} | {n_eth_pl} | {n_all_pl} |")
    P("")
    # heuristic calibration on our 24: does the keyword flag predict A2 M?
    dts = pd.read_parquet(ROOT / "data/processed/features.parquet").set_index("incident")["date"].to_dict()
    flag = []
    for inc in sheet.incident_id:
        d0 = pd.Timestamp(dts[inc])
        near = h[(pd.to_datetime(h.date, format="%Y%m%d") - d0).abs() <= pd.Timedelta(days=4)]
        sc = near["name"].map(lambda n: difflib.SequenceMatcher(None, _norm(n), _norm(inc)).ratio())
        flag.append(near.loc[sc.idxmax()].category if len(near) and sc.max() >= 0.5 else "unmatched")
    sheet["kw_cat"] = flag
    matched = sheet[sheet.kw_cat != "unmatched"]
    kwp = matched.kw_cat == "price/oracle/rate manipulation"
    tp = int((kwp & (matched.category == "M")).sum()); fp = int((kwp & (matched.category != "M")).sum()); fn = int((~kwp & (matched.category == "M")).sum())
    P(f"- Keyword flag vs A2 label on our {len(matched)} matched attacks (names matched to README headings, best-effort): flagged & M = {tp}, flagged & not-M = {fp}, M not flagged = {fn}. "
      f"Precision of the flag for M is {tp}/{tp + fp} = {tp / max(tp + fp, 1):.2f} (n tiny; treat as a rough guide only).")
    prec = tp / max(tp + fp, 1)
    exp_m = n_eth_pl * prec
    P(f"- Expected verified-M-like Ethereum incidents available in DeFiHackLabs at that precision: {n_eth_pl} x {prec:.2f} = **~{exp_m:.0f}** (before requiring a second source, which currently cuts M by {n_m}->{n_vm}), i.e. roughly {exp_m * n_vm / max(n_m, 1):.0f}.")
    P("")

    # ---- A10 rerun ----
    P("### 1c. A10 power analysis rerun with the verified counts (`a10_power_analysis.py` functions; N_NEG=138)")
    P("")
    P("| Positive set | n_pos | Null SE | MDE AUC (single test) | MDE AUC (Holm m=4) | Wilson 95% CI at 85% recall* |")
    P("|---|---|---|---|---|---|")
    for lab, n in [("audit: all 24 (old)", 24), ("A2 M, any tier", n_m), ("verified M", n_vm), ("verified M, no math_enabled", n_vs)]:
        k = int(round(0.85 * n)); lo, hi = a10.wilson(k, n)
        P(f"| {lab} | {n} | {a10.se_null(n, 138):.3f} | {a10.auc_mde(n, 138):.3f} | {a10.auc_mde(n, 138, 0.05 / 4):.3f} | {k}/{n}: [{lo:.2f}, {hi:.2f}] |")
    P("")
    P("*recall of 85% assumed only to size the interval; not a result.")
    P("")
    P("Positives needed (alpha .05 one-sided, power .80) to detect a true AUC vs 0.5, by negative:positive ratio:")
    P("")
    P("| Target AUC | ratio 1 | ratio 2 | ratio 5.75 (current 138:24) | ratio 15.3 (138:9) |")
    P("|---|---|---|---|---|")
    for t in (0.70, 0.75, 0.80, 0.85):
        P(f"| {t:.2f} | " + " | ".join(str(a10.n_pos_for_auc(t, r)) for r in (1, 2, 5.75, 15.3)) + " |")
    P("")
    P("Triggered anomalies A0 must produce to obtain n_pos verified attacks, by attack prevalence among triggered anomalies:")
    P("")
    P("| Prevalence | n_pos=30 | n_pos=50 | n_pos=80 |")
    P("|---|---|---|---|")
    for prev in (0.30, 0.15, 0.05, 0.02):
        P(f"| {prev:.2f} | " + " | ".join(str(int(np.ceil(k / prev))) for k in (30, 50, 80)) + " |")
    P("")
    P(f"Bottom line: the verified positive class is n={n_vm} ({n_vs} without `math_enabled`), not 24. At n={n_vm} the smallest true AUC "
      f"detectable vs chance is {a10.auc_mde(n_vm, 138):.2f} (single test), i.e. only a true AUC of about that size or larger can be told apart from chance with 80% power. "
      f"DeFiHackLabs, at the heuristic precision above, offers on the order of {exp_m * n_vm / max(n_m, 1):.0f} more verified-M-like Ethereum incidents, "
      f"so reaching n_pos=30 needs multi-chain data (C6) or a looser class.")
    body = "\n".join(out)
    print(body)
    write_section("cjsj_01_a2_labels.py", "1", "A2 labels, DeFiHackLabs counts, A10 rerun", TAG_CONFOUNDED, body)


if __name__ == "__main__":
    main()
