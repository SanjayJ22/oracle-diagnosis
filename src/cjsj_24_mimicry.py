"""CJSJ item 24: evasion by mimicry (threat model). Each attack's features are moved toward its nearest volatility incident by a fraction a:
x' = x + a * (x_nn - x). The nearest volatility incident is found in standardized ALW space (median-imputed, distance as cjsj_lc.nn_order) over all 138.
Only features the attack actually has are shifted (a missing value stays missing: an attacker cannot create data that is not observed); if the neighbour's value is
missing the attack's value is kept. reserve_skew is used clipped at +-3 (project convention).
Models (trained WITHOUT the attack, i.e. leave-one-attack-out, on the other attacks + all 138 volatility incidents): BN (full production), RF (150 trees, ALW), XGB (fixed
config, ALW). Threshold .5. Three attacker capabilities:
  all features   : every feature moves (worst case, white-box)
  venue side only: reserve_skew, reserve_skew_localization, price_dev, cross_venue_spread, dex_oracle_spread move (an attacker who spreads or disguises venue effects)
  ETH context only: heartbeat, congestion, ref_realized_vol, temporal_* move (features of the ETH market; tests how much each model leans on the shortcut)
Reported: recall vs a in {0, .25, .5, .75, 1} with 95% bootstrap CI over attacks, mean P(manipulation), and the smallest a on a 0.05 grid at which the model stops flagging the attack
(a*; 'never' if still flagged at a=1). Attack sets: verified M (9) evaluated with models trained on verified M + negatives; all 24 with models trained on all 24 + negatives."""
from cjsj_common import ensure_omp
ensure_omp()
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from cjsj_common import TAG_VERIFIED, write_section
import cjsj_eval as E
import cjsj_lc as LC
import cjsj_lcs as S
from models import BN_RAW_TO_DISCRETE, RESERVE_SKEW_CLIP

VENUE = ["reserve_skew", "reserve_skew_localization", "price_dev", "cross_venue_spread", "dex_oracle_spread"]
ETHC = ["heartbeat_elapsed", "congestion", "ref_realized_vol", "temporal_deviation_persistence", "temporal_slope", "temporal_step_change_count", "temporal_gap_trend"]
ALLF = sorted(set(VENUE + ETHC))
GRID = np.round(np.arange(0, 1.0001, 0.05), 2); REP = [0, 0.25, 0.5, 0.75, 1.0]


def one_attack(base, pos_inc, inc, fs):
    i = int(base.index[base.incident == inc][0]); base = base.copy()
    for c in ALLF: base[c] = (base[c].replace([np.inf, -np.inf], RESERVE_SKEW_CLIP) if c == "reserve_skew" else base[c]).astype(float)
    d0 = base.copy()
    keep = base.label.eq(E.VOL) | base.incident.isin(pos_inc); tr = np.where(keep & (base.index != i))[0]
    row = base.loc[i]; neg = np.where(base.label.values == E.VOL)[0]
    nn = LC.nn_order(base, E.feats(base).iloc[i], neg)[0]; nrow = base.loc[nn]
    out = {}
    for cap, cols in [("all features", ALLF), ("venue side only", [c for c in VENUE]), ("ETH context only", ETHC)]:
        rows = []
        for a in GRID:
            d = d0.copy()
            for c in cols:
                x, y = row[c], nrow[c]
                d.loc[i, c] = x if (pd.isna(x) or pd.isna(y)) else x + a * (y - x)
            rows.append(d.iloc[[i]])
        big = pd.concat([d0.drop(index=[i])] + rows, ignore_index=False)
        # stack shifted rows after the base rows so one fit serves all a
        big = pd.concat([d0.drop(index=[i]), *rows], ignore_index=True)
        trn = np.where(keep.drop(index=[i]).values)[0]
        te = np.arange(len(d0) - 1, len(d0) - 1 + len(GRID))
        P = S.predict_models(big, trn, te, fs, ["BN", "RF", "XGB"])
        out[cap] = {m: P[m] for m in P}
    return inc, out


