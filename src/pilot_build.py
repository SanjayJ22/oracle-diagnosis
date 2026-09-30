"""Build data/processed/pilot.parquet: matched-negative pilot under A0/A1 (G1 block-close).

Feature set (locked): Tier P = P1,P2,P3 at a=T-1;  Tier D = D1,D2,D3,D5 at end of T.
Never touches models.py / features.parquet.  QA runs on every pull (pilot_lib QA_LOG).
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import pilot_rpc as R
import pilot_scan as S
from pilot_lib import *

ROOT = Path(__file__).resolve().parent.parent
CAND = ROOT / "data" / "processed" / "pilot_candidates.json"
OUT = ROOT / "data" / "processed" / "pilot.parquet"
SEED = 20260930
CAP0 = 6                 # per (event, source) cell; reduced uniformly until total <= TARGET_MAX
TARGET_MAX = 40
W = 300                  # A1 lookback (blocks)
D5_CAP = 1800            # A1 placeholder Y_max
D5_STRIDE = 10
BAND = 0.005

POOLS = {
    "3pool_USDC_USDT": ("0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7", 1, 2),
    "3pool_USDT_USDC": ("0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7", 2, 1),
    "3pool_USDC_DAI": ("0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7", 1, 0),
    "steth_stETH_ETH": ("0xDC24316b9AE028F1497c275EB9192a3Ea0f67022", 1, 0),
    "mim3crv_MIM_3CRV": ("0x5a6A4D54456819380173272A5E8E9B9904BdF41B", 0, 1),
    "usde_usdc_USDe_USDC": ("0x02950460E2b9529D0E00284A5fA2d7bDF3fA4d72", 0, 1),
    "frxeth_frxETH_ETH": ("0xa1F8A6807c402E4A15ef4EBa36528A3FED24E577", 1, 0),
    "dusd_usdc_USDC_DUSD": ("0x32e616f4f17d43f9a5cd9be0e294727187064cb3", 0, 1),   # Makina pool: price of USDC in DUSD
}
THREEPOOL = "0xbEbc44782C7dB0a1A60Cb6fe97d0b483032FF1C7"
ETHUSD = ChainlinkFeed(CL_FEEDS["ETH"], "ETH/USD")
_LP = None
_POOL_CACHE = {}

# known exploits per source (block of T) for the "not within a day" rule
EXPLOITS = {"LP_tricrypto2_yv": [14972419],            # Inverse Finance
            "usde_usdc_USDe_USDC": [20061319],         # UwU Lend
            "dusd_usdc_USDC_DUSD": [24273362]}         # Makina
DAY = 7200

LABELS = ROOT / "data" / "processed" / "labels_a2.csv"
Y_POOL = "0x45F783CCE6B7FF23B2ab2D70e416cdb7D6055f51"
ZUNAMI_POOL = "0x68934F60758243eafAf4D2cFeD27BF8010bede3a"
UZD = "0xb40b6608B2743E691C9B54DdBDEe7bf03cd79f1c"
# incident -> reader configuration for the label sheet's S column (verified-M rows only)
CFG = {
    "Harvest Finance": dict(kind="curve", src="curve_y_yUSDC_yUSDT", stype="curve_spot"),
    "Inverse Finance": dict(kind="curve", src="LP_tricrypto2_yv", stype="curve_lp"),
    "UwU Lend": dict(kind="curve", src="usde_usdc_USDe_USDC", stype="curve_spot"),
    "ZunamiProtocol": dict(kind="curve", src="zunami_UZD_crvFRAX", stype="curve_spot"),
    "Makina": dict(kind="curve", src="dusd_usdc_USDC_DUSD", stype="curve_spot"),
    "Cream Finance": dict(kind="vault", addr="0x4B5BfD52124784745c1071dcB244C6688d2533d3", stype="vault_rate"),
    "CurveLlamaLend": dict(kind="vault", addr="0xb45ad160634c528Cc3D2926d9807104FA3157305", stype="vault_rate"),
    "ResupplyFi": dict(kind="vault", addr="0x01144442fba7adccb5c9dc9cf33dd009d50a9e1d", stype="vault_rate"),   # pair.collateral(); the label sheet address is the crvUSD controller, not the vault
    "BalancerBoostedPool2023": dict(kind="unsupported", stype="balancer_rate_provider"),
}


def pool_for(src, ref_block):
    if src not in _POOL_CACHE:
        if src == "curve_y_yUSDC_yUSDT":                       # Harvest: price of yUSDC in yUSDT on the Y pool (label sheet S)
            _POOL_CACHE[src] = CurvePool(Y_POOL, 1, 2, src, ref_block)
        elif src == "zunami_UZD_crvFRAX":                      # price of UZD in the pool's other coin
            probe = CurvePool(ZUNAMI_POOL, 0, 1, src, ref_block)
            iu = [c.lower() for c in probe.coins].index(UZD.lower())
            _POOL_CACHE[src] = CurvePool(ZUNAMI_POOL, iu, 1 - iu, src, ref_block)
        else:
            addr, i, j = POOLS[src]
            _POOL_CACHE[src] = CurvePool(addr, i, j, src, ref_block)
    return _POOL_CACHE[src]


def lp():
    global _LP
    if _LP is None:
        _LP = TricryptoLP()
    return _LP


def s_series(src, blocks, qa):
    """(p_S, R_series) for arbitrary blocks. R: parity (R4) for pegged pairs; 1/vp3 for MIM metapool; Curve fair LP formula for LP."""
    if src.startswith("LP_"):
        return lp().series(blocks, qa)
    pool = pool_for(src, blocks[0])
    p = pool.series(blocks, qa)
    if src == "curve_y_yUSDC_yUSDT":                           # R4: fundamental yUSDC/yUSDT share-price ratio (independent of pool state)
        pp = [np.array([np.nan if dec_uint(o) is None else dec_uint(o) / 1e18 for o in
                        R.eth_call_blocks(pool.coins[k], sel("getPricePerFullShare()"), blocks)]) for k in (1, 2)]
        Rv = pp[0] / pp[1]
    elif src.startswith("mim3crv"):
        vp = np.array([np.nan if dec_uint(o) is None else dec_uint(o) / 1e18 for o in
                       R.eth_call_blocks(THREEPOOL, sel("get_virtual_price()"), blocks)])
        Rv = 1.0 / vp
    else:
        Rv = np.ones(len(blocks))
    return p, Rv


def eth_context(a, T, qa):
    """ETH-context control features (mirror of the audit's C1 family): all describe the ETH market, not S."""
    grid = list(range(a - W, a + 1, 10))
    px, upd = ETHUSD.series(grid, qa)
    r = np.diff(np.log(px))
    hb = R.get_blocks(grid)
    util = np.array([int(b["gasUsed"], 16) / int(b["gasLimit"], 16) for b in hb])
    pT, updT = ETHUSD.series([a, T], qa)
    bT = R.get_blocks([T])[0]
    p50, _ = ETHUSD.series([T - 50, T], qa)
    ts_a = int(R.get_blocks([a])[0]["timestamp"], 16)
    return {
        "eth_ret_300": float(np.log(px[-1] / px[0])),
        "eth_vol_300": float(np.std(r, ddof=1)),
        "eth_gas_util_300": float(util.mean()),
        "eth_gas_util_T": int(bT["gasUsed"], 16) / int(bT["gasLimit"], 16),
        "eth_absret_T": float(abs(np.log(pT[1] / pT[0]))),
        "eth_absret_50": float(abs(np.log(p50[1] / p50[0]))),
        "eth_cl_stale_a": float(ts_a - upd[-1]),
    }


def features_for(src, stype, T, qa):
    a = T - 1
    blocks = list(range(a - W, T + 1))                        # per-block, [a-W, T]
    p, Rv = s_series(src, blocks, qa)
    pa, pT, paW = p[W], p[W + 1], p[0]
    Ra, RT = Rv[W], Rv[W + 1]
    after_blocks = list(range(T + D5_STRIDE, T + D5_CAP + 1, D5_STRIDE))
    p_after, _ = s_series(src, after_blocks, new_qa(qa.name + "_after"))
    f = {
        "P1": f_P1(pa, Ra), "P2": f_P2(pa, paW), "P3": f_P3(p[: W + 1]),
        "D1": f_D1(pT, pa), "D2": f_D2(pT, RT), "D3": f_D3(RT, Ra),
        "D5": f_D5(p_after, pa, BAND, cap=D5_CAP // D5_STRIDE) * D5_STRIDE,
        "p_a": float(pa), "p_T": float(pT), "R_a": float(Ra), "R_T": float(RT),
    }
    return f, p, blocks


def attack_trigger(src, T, qa):
    """First G1 firing in [T-W, T+Y_MERGE] (pre-window W because table blocks are not always the first manipulating tx)."""
    blocks = list(range(T - W - S.Y_BLOCKS, T + S.Y_MERGE + 1))
    p, _ = s_series(src, blocks, qa)
    fire, mag = trigger_fires(p, S.Y_BLOCKS, S.X_PEGGED)
    idx = [i for i in np.where(fire)[0] if blocks[i] >= T - W]
    return (blocks[idx[0]] if idx else None), float(mag[[i for i in range(len(blocks)) if blocks[i] >= T - W]].max())


def select_benign(cands, seed=SEED):
    rng = np.random.default_rng(seed)
    kept = []
    for c in cands:                                           # exploit-adjacency exclusion (feature-blind)
        bad = any(abs(c["first_grid_fire"] - e) <= DAY for e in EXPLOITS.get(c["source"], []))
        c["excluded_exploit_adjacent"] = bool(bad)
        if not bad:
            kept.append(c)
    cells = {}
    for c in kept:
        cells.setdefault((c["event"], c["source"]), []).append(c)
    for cap in range(CAP0, 0, -1):
        rng = np.random.default_rng(seed)                     # same seed for every cap; cells visited in sorted order
        sel = []
        for k in sorted(cells):
            lst = cells[k]
            idx = sorted(rng.choice(len(lst), size=min(cap, len(lst)), replace=False))
            sel += [lst[i] for i in idx]
        if len(sel) <= TARGET_MAX:
            return sel, cap, len(kept)
    return sel, 1, len(kept)


def main():
    cands = json.load(open(CAND))
    sel, cap, n_kept = select_benign(cands)
    print(f"candidates {len(cands)}, after exploit-adjacency {n_kept}, cap {cap} -> selected {len(sel)}", flush=True)
    rows = []
    for c in sel:
        src, stype = c["source"], c["S_type"]
        b0, b1 = c["window_start_block"], c["window_end_block"]
        qa = new_qa(f"benign_{c['event']}_{src}_{c['first_grid_fire']}")
        T = S.refine_T(lambda bl: s_series(src, bl, qa)[0], c["first_grid_fire"])
        if T is None:
            rows.append(dict(episode_id=f"B-{src}-{c['first_grid_fire']}", cls="benign", event=c["event"], source=src, S_type=stype,
                             T=c["first_grid_fire"], in_analysis=False, note="T refinement found no exact firing"))
            continue
        f, p, blocks = features_for(src, stype, T, qa)
        e = eth_context(T - 1, T, qa)
        rows.append(dict(episode_id=f"B-{src}-{T}", cls="benign", label="G", event=c["event"], source=src, S_type=stype, T=T,
                         T_trigger=T, T_method="first G1 trigger block, refined per-block", peak_mag_grid=c["peak_mag"],
                         cell=f"{c['event']}|{src}", R_tier="R4" if stype == "curve_spot" else "R2/R4", qa_ok=qa.ok,
                         qa_fail="; ".join(f"{a}:{b}" for a, b in qa.failures()), in_analysis=bool(qa.ok), **f, **e))
        print("benign", rows[-1]["episode_id"], f"D1={f['D1']:.4f} D2={f['D2']:.4f}", flush=True)
    labels = pd.read_csv(LABELS)
    vm = labels[labels.a2_verified_M == True]                  # noqa: E712  verified-M only (9)
    n_by_type = {}
    for _, lr in vm.iterrows():
        name, T = lr["incident"], int(lr["T_block"])
        cfg = CFG[name]
        stype = cfg["stype"]
        n_by_type[stype] = n_by_type.get(stype, 0) + 1
        qa = new_qa(f"attack_{name}")
        verify_tx(lr["T_tx"], T, qa)
        base = dict(episode_id=f"A-{name.replace(' ', '')}-{T}", cls="attack", label="M", event=name, S_type=stype, T=T,
                    date=str(lr["date"]), T_method="labels_a2.csv T_tx (receipt block verified)", atomic_label=lr["atomic_label"],
                    label_source="labels_a2.csv a2_verified_M", S_label_sheet=str(lr["S"]))
        if cfg["kind"] == "unsupported":
            rows.append(dict(base, source="n/a", in_analysis=False, trigger_fired=None, qa_ok=qa.ok,
                             note="source is a Balancer linear-pool rate provider: outside Curve/Uniswap/vault-rate scope; no reader built"))
            print("attack", base["episode_id"], "UNSUPPORTED source type", flush=True)
            continue
        if cfg["kind"] == "vault":                             # descriptive only: no independent R for a vault's own rate (A1 s4 'none')
            try:
                a_ = T - 1
                vr = VaultRate(cfg["addr"], name, a_)
                blocks = list(range(a_ - W, T + 1)); p = vr.series(blocks, qa)
                pa_ = vr.series(list(range(T + D5_STRIDE, T + D5_CAP + 1, D5_STRIDE)), new_qa(qa.name + "_after"))
                fire, mag = trigger_fires(p, S.Y_BLOCKS, S.X_PEGGED)
                rows.append(dict(base, source=cfg["addr"], trigger_fired=bool(fire[W:].any()), max_mag_window=float(mag[W:].max()),
                                 P2=f_P2(p[W], p[0]), P3=f_P3(p[: W + 1]), D1=f_D1(p[W + 1], p[W]),
                                 D5=f_D5(pa_, p[W], BAND, cap=D5_CAP // D5_STRIDE) * D5_STRIDE, p_a=float(p[W]), p_T=float(p[W + 1]),
                                 qa_ok=qa.ok, in_analysis=False, R_tier="none",
                                 note="vault_rate excluded from analysis: no independent reference price R (A1 s4 tier none); price path shown descriptively"))
                print("vault attack", base["episode_id"], f"D1={rows[-1]['D1']:.4f}", flush=True)
            except Exception as ex:
                rows.append(dict(base, source=cfg["addr"], in_analysis=False, qa_ok=False, note=f"vault reader failed: {ex}"))
                print("vault attack FAILED", name, ex, flush=True)
            continue
        src = cfg["src"]
        Tt, mx = attack_trigger(src, T, qa)
        row = dict(base, source=src, T_trigger=Tt, trigger_fired=Tt is not None, max_mag_window=mx, qa_ok=qa.ok,
                   qa_fail="; ".join(f"{x}:{y}" for x, y in qa.failures()))
        if Tt is not None:
            f, p, blocks = features_for(src, stype, T, qa)
            e = eth_context(T - 1, T, qa)
            row.update(f); row.update(e)
            row.update(R_tier="R4" if stype == "curve_spot" else "R2/R4", in_analysis=bool(qa.ok), gap_trigger_minus_T=int(Tt - T))
        else:
            row.update(in_analysis=False, note="trigger miss under G1 (block-close): S never moved >= X within Y at block close in [T-W, T+Ymerge]")
        rows.append(row)
        print("attack", row["episode_id"], "fired" if Tt else "MISS", f"max_mag={mx:.4f}", flush=True)
    print("verified-M by S_type:", n_by_type, flush=True)
    df = pd.DataFrame(rows)
    df.to_parquet(OUT)
    json.dump([(q.name, q.ok, q.failures(), len(q.checks)) for q in QA_LOG], open(ROOT / "data" / "processed" / "pilot_qa_log.json", "w"), indent=1)
    print("wrote", OUT, df.shape, "| RPC", R.stats(), flush=True)


if __name__ == "__main__":
    main()
