"""CJSJ item 34: independent adversarial check of reports/cjsj_submission/JillellamudiSanjay_paper.{pdf,docx} against reports/cjsj_numbers.md, reports/research_audit.md and
reports/pilot_results.md (plus models.py, spec_lock_2026-09-30.md, c4_novelty_reverification.md, temporal_features.md where a claim lives there). I did not write the paper.
The PDF (pypdf) and docx (python-docx) were extracted and their numeric tokens diffed: identical. This script (1) recomputes the handful of quantities no existing section contains
and (2) writes the claim table. The paper was UPDATED at 13:17 (after the first pass at about 12:26); this script re-reads the current files, recomputes the new claims (second-labeler agreement from reports/second_labeler/second_labeler_results.csv) and re-tests which earlier mismatches remain. THIRD PASS (paper re-read from the current .docx after it changed again: 30-seed numbers in abstract/3.3/Figure 3, aggregator sentence, corrected references, code availability line). Every row carries a 'needle' phrase that is searched for in the current docx text so a stale row cannot survive unnoticed. Status: MATCH (value reproduced at the cited source), MISMATCH (value or wording not supported / inconsistent with the source), UNVERIFIABLE (no source
in the files provided; stated so, not guessed). Notes carry caveats for MATCH rows."""
from cjsj_common import ensure_omp
ensure_omp()
import numpy as np, pandas as pd
from scipy.stats import mannwhitneyu
from cjsj_common import REPORTS, TAG_CONFOUNDED, write_section
import cjsj_eval as E
import cjsj_lcs as S
from cjsj_fwd import forward_all
from cjsj_28_drop_one import run as run28, CONFIGS as C28
import cjsj_28_drop_one as D28


def recompute():
    base = E.load_base(); pos = E.positive_sets(base)["all 24 (audit baseline)"]; out = {}
    # (1) forward totals under the different RF/XGB configurations (all 24 training)
    R = forward_all(base, E.CUTOFFS); ok = [r for r in R if r["ok"]]; y = E.labels(base)
    def fa(P, r):
        te = r["te"]; isneg = base.label.values[te] == E.VOL; return int((P[te][isneg] >= .5).sum())
    out["rf300_total"] = sum(fa(r["P"]["RF"], r) for r in ok); out["rf300_by"] = [fa(r["P"]["RF"], r) for r in ok]
    out["xgb_nested_total"] = sum(fa(r["P"]["XGB"], r) for r in ok); out["xgb_nested_by"] = [fa(r["P"]["XGB"], r) for r in ok]
    out["bn_total"] = sum(fa(r["P"]["BN"], r) for r in ok); out["n_test_neg_sum"] = sum(int((base.label.values[r["te"]] == E.VOL).sum()) for r in ok)
    out["unique_test_neg"] = len({i for r in ok for i in r["te"] if base.label.values[i] == E.VOL})
    # (2) RF 150 trees seed 0 (the 46) and XGB fixed (the 108)
    tot150 = 0; xf = 0; by150 = []
    for r in ok:
        c = pd.Timestamp(r["cut"]); neg = np.where((base.dt < c) & (base.label == E.VOL))[0]; p_ = np.where((base.dt < c) & base.incident.isin(pos))[0]; tr = np.concatenate([neg, p_]); te = r["te"]
        isneg = base.label.values[te] == E.VOL
        by150.append(int((E.rf_proba(base, tr, te, cols=E.ALW, n_est=150, seed=0)[isneg] >= .5).sum())); xf += int((S.xgb_scores(base, tr, te, E.ALW, True)[isneg] >= .5).sum())
    out["rf150_total"] = sum(by150); out["rf150_by"] = by150; out["xgb_fixed_total"] = xf
    # (3) drop heartbeat starting from the paper's own 8-feature set (ALW), all 24
    D28.CONFIGS["ALW minus heartbeat"] = [c for c in E.ALW if c != "heartbeat_elapsed"]
    name, o = run28(base, pos, "ALW minus heartbeat"); out["alw_nohb_rf"] = sum(x["rf_fa"] for x in o); out["alw_nohb_xgb"] = sum(x["xgb_fa"] for x in o)
    name, o = run28(base, pos, "ALW (audit 8 features, no congestion)"); out["alw_rf5"] = sum(x["rf_fa"] for x in o); out["alw_xgb"] = sum(x["xgb_fa"] for x in o)
    # (4) drift within separately collected batches
    v = base[base.label == E.VOL]; out["batch"] = {}
    for c, d in v.groupby("cohort"):
        a = d[d.dt < "2024-01-01"].heartbeat_elapsed; z = d[d.dt >= "2024-01-01"].heartbeat_elapsed
        out["batch"][c] = (len(a), len(z), a.median() if len(a) else np.nan, z.median() if len(z) else np.nan, mannwhitneyu(a, z).pvalue if len(a) > 2 and len(z) > 2 else np.nan)
    sh = pd.read_csv(REPORTS / "a2_label_sheet.csv"); out["tiers"] = sh.evidence_tier.value_counts().to_dict(); out["mev_same_pool"] = "same WETH/USDC V3" in open(REPORTS / "a2_label_sheet.csv").read() or True
    return out


ROWS = []  # (id, location, claim, paper, source_value, source, status, note)
def row(*a): ROWS.append(a)


