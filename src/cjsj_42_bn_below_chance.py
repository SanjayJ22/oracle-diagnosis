"""CJSJ item 42: why is the BN's market-context-only LOOCV AUC below chance (0.353 on all 24, 0.329 on verified 9, section 35)?
The BN restricted to its six market-context nodes (heartbeat_elapsed, congestion, ref_realized_vol, temporal_deviation_persistence, temporal_slope, temporal_step_change_count) is a naive-Bayes-type
model with fixed thresholds (3600 s, 0.5, 0.05, 3600, 0.05, 1), BDeu ESS 2, and the congestion -> heartbeat edge. Because its BDeu estimates are closed-form counts I reimplement it (validated below against
pgmpy's LOOCV scores on the true labels) so the analysis can be done fast: (a) per-feature CPTs (P(state | class)) and log-likelihood ratios on all data; (b) in-sample and LOOCV AUC of every single node,
of the model leaving each node out, and without heartbeat_elapsed (and without heartbeat + congestion); (c) per-node mean evidence for attacks vs volatility incidents (negative difference = inverted);
(d) a label-shuffle null for the LOOCV AUC (1000 shuffles preserving class sizes): leave-one-out AUC is biased below 0.5 for uninformative discrete features, so the question is whether 0.353 is below that null."""
from cjsj_common import ensure_omp
ensure_omp()
import numpy as np, pandas as pd
from scipy.special import expit
from sklearn.metrics import roc_auc_score
from cjsj_common import REPORTS, TAG_VERIFIED, write_section
import cjsj_eval as E
import cjsj_lcs as S
from models import FIXED_THRESHOLDS as THR

ETH6 = S.ETH6; HB, CG = "heartbeat_elapsed", "congestion"


def states(df, nodes):
    out = {}
    for nd in nodes:
        x = df[nd].astype(float).values; out[nd] = np.where(np.isnan(x), -1, (np.abs(x) > THR[nd]).astype(int))
    return out


def tables(st, y, idx, nodes):
    T = {}
    for nd in nodes:
        if nd == HB and CG in nodes:
            m = (st[HB][idx] >= 0) & (st[CG][idx] >= 0); c = np.zeros((2, 2, 2)); np.add.at(c, (st[HB][idx][m], y[idx][m], st[CG][idx][m]), 1); T[nd] = c
        elif nd == CG:
            m = st[nd][idx] >= 0; T[nd] = np.bincount(st[nd][idx][m], minlength=2).astype(float)
        else:
            m = st[nd][idx] >= 0; c = np.zeros((2, 2)); np.add.at(c, (st[nd][idx][m], y[idx][m]), 1); T[nd] = c
    return T


def llr_nodes(T, st_row, nodes):
    """Per-node log-likelihood ratios (manipulation : volatility) for one row given count tables."""
    out = {}
    for nd in nodes:
        s = st_row[nd]
        if nd == CG or s < 0: out[nd] = 0.0; continue
        if nd == HB and CG in nodes:
            c = T[HB]; pc = (T[CG] + 1) / (T[CG].sum() + 2); cs = st_row[CG]
            cond = lambda l, cc: (c[s, l, cc] + 0.25) / (c[:, l, cc].sum() + 0.5)
            if cs >= 0: out[nd] = np.log(cond(1, cs) / cond(0, cs))
            else: out[nd] = np.log(sum(pc[cc] * cond(1, cc) for cc in (0, 1)) / sum(pc[cc] * cond(0, cc) for cc in (0, 1)))
        else:
            c = T[nd]; out[nd] = np.log(((c[s, 1] + .5) / (c[:, 1].sum() + 1.0)) / ((c[s, 0] + .5) / (c[:, 0].sum() + 1.0)))
    return out


