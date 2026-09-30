"""CJSJ item 33: why does heartbeat_elapsed drift? Chainlink ETH/USD feed (proxy 0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419) update behavior by quarter.

Data access: the free Alchemy tier limits eth_getLogs to 10 blocks, so the full AnswerUpdated history cannot be scanned. Instead rounds are read with proxy.getRoundData(roundId)
(archive-free: rounds persist in aggregator state) in two SAMPLED designs (cache data/raw/chainlink_rounds.json):
  (A) per quarter 2020Q4-2026Q3: 3 windows of 250 CONSECUTIVE rounds starting at 20%, 50%, 80% of the quarter -> median gap between consecutive updates, p90, share of gaps >= 3000 s
      (heartbeat-triggered), median |price change| per update. 'All rounds' below = these samples.
  (B) windows of +-50 rounds around the block of each of the 138 volatility incidents (the incidents ARE >=3-5% ETH moves): gaps between updates within +-1 h of the incident block,
      grouped by the incident's quarter ('during >=3% moves').
Also: phase (aggregator contract) switch dates from the proxy's phase aggregators' first/last rounds; configuration-change points for the current OCR2 aggregator from
latestConfigDetails().configCount located by bisection over historical blocks (eth_call at block); validation that the dataset's heartbeat_elapsed equals block timestamp minus the
last update at or before the incident block (recomputed from the rounds).
Limits: samples, not the full history (an estimate of medians with sampling error shown by window-to-window spread); round lookup by timestamp uses interpolation+bisection."""
import json, time, bisect
from datetime import datetime, timezone
import numpy as np, pandas as pd, requests
from concurrent.futures import ThreadPoolExecutor
from cjsj_common import ROOT, REPORTS, TAG_CONFOUNDED, _env, rpc, write_section
from web3 import Web3
import cjsj_eval as E

PROXY = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"; URL = f"https://eth-mainnet.g.alchemy.com/v2/{_env()['ALCHEMY_KEY']}"
CACHE = ROOT / "data" / "raw" / "chainlink_rounds.json"; RC = json.loads(CACHE.read_text()) if CACHE.exists() else {}
PH = lambda p: p << 64
SEL = lambda s: Web3.keccak(text=s).hex().removeprefix("0x")[:8]
GRD = "0x" + SEL("getRoundData(uint80)"); LRD = "0xfeaf968c"


def batch(calls):
    """calls: list of (to, data, block). Returns list of hex results or None on revert. Batched JSON-RPC, 50 per request."""
    out = [None] * len(calls)
    for s in range(0, len(calls), 50):
        chunk = calls[s:s + 50]; body = [{"jsonrpc": "2.0", "id": i, "method": "eth_call", "params": [{"to": c[0], "data": c[1]}, c[2]]} for i, c in enumerate(chunk)]
        for att in range(6):
            try:
                r = requests.post(URL, json=body, timeout=120)
                if r.status_code == 200 and isinstance(r.json(), list):
                    for x in r.json(): out[s + x["id"]] = x.get("result")
                    break
            except requests.exceptions.RequestException: pass
            time.sleep(2 * (att + 1))
    return out


def rounds(ids):
    need = [i for i in ids if str(i) not in RC]
    if need:
        res = batch([(PROXY, GRD + hex(i)[2:].rjust(64, "0"), "latest") for i in need])
        for i, r in zip(need, res):
            v = None if (r is None or r == "0x" or len(r) < 322) else [int(r[2 + 64 * k:2 + 64 * (k + 1)], 16) for k in range(5)]
            RC[str(i)] = None if (v is None or v[3] == 0) else v
        CACHE.write_text(json.dumps(RC))
    return [RC[str(i)] for i in ids]


def one(i): return rounds([i])[0]