def build(o):
    row("A1", "Abstract", "sample size", "162 incidents; 24 exploits; 138 market moves", "162 / 24 / 138", "research_audit.md (Scope); features.parquet", "MATCH", "")
    row("A2", "Abstract", "LOOCV accuracy of BN, RF, XGB", "95 to 98%", "BN 0.951, RF 0.975, XGB (nested-tuned) 0.981", "cjsj_numbers §3a, §2A", "MATCH", "")
    row("A3", "Abstract", "AUC of market-context-only features", "0.91", "0.906 [0.845, 0.960]", "cjsj_numbers §9a; research_audit.md C1 table", "MATCH", "rounds 0.906")
    row("A4", "Abstract", "permutation p for that AUC", "<= 0.001", "p <= 0.001 (observed 10-fold AUC 0.899, not LOOCV 0.906)", "cjsj_numbers §23", "MATCH", "the test statistic is a different (10-fold, 40-tree) AUC than the 0.906 quoted")
    row("A5", "Abstract; §3.3", "false alarms summed over 7 splits: RF and XGBoost", "46 (RF), 108 (XGBoost)", f"RF 46 = 150 trees, seed 0 (recomputed {o['rf150_total']}); XGB 108 = FIXED config (recomputed {o['xgb_fixed_total']})", "cjsj_numbers §21c baseline, §30a", "MATCH",
        f"numbers exist but are configuration-specific: RF with 300 trees (the audit's model) gives {o['rf300_total']} ({o['rf300_by']}); RF over 30 seeds 40.3, seed range 17-60 (§32); nested-tuned XGBoost gives {o['xgb_nested_total']} ({o['xgb_nested_by']}); XGBoost with row/column sampling over 30 seeds 99.3 (§32)")
    row("A6", "Abstract; §3.3", "BN false alarms over 7 splits", "14", f"14 (recomputed {o['bn_total']})", "cjsj_numbers §21c; research_audit.md forward table (2,3,3,2,2,1,1)", "MATCH", "")
    row("A7", "Abstract; §3.3", "removing shortcut features eliminated the bursts", "qualitative (RF 3, XGB 2 in §3.3)", "RF 3 and XGB 2 (deterministic); with XGBoost row/column sampling over 30 seeds 10.5 [8, 13]", "cjsj_numbers §21c, §32", "MATCH", "'eliminated' is fair for RF (mean 1.2); XGBoost's 2 is seed-sensitive")
    row("A8", "Abstract; §3.4", "attack class after label verification", "24 to 9", "9 verified M", "cjsj_numbers §1a", "MATCH", "")
    row("A9", "Abstract; §3.4", "pilot: attacks observable at block resolution", "3 of 9", "3 usable of 9", "pilot_results.md §1", "MATCH", "pilot is framed there as feasibility, not a result")
    row("M1", "§2 Data", "number and period of exploits; on-chain confirmation", "24 exploits, 2020 to 2026, each confirmed on-chain", "24 rows, 2020-10-26 to 2026-09-05; all 24 attack txs have status success", "cjsj_numbers §6, a2_label_sheet.csv", "MATCH", "")
    row("M2", "§2 Data", "negative class definition", "138 moves, ETH/USD moved 3 to 5% or more", "138; selected by ETH/USD move 3 to 5% or more", "research_audit.md C1", "MATCH", "")
    row("M3", "§2 Data", "four statistics of the trailing 24-hour trajectory", "four; 24-hour; strictly trailing", "4 temporal features, fixed 24 h trailing window", "temporal_features.md §1-2", "MATCH", "")
    row("M4", "§2 Data", "reserve skew over about 300 blocks", "about 300 blocks", "incident block vs block-300", "features notes; a1_measurement_spec.md", "MATCH", "")
    row("M5", "§2 Models", "BN thresholds", "5% price-type, 3,600 s freshness, 50% congestion", "0.05, 3600, 0.5", "src/models.py FIXED_THRESHOLDS", "MATCH", "")
    row("M6", "§2 Models", "XGBoost 'tuned by nested cross-validation'", "tuned by nested CV", "only the LOOCV XGB (21/24) is nested-tuned; the 108 (and 92/133, 2) forward numbers use a fixed config; nested-tuned forward total is " + str(o['xgb_nested_total']), "cjsj_numbers §3, §21c", "MISMATCH", "the forward false-alarm figures quoted in the abstract/§3.3 are not from the nested-tuned model")
    row("M7", "§2 Evaluation", "seven forward cutoffs", "July 2022 to July 2025", "2022-07, 2023-01, 2023-07, 2024-01, 2024-07, 2025-01, 2025-07", "research_audit.md forward table", "MATCH", "")
    row("M8", "§2 Evaluation", "permutation tests use 1,000 label shuffles", "1,000", "1,000 for the AUC tests (§23); the date test in §3.2 used 5,000 shuffles (§22)", "cjsj_numbers §22, §23", "MISMATCH", "minor: applies to the date probe only")
    row("M9", "§2 Evaluation", "exact McNemar with Holm; bootstrap CIs", "as stated", "exact McNemar, Holm, bootstrap CIs used", "cjsj_numbers §3, §9", "MATCH", "")
    row("M10", "§2 Shortcut audit", "each exploit classified using at least two independent post-mortems", "at least two independent post-mortems", f"evidence tiers over the 24: {o['tiers']}; only the 9 verified M (13 of 24 overall) meet two independent mechanism-level sources", "cjsj_numbers §1a; a2_label_sheet.csv", "MISMATCH", "overstated: 6 of 24 single-source, 5 'weak' (news-level only); the second labeler (13:17 version) saw the first labeler's source links, see N3")
    row("M11", "§2 Pilot", "trigger thresholds", "0.5% for pegged assets or 5% otherwise, within 50 blocks", "0.5% for pegged or slow sources, 5% for volatile-pair Uniswap; Y = 50 blocks", "spec_lock_2026-09-30.md", "MATCH", "'slow sources' omitted")
    row("M12", "§2 Pilot", "benign events", "March 2023 USDC depeg, June 2022 stETH discount", "both in the named events", "spec_lock_2026-09-30.md; pilot_results.md §2", "MATCH", "pilot §2: USDT Jun 2023, USDe Oct 2025 and Nov 2022 LSD windows produced 0 fired episodes (not mentioned)")
    row("R1", "§3.1", "RF LOOCV", "20 of 24, no false alarms, 97.5%", "20/24, 0/138, 0.975", "cjsj_numbers §3a", "MATCH", "")
    row("R2", "§3.1", "XGBoost LOOCV", "21, none", "21/24, 0/138", "cjsj_numbers §3a", "MATCH", "nested-tuned")
    row("R3", "§3.1", "BN LOOCV", "20 with 4 false alarms of 138, 95.1%", "20/24, 4/138, 0.951", "cjsj_numbers §3a", "MATCH", "")
    row("R4", "§3.1", "BN vs RF McNemar", "p = 0.125; 0.688 on verified labels", "0.125; 0.688", "cjsj_numbers §2A (all 24; verified M)", "MATCH", "")
    row("R5", "§3.1", "logistic regression accuracy", "99.4%", "0.994 is LR WITH missingness indicators; LR without them 0.889", "cjsj_numbers §9b; research_audit.md C3", "MATCH", "value reproduced, but placed under 'high apparent accuracy' without saying it uses the missingness shortcut (explained one section later)")
    row("S1", "§3.2", "attacked assets with no Chainlink feed", "23 of 24 had no Chainlink feed, so ETH/USD stood in", "23 of 24 use ETH/USD as a documented fallback; reasons vary (e.g. Inverse Finance: WBTC/USDT; CompoundUni: a UNI price feed 'unverified'); the 24th (MEVBOTa47b) is on the ETH pool", "research_audit.md C1; features reference_note", "MISMATCH", "sources support 'ETH/USD used as fallback for 23 of 24', not 'no Chainlink feed' for all 23")
    row("S2", "§3.2", "RF AUC, market-context only", "0.906 [0.845, 0.960]; 0.917 [0.802, 0.989] (9 verified)", "0.906 [0.845, 0.960]; 0.917 [0.802, 0.989]", "cjsj_numbers §9a", "MATCH", "")
    row("S3", "§3.2", "venue-feature AUCs", "0.901 and 0.808", "0.901 [0.811, 0.974]; 0.808 [0.623, 0.941]", "cjsj_numbers §9a", "MATCH", "'matching' is supported: difference +0.108 [-0.021, +0.267] on verified M")
    row("S4", "§3.2", "permutation p for both", "<= 0.002 throughout", "max p 0.002 over the 6 ETH-context and venue+localization tests", "cjsj_numbers §23", "MATCH", "10-fold statistic (AUCs 0.899, 0.857, 0.902 / 0.888, 0.857, 0.815)")
    row("S5", "§3.2", "missing price features", "83 to 96% of attacks, 0% of market moves", "price_dev 83%; cross_venue_spread, dex_oracle_spread 96%; 0% for volatility", "research_audit.md C3", "MATCH", "")
    row("S6", "§3.2", "LR with/without missingness; recall", "99.4% vs 88.9%; 0.958 to 0.375", "0.994 vs 0.889; 23/24 = 0.958 vs 9/24 = 0.375", "cjsj_numbers §9b; research_audit.md", "MATCH", "")
    row("S7", "§3.2", "attack reserve-skew values above 90%", "16 of 24", "16/24 have |skew| >= 0.9", "research_audit.md C2", "MATCH", "'exceeded' vs 'of 0.9 or more'")
    row("S8", "§3.2", "largest market-move skew", "no market move exceeded 19%", "no volatility incident exceeds 0.19", "research_audit.md C2", "MATCH", "")
    row("S9", "§3.2", "date alone", "AUC 0.575, p = 0.23", "rank AUC 0.575, permutation p 0.232", "cjsj_numbers §22", "MATCH", "")
    row("T1", "§3.3, Fig 3", "'489 test market moves'", "489", f"{o['n_test_neg_sum']} = 114+102+85+70+53+38+27; only {o['unique_test_neg']} distinct incidents", "cjsj_numbers §32; research_audit.md forward table", "MATCH", f"the seven test sets overlap, so 489 counts the same incident up to seven times; {o['unique_test_neg']} distinct market moves are ever tested (the 24 earliest are never in a test set)")
    row("T2", "§3.3", "January 2024 cutoff", "RF 16 false alarms of 70; BN 2", "audit RF (300 trees) 16/70, BN 2/70; the 46-total RF (150 trees) has 15/70 at this cutoff", "research_audit.md forward table; cjsj_numbers §21c", "MATCH", "the abstract total (46) and this cutoff (16) come from two different RF configurations (150 vs 300 trees)")
    row("T3", "§3.3", "significance at that cutoff", "p = 0.0044; significant after Holm; 23 of 24 threshold perturbations", "0.0044; Holm-adjusted 0.031; 23 of 24 keep p<.05", "cjsj_numbers §2, §3b, §5", "MATCH", "same section shows the BN-over-RF edge does not reproduce on verified-M positives (§2, §8)")
    row("T4", "§3.3", "without market-context features", "tree false alarms 3 and 2", "RF 3, XGB 2 (venue-only, trained on all 24, seed 0 / deterministic)", "cjsj_numbers §21c", "MATCH", "30 seeds: RF 1.2 [0, 6]; XGBoost with sampling 10.5 [2, 23] (§32)")
    row("T5", "§3.3", "market-context features only", "92 and 133", "RF 92, XGB 133", "cjsj_numbers §21c, §30a", "MATCH", "30 seeds: RF 101.8, XGB-sampled 131.2 (§32)")
    row("T6", "§3.3", "drift of update freshness", "median 264 s before 2024, 300 s after; p = 8e-7", "264 -> 300; p = 8.4e-07", "cjsj_numbers §28a; research_audit.md", "MATCH", "")
    row("T7", "§3.3", "drift within separately collected batches", "p <= 0.002", "not in the three files; recomputed here: phase2 p=" + f"{o['batch']['phase2'][4]:.1e}" + f", phase3 p={o['batch']['phase3'][4]:.4f}; phase1 p={o['batch']['phase1'][4]:.2f}, original_20 p={o['batch']['original_20'][4]:.2f} (opposite direction)", "this script (cohort splits at 2024-01)", "MATCH", "holds for the two large batches, not the two small ones; the claim was UNVERIFIABLE from the named sources")
    row("T8", "§3.3", "only market-context feature that drifted", "all others p >= 0.18", "min other p = 0.18 (ref_realized_vol, temporal_gap_trend)", "cjsj_numbers §28a", "MATCH", "")
    row("T9", "§3.3", "removing heartbeat alone", "all of RF's false alarms, 85% of XGBoost's", f"from ALW+congestion: RF 75.0 -> 0.0, XGB 110 -> 17 (85%). From the paper's own 8-feature set (RF {o['alw_rf5']:.1f} over 5 seeds / XGB {o['alw_xgb']}): minus heartbeat RF {o['alw_nohb_rf']:.1f}, XGB {o['alw_nohb_xgb']}", "cjsj_numbers §28b; recomputed here", "MATCH", f"the quoted 100% / 85% come from the 9-feature baseline (ALW + congestion); from the paper's own 8-feature models the reduction is RF {100 * (1 - o['alw_nohb_rf'] / o['alw_rf5']):.0f}% (seed-mean) and XGBoost {100 * (1 - o['alw_nohb_xgb'] / o['alw_xgb']):.0f}%")
    row("T10", "§3.3", "attribution share on market-context features", "32% [23, 44], 36% [19, 50], BN 8% [3, 15]", "same", "cjsj_numbers §29", "MATCH", "held-out incidents, 200 refits")
    row("T11", "§3.3", "three random label flips", "+3.0 RF, +2.8 XGB, +0.7 BN forward false alarms", "+3.0 / +2.8 / +0.7", "cjsj_numbers §21e column 4", "MATCH", "verified-M training, mean over the 2023-01, 2023-07, 2024-01 cutoffs, 20 seeds (not stated in the paper)")
    row("T12", "§3.3", "one mislabeled bot exploit accounted for most of RF's false alarms", "most", "removing MEVBOTa47b alone: -10.6, -9.2, -14.2 of 11.6, 9.2, 14.4 (three cutoffs); but removing Inverse Finance (verified M) removes -5.8, -5.4, -13.6; adding MEVBOTa47b alone gives only 5.4, 1.4, 2.0", "cjsj_numbers §8, §14", "MATCH", "necessary, not sufficient; Inverse Finance carries comparable influence (mean forward effect -2.62 vs -3.87); the K label rests on one source")
    row("T13", "§3.3", "BN calibration", "slope 0.45; Platt 1.01; log-loss 0.283 to 0.177", "0.45 [0.33, 0.71]; 1.01; 0.283 -> 0.177", "cjsj_numbers §25", "MATCH", "")
    row("V1", "§3.4", "label verification counts", "12 manipulations; 9 with two sources; rounding 3; accounting/access 5; bot/governance 2; unresolved 2", "M 12, R 3, A 5, K 2, O 2; verified M 9", "cjsj_numbers §1a", "MATCH", "")
    row("V2", "§3.4", "DeFiHackLabs counts", "875 incidents; about 41 flagged; roughly 20 verifiable", "875; 41 (keyword heuristic); ~20 expected", "cjsj_numbers §1b", "MATCH", "41 comes from a keyword screen of README headings, not labels; ~20 is an estimate")
    row("V3", "§3.4", "minimum detectable AUC", "0.745 (9) vs 0.660 (24)", "0.745 / 0.660", "cjsj_numbers §1c", "MATCH", "")
    row("V4", "§3.4", "single-transaction attacks", "between 12 and 21 of 24", "12 (raw same-target) to 21 (repeat-verified)", "cjsj_numbers §6", "MATCH", "sender-only scan, lower bound for multi-block")
    row("V5", "§3.4", "pilot outcome breakdown", "3 of 9; two restored in-block; two lacked reference price; two not readable", "3 usable; Harvest, UwU trigger misses; Cream, sDOLA no reference; Resupply reader failed, BalancerBoosted no reader", "pilot_results.md §1", "MATCH", "3+2+2+2 = 9")
    row("V6", "§3.4", "pilot control", "one-sided 95% upper bound 0.64 to 0.80", "0.635 (RF), 0.795 (logit)", "pilot_results.md §3", "MATCH", "")
    row("D1", "§4", "trees at least as stable without shortcut features", "at least as stable", "all 24: venue-only BN 7 vs RF 3, XGB 2; extended BN 14 vs RF 0, XGB 4; but XGBoost with sampling (30 seeds) 10.5 [8, 13] vs BN 7", "cjsj_numbers §21c, §32", "MISMATCH", "true for RF; for XGBoost it holds for the deterministic run only")
    row("D2", "§4", "BN small-sample advantage traced to fixed threshold on leaky reserve skew", "traced to", "advantage persists with venue-only features and reverses with extended features (§21a); never tested by varying the threshold directly", "cjsj_numbers §21a", "UNVERIFIABLE", "consistent with the evidence, but the causal wording is not tested")
    row("D3", "§4", "precision at 1% prevalence", "BN 0.23; RF conservative bound 0.19", "BN 0.225; RF Wilson-conservative 0.193", "cjsj_numbers §4", "MATCH", "0.225 rounds to 0.23 only upward")
    row("C1", "§5", "conclusion numbers", "AUC 0.91; single digits; many within one transaction", "0.906; 9; 12-21", "cjsj_numbers §9a, §1a, §6", "MATCH", "")
    row("F1", "Fig 1 caption", "attacked venues", "24 different attacked venues; market moves on a single ETH pool", "MEVBOTa47b was measured on the SAME WETH/USDC pool as the market moves (stored note and A2 sheet), so 23, not 24, differ", "features reference_note; a2_label_sheet.csv", "MISMATCH", "the 12:26 version of §3.3 also said so (that sentence was removed in the 13:17 version); Figure 1's caption still says 24")
    row("F2", "Fig 1/2 captions", "83 to 96%; AUC 0.91; 23 of 24", "as stated", "83-96%; 0.906; 23/24", "research_audit.md C1, C3", "MATCH", "")
    row("F3", "Fig 2", "bar values", "0.906/0.917 and 0.901/0.808 with CIs", "same", "cjsj_numbers §9a", "MATCH", "figures.py transcribes the numbers")
    row("F4", "Fig 3", "bars", "BN 14/7/0, RF 46/3/92, XGB 108/2/133; shares 8/32/36", "same", "cjsj_numbers §21c, §29", "MATCH", "BN 0 with market-context only because it flags nothing (caught 0/98); single-run bars, no intervals in the figure (see §32)")
    row("R6", "References", "[6] DeFiTrace, doi 10.1145/3817054, TOPS 2026; [7] TOAD-ML doi 10.3389/fbloc.2026.1903202; [8] Chockalingam et al., Cybersecurity 4(1):29, 2021, doi 10.1186/s42400-021-00086-6", "as stated", "same DOIs, venues, authors", "c4_novelty_reverification.md", "MATCH", "TOAD-ML 'vol. 9' is not in the source: UNVERIFIABLE; the paper's description of TOAD-ML matches the source's abstract-level summary (the source warns it was not read in full)")
    row("R7", "References", "[1]-[5], [9]-[13]", "as stated", "not covered by the three named files or the novelty report", "none", "UNVERIFIABLE", "standard references; I did not check them against external sources")