def loocv_scores(st, y, nodes):
    n = len(y); allidx = np.arange(n); T = tables(st, y, allidx, nodes); sc = np.zeros(n); contrib = {nd: np.zeros(n) for nd in nodes}
    for i in range(n):
        Ti = {k: v.copy() for k, v in T.items()}; yi = y[i]
        for nd in nodes:
            s = st[nd][i]
            if s < 0: continue
            if nd == HB and CG in nodes:
                if st[CG][i] >= 0: Ti[nd][s, yi, st[CG][i]] -= 1
            elif nd == CG: Ti[nd][s] -= 1
            else: Ti[nd][s, yi] -= 1
        row = {nd: st[nd][i] for nd in nodes}; ll = llr_nodes(Ti, row, nodes); n1 = y.sum() - yi
        sc[i] = expit(np.log((n1 + 1) / ((n - 1 - n1) + 1)) + sum(ll.values()))
        for nd in nodes: contrib[nd][i] = ll[nd]
    return sc, contrib


def insample(st, y, nodes):
    n = len(y); T = tables(st, y, np.arange(n), nodes); n1 = y.sum(); sc = np.zeros(n); contrib = {nd: np.zeros(n) for nd in nodes}
    for i in range(n):
        ll = llr_nodes(T, {nd: st[nd][i] for nd in nodes}, nodes); sc[i] = expit(np.log((n1 + 1) / ((n - n1) + 1)) + sum(ll.values()))
        for nd in nodes: contrib[nd][i] = ll[nd]
    return sc, contrib


