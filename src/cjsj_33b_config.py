"""CJSJ item 33 (part b): feed configuration changes. For each phase aggregator behind the Chainlink ETH/USD proxy (phases 3-7), read latestConfigDetails().configCount at historical blocks
(archive eth_call; every ~150,000 blocks, about 3 weeks) and bisect every change down to its block, then map blocks to timestamps. A configCount increase = the oracle committee / offchain config
(which includes the update-trigger parameters) was reset. Also reports the aggregator's `decimals`/`description` and the block of each phase's first round. Writes reports/cjsj_33b_config.csv."""
import json, time
import pandas as pd, requests
from cjsj_common import ROOT, REPORTS, _env, rpc
from web3 import Web3
from datetime import datetime, timezone

URL = f"https://eth-mainnet.g.alchemy.com/v2/{_env()['ALCHEMY_KEY']}"
AGG = {3: "0x00c7a37b03690fb9f41b5c5af8131735c7275446", 4: "0xd3fcd40153e56110e6eeae13e12530e26c9cb4fd", 5: "0x37bc7498f4ff12c19678ee8fe19d713b87f6a9e6", 6: "0xe62b71cf983019bff55bc83b48601ce8419650cc", 7: "0x7d4e742018fb52e48b08be73d041c18b21de6fb5"}
SEL = lambda s: "0x" + Web3.keccak(text=s).hex().removeprefix("0x")[:8]
LCD = SEL("latestConfigDetails()")


def call(to, data, block):
    r = rpc("eth_call", [{"to": to, "data": data}, hex(block) if isinstance(block, int) else block])
    return r


def cfg_count(a, block):
    try:
        r = call(a, LCD, block); return int(r[2:66], 16), int(r[66:130], 16)
    except Exception:
        return None


def ts(block): return int(rpc("eth_getBlockByNumber", [hex(block), False])["timestamp"], 16)


def main():
    latest = int(rpc("eth_blockNumber", []), 16); rows = []
    # phase block ranges by bisecting the first round's existence is costly; use timestamps from cjsj_33 cache instead: approximate by probing configCount != None
    for ph, a in AGG.items():
        lo, hi = 10_900_000, latest
        # find first block where the contract answers
        first = None
        for b in range(lo, hi, 250_000):
            if cfg_count(a, b) is not None: first = b; break
        if first is None: rows.append(dict(phase=ph, note="no answer")); continue
        s = max(first - 250_000, lo)
        while first - s > 1000:
            m = (s + first) // 2
            if cfg_count(a, m) is not None: first = m
            else: s = m
        prev = cfg_count(a, first); rows.append(dict(phase=ph, event="first block answering", block=first, config_count=prev[0], config_block=prev[1], time=datetime.fromtimestamp(ts(first), timezone.utc).strftime("%Y-%m-%d")))
        b = first; samples = list(range(first, latest, 150_000)) + [latest]
        last_cc = prev[0]; last_b = first
        for b in samples[1:]:
            cc = cfg_count(a, b)
            if cc is None: break
            if cc[0] != last_cc:
                lo2, hi2 = last_b, b
                while hi2 - lo2 > 1:
                    m = (lo2 + hi2) // 2; c = cfg_count(a, m)
                    if c is not None and c[0] == last_cc: lo2 = m
                    else: hi2 = m
                cc2 = cfg_count(a, hi2)
                rows.append(dict(phase=ph, event=f"configCount {last_cc} -> {cc2[0]}", block=hi2, config_count=cc2[0], config_block=cc2[1], time=datetime.fromtimestamp(ts(hi2), timezone.utc).strftime("%Y-%m-%d")))
                last_cc = cc[0] if cc[0] == cc2[0] else cc2[0]
            last_b = b
        print(ph, "done", flush=True)
    R = pd.DataFrame(rows); R.to_csv(REPORTS / "cjsj_33b_config.csv", index=False); print(R.to_string())


if __name__ == "__main__":
    main()