def addendum(o):
    from pypdf import PdfReader
    from sklearn.metrics import cohen_kappa_score
    txt = " ".join(" ".join(p.extract_text().split()) for p in PdfReader(REPORTS / "cjsj_submission" / "JillellamudiSanjay_paper.pdf").pages)
    first = pd.read_csv(REPORTS / "a2_label_sheet.csv").set_index("incident_id"); a = pd.read_csv(REPORTS / "second_labeler" / "second_labeler_results.csv").rename(columns={"category": "cat2"}); a["cat1"] = a.incident_id.map(first.category)
    agree = int((a.cat1 == a.cat2).sum()); k5 = cohen_kappa_score(a.cat1, a.cat2, labels=list("MRAKO")); k2 = cohen_kappa_score(a.cat1 == "M", a.cat2 == "M")
    rng = np.random.default_rng(0); bs = []
    for _ in range(5000):
        i = rng.integers(0, len(a), len(a)); x, y = a.cat1.values[i], a.cat2.values[i]
        if len(set(x)) > 1 or len(set(y)) > 1:
            with np.errstate(all="ignore"): v = cohen_kappa_score(x, y)
            if not np.isnan(v): bs.append(v)
    lo, hi = np.percentile(bs, [2.5, 97.5]); vm = first.index[first.verified_M]; both = int(((a.cat1 == "M") & (a.cat2 == "M") & a.incident_id.isin(vm)).sum())
    for r in ROWS:
        if r[0] == "T12": ROWS[ROWS.index(r)] = (r[0], r[1], r[2] + " [sentence removed in the 13:17 version]", r[3], r[4], r[5], "SUPERSEDED", "the current paper no longer makes this claim")
    row("N1", "§1 Abstract/§3.4 (13:17 version)", "total losses of the 24 exploits", "about $370 million", "370,176,240 USD (per-incident figures; Cream + BalancerV2 = 68%)", "cjsj_numbers §26a (cjsj_26_losses.csv)", "MATCH", "five older figures are reported amounts from web sources, three multi-pool incidents use per-pool/per-tx figures")
    row("N2", "§3.4 (13:17 version)", "second-labeler agreement", "15 of 24; kappa 0.46 [0.18, 0.71]; 0.50 manipulation vs not; both label 7 of 9 verified as manipulation", f"{agree} of 24; kappa {k5:.3f} (bootstrap 95% CI [{lo:.2f}, {hi:.2f}]); M-vs-not {k2:.2f}; both M on {both} of 9 verified", "recomputed from reports/second_labeler/second_labeler_results.csv vs a2_label_sheet.csv", "MATCH", "CI method is not stated in the paper; my 5,000-rep bootstrap reproduces it")
    row("N3", "§3.4 (13:17 version)", "second labeler 'blind to these labels'", "blind", "the packet hid the first labeler's categories, S, C and notes but SHOWED the first labeler's source links ('Starting source'); the second labeler's answers list almost the same sources; the labeler's identity is not documented in the files I read", "reports/second_labeler/build_packet.py", "UNVERIFIABLE", "blind to categories: yes; independent of the first labeler's evidence: no, so the agreement measures agreement on interpreting shared sources")
    row("N4", "§3.4 (13:17 version)", "intra-block replay of UwU", "UwU's source deviated 8.6% mid-block but under 0.1% at every block close; balances matched to 1e-5", "peak 8.57% (blocks T and T+3); block-close deviation never above 0.08%; replay reproduces end-of-block balances to 1e-5 or better", "pilot_results.md §6.2", "MATCH", "pilot_results.md also says replay does not rescue Harvest, and Makina's replay is unreliable (33% off on one balance)")
    row("N5", "§4 Limitations (13:17 version)", "label agreement is moderate", "moderate", f"kappa {k5:.2f} falls in the Landis-Koch 0.41-0.60 'moderate' band", "a9_kappa.py interpretation guide; recomputed", "MATCH", "CI spans fair to substantial")
    flags = {"M6": "tuned by nested", "M8": "1,000 label shuffles", "M10": "at least two independent", "S1": "no Chainlink feed", "D1": "at least as stable", "F1": "24 different attacked", "A5/T2": "46 for the random forest"}
    return {k: (ph in txt) for k, ph in flags.items()}



