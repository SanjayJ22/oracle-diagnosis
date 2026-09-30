"""CJSJ item 33 (final): pooled before/after comparisons from the cached Chainlink rounds (cjsj_33_chainlink.py cache) and the configuration-change table (cjsj_33b_config.py),
then writes section 33. Splits: phase 7 aggregator launch (2024-09-18) and its first configCount change (2025-01-06). For the 138 volatility incidents: recomputed elapsed since last update at
the incident block, local median update gap within +-1 h of the block, number of updates in that hour, and their ratio; plus calm-market samples: share of gaps >= 3000 s (heartbeat-triggered) and
median |price change| of deviation-triggered updates (gap < 3000 s), by period."""
import numpy as np, pandas as pd
from datetime import datetime, timezone
from scipy.stats import mannwhitneyu, spearmanr
import cjsj_33_chainlink as C
import cjsj_eval as E
from cjsj_common import REPORTS, TAG_CONFOUNDED, rpc, write_section


def main():
    info = C.phase_info(); base = E.load_base(); v = base[base.label == E.VOL]; L = []; Q = L.append
    body = (REPORTS / "cjsj_33_body_partial.md").read_text(); cfg = pd.read_csv(REPORTS / "cjsj_33b_config.csv")
    T7 = info[7]["t_first"]; CC1 = int(pd.Timestamp("2025-01-06", tz="UTC").timestamp())
    rows = []
    for r in v.itertuples():
        bt = int(rpc("eth_getBlockByNumber", [hex(int(r.block)), False])["timestamp"], 16)
        rid, d = C.find_round(bt, info); rs = [x for x in C.rounds([rid + k for k in range(-50, 51)]) if x]; ts = np.array([x[3] for x in rs]); m = (ts >= bt - 3600) & (ts <= bt + 3600)
        g = np.diff(ts[m]); rows.append(dict(incident=r.incident, t=bt, elapsed=bt - d[3], ds_elapsed=r.heartbeat_elapsed, med_gap=np.median(g) if g.size else np.nan, n_upd=int(m.sum())))
    B = pd.DataFrame(rows); B["ratio"] = B.elapsed / B.med_gap
    def cmp(col, t0):
        a, b = B[B.t < t0][col].dropna(), B[B.t >= t0][col].dropna(); return len(a), len(b), a.median(), b.median(), mannwhitneyu(a, b).pvalue
    Q(body.split("#### 33d")[0].rstrip()); Q("")
    Q("#### 33e. Feed configuration changes (from `latestConfigDetails().configCount` over historical blocks; `reports/cjsj_33b_config.csv`)"); Q("")
    Q("| Phase (aggregator) | event | block | date (UTC) |"); Q("|---|---|---|---|")
    for r in cfg.dropna(subset=["event"]).itertuples(): Q(f"| {r.phase} | {r.event} | {int(r.block)} | {r.time} |")
    Q(""); Q("Phase 3's aggregator did not answer `latestConfigDetails` (older contract type). A configCount increase means the oracle set / offchain configuration (which carries the update-trigger parameters) was replaced; the contents of the configuration were not decoded.")
    Q("")
    Q("#### 33f. Pooled before/after comparisons (volatility incidents; recomputed elapsed validated in 33c)"); Q("")
    Q("| Quantity | split | n before / after | median before | median after | Mann-Whitney p |"); Q("|---|---|---|---|---|---|")
    for col, lab in [("ds_elapsed", "dataset heartbeat_elapsed"), ("elapsed", "recomputed elapsed since last update at the incident block"), ("med_gap", "local median update gap within +-1 h of the incident"), ("n_upd", "updates in the +-2 h window"), ("ratio", "elapsed / local median gap")]:
        for t0, nm in [(T7, "phase 7 launch 2024-09-18"), (CC1, "first phase-7 config change 2025-01-06")]:
            n1, n2, m1, m2, p = cmp(col, t0); Q(f"| {lab} | {nm} | {n1} / {n2} | {m1:.4g} | {m2:.4g} | {p:.2g} |")
    Q("")
    # calm-market samples from cached rounds: rebuild A windows
    A = []
    for q in sorted({C.q_of(t) for t in range(int(pd.Timestamp("2020-10-01", tz="UTC").timestamp()), info[7]["t_last"], 86400 * 30)}):
        y, k = int(q[:4]), int(q[-1]); a = datetime(y, 3 * (k - 1) + 1, 1, tzinfo=timezone.utc).timestamp(); b = datetime(y + (k == 4), (3 * k) % 12 + 1, 1, tzinfo=timezone.utc).timestamp()
        for f in (0.2, 0.5, 0.8):
            t = a + f * (b - a)
            if t < info[3]["t_first"] or t > info[7]["t_last"]: continue
            rid, d = C.find_round(t, info); rs = [r for r in C.rounds([rid + k2 for k2 in range(250)]) if r]; ts = np.array([r[3] for r in rs]); pr = np.array([r[1] / 1e8 for r in rs])
            if len(ts) > 5: A.append(dict(t=t, gaps=np.diff(ts), dp=np.abs(np.diff(pr)) / pr[:-1]))
    def pool(lo, hi):
        g = np.concatenate([w["gaps"] for w in A if lo <= w["t"] < hi]); dp = np.concatenate([w["dp"] for w in A if lo <= w["t"] < hi]); return g, dp
    Q("#### 33g. Calm-and-volatile sampled windows (design A), by period"); Q("")
    Q("| Period | updates sampled | median gap (s) | share of gaps >= 3000 s | median |price change| of updates with gap < 3000 s | p10 of that change |"); Q("|---|---|---|---|---|---|")
    bounds = [("2021Q2-2024Q2 (before phase 7)", int(pd.Timestamp("2021-04-01", tz="UTC").timestamp()), T7), ("phase 7 until first config change (2024-09-18 to 2025-01-06)", T7, CC1), ("after 2025-01-06", CC1, info[7]["t_last"] + 1)]
    sts = {}
    for nm, lo, hi in bounds:
        g, dp = pool(lo, hi); dev = dp[g < 3000]; sts[nm] = (np.median(g), (g >= 3000).mean(), np.median(dev), len(g), np.percentile(dev, 10))
        Q(f"| {nm} | {len(g)} | {np.median(g):.0f} | {(g >= 3000).mean():.2f} | {100 * np.median(dev):.2f}% | {100 * np.percentile(dev, 10):.2f}% |")
    Q("")
    n1, n2, m1, m2, p = cmp("ds_elapsed", T7); _, _, e1, e2, pe = cmp("elapsed", T7); _, _, g1, g2, pg = cmp("med_gap", T7); _, _, r1, r2, pr_ = cmp("ratio", T7)
    qdf = pd.read_csv(REPORTS / "cjsj_33_quarterly.csv"); ok = qdf.dropna(subset=["a_med", "he_med"])
    rho_a = spearmanr(ok.a_med, ok.he_med)[0]; ok2 = qdf.dropna(subset=["b_med", "he_med"]); rho_b = spearmanr(ok2.b_med, ok2.he_med)[0]
    Q("#### 33h. Does the feed's own update behavior explain the 2025-2026 rise? (computed)"); Q("")
    Q(f"- The rise is real in the dataset and recomputable from the chain: dataset `heartbeat_elapsed` median {m1:.0f} s before the phase-7 launch vs {m2:.0f} s after (p = {p:.2g}); recomputed elapsed {e1:.0f} vs {e2:.0f} s (p = {pe:.2g}); recomputation matches the dataset within 30 s for 83% of incidents (33c).")
    Q(f"- The feed's update cadence during the incident windows did NOT slow by a matching amount: local median gap {g1:.0f} s before vs {g2:.0f} s after (p = {pg:.2g}); the elapsed-to-gap ratio moved from {r1:.2f} to {r2:.2f} (p = {pr_:.2g}).")
    Q("- Calm-and-volatile sampling (33g) shows a change in the feed's update rule at the phase-7 launch: " + "; ".join(f"{nm}: heartbeat-triggered share {s[1]:.2f}, median deviation-triggered update {100 * s[2]:.2f}%, 10th percentile {100 * s[4]:.2f}%" for nm, s in sts.items()) +
      ". The median trigger size is unchanged near 0.5%, but before phase 7 a tenth of the non-heartbeat updates followed moves of about 0.05% or less, while from phase 7 on essentially every non-heartbeat update follows a move of at least 0.5%; heartbeat-only updates rose from about 30% to about 45% of gaps.")
    Q(f"- Quarterly correlation between the feed's sampled median gap and the incidents' median elapsed: Spearman {rho_a:+.2f} (all rounds), {rho_b:+.2f} (gaps during >=3% moves); quarters have 3-9 incidents each, so these are weak evidence.")
    Q(f"- Timing: the jump in `heartbeat_elapsed` (546 s in 2024Q4 vs 264 s in 2024Q3) coincides with the launch of the phase-7 aggregator on 2024-09-18 and its first configuration changes (2025-01-06, 2025-06-27, 2025-07-08, 2026-02-05, 2026-05-20, 2026-06-11, 2026-07-18; 33e). The quarterly medians of 504 s and 786 s quoted in the request are not reproduced exactly: the dataset quarterly medians are 492 (2025Q1), 402 (2025Q2), 1140 (2025Q3), 606, 960, 1068, 564 s, with 3-8 incidents per quarter.")
    Q("- **Reading:** partly yes. The feed's own update behavior changed at the phase-7 launch (2024-09-18): updates triggered by small moves (<0.5%) disappeared and a larger share of updates are heartbeat-only (33g), which lengthens the time since the last update at an arbitrary block, and the rise in `heartbeat_elapsed` starts at that date (33f; 2024Q4 546 s vs 2024Q3 264 s). It is not a simple slowdown of updates during large moves: the local median gap around the incidents fell rather than rose (816 s -> 540 s, p = 0.13) and the updates in the +-2 h window are unchanged, but the elapsed-to-gap ratio doubled (0.27 -> 0.60), i.e. incident blocks now sit later in the update cycle. The jump is already present in 2024Q4, before the first phase-7 configuration change (2025-01-06), so it is tied to the launch itself; the later configuration changes (33e) show no further step that this sample can resolve. The data cannot separate a change in trigger behavior from how the incident blocks were anchored relative to the update cycle; causal attribution to a specific configuration change is not established.")
    Q("")
    Q("Limits: rounds are sampled (3 windows of 250 consecutive rounds per quarter; +-50 rounds around each incident), quarterly cells have few incidents, and the free RPC tier's 10-block `eth_getLogs` cap prevented a full AnswerUpdated scan.")
    Q("")
    Q("(scripts cjsj_33_chainlink.py, cjsj_33b_config.py, cjsj_33_finalize.py)")
    out = "\n".join(L); print(out)
    write_section("cjsj_33_finalize.py", "33", "Why heartbeat_elapsed drifts: Chainlink ETH/USD update behavior by quarter and feed configuration changes", TAG_CONFOUNDED + " (oracle-history analysis; uses the 138 volatility incidents' blocks)", out)


if __name__ == "__main__":
    main()
