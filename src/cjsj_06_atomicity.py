"""CJSJ item 6 (B8): classify each of the 24 attacks as single-tx or multi-block from transaction receipts and same-sender history.

For each attack tx (reports/a2_label_sheet.csv `T_tx`):
  1. receipt + tx: status, sender (EOA), target (tx.to, or the created contract for a deployment), log count, gas.
  2. Flash-loan funding inside the receipt (event topics): Aave V2, Aave V3, Balancer Vault, Uniswap V3 Flash, Maker DSS Flash, dYdX
     LogOperation. Uniswap V2 flash swaps and bespoke lenders are NOT detected (limitation).
  3. Same-sender scan of blocks [T-W, T+W] (eth_getBlockByNumber, full txs, filtered to tx.from == sender), then receipts for the
     matches. 'Same-target' txs = other txs by that sender to the same target (or, for deployments, other deployments).
Class (W=100 blocks, about 20 min; W=20 as sensitivity):
  single-tx          : no other successful same-target tx by the sender in the window
  multi-tx same block: others exist, all in block T
  multi-block        : at least one other successful same-target tx in another block
Limits: a different sender (multi-EOA campaigns, MEV front-runners such as Makina/EFLeverVault) is invisible; a campaign longer than the
window (Ajna: 7 pools over ~2 days) is under-detected, so multi-block here is a lower bound; 'single-tx' means the dataset tx is
self-contained for this sender within the window, not that the manipulated price cannot persist afterwards.
"""
import json, time
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from web3 import Web3
from cjsj_common import ROOT, TAG_CONFOUNDED, rpc, write_section, _env
import requests

W = 100; W_SMALL = 20
CACHE = ROOT / "data" / "raw" / "atomicity_cache"
K = lambda s: "0x" + Web3.keccak(text=s).hex().removeprefix("0x")
FLASH = {
    K("FlashLoan(address,address,address,uint256,uint256,uint16)"): "Aave V2",
    K("FlashLoan(address,address,address,uint256,uint8,uint256,uint16)"): "Aave V3",
    K("FlashLoan(address,address,uint256,uint256)"): "Balancer/Maker",
    K("Flash(address,address,uint256,uint256,uint256,uint256)"): "Uniswap V3",
    K("LogOperation(address)"): "dYdX Solo",
}


