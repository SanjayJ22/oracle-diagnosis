"""Enumerate trigger-fired benign episodes (A0 G1, source price path only) for the named events.
Writes data/processed/pilot_candidates.json. Selection here is enumeration only (no sampling, no features)."""
import json, sys
from pathlib import Path
import numpy as np
import pilot_scan as S, pilot_rpc as R
from pilot_lib import *

OUT = Path(__file__).resolve().parent.parent / "data" / "processed" / "pilot_candidates.json"
POOLS = {  # name: (address, i, j, description)
    "3pool_USDC_USDT": ("0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7", 1, 2),
    "3pool_USDT_USDC": ("0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7", 2, 1),
    "3pool_USDC_DAI": ("0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7", 1, 0),
    "steth_stETH_ETH": ("0xDC24316b9AE028F1497c275EB9192a3Ea0f67022", 1, 0),
    "mim3crv_MIM_3CRV": ("0x5a6A4D54456819380173272A5E8E9B9904BdF41B", 0, 1),
    "usde_usdc_USDe_USDC": ("0x02950460E2b9529D0E00284A5fA2d7bDF3fA4d72", 0, 1),
    "frxeth_frxETH_ETH": ("0xa1F8A6807c402E4A15ef4EBa36528A3FED24E577", 1, 0),
}
# (event, source, start, end)  -- UST-linked windows/pools deliberately absent
JOBS = [
    ("USDC_Mar2023", "3pool_USDC_USDT", S.utc(2023, 3, 10), S.utc(2023, 3, 15)),
    ("USDC_Mar2023", "3pool_USDC_DAI", S.utc(2023, 3, 10), S.utc(2023, 3, 15)),
    ("USDT_Jun2023", "3pool_USDT_USDC", S.utc(2023, 6, 10), S.utc(2023, 6, 20)),
    ("stETH_Jun2022", "steth_stETH_ETH", S.utc(2022, 6, 10), S.utc(2022, 6, 20)),
    ("MIM_Jun2022", "mim3crv_MIM_3CRV", S.utc(2022, 6, 10), S.utc(2022, 6, 20)),
    ("USDe_Oct2025", "usde_usdc_USDe_USDC", S.utc(2025, 10, 9), S.utc(2025, 10, 14)),
    ("LSD_May2022", "steth_stETH_ETH", S.utc(2022, 5, 9), S.utc(2022, 5, 14)),
    ("LSD_Nov2022", "steth_stETH_ETH", S.utc(2022, 11, 8), S.utc(2022, 11, 12)),
    ("LSD_Nov2022", "frxeth_frxETH_ETH", S.utc(2022, 11, 8), S.utc(2022, 11, 12)),
    ("LP_Jun2022", "LP_tricrypto2_yv", S.utc(2022, 6, 10), S.utc(2022, 6, 14, 12)),   # ends >1 day before Inverse (Jun 16)
    ("LP_Nov2022", "LP_tricrypto2_yv", S.utc(2022, 11, 8), S.utc(2022, 11, 11)),
]


def main(only=None):
    lp = TricryptoLP()
    res = []
    for ev, src, t0, t1 in JOBS:
        if only and ev not in only:
            continue
        b0, b1 = S.block_at(t0), S.block_at(t1)
        stride = 20 if src.startswith("LP_") else S.STRIDE          # LP reads cost 7 calls/block: coarser grid (Y=50 still spans 2 steps)
        blocks = list(range(b0, b1 + 1, stride))
        qa = new_qa(f"scan_{ev}_{src}")
        if src.startswith("LP_"):
            p, _ = lp.series(blocks, qa)
            stype = "curve_lp"
        else:
            addr, i, j = POOLS[src]
            pool = CurvePool(addr, i, j, src, b0)
            p = pool.series(blocks, qa)
            stype = "curve_spot"
        ts, _ = block_times(blocks[::max(1, len(blocks) // 200)], qa)       # block/timestamp verification on a grid
        eps = S.episodes_from_series(blocks, p, stride=stride)
        print(f"{ev:14s} {src:22s} blocks {b0}-{b1} n={len(blocks)} QA_ok={qa.ok} fails={qa.failures()} episodes={len(eps)}", flush=True)
        for e in eps:
            e.update({"event": ev, "source": src, "S_type": stype, "window_start_block": b0, "window_end_block": b1})
            res.append(e)
    OUT.parent.mkdir(exist_ok=True, parents=True)
    json.dump(res, open(OUT, "w"), indent=1)
    print("TOTAL episodes enumerated:", len(res), "| RPC:", R.stats(), flush=True)


if __name__ == "__main__":
    main(set(sys.argv[1:]) or None)