def main():
    base = E.load_base(); sets = E.positive_sets(base); fs = S.FEATSETS["all features (baseline)"]; L = []; Q = L.append; res_all = {}
    for sname, key in [("verified M (9)", "verified M (9)"), ("all 24", "all 24 (audit baseline)")]:
        pos = sets[key]; df = E.subset(base, pos)
        res = Parallel(n_jobs=8)(delayed(one_attack)(df, pos, inc, fs) for inc in pos); res_all[sname] = dict(res)
    rng = np.random.default_rng(0)
    for sname in res_all:
        R = res_all[sname]; incs = list(R); Q(f"### Attack set: {sname} ({len(incs)} attacks)"); Q("")
        for cap in ["all features", "venue side only", "ETH context only"]:
            Q(f"#### Attacker can shift: {cap}"); Q("")
            Q("| Model | " + " | ".join(f"recall a={a:g} [CI]" for a in REP) + " | median a* | attacks never stopped (a*>1) |"); Q("|---|" + "---|" * (len(REP) + 2))
            for m in ["BN", "RF", "XGB"]:
                M = np.array([R[i][cap][m] for i in incs])              # attacks x grid
                flag = M >= .5; cells = []
                for a in REP:
                    j = int(np.where(GRID == a)[0][0]); v = flag[:, j].astype(float); bs = [rng.choice(v, len(v)).mean() for _ in range(1000)]
                    cells.append(f"{v.mean():.2f} [{np.percentile(bs, 2.5):.2f}, {np.percentile(bs, 97.5):.2f}]")
                astar = np.array([GRID[np.where(~flag[k])[0][0]] if (~flag[k]).any() else np.inf for k in range(len(incs))])
                caught0 = flag[:, 0]; ast = astar[caught0] if caught0.any() else np.array([np.nan])
                Q(f"| {m} | " + " | ".join(cells) + f" | {np.nanmedian(np.where(np.isinf(ast), 1.05, ast)):.2f}{' (caught at a=0 only: ' + str(int(caught0.sum())) + ')'} | {int(np.isinf(astar[caught0]).sum())} of {int(caught0.sum())} |")
            Q("")
        # ranking
    Q("### Reading (computed)"); Q("")
    Q("a50 = smallest a at which the model's mean recall falls to half of its unshifted (a=0) recall (grid step 0.05; 'none' if it never does before a=1). Paired bootstrap difference in recall at a=0.75 is over attacks (same resamples). At a=1 an attack's features equal its nearest volatility incident's, so near-zero recall there is expected for every model and is not informative.")
    Q("")
    Q("| Attack set | Attacker shifts | BN a50 | RF a50 | XGB a50 | recall a=.75 BN / RF / XGB | BN - RF at a=.75 [CI] | BN - XGB at a=.75 [CI] | RF - XGB at a=.75 [CI] |"); Q("|---|---|---|---|---|---|---|---|---|")
    j75 = int(np.where(GRID == .75)[0][0]); rg = np.random.default_rng(1)
    for sname in res_all:
        R = res_all[sname]; incs = list(R)
        for cap in ["all features", "venue side only", "ETH context only"]:
            F = {m: np.array([R[i][cap][m] >= .5 for i in incs]).astype(float) for m in ["BN", "RF", "XGB"]}
            a50 = {}
            for m in F:
                c = F[m].mean(0); hit = np.where(c <= 0.5 * c[0])[0]; a50[m] = f"{GRID[hit[0]]:.2f}" if (len(hit) and c[0] > 0) else "none"
            def pdiff(m1, m2):
                d = F[m1][:, j75] - F[m2][:, j75]; bs = [rg.choice(d, len(d)).mean() for _ in range(1000)]; return f"{d.mean():+.2f} [{np.percentile(bs, 2.5):+.2f}, {np.percentile(bs, 97.5):+.2f}]"
            Q(f"| {sname} | {cap} | {a50['BN']} | {a50['RF']} | {a50['XGB']} | {F['BN'][:, j75].mean():.2f} / {F['RF'][:, j75].mean():.2f} / {F['XGB'][:, j75].mean():.2f} | {pdiff('BN', 'RF')} | {pdiff('BN', 'XGB')} | {pdiff('RF', 'XGB')} |")
    Q("")
    body = "\n".join(L); print(body)
    write_section("cjsj_24_mimicry.py", "24", "Evasion by mimicry: recall vs fraction moved toward the nearest volatility incident", TAG_VERIFIED + "; all-24 rows are within-benchmark (confounded data, see research_audit.md)", body)


if __name__ == "__main__":
    main()