NEEDLES = {"A1": "162 Ethereum incidents", "A2": "95 to 98%", "A3": "AUC of 0.91", "A4": "p ≤ 0.001", "A5": "40 (random forest) and 99 (XGBoost)", "A6": "against 14", "A7": "removing the shortcut features eliminated the bursts",
           "A8": "from 24 to 9", "A9": "only 3 of those 9", "M1": "Twenty-four exploits (2020 to 2026)", "M2": "3 to 5% or more", "M3": "trailing 24-hour", "M4": "about 300 blocks", "M5": "3,600 s", "M6": "nested-CV tuned for LOOCV",
           "M7": "July 2022 to July 2025", "M8": "at least 1,000 label shuffles", "M9": "exact McNemar", "M10": "counted as verified only with two independent post-mortems", "M11": "0.5% for pegged assets or 5% otherwise", "M12": "March 2023 USDC depeg",
           "R1": "caught 20 of 24 attacks", "R2": "XGBoost caught 21", "R3": "95.1%", "R4": "p = 0.688", "S1": "for 23 of 24 attacks ETH/USD data stood in as a fallback", "S2": "0.906 [0.845, 0.960]", "S3": "0.901 and 0.808", "S4": "permutation p ≤ 0.002",
           "S5": "83 to 96%", "S6": "99.4% with missingness indicators", "S7": "16 of 24 attack values exceeded 90%", "S8": "no market move exceeded 19%", "S9": "AUC 0.575, p = 0.23", "T1": "489 test market moves", "T2": "16 false alarms among 70",
           "T3": "p = 0.0044", "T4": "1.2 and 10.5", "T5": "102 and 131", "T8": "all others p ≥ 0.18", "T9": "eliminated all of the random forest's false alarms and 85%", "T10": "32% [23, 44]", "T13": "0.283 to 0.177",
           "V1": "12 of the 24 exploits", "V2": "875 DeFiHackLabs incidents", "V3": "0.745, against 0.660", "V4": "Between 12 and 21", "V5": "two manipulated prices were restored", "V6": "0.64 to 0.80", "D1": "comparably stable",
           "D2": "consistent with its fixed threshold", "D3": "the random forest's conservative bound is 0.19", "C1": "AUC of 0.91", "F1": "23 of 24 differ", "F3": "Bars show random-forest LOOCV AUC", "F4": "mean of 30 training seeds",
           "N1": "$370 million", "N2": "15 of 24", "N3": "blind to these labels", "N4": "8.6% mid-block", "N5": "label agreement is moderate"}


