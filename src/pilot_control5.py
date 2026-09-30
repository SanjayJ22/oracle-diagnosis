"""Negative control (market-context-only) rerun: 3 attacks vs 5 attacks (+ Harvest, UwU). Label: pilot, underpowered per A10.
ETH-context features are the locked seven (pilot_model.ETH), measured at T-1/T exactly as for the other rows.
Harvest and UwU enter through G2 (intra-block), while benign episodes were screened under G1 only: different doors (caveat in the report).
"""
import json
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
from sklearn.metrics import roc_auc_score
import pilot_build as B, pilot_model as M
from pilot_lib import *
from a10_power_analysis import auc_mde, hanley_mcneil_se, se_null

ROOT = Path(__file__).resolve().parent.parent
OUT_PQ = ROOT / "data" / "processed" / "pilot_5att.parquet"
OUT_JS = ROOT / "reports" / "pilot_control5_results.json"
NEW = [dict(episode_id="A-HarvestFinance-11129474", event="Harvest Finance", T=11129474, source="fUSDC vault-read share price (Curve Y zap calc_withdraw_one_coin)",
            g2_peak_dev=-0.008926, g2_value="fUSDC share price, intra-block peak (pilot_g2_harvest.json, T+0)", S_type="vault_read_via_curve"),
       dict(episode_id="A-UwULend-20061319", event="UwU Lend", T=20061319, source="Curve USDe/USDC pool price (get_p spot)",
            g2_peak_dev=0.085712, g2_value="pool price, intra-block peak (pilot_g2_results.json, T)", S_type="curve_spot")]
RNG = np.random.default_rng(20260930)


def build():
    df = pd.read_parquet(B.OUT)
    a = df[df.in_analysis == True].copy()                                   # noqa: E712
    rows = []
    for n in NEW:
        qa = new_qa("control5_" + n["event"])
        e = B.eth_context(n["T"] - 1, n["T"], qa)
        rows.append(dict(episode_id=n["episode_id"], cls="attack", label="M", event=n["event"], source=n["source"], S_type=n["S_type"], T=n["T"],
                         in_analysis=False, g2_peak_dev=n["g2_peak_dev"], g2_value=n["g2_value"], qa_ok=qa.ok,
                         note="G2-entry attack added for the 5-attack control; G1 trigger miss", **e))
        print(n["event"], "ETH ctx:", {k: round(v, 6) for k, v in e.items()}, "QA", qa.ok, qa.failures(), flush=True)
    df = df[~df.episode_id.isin([n['episode_id'] for n in NEW])]          # replace the original G1-miss rows (no ETH features) instead of duplicating them
    out = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
    out.to_parquet(OUT_PQ)
    return a, pd.DataFrame(rows)


def evaluate(frame, kind, n_perm=300, cols=None):
    cols = cols or M.ETH
    y = (frame.cls == "attack").astype(int).values
    X = frame[cols].astype(float).values
    s = M.loocv_scores(X, y, kind)
    auc = float(roc_auc_score(y, s)); npos, nneg = int(y.sum()), int((1 - y).sum())
    se = float(hanley_mcneil_se(min(max(auc, 0.02), 0.98), npos, nneg))
    pi, ni = np.where(y == 1)[0], np.where(y == 0)[0]
    boots = [roc_auc_score(y[i], s[i]) for i in (np.concatenate([RNG.choice(pi, len(pi)), RNG.choice(ni, len(ni))]) for _ in range(2000))]
    r = dict(kind=kind, n_pos=npos, n_neg=nneg, auc=auc, hm_se=se, hm_ci95=[max(0, auc - 1.96 * se), min(1, auc + 1.96 * se)],
             hm_upper_one_sided95=min(1.0, auc + 1.645 * se), boot_upper_one_sided95=float(np.percentile(boots, 95)),
             boot_ci95=[float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))], se_null=float(se_null(npos, nneg)),
             expected_null_upper_bound=0.5 + 1.645 * float(se_null(npos, nneg)), mde_auc=float(auc_mde(npos, nneg)),
             scores={frame.iloc[i].episode_id: float(s[i]) for i in pi})
    if kind == "logit":
        nullc = []
        for _ in range(n_perm):
            yp = RNG.permutation(y); nullc.append(roc_auc_score(yp, M.loocv_scores(X, yp, "logit")))
        nullc = np.array(nullc)
        r.update(perm_null_mean=float(nullc.mean()), perm_null_p95=float(np.percentile(nullc, 95)), perm_p_one_sided=float((1 + (nullc >= auc).sum()) / (1 + n_perm)))
    return r


if __name__ == "__main__":
    a, new = build()
    f3 = a
    f5 = pd.concat([a, new], ignore_index=True)
    res = {"label": "pilot, underpowered per A10", "features": M.ETH, "runs": {}}
    for tag, fr in (("3_attacks", f3), ("5_attacks", f5)):
        for kind in ("logit", "rf"):
            r = evaluate(fr, kind); res["runs"][f"{tag}|{kind}"] = r
            print(f"{tag:10s} {kind:5s} n_pos={r['n_pos']} n_neg={r['n_neg']} AUC={r['auc']:.3f}  HM one-sided95 upper={r['hm_upper_one_sided95']:.3f}  boot upper={r['boot_upper_one_sided95']:.3f} "
                  f"boot CI=[{r['boot_ci95'][0]:.2f},{r['boot_ci95'][1]:.2f}] MDE={r['mde_auc']:.3f} null-expected-upper={r['expected_null_upper_bound']:.3f}"
                  + (f" perm p95={r['perm_null_p95']:.3f} p={r['perm_p_one_sided']:.3f}" if kind == "logit" else ""), flush=True)
    # sensitivity: drop eth_gas_util_T (the block containing the attack tx; may carry the attack's own gas)
    cols = [c for c in M.ETH if c != "eth_gas_util_T"]
    res["sensitivity_without_eth_gas_util_T"] = {}
    for tag, fr in (("3_attacks", f3), ("5_attacks", f5)):
        for kind in ("logit", "rf"):
            r = evaluate(fr, kind, n_perm=0 if kind == "logit" else 0, cols=cols) if False else evaluate(fr, kind, n_perm=1, cols=cols)
            res["sensitivity_without_eth_gas_util_T"][f"{tag}|{kind}"] = {k: r[k] for k in ("n_pos", "auc", "hm_upper_one_sided95", "boot_upper_one_sided95")}
            print(f"[no gas_util_T] {tag:10s} {kind:5s} AUC={r['auc']:.3f} HM upper={r['hm_upper_one_sided95']:.3f} boot upper={r['boot_upper_one_sided95']:.3f}", flush=True)
    res["gas_util_T_by_row"] = {"attacks": {r.event: float(r.eth_gas_util_T) for _, r in pd.concat([f3[f3.cls == "attack"], new]).iterrows()},
                                "benign_median": float(f3[f3.cls == "benign"].eth_gas_util_T.median()),
                                "benign_share_above_0.99": float((f3[f3.cls == "benign"].eth_gas_util_T > 0.99).mean())}
    OUT_JS.write_text(json.dumps(res, indent=1))