def phase_info():
    info = {}
    for p in range(3, 8):
        first = one(PH(p) | 1)
        lo = 1; hi = 1
        while one(PH(p) | (hi * 2)) is not None: hi *= 2
        top = hi * 2
        while top - hi > 1:
            m = (hi + top) // 2
            if one(PH(p) | m) is not None: hi = m
            else: top = m
        info[p] = dict(first_round=1, last_round=hi, t_first=first[3], t_last=one(PH(p) | hi)[3], price_first=first[1] / 1e8)
    return info


def find_round(t, info):
    """Greatest (proxy round id, data) with updatedAt <= t (interpolation then bisection inside the right phase)."""
    ph = max(p for p in info if info[p]["t_first"] <= t) if t >= info[3]["t_first"] else 3
    lo, hi = 1, info[ph]["last_round"]; tl, th = info[ph]["t_first"], info[ph]["t_last"]
    if t >= th: return PH(ph) | hi, one(PH(ph) | hi)
    while hi - lo > 1:
        m = lo + int((hi - lo) * (t - tl) / max(th - tl, 1)); m = min(max(m, lo + 1), hi - 1); d = one(PH(ph) | m)
        if d is None: hi = m; continue
        if d[3] <= t: lo, tl = m, d[3]
        else: hi, th = m, d[3]
    return PH(ph) | lo, one(PH(ph) | lo)