def revise(o):
    """Apply the changes between the 13:17 and the current paper."""
    import docx, re
    from pypdf import PdfReader
    d = docx.Document(REPORTS / "cjsj_submission" / "JillellamudiSanjay_paper.docx"); text = " ".join(" ".join(p.text.split()) for p in d.paragraphs)
    pdf = " ".join(" ".join(p.extract_text().split()) for p in PdfReader(REPORTS / "cjsj_submission" / "JillellamudiSanjay_paper.pdf").pages)
    nums = lambda t: sorted(re.findall(r"\d[\d,]*\.?\d*%?", t.replace("−", "-")))
    same = nums(text) == nums(pdf)
    sec39 = pd.read_csv(REPORTS / "cjsj_39_heartbeat_seeds.csv").set_index(["baseline", "model"]); c32 = pd.read_csv(REPORTS / "cjsj_32_fig3_ci.csv").set_index(["feature_set", "model"])
    ids = {r[0]: r for r in ROWS}
    def setr(i, **kw):
        r = list(ids[i]); f = dict(id=0, loc=1, claim=2, paper=3, src_val=4, src=5, status=6, note=7)
        for k, v in kw.items(): r[f[k]] = v
        ROWS[ROWS.index(ids[i])] = tuple(r); ids[i] = tuple(r)
    def gone(i, why): setr(i, status="SUPERSEDED", note=why)
    rf = c32.loc[("all features", "RF")]; xg = c32.loc[("all features", "XGB (30 seeds)")]; rf0 = c32.loc[("without market-context (venue only)", "RF")]; xg0 = c32.loc[("without market-context (venue only)", "XGB (30 seeds)")]
    rf1 = c32.loc[("market-context only", "RF")]; xg1 = c32.loc[("market-context only", "XGB (30 seeds)")]
    setr("A5", paper="40 (RF) and 99 (XGBoost) false alarms; 40 [13, 70] and 99 [61, 141] in 3.3 (means over 30 seeds)", src_val=f"RF {rf['mean']:.1f} [{rf.comb_lo:.0f}, {rf.comb_hi:.0f}]; XGB {xg['mean']:.1f} [{xg.comb_lo:.0f}, {xg.comb_hi:.0f}] (combined 95% intervals)", src="cjsj_numbers §32", status="MATCH", note="XGBoost's 30 seeds come from the fixed config WITH row/column sampling (0.8); see M6b")
    setr("A7", src_val=f"RF 1.2 [{rf0.comb_lo:.0f}, {rf0.comb_hi:.0f}], XGB 10.5 [{xg0.comb_lo:.0f}, {xg0.comb_hi:.0f}] without market-context (30 seeds)", src="cjsj_numbers §32", note="abstract says 'eliminated'; XGBoost falls 99 -> 10.5 (-89%), still above the BN's 7")
    setr("M6", paper="XGBoost 'nested-CV tuned for LOOCV, fixed configuration for time splits'", src_val="LOOCV XGB nested-tuned (21/24); forward numbers use the fixed config", src="cjsj_numbers §3a, §21c, §32", status="MATCH", note="the earlier mismatch is fixed")
    row("M6b", "§2 Models / §3.3", "XGBoost used for the 30-seed numbers", "fixed configuration", "the 30-seed XGBoost (99, 10.5, 131) adds row and column subsampling (0.8) so that seeds differ; the deterministic fixed config gives 108 / 2 / 133", "cjsj_numbers §32 docstring and table", "MISMATCH", "undisclosed: 'fixed configuration' does not mention the sampling that produces the 30-seed spread")
    setr("M8", paper="permutation tests use 'at least 1,000' label shuffles", src_val="1,000 (AUC tests, §23); 5,000 (date probe, §22)", status="MATCH", note="the earlier mismatch is fixed")
    setr("M10", paper="'counted as verified only with two independent post-mortems'", src_val="all 9 verified M have the 2-source tier (auditor / protocol post-mortems); 13 of 24 attacks overall have it", src="cjsj_numbers §1a", status="MATCH", note="the earlier mismatch is fixed; the sentence no longer says every exploit was classified with two post-mortems")
    setr("S1", paper="'for 23 of 24 attacks ETH/USD data stood in as a fallback'", src_val="23 of 24 use ETH/USD as a documented fallback", src="research_audit.md C1", status="MATCH", note="the earlier mismatch is fixed")
    setr("T2", paper="'the random forest raised 16 false alarms among 70 market moves against the BN's 2 (p = 0.0044 ...)'", src_val="16/70 and p = 0.0044 are the audit's single-run 300-tree forest; the same paragraph's totals (40, 99) are 150-tree 30-seed means, whose January 2024 mean is 12.9 false alarms (39c)", src="research_audit.md; cjsj_numbers §2, §39c", status="MISMATCH", note="two RF configurations are mixed in one paragraph; 16 and p = 0.0044 do not belong to the 30-seed model behind '40 [13, 70]'")
    setr("T4", src_val=f"RF {rf0['mean']:.1f}, XGB {xg0['mean']:.1f} (30 seeds)", src="cjsj_numbers §32", note="matches the 30-seed numbers")
    setr("T5", src_val=f"RF {rf1['mean']:.1f}, XGB {xg1['mean']:.1f} (30 seeds)", src="cjsj_numbers §32", note="matches the 30-seed numbers")
    gone("T7", "within-batch drift sentence removed from the current paper")
    row("T6a", "§3.3", "new aggregator launch date", "Chainlink launched a new ETH/USD aggregator on 18 September 2024", "phase-7 aggregator's first round 2024-09-18", "cjsj_numbers §33a", "MATCH", "")
    row("T6b", "§3.3", "drift before/after launch", "median 271 s before, 576 s after; Mann-Whitney p = 7e-8", "271 s / 576 s; p = 6.7e-08", "cjsj_numbers §33f", "MATCH", "the split date differs from the 2024-01 split used for the other features' p >= 0.18 (T8)")
    row("T6c", "§3.3", "what changed in the update rule", "updates for moves under 0.5% stopped; heartbeat-only updates rose from 30% to 45%", "10th percentile of non-heartbeat update size 0.05% before vs 0.50% after; share of gaps >= 3000 s 0.30 before, 0.45 / 0.44 after", "cjsj_numbers §33g", "MATCH", "sampled windows, not the full history; 'stopped' = essentially all non-heartbeat updates are >= 0.5% moves")
    row("T6d", "§3.3", "causal statement", "'The drift is a change in the oracle itself'", "timing (launch date) and update-rule change are supported; §33h says causal attribution cannot be separated from how incident blocks sit in the update cycle (elapsed-to-gap ratio 0.27 -> 0.60, local median gap did not rise)", "cjsj_numbers §33f, §33h", "UNVERIFIABLE", "supported as coincidence plus a documented rule change; not established as the sole cause")
    p = sec39.loc[("A", "RF")]; q = sec39.loc[("A", "XGB")]
    setr("T9", paper="'Removing it alone eliminated all of the random forest's false alarms and 85% of XGBoost's'", src_val=f"30-seed means, paper's 8-feature models: RF {p.total_with:.1f} -> {p.total_without:.1f} ({p.reduction:.0%} [{p.ci_lo:.0%}, {p.ci_hi:.0%}]); XGB {q.total_with:.1f} -> {q.total_without:.1f} ({q.reduction:.0%} [{q.ci_lo:.0%}, {q.ci_hi:.0%}])", src="cjsj_numbers §39", status="MATCH", note="85% is the single-run 9-feature figure; the 30-seed value is 87% and the deterministic 8-feature run gives 81%")
    gone("T11", "label-noise sentence removed from the current paper"); gone("T12", "bot-exploit sentence removed from the current paper"); gone("R5", "the logistic-regression 99.4% sentence was removed from 3.1")
    setr("D1", paper="'with the shortcut features removed, the tree models were comparably stable'", src_val="all 24: BN 7 [0, 21] vs RF 1.2 [0, 6], XGB 10.5 [2, 23] (30 seeds): intervals overlap", src="cjsj_numbers §32", status="MATCH", note="the earlier mismatch is fixed by the softer wording")
    setr("D2", paper="'the BN's apparent small-sample advantage is consistent with its fixed threshold on the leaky reserve-skew feature'", src_val="advantage persists with venue-only features and reverses with the extended set (§21a); threshold not varied directly", src="cjsj_numbers §21a", status="MATCH", note="hedged wording ('consistent with') is supported; the causal version would not be")
    setr("F1", paper="Figure 1 caption: '23 of 24 differ from the market moves' pool'", src_val="23 of 24 (MEVBOTa47b is on the market moves' pool)", src="a2_label_sheet.csv; research_audit.md C1", status="MATCH", note="the earlier mismatch is fixed")
    setr("F4", paper="Fig 3 (image and caption): attribution 8/32/36%; false alarms BN 14/7/0, RF 40/1.2/102, XGB 99/10.5/131; 'mean of 30 training seeds; intervals combine seed and incident resampling'", src_val=f"same (read off the PNG): RF {rf['mean']:.0f} [{rf.comb_lo:.0f}, {rf.comb_hi:.0f}], XGB {xg['mean']:.0f} [{xg.comb_lo:.0f}, {xg.comb_hi:.0f}]; shares §29", src="cjsj_numbers §29, §32", status="MATCH", note="figure values were checked against the image, not only the caption")
    # references
    for i in [i for i in ids if i.startswith("R6") or i.startswith("R7")]: ROWS.remove(ids[i])
    refs = [("Ref 1", "[1] Ellis, Juels, Nazarov, ChainLink white paper, 2017", "authors, title, year confirmed on research.chain.link / search", "MATCH", "web search"),
            ("Ref 2", "[2] Werner et al., SoK: DeFi, AFT 2022, pp. 30-46, doi 10.1145/3558535.3559780", "authors, venue, pages, DOI confirmed (ACM DL listing)", "MATCH", "web search"),
            ("Ref 3", "[3] Qin, Zhou, Livshits, Gervais, FC 2021, LNCS 12674, pp. 3-32, doi 10.1007/978-3-662-64322-8_1", "confirmed (Springer listing)", "MATCH", "web search"),
            ("Ref 4", "[4] Xi, Wang, Pattabiraman, POMABuster, IEEE S&P 2024, pp. 3923-3942, doi 10.1109/SP54263.2024.00257", "authors, venue, pages, DOI confirmed", "MATCH", "web search"),
            ("Ref 5", "[5] Wu, Yu, Wang, Zhou, Wu, Wang, Yuan, DeFiRanger, IEEE TDSC 21(4), pp. 4147-4161, 2024, doi 10.1109/TDSC.2023.3346888", "authors (Melbourne record), volume/issue/pages and DOI confirmed", "MATCH", "web search, Univ. of Melbourne record"),
            ("Ref 6", "[6] Pratiwi and Choi, DeFiTrace, ACM TOPS vol. 29, no. 3, pp. 1-28, 2026, doi 10.1145/3817054", "authors, title, DOI, venue and online date (22 May 2026) in c4_novelty_reverification.md; volume, number and pages not checkable (ACM page returned 403)", "UNVERIFIABLE", "c4_novelty_reverification.md; web"),
            ("Ref 7", "[7] Venkatraman and Kuppusamy, TOAD-ML, Frontiers in Blockchain vol. 9, Art. 1903202, 2026, doi 10.3389/fbloc.2026.1903202", "authors (Dhivyalakshmi Venkatraman, Manikandan Kuppusamy), volume 9, article number, DOI confirmed on frontiersin.org", "MATCH", "web fetch; c4_novelty_reverification.md"),
            ("Ref 8", "[8] Chockalingam, Pieters, Teixeira, van Gelder, Cybersecurity 4(1):29, 2021, doi 10.1186/s42400-021-00086-6", "same", "MATCH", "c4_novelty_reverification.md"),
            ("Ref 9", "[9] Geirhos et al., Shortcut learning in deep neural networks, Nat. Mach. Intell. 2(11), pp. 665-673, 2020, doi 10.1038/s42256-020-00257-z", "authors (Michaelis spelling), volume, pages, DOI confirmed; issue number 11 not shown in the listing", "MATCH", "web search"),
            ("Ref 10", "[10] SunWeb3Sec, DeFiHackLabs, GitHub", "the repository I cloned and parsed is github.com/SunWeb3Sec/DeFiHackLabs", "MATCH", "cjsj_numbers §1b"),
            ("Ref 11", "[11] Ankan and Panda, pgmpy, Proc. 14th Python in Science Conf., 2015, pp. 6-11, doi 10.25080/Majora-7b98e3ed-001", "authors (Ankur Ankan, Abinash Panda), venue, pages, DOI confirmed", "MATCH", "web search"),
            ("Ref 12", "[12] Chen and Guestrin, XGBoost, Proc. 22nd ACM SIGKDD, 2016, pp. 785-794", "confirmed (ACM DL listing)", "MATCH", "web search"),
            ("Ref 13", "[13] Lundberg and Lee, A unified approach to interpreting model predictions, NeurIPS 30, 2017, pp. 4765-4774", "sources disagree: ACM DL lists pp. 4768-4777, another source 4765-4774", "UNVERIFIABLE", "web search")]
    for k, (c, v, n, st, src) in enumerate(refs): row(f"R{6 + k}", "References", c + ": " + v, v, n, src, st, "")
    row("R19", "Code availability", "statement", "'Analysis code and processed features are available from the author on request'", "code is in this repository on branch cjsj-analysis; processed features exist locally (data/processed/features.parquet) but data/ is gitignored and not in git", "repository listing", "UNVERIFIABLE", "an availability promise cannot be checked; the files it refers to exist")
    # needle check
    miss = []
    norm = lambda t: re.sub(r"\s+", " ", t.replace(" ", " ")).lower()
    tn = norm(text)
    for r in ROWS:
        nd = NEEDLES.get(r[0])
        if nd is not None and norm(nd) not in tn: miss.append(r[0])
    return same, miss, tn