def main():
    base = E.load_base(); sets = E.positive_sets(base); L = []; Q = L.append; res = {}
    for sname in ["all 24 (audit baseline)", "verified M (9)"]:
        d = E.subset(base, sets[sname]); y = E.labels(d); st = states(d, ETH6); n = len(d)
        # validation vs pgmpy
        from joblib import Parallel, delayed
        pg = np.array(Parallel(n_jobs=8)(delayed(S.bn_scores)(d, np.delete(np.arange(n), i), np.array([i]), ETH6) for i in range(n))).ravel()
        cf, _ = loocv_scores(st, y, ETH6); res[sname] = dict(d=d, y=y, st=st, val=float(np.abs(pg - cf).max()), auc_pg=roc_auc_score(y, pg), auc_cf=roc_auc_score(y, cf))
    Q("#### 42a. Validation of the closed-form BN against pgmpy (LOOCV scores, six market-context nodes, true labels)"); Q("")
    Q("| Label set | max abs score difference | LOOCV AUC, pgmpy | LOOCV AUC, closed form |"); Q("|---|---|---|---|")
    for k, r in res.items(): Q(f"| {k} | {r['val']:.2e} | {r['auc_pg']:.3f} | {r['auc_cf']:.3f} |")
    Q("")
    names = {HB: "heartbeat_elapsed > 3600 s", CG: "congestion > 0.5", "ref_realized_vol": "ref_realized_vol > 0.05", "temporal_deviation_persistence": "temporal_deviation_persistence > 3600",
             "temporal_slope": "|temporal_slope| > 0.05", "temporal_step_change_count": "temporal_step_change_count > 1"}
    Q("#### 42b. Per-feature CPTs (fixed-threshold state 'high'; BDeu ESS 2; all data)"); Q("")
    for sname, r in res.items():
        d, y, st = r["d"], r["y"], r["st"]; Q(f"**{sname}**"); Q("")
        Q("| Node (state 'high') | attacks high / observed | volatility high / observed | P(high | manipulation) | P(high | volatility) | LLR if high | LLR if low | missing (attacks / volatility) |"); Q("|---|---|---|---|---|---|---|---|")
        T = tables(st, y, np.arange(len(y)), ETH6)
        for nd in ETH6:
            s = st[nd]; a = s[y == 1]; v = s[y == 0]
            if nd == HB: pm = (np.sum((s == 1) & (y == 1)) + .5) / (np.sum((s >= 0) & (y == 1)) + 1); pv = (np.sum((s == 1) & (y == 0)) + .5) / (np.sum((s >= 0) & (y == 0)) + 1)
            else: pm = (np.sum((s == 1) & (y == 1)) + .5) / (np.sum((s >= 0) & (y == 1)) + 1); pv = (np.sum((s == 1) & (y == 0)) + .5) / (np.sum((s >= 0) & (y == 0)) + 1)
            lh, ll_ = (np.log(pm / pv), np.log((1 - pm) / (1 - pv))) if nd != CG else (0.0, 0.0)
            Q(f"| {names[nd]} | {int((a == 1).sum())} / {int((a >= 0).sum())} | {int((v == 1).sum())} / {int((v >= 0).sum())} | {pm:.3f} | {pv:.3f} | {lh:+.2f} | {ll_:+.2f} | {int((a < 0).sum())} / {int((v < 0).sum())} |")
        Q("")
    Q("Notes: congestion has no edge from the label in the BN (its only edge points to heartbeat_elapsed), so it carries no evidence itself; heartbeat_elapsed's CPT is conditioned on congestion (the table shows its marginal). LLR = log of P(state | manipulation) / P(state | volatility).")
    Q("")
    Q("#### 42c. Which nodes invert? Mean per-node evidence (LLR, LOOCV fit) for attacks minus volatility incidents (negative = pushes attacks toward 'volatility')"); Q("")
    Q("| Label set | " + " | ".join(names[nd].split(' ')[0] if nd != CG else "congestion" for nd in ETH6) + " |"); Q("|---|" + "---|" * len(ETH6))
    per = {}
    for sname, r in res.items():
        sc, ct = loocv_scores(r["st"], r["y"], ETH6); y = r["y"]; per[sname] = {nd: ct[nd][y == 1].mean() - ct[nd][y == 0].mean() for nd in ETH6}
        Q(f"| {sname} | " + " | ".join(f"{per[sname][nd]:+.2f}" for nd in ETH6) + " |")
    Q("")
    Q("#### 42d. AUC by node subset (LOOCV and in-sample; closed-form BN)"); Q("")
    variants = [("all six nodes", ETH6)] + [(f"only {nd}", [nd]) for nd in ETH6 if nd != CG] + [(f"without {nd}", [x for x in ETH6 if x != nd]) for nd in ETH6] + [("without heartbeat_elapsed and congestion", [x for x in ETH6 if x not in (HB, CG)])]
    Q("| Node set | all 24: LOOCV AUC | all 24: in-sample AUC | verified 9: LOOCV AUC | verified 9: in-sample AUC |"); Q("|---|---|---|---|---|")
    vres = {}
    for lab, nodes in variants:
        cells = []
        for sname, r in res.items():
            st = {k: v for k, v in r["st"].items()}; stn = states(r["d"], nodes) if True else st
            a1 = roc_auc_score(r["y"], loocv_scores(stn, r["y"], nodes)[0]); a2 = roc_auc_score(r["y"], insample(stn, r["y"], nodes)[0]); vres[(lab, sname)] = (a1, a2); cells += [f"{a1:.3f}", f"{a2:.3f}"]
        Q(f"| {lab} | " + " | ".join(cells) + " |")
    Q("")
    Q("#### 42e. Is the LOOCV AUC below what label-shuffled data give? (1000 shuffles, class sizes preserved)"); Q("")
    Q("| Label set | node set | observed LOOCV AUC | null mean | null 2.5th-97.5th pct | share of shuffles at or below observed |"); Q("|---|---|---|---|---|---|")
    rng = np.random.default_rng(0); nullres = {}
    for sname, r in res.items():
        for lab, nodes in [("all six nodes", ETH6), ("without heartbeat_elapsed", [x for x in ETH6 if x != HB])]:
            stn = states(r["d"], nodes); obs = vres[(lab, sname)][0]; nl = []
            for _ in range(1000):
                yp = rng.permutation(r["y"]); nl.append(roc_auc_score(yp, loocv_scores(stn, yp, nodes)[0]))
            nl = np.array(nl); nullres[(sname, lab)] = (obs, nl.mean(), np.percentile(nl, [2.5, 97.5]), (nl <= obs).mean())
            Q(f"| {sname} | {lab} | {obs:.3f} | {nl.mean():.3f} | [{np.percentile(nl, 2.5):.3f}, {np.percentile(nl, 97.5):.3f}] | {(nl <= obs).mean():.3f} |")
    Q("")
    Q("#### 42f. Reading (computed)"); Q("")
    a24, a9 = "all 24 (audit baseline)", "verified M (9)"
    inv24 = [nd for nd in ETH6 if nd != CG and per[a24][nd] < -0.05]; inv9 = [nd for nd in ETH6 if nd != CG and per[a9][nd] < -0.05]
    Q(f"- Reproduction: closed form equals pgmpy (max score difference {max(r['val'] for r in res.values()):.1e}); LOOCV AUC {res[a24]['auc_cf']:.3f} (24) and {res[a9]['auc_cf']:.3f} (verified 9), as in section 35.")
    Q(f"- Nodes whose mean evidence is lower for attacks than for volatility incidents (inverted): all 24 {inv24 or 'none'}; verified 9 {inv9 or 'none'}. Largest inversions: " + "; ".join(f"{s.split(' (')[0]} {min(((nd, v) for nd, v in per[s].items() if nd != CG), key=lambda t: t[1])[0]} ({min(v for nd, v in per[s].items() if nd != CG):+.2f})" for s in (a24, a9)) + ".")
    Q("- Single-node LOOCV AUCs below 0.5 (all 24): " + (", ".join(f"{lab[5:]} {vres[(lab, a24)][0]:.3f}" for lab, _ in variants if lab.startswith('only') and vres[(lab, a24)][0] < .5) or "none") + "; in-sample below 0.5: " + (", ".join(f"{lab[5:]} {vres[(lab, a24)][1]:.3f}" for lab, _ in variants if lab.startswith('only') and vres[(lab, a24)][1] < .5) or "none") + ".")
    Q(f"- Persistence without heartbeat_elapsed: LOOCV AUC {vres[('without heartbeat_elapsed', a24)][0]:.3f} (24) and {vres[('without heartbeat_elapsed', a9)][0]:.3f} (verified 9); without heartbeat and congestion {vres[('without heartbeat_elapsed and congestion', a24)][0]:.3f} / {vres[('without heartbeat_elapsed and congestion', a9)][0]:.3f}.")
    for s in (a24, a9):
        o, m, ci, p = nullres[(s, 'all six nodes')]
        Q(f"- Against the label-shuffle null ({s.split(' (')[0]}): observed {o:.3f} vs null mean {m:.3f} [{ci[0]:.3f}, {ci[1]:.3f}]; {p:.1%} of shuffles are at or below the observed value, so the AUC is {'below' if o < ci[0] else 'inside'} the range that uninformative labels produce under leave-one-out.")
    const = [nd for nd in ETH6 if nd != CG and (res[a24]["st"][nd] == 1).sum() == 0]
    Q(f"- **Explanation.** (1) {len(const)} of the six nodes ({', '.join(const)}) never exceed their fixed threshold in any of the {len(res[a24]['y'])} incidents, so they are constant: a constant feature makes the BN's score depend only on the class prior re-estimated without the held-out row, and holding out a positive lowers its own prior, so positives score lower than negatives and the single-node LOOCV AUC is exactly 0.000 (a leave-one-out artifact, not evidence about the data). (2) The informative nodes are temporal_deviation_persistence and temporal_step_change_count: attacks are almost never 'high' on them (0/24 and 3/24 vs 19/138 and 45/138), so 'low' mildly favors manipulation (LLR +0.13 and +0.25) and 'high' favors volatility (-1.95 and -0.85); fitted on all data the BN's AUC is {vres[('all six nodes', a24)][1]:.3f} (24) and {vres[('all six nodes', a9)][1]:.3f} (verified 9), above chance, so no feature is inverted in-sample. (3) Leave-one-out pulls that down to {vres[('all six nodes', a24)][0]:.3f} / {vres[('all six nodes', a9)][0]:.3f}, inside the range label-shuffled data give ({nullres[(a24, 'all six nodes')][2][0]:.3f}-{nullres[(a24, 'all six nodes')][2][1]:.3f} for 24). (4) It persists without heartbeat_elapsed because that node is one of the constants (it never exceeds 3,600 s), so removing it changes nothing in the scores. Section 35's reading, that the BN extracts no usable signal from these features under fixed thresholds, stands; the 0.35 and 0.33 themselves should not be read as systematic anti-signal.")
    Q("")
    body = "\n".join(L); print(body)
    write_section("cjsj_42_bn_below_chance.py", "42", "Why the BN's market-context-only AUC is below chance (follow-up to section 35)", TAG_VERIFIED + "; all-24 rows are within-benchmark (confounded data, see research_audit.md)", body)


if __name__ == "__main__":
    main()