def q_of(ts): d = datetime.fromtimestamp(ts, timezone.utc); return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def main():
    t0 = time.time(); base = E.load_base(); info = phase_info(); L = []; Q = L.append
    t_start, t_end = info[3]["t_first"], info[7]["t_last"]
    # (A) quarterly windows
    qs = sorted({q_of(t) for t in range(int(pd.Timestamp("2020-10-01", tz="UTC").timestamp()), t_end, 86400 * 30)})
    def qbounds(q):
        y, k = int(q[:4]), int(q[-1]); a = datetime(y, 3 * (k - 1) + 1, 1, tzinfo=timezone.utc); b = datetime(y + (k == 4), (3 * k) % 12 + 1, 1, tzinfo=timezone.utc); return a.timestamp(), b.timestamp()
    A = []
    for q in qs:
        a, b = qbounds(q)
        for f in (0.2, 0.5, 0.8):
            t = a + f * (b - a)
            if t < info[3]["t_first"] or t > t_end: continue
            rid, d = find_round(t, info); ids = [rid + k for k in range(250)]; rs = [r for r in rounds(ids) if r]
            ts = np.array([r[3] for r in rs]); pr = np.array([r[1] / 1e8 for r in rs])
            if len(ts) > 5: A.append(dict(q=q, w=f, gaps=np.diff(ts), dp=np.abs(np.diff(pr)) / pr[:-1]))
        print("A", q, f"{time.time() - t0:.0f}s", flush=True)
    # (B) incident windows
    bm = base[base.label == E.VOL].copy(); Bw = []; val = []
    for r in bm.itertuples():
        bt = int(rpc("eth_getBlockByNumber", [hex(int(r.block)), False])["timestamp"], 16)
        rid, d = find_round(bt, info); ids = [rid + k for k in range(-50, 51)]; rs = [x for x in rounds(ids) if x]
        ts = np.array([x[3] for x in rs]); m = (ts >= bt - 3600) & (ts <= bt + 3600)
        Bw.append(dict(q=q_of(bt), t=bt, gaps=np.diff(ts[m]) if m.sum() > 1 else np.array([]), elapsed=bt - d[3], ds_elapsed=r.heartbeat_elapsed, incident=r.incident))
        val.append((bt - d[3], r.heartbeat_elapsed))
    print("B", f"{time.time() - t0:.0f}s", flush=True)
    # tables
    Q("Sampled estimate (see docstring): (A) 3 windows x 250 consecutive rounds per quarter, (B) +-1 h around each of the 138 volatility incidents.")
    Q("")
    Q("#### 33a. Phases (aggregator contracts behind the proxy)"); Q("")
    Q("| Phase | first update (UTC) | last sampled update (UTC) | rounds | first price |"); Q("|---|---|---|---|---|")
    fmt = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
    for p, i in info.items(): Q(f"| {p} | {fmt(i['t_first'])} | {fmt(i['t_last'])} | {i['last_round']} | {i['price_first']:.2f} |")
    Q("")
    Q("#### 33b. Update gaps by quarter (seconds) and heartbeat_elapsed of incidents"); Q("")
    Q("| Quarter | A: median gap, all rounds | A: p90 gap | A: share of gaps >= 3000 s | A: median |price change| per update | A: rounds | B: median gap during >=3% moves | B: gaps | dataset heartbeat_elapsed, volatility incidents (median, n) |"); Q("|---|---|---|---|---|---|---|---|---|")
    rows = []
    for q in qs:
        g = np.concatenate([w["gaps"] for w in A if w["q"] == q]) if any(w["q"] == q for w in A) else np.array([])
        dp = np.concatenate([w["dp"] for w in A if w["q"] == q]) if g.size else np.array([])
        bg = np.concatenate([w["gaps"] for w in Bw if w["q"] == q]) if any(w["q"] == q for w in Bw) else np.array([])
        he = np.array([w["ds_elapsed"] for w in Bw if w["q"] == q])
        rows.append(dict(q=q, a_med=np.median(g) if g.size else np.nan, a_p90=np.percentile(g, 90) if g.size else np.nan, a_hb=(g >= 3000).mean() if g.size else np.nan, a_dp=np.median(dp) if g.size else np.nan, a_n=g.size,
                         b_med=np.median(bg) if bg.size else np.nan, b_n=bg.size, he_med=np.median(he) if he.size else np.nan, he_n=he.size))
        r = rows[-1]; f = lambda v, p=0: "-" if np.isnan(v) else f"{v:.{p}f}"
        Q(f"| {q} | {f(r['a_med'])} | {f(r['a_p90'])} | {f(r['a_hb'], 2)} | {f(100 * r['a_dp'], 2)}% | {r['a_n']} | {f(r['b_med'])} | {r['b_n']} | {f(r['he_med'])} ({r['he_n']}) |")
    R = pd.DataFrame(rows); R.to_csv(REPORTS / "cjsj_33_quarterly.csv", index=False)
    Q("")
    v = np.array(val); match = (np.abs(v[:, 0] - v[:, 1]) <= 1).mean(); within = (np.abs(v[:, 0] - v[:, 1]) <= 30).mean()
    Q(f"#### 33c. Validation of the dataset feature\n\nRecomputed elapsed (block timestamp minus last update at or before the block) equals the dataset's `heartbeat_elapsed` within 1 s for {match:.0%} of the 138 volatility incidents and within 30 s for {within:.0%}; Spearman {pd.Series(v[:, 0]).corr(pd.Series(v[:, 1]), method='spearman'):.3f}.")
    Q("")
    pre = R[R.q < "2024Q1"]; post = R[R.q >= "2025Q1"]
    Q("#### 33d. Does the feed's own update behavior explain the 2025-2026 rise? (computed)"); Q("")
    Q(f"- Median gap between updates, all rounds: before 2024 (quarterly medians) {pre.a_med.min():.0f}-{pre.a_med.max():.0f} s; 2025-2026 {post.a_med.min():.0f}-{post.a_med.max():.0f} s (sampled).")
    Q(f"- Median gap during >=3% moves (B): before 2024 {pre.b_med.min():.0f}-{pre.b_med.max():.0f} s; 2025-2026 {post.b_med.min():.0f}-{post.b_med.max():.0f} s.")
    Q(f"- Dataset heartbeat_elapsed of volatility incidents (quarterly medians): before 2024 {pre.he_med.min():.0f}-{pre.he_med.max():.0f} s; 2025-2026 {post.he_med.min():.0f}-{post.he_med.max():.0f} s.")
    return L, dict(info=info, A=A, Bw=Bw, R=R, qs=qs, t0=t0)


if __name__ == "__main__":
    L, st = main(); body = "\n".join(L); print(body)
    (REPORTS / "cjsj_33_body_partial.md").write_text(body)
