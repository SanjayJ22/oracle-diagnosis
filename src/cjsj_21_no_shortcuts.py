"""CJSJ item 21: confound check on the BN's advantages. Rerun the learning-curve (items 12/20), label-noise (item 13) and forward-time-stability
(items 2/8/13d) experiments with the ETH-context features removed, and with ETH-context features only, for BN, RF, XGB (fixed config, RF 150 trees).
Feature sets (cjsj_lcs.FEATSETS):
  baseline                : ALW (8) for RF/XGB, full production BN
  no ETH, venue only      : reserve_skew + reserve_skew_localization for ALL three models (BN keeps only those two nodes)
  no ETH, extended        : + price_dev, cross_venue_spread, dex_oracle_spread (BN and ML share them; note ML median-imputation can encode missingness, audit C3)
  ETH-context only        : heartbeat_elapsed, congestion, ref_realized_vol, temporal_{deviation_persistence, slope, step_change_count} (6 that the BN has nodes for)
ETH-context = every feature that is a property of the ETH market rather than of the attacked venue (heartbeat, congestion, ref_realized_vol, temporal_*).
A. learning curve: 30 seeds, protocol of item 12, plus recall at matched false alarms (item 20 method; BN's false alarms at .5 set the budget).
B. static label noise: verified-M base, 20 seeds, flips k=1..3 random / targeted (nearest to MEVBOTa47b in ALW space), + MEVBOTa47b.
C. forward-time stability: 7 audit cutoffs, verified M (9) and all 24 as training positives, false alarms and manipulations caught, RF/XGB/BN.
D. forward-time label noise (cutoffs 2023-01, 2023-07, 2024-01): 20 seeds random flips k=1..3, targeted k=3, + MEVBOTa47b.
Raw: reports/cjsj_21_*.csv. Verified-M rows use verified labels; negatives unchanged (C1-C3 still apply, and removing ETH-context features leaves few informative features)."""
from cjsj_common import ensure_omp
ensure_omp()
import time
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from cjsj_common import REPORTS, TAG_VERIFIED, write_section
import cjsj_eval as E
import cjsj_lc as LC
import cjsj_lcs as S

W3 = ["BN", "RF", "XGB"]; MEV = "MEVBOTa47b"
SHORT = {"all features (baseline)": "baseline", "no ETH-context, venue only (reserve_skew, localization)": "no ETH, venue only",
         "no ETH-context, extended (+price_dev, cross_venue_spread, dex_oracle_spread)": "no ETH, extended", "ETH-context only (6 BN-compatible features)": "ETH-context only"}
LCPOOLS = {"verified M (9)": [2, 3, 4, 6, 9], "all 24": [2, 4, 10, 20]}


def bm(v, B=1000, seed=0):
    v = np.asarray(v, float); rng = np.random.default_rng(seed); b = [rng.choice(v, len(v)).mean() for _ in range(B)]
    return v.mean(), *np.percentile(b, [2.5, 97.5])


def lc_task(df, pool, fsn, k, seed):
    r = S.protocol_scores(df, pool, S.FEATSETS[fsn], W3, n_sub=k, seed=1000 * k + seed); fa_bn = int((r["neg"]["BN"] >= .5).sum()); out = []
    for m in W3:
        n, p = r["neg"][m], r["pos"][m]
        out.append(dict(fs=fsn, k=k, seed=seed, model=m, fa=int((n >= .5).sum()), rec=float((p >= .5).mean()), rec_matched=S.recall_at_fa(n, p, fa_bn), auc=S.auc(n, p)))
    return out


def noise_task(df, pool, fsn, mode, k, seed, target, extra, cond):
    r = S.protocol_scores(df, pool, S.FEATSETS[fsn], W3, extra_pos=extra, flip_mode=mode, k_flip=k, seed=seed, target_row=target)
    return [dict(fs=fsn, cond=cond, seed=seed, model=m, fa=int((r["neg"][m] >= .5).sum()), rec=float((r["pos"][m] >= .5).mean())) for m in W3]