def main():
    o = recompute(); build(o); still = addendum(o); same, missing, _ = revise(o); L = []; Q = L.append
    st = pd.Series([r[6] for r in ROWS]).value_counts().to_dict()
    Q(f"Paper checked: `reports/cjsj_submission/JillellamudiSanjay_paper.pdf` (3 pages) and `.docx` (numeric tokens identical). {len(ROWS)} claim rows: {st}. Sources: cjsj_numbers.md (this file), research_audit.md, pilot_results.md, and where a claim lives there models.py, spec_lock_2026-09-30.md, c4_novelty_reverification.md, temporal_features.md.")
    Q("")
    Q("Recomputed here for claims no section covered: RF 150 trees seed 0 forward total " + f"{o['rf150_total']} ({o['rf150_by']}); RF 300 trees {o['rf300_total']} ({o['rf300_by']}); XGBoost fixed {o['xgb_fixed_total']}; XGBoost nested-tuned {o['xgb_nested_total']} ({o['xgb_nested_by']}); BN {o['bn_total']}; test incidents {o['n_test_neg_sum']} counted / {o['unique_test_neg']} distinct; heartbeat drift by collection batch (before 2024 n, after n, medians, p): " +
      "; ".join(f"{k} {v[0]}/{v[1]} {v[2]:.0f}->{v[3]:.0f} p={v[4]:.2g}" for k, v in o['batch'].items()) + ".")
    Q("")
    Q("| # | Paper location | Claim | Paper value | Source value | Source section | Status | Note |"); Q("|---|---|---|---|---|---|---|---|")
    for r in ROWS: Q("| " + " | ".join(str(x).replace("|", "/") for x in r) + " |")
    Q("")
    mm = [r for r in ROWS if r[6] == "MISMATCH"]
    Q("Status of the six mismatches from the first two passes in the current paper: M6 (XGBoost nested vs fixed) FIXED by rewording ('nested-CV tuned for LOOCV, fixed configuration for time splits'); M8 (shuffle count) FIXED ('at least 1,000'); M10 (two post-mortems) FIXED (verified only with two); S1 (no Chainlink feed) FIXED (ETH/USD 'stood in as a fallback'); D1 (trees as stable) FIXED by softer wording; F1 (24 vs 23 venues) FIXED. Changes since the 13:17 version: the headline false-alarm numbers are now 30-seed means with intervals (40 [13, 70], 99 [61, 141], 1.2, 10.5, 102, 131) and Figure 3 was redrawn to match; the drift sentence now names the 18 September 2024 aggregator launch (271 s -> 576 s, p = 7e-8) and the update-rule change; the logistic-regression 99.4%, within-batch drift, label-noise and bot-exploit sentences were removed; the references gained volumes, pages and DOIs; a code-availability line was added.")
    Q("")
    Q(f"Needle check against the current docx: {len(NEEDLES) - len([m for m in missing if m in NEEDLES])} of {len(NEEDLES)} row phrases found; rows whose phrase is NOT in the current paper: {', '.join(missing) if missing else 'none'} (these are either SUPERSEDED rows or need a wording update). PDF vs docx numeric tokens identical: {same}.")
    Q("")
    Q("**Mismatches to fix (computed from the table):**"); Q("")
    for r in mm: Q(f"- **{r[0]}** ({r[1]}): {r[2]} - paper: {r[3]}; source: {r[4]}. {r[7]}")
    Q("")
    Q("**UNVERIFIABLE rows:**"); Q("")
    for r in [r for r in ROWS if r[6] == "UNVERIFIABLE"]: Q(f"- **{r[0]}** ({r[1]}): {r[2]} - {r[4]}. {r[7]}")
    Q("")
    Q("**MATCH rows whose wording deserves care (from the Note column):** A4/S4 (the permutation p belongs to a 10-fold AUC statistic, not the quoted LOOCV AUC); T1 ('489 test market moves' counts 114 distinct incidents repeatedly); T9 (85% is the single-run 9-feature figure; the 30-seed values are 87% [65%, 99%] for XGBoost and 100% for RF); T6b (the 271 -> 576 s split date differs from the 2024-01 split behind 'all others p >= 0.18'); T6c (sampled round windows); N2/N3 (second-labeler agreement is on shared sources).")
    Q("")
    body = "\n".join(L); print(body)
    pd.DataFrame(ROWS, columns=["id", "location", "claim", "paper", "source_value", "source", "status", "note"]).to_csv(REPORTS / "cjsj_34_paper_check.csv", index=False)
    write_section("cjsj_34_paper_check.py", "34", "Independent verification of the paper against the numbers files", TAG_CONFOUNDED + " (this section checks reported numbers; it adds no new model results except where marked recomputed)", body)


if __name__ == "__main__":
    main()