def sender_txs(block, sender):
    """Txs in `block` sent by `sender` (cached per (sender, block), filtered so the cache stays small)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{sender}_{block}.json"
    if f.exists():
        return json.loads(f.read_text())
    url = f"https://eth-mainnet.g.alchemy.com/v2/{_env()['ALCHEMY_KEY']}"
    err = ""
    for i in range(10):
        try:
            r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "eth_getBlockByNumber", "params": [hex(block), True]}, timeout=90)
            if r.status_code == 200 and r.json().get("result"):
                txs = [dict(hash=t["hash"], block=block, idx=int(t["transactionIndex"], 16), to=(t["to"] or "").lower(), inp=len(t["input"]) // 2 - 1)
                       for t in r.json()["result"]["transactions"] if t["from"].lower() == sender]
                f.write_text(json.dumps(txs)); return txs
            err = f"HTTP {r.status_code} {r.text[:100]}"
        except requests.exceptions.RequestException as e:
            err = type(e).__name__
        time.sleep(2.0 * (i + 1))
    raise RuntimeError(f"block {block} failed: {err}")


def analyse(row):
    tx = rpc("eth_getTransactionByHash", [row.T_tx]); rc = rpc("eth_getTransactionReceipt", [row.T_tx])
    T = int(rc["blockNumber"], 16); sender = tx["from"].lower(); deploy = tx["to"] is None
    target = "" if deploy else tx["to"].lower()
    providers = sorted({FLASH[l["topics"][0]] for l in rc["logs"] if l["topics"] and l["topics"][0] in FLASH})
    with ThreadPoolExecutor(6) as ex:
        per_block = list(ex.map(lambda b: sender_txs(b, sender), range(T - W, T + W + 1)))
    allx = [t for blk in per_block for t in blk]
    same = [t for t in allx if t["hash"] != row.T_tx and t["to"] == target]           # target "" == deployments
    common = {"0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "0xdac17f958d2ee523a2206206994597c13d831ec7",
              "0x6b175474e89094c44da98b954eedeac495271d0f", "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"}     # WETH USDC USDT DAI WBTC
    emit = lambda r: {l["address"].lower() for l in r["logs"]} - common
    ET = emit(rc); gasT = int(rc["gasUsed"], 16)
    ok = []
    for t in same:
        r2 = rpc("eth_getTransactionReceipt", [t["hash"]])
        # 'repeat' = successful AND touches >=50% of the attack tx's non-token log emitters AND uses >=10% of its gas
        # (filters out withdrawals / cleanup calls to the same contract)
        rep = r2["status"] == "0x1" and len(ET) > 0 and len(ET & emit(r2)) / len(ET) >= 0.5 and int(r2["gasUsed"], 16) >= 0.1 * gasT
        ok.append((t, r2["status"] == "0x1", rep))
    def cls(win, key):
        oth = [t for t, s, rp in ok if (rp if key == "repeat" else s) and abs(t["block"] - T) <= win]
        if not oth: return "single-tx"
        return "multi-tx same block" if all(t["block"] == T for t in oth) else "multi-block"
    rep_t = [t for t, s, rp in ok if rp]; succ = [t for t, s, rp in ok if s]; rev = [t for t, s, rp in ok if not s]
    return dict(incident=row.incident_id, category=row.category, verified_M=bool(row.verified_M), T=T, sender=sender, target=target or "(deployment)",
                status=rc["status"], logs=len(rc["logs"]), gas=gasT, flash=", ".join(providers) or "none detected",
                class100=cls(W, "repeat"), class20=cls(W_SMALL, "repeat"), class100_raw=cls(W, "raw"),
                n_same_target_success=len(succ), n_repeat_before=sum(t["block"] < T for t in rep_t), n_repeat_after=sum(t["block"] >= T for t in rep_t),
                n_reverted=len(rev),
                span=(f"{min(t['block'] for t in rep_t) - T:+d}..{max(t['block'] for t in rep_t) - T:+d}" if rep_t else "-"))


def main():
    t0 = time.time()
    sh = pd.read_csv(ROOT / "reports" / "a2_label_sheet.csv")
    R = pd.DataFrame([analyse(r) for r in sh.itertuples()])
    R.to_csv(ROOT / "reports" / "cjsj_06_atomicity.csv", index=False)
    out = []; Q = out.append
    Q(f"Window W={W} blocks (about {W * 12 // 60} min) each side; sensitivity W={W_SMALL}. Per-attack CSV: `reports/cjsj_06_atomicity.csv`. Sender-only scan: see limits in the script docstring.")
    Q("")
    Q("| Incident | A2 cat | class (repeat-verified, W=100) | class (W=20) | class (raw same-target, W=100) | flash-loan events in tx | repeat txs before/after (span in blocks) | same-target successful (any) | reverted same-target | tx logs |")
    Q("|---|---|---|---|---|---|---|---|---|---|")
    for r in R.itertuples():
        Q(f"| {r.incident} | {r.category}{' (verified)' if r.verified_M else ''} | {r.class100} | {r.class20} | {r.class100_raw} | {r.flash} | {r.n_repeat_before}/{r.n_repeat_after} ({r.span}) | {r.n_same_target_success} | {r.n_reverted} | {r.logs} |")
    Q("")
    def cnt(df, col): return ", ".join(f"{k}={v}" for k, v in df[col].value_counts().items())
    Q("'Repeat-verified' counts a later same-sender same-target tx only if it is successful, touches >=50% of the attack tx's non-token log emitters and uses >=10% of its gas (so cleanup/withdrawal calls do not count); 'raw' counts any successful same-target tx.")
    Q("")
    Q(f"- All 24, W=100 repeat-verified: {cnt(R, 'class100')}.  W=20: {cnt(R, 'class20')}.  Raw same-target W=100: {cnt(R, 'class100_raw')}.  [cjsj_06_atomicity.py]")
    Q(f"- Verified M ({int(R.verified_M.sum())}), W=100: {cnt(R[R.verified_M], 'class100')}.")
    Q(f"- A2 category M any tier ({int((R.category == 'M').sum())}), W=100: {cnt(R[R.category == 'M'], 'class100')}.")
    Q(f"- Flash-loan event detected in the attack tx: {int((R.flash != 'none detected').sum())}/24 (verified M: {int(((R.flash != 'none detected') & R.verified_M).sum())}/{int(R.verified_M.sum())}).")
    Q(f"- Attack txs with status success: {int((R.status == '0x1').sum())}/24.")
    body = "\n".join(out); print(body)
    write_section("cjsj_06_atomicity.py", "6", "B8 single-tx vs multi-block classification from tx receipts", TAG_CONFOUNDED, body)
    print(f"(runtime {time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