def fwd_one(base, pos_inc, cut, fsn, flip_mode=None, k=0, seed=0, target=None):
    c = pd.Timestamp(cut); rng = np.random.default_rng(seed)
    neg = np.where((base.dt < c) & (base.label == E.VOL))[0]; pos = np.where((base.dt < c) & base.incident.isin(pos_inc))[0]
    te = np.where(base.dt >= c)[0]; d = base
    if k:
        fl = rng.choice(neg, k, replace=False) if flip_mode == "random" else LC.nn_order(base, target, neg)[:k]
        d = base.copy(); d.loc[fl, "label"] = E.MAN
    P = S.predict_models(d, np.concatenate([neg, pos]), te, S.FEATSETS[fsn], W3)
    isneg = (base.label.values[te] == E.VOL); ismanp = ~isneg & base.incident.isin(pos_inc).values[te]
    return {m: (int((P[m][isneg] >= .5).sum()), int((P[m][ismanp] >= .5).sum()), int(ismanp.sum()), int(isneg.sum())) for m in W3}


def main():
    t0 = time.time(); base = E.load_base(); sets = E.positive_sets(base); ver = sets["verified M (9)"]; allp = sets["all 24 (audit baseline)"]
    target = E.feats(base).loc[base.incident == MEV].iloc[0]; FSN = list(S.FEATSETS)
    L = []; Q = L.append
    Q("Feature-set names: " + "; ".join(f"**{SHORT[k]}** = {', '.join(S.FEATSETS[k]['ml'])}" for k in FSN) + ".")
    Q("")
    # ---------- A ----------
    A = []
    for pname, ks in LCPOOLS.items():
        pool = ver if pname.startswith("verified") else allp; df = E.subset(base, pool)
        res = Parallel(n_jobs=8)(delayed(lc_task)(df, pool, fsn, k, s) for fsn in FSN for k in ks for s in range(30))
        for rr in res:
            for r in rr: A.append(dict(pool=pname, **r))
        print("A", pname, f"{time.time() - t0:.0f}s", flush=True)
    A = pd.DataFrame(A); A.to_csv(REPORTS / "cjsj_21_learning_curve.csv", index=False)
    Q("### 21a. Learning curve by feature set (false alarms of 138 at .5 / recall at .5; recall at BN-matched false alarms; paired BN minus model)"); Q("")
    adv = {}
    for pname, ks in LCPOOLS.items():
        for fsn in FSN:
            Q(f"#### {pname}, {SHORT[fsn]}"); Q("")
            Q("| k | BN FA / rec | RF FA / rec | XGB FA / rec | RF rec at matched FA [CI] | XGB rec at matched FA [CI] | BN - RF (matched) [CI] | BN - XGB (matched) [CI] |"); Q("|---|---|---|---|---|---|---|---|")
            for k in ks:
                d = {m: A[(A.pool == pname) & (A.fs == fsn) & (A.k == k) & (A.model == m)].sort_values("seed") for m in W3}
                f = lambda m: f"{d[m].fa.mean():.1f} / {d[m].rec.mean():.2f}"
                g = lambda t: f"{t[0]:.2f} [{t[1]:.2f}, {t[2]:.2f}]"
                def diff(m):
                    x = d["BN"].rec.values - d[m].rec_matched.values; rng = np.random.default_rng(0); b = [rng.choice(x, len(x)).mean() for _ in range(1000)]
                    return x.mean(), *np.percentile(b, [2.5, 97.5])
                dr, dx = diff("RF"), diff("XGB"); adv[(pname, fsn, k)] = (dr, dx)
                sg = lambda t: f"{t[0]:+.2f} [{t[1]:+.2f}, {t[2]:+.2f}]" + (" *" if t[1] > 0 else "")
                Q(f"| {k} | {f('BN')} | {f('RF')} | {f('XGB')} | {g(bm(d['RF'].rec_matched))} | {g(bm(d['XGB'].rec_matched))} | {sg(dr)} | {sg(dx)} |")
            Q("")
    Q("`*` = 95% CI (over seeds) excludes 0 in the BN's favour.")
    Q("")
    # ---------- B ----------
    dv = E.subset(base, ver); dm = E.subset(base, ver + [MEV]); conds = [("clean", None, 0, ())] + [(f"random flips k={k}", "random", k, ()) for k in (1, 2, 3)] + \
        [(f"targeted flips k={k}", "nn", k, ()) for k in (1, 2, 3)] + [("+ MEVBOTa47b", None, 0, (MEV,))]
    jobs = []
    for fsn in FSN:
        for cond, mode, k, extra in conds:
            for s in range(20): jobs.append((dm if extra else dv, ver, fsn, mode, k, 3000 + 50 * k + s, target, extra, cond))
    res = Parallel(n_jobs=8)(delayed(noise_task)(*j) for j in jobs); B = pd.DataFrame([r for rr in res for r in rr]); B.to_csv(REPORTS / "cjsj_21_label_noise.csv", index=False)
    print("B", f"{time.time() - t0:.0f}s", flush=True)
    Q("### 21b. Static label noise by feature set (verified-M base; false alarms of 138, mean over 20 seeds; recall on the 9 verified positives in brackets)"); Q("")
    Q("| Feature set | Condition | BN FA (rec) | RF FA (rec) | XGB FA (rec) |"); Q("|---|---|---|---|---|")
    noise = {}
    for fsn in FSN:
        for cond, *_ in conds:
            cells = []
            for m in W3:
                d = B[(B.fs == fsn) & (B.cond == cond) & (B.model == m)]; noise[(fsn, cond, m)] = d.fa.mean(); cells.append(f"{d.fa.mean():.1f} ({d.rec.mean():.2f})")
            Q(f"| {SHORT[fsn]} | {cond} | " + " | ".join(cells) + " |")
    Q("")
    # ---------- C ----------
    Q("### 21c. Forward-time stability by feature set (train < cutoff, test >= cutoff; audit skip rule; RF 150 trees, XGB fixed config)"); Q("")
    fw = {}
    for tname, pos_inc in [("verified M (9)", ver), ("all 24", allp)]:
        ok = []
        for c in E.CUTOFFS:
            cc = pd.Timestamp(c); ntp = int(base.incident.isin(pos_inc)[(base.dt < cc)].sum()); nte = int((base.incident.isin(pos_inc) & (base.dt >= cc)).sum())
            if ntp >= 3 and nte >= 2: ok.append(c)
        res = Parallel(n_jobs=8)(delayed(fwd_one)(base, pos_inc, c, fsn) for fsn in FSN for c in ok)
        it = iter(res); Q(f"#### training positives: {tname}"); Q("")
        Q("| Feature set | Cutoff | BN FA / caught | RF FA / caught | XGB FA / caught |"); Q("|---|---|---|---|---|")
        for fsn in FSN:
            tot = {m: [0, 0, 0] for m in W3}
            for c in ok:
                r = next(it)
                for m in W3: tot[m][0] += r[m][0]; tot[m][1] += r[m][1]; tot[m][2] += r[m][2]
                Q(f"| {SHORT[fsn]} | {c[:7]} | " + " | ".join(f"{r[m][0]}/{r[m][3]} / {r[m][1]}/{r[m][2]}" for m in W3) + " |")
            fw[(tname, fsn)] = tot
            Q(f"| **{SHORT[fsn]} sum over cutoffs** | | " + " | ".join(f"**{tot[m][0]} FA / {tot[m][1]}/{tot[m][2]} caught**" for m in W3) + " |")
        Q("")
    print("C", f"{time.time() - t0:.0f}s", flush=True)
    # ---------- D ----------
    FC = ["2023-01-01", "2023-07-01", "2024-01-01"]
    jobs = []
    for fsn in FSN:
        for c in FC:
            jobs += [(base, ver, c, fsn, None, 0, 0, None, "clean"), (base, ver + [MEV], c, fsn, None, 0, 0, None, "+ MEVBOTa47b"), (base, ver, c, fsn, "nn", 3, 0, target, "targeted flips k=3")]
            jobs += [(base, ver, c, fsn, "random", k, 9000 + 100 * k + s, None, f"random flips k={k}") for k in (1, 2, 3) for s in range(20)]
    res = Parallel(n_jobs=8)(delayed(lambda j: (j[3], j[2], j[8], fwd_one(*j[:8])))(j) for j in jobs)
    D = pd.DataFrame([dict(fs=f, cut=c, cond=cd, model=m, fa=v[0], nte=v[3]) for f, c, cd, r in res for m, v in r.items()]); D.to_csv(REPORTS / "cjsj_21_forward_noise.csv", index=False)
    Q("### 21d. Forward-time label noise by feature set (verified-M training; false alarms on volatility incidents at/after the cutoff; mean over 20 seeds for random flips)"); Q("")
    Q("| Feature set | Cutoff | Condition | BN FA | RF FA | XGB FA |"); Q("|---|---|---|---|---|---|")
    fn = {}
    for fsn in FSN:
        for c in FC:
            for cond in ["clean", "random flips k=1", "random flips k=2", "random flips k=3", "targeted flips k=3", "+ MEVBOTa47b"]:
                cells = []
                for m in W3:
                    v = D[(D.fs == fsn) & (D.cut == c) & (D.cond == cond) & (D.model == m)].fa; fn[(fsn, c, cond, m)] = v.mean(); cells.append(f"{v.mean():.1f}")
                Q(f"| {SHORT[fsn]} | {c[:7]} | {cond} | " + " | ".join(cells) + " |")
    Q("")
    # ---------- E ----------
    Q("### 21e. Does any BN advantage survive without the shortcut features? (computed)"); Q("")
    Q("| Feature set | (1) BN recall advantage at k=2-4 after matching FA (verified pool): k with CI>0 vs RF / vs XGB | (2) static-noise FA growth at k=3 random flips: BN / RF / XGB | (3) forward FAs summed over cutoffs, verified-M training: BN / RF / XGB | (4) forward FA growth under 3 random flips (mean over 3 cutoffs): BN / RF / XGB |"); Q("|---|---|---|---|---|")
    for fsn in FSN:
        ks = [k for k in LCPOOLS["verified M (9)"] if 2 <= k <= 4]
        a1 = [k for k in ks if adv[("verified M (9)", fsn, k)][0][1] > 0]; a2 = [k for k in ks if adv[("verified M (9)", fsn, k)][1][1] > 0]
        g2 = " / ".join(f"{noise[(fsn, 'random flips k=3', m)] - noise[(fsn, 'clean', m)]:+.1f}" for m in W3)
        t = fw[("verified M (9)", fsn)]; g3 = " / ".join(str(t[m][0]) for m in W3)
        g4 = " / ".join(f"{np.mean([fn[(fsn, c, 'random flips k=3', m)] - fn[(fsn, c, 'clean', m)] for c in FC]):+.1f}" for m in W3)
        Q(f"| {SHORT[fsn]} | {a1 or 'none'} / {a2 or 'none'} | {g2} | {g3} | {g4} |")
    Q("")
    Q(f"(runtime {time.time() - t0:.0f}s; cjsj_21_no_shortcuts.py)")
    body = "\n".join(L); print(body)
    write_section("cjsj_21_no_shortcuts.py", "21", "Confound check on the BN's advantages: ETH-context features removed / ETH-context only", TAG_VERIFIED, body)


if __name__ == "__main__":
    main()
