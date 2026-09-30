# Oracle diagnosis: price-oracle attacks vs genuine market volatility

Code, analysis logs and paper for *Distinguishing Price-Oracle Attacks from Genuine Market Volatility in Decentralized Finance Using Market Data* (Sanjay Jillellamudi).

Main finding: on 162 Ethereum incidents (24 exploits, 138 large market moves) a Bayesian network (BN), a random forest and XGBoost all reach 95-98% leave-one-out accuracy, but most of the separation is a
measurement shortcut (market-context features that say nothing about the attacked asset predict the label with AUC about 0.91). Verifying the labels against two independent post-mortems reduces the attack
class from 24 to 9. **All model results on the 162-incident table are within-benchmark results on confounded data**; read `reports/research_audit.md` before citing any of them.

## Licence

Code: MIT (see `LICENSE`). The data files `data/processed/features.parquet` and `data/processed/labels_a2.csv` are licensed CC BY 4.0. The paper files are not distributed in this repository (build scripts and figure PNGs are).

## Layout

| Path | Contents |
|---|---|
| `src/cjsj_*.py` | one script per numbered analysis section (1-47); each rewrites its own `## N.` section of `reports/cjsj_numbers.md` |
| `src/cjsj_common.py`, `cjsj_eval.py`, `cjsj_lcs.py`, ... | shared helpers (evaluation harness, BN, feature sets, attribution) |
| `src/models.py`, `build_features.py`, `fetch_*.py`, `mine_*.py` | dataset construction and the three models (earlier phases) |
| `src/pilot_*.py` | pilot of the corrected measurement protocol (block-resolution re-measurement) |
| `reports/cjsj_numbers.md` | the results log: every number cites its script |
| `reports/cjsj_*.csv`, `reports/figures/` | per-script raw outputs and figures |
| `reports/research_audit.md`, `a2_label_*`, `pilot_results.md`, `spec_lock_2026-09-30.md` | validity audit, label protocol and sheet, pilot results, pre-registered pilot spec |
| `reports/second_labeler/` | second-labeler packet and answers (agreement study) |
| `reports/cjsj_submission/` | figure PNGs and the paper build scripts (the paper files themselves are not tracked) |
| `requirements-cjsj.txt` | pinned package versions the numbers were produced with (Python 3.13) |

## Reproduce the CJSJ numbers (one command)

```bash
python3.13 -m venv .venv && .venv/bin/pip install -r requirements-cjsj.txt
# macOS only, once, if xgboost cannot find libomp:  brew install libomp   (the scripts also try the libomp bundled with scikit-learn)
.venv/bin/python src/reproduce_cjsj.py
```

This runs the 40 offline scripts in dependency order (03 writes the LOOCV predictions used by 04, 07, 25, 43, 45; 28/29/32 feed the figure scripts 30/31; 39 feeds the paper check 34), rewrites the sections
of `reports/cjsj_numbers.md` in numeric order, and prints one `ok`/`FAIL` line per script. Options: `--only 35,47` (selected items), `--keep-going`, `--network` (see below).
Random seeds are fixed in every script; a clean-clone test of items 35, 42 and 47 reproduced those sections exactly apart from the `(run ...)` timestamp. The full run has not been timed end to end
(on 8 cores individual scripts take from about 20 s to a few minutes).

**Input data.** The scripts read `data/processed/features.parquet` (the 162-incident feature table, 556 KB) and, for the label sets, `reports/a2_label_sheet.csv`. Both files are tracked in this repository (everything else under `data/` is gitignored), so a fresh clone reproduces without extra data; `labels_a2.csv` is also rewritten by item 11. Rebuilding the table from scratch means re-reading Ethereum history
(`src/fetch_*.py`, `build_features.py`) and needs an archive-node endpoint.

**Network scripts (skipped by default).** Items 06 (same-sender transaction history), 26 (ETH/USD at the attack block for dollar losses) and 33 (Chainlink feed history) read Ethereum mainnet through an
Alchemy endpoint. Their outputs are committed (`cjsj_06_atomicity.csv`, `cjsj_26_losses.csv`, `cjsj_33*.csv`) and later scripts read those. To rerun them, create `.env` with your own
`ALCHEMY_KEY=<key>` (never commit it) and pass `--network`. The free tier caps `eth_getLogs` at 10 blocks; the scripts use point reads (`getRoundData`, `eth_call`) for that reason.

## Checking the paper against the numbers

`src/cjsj_34_paper_check.py` (run automatically only if the paper `.docx` is present locally; otherwise the driver skips it) compares each quantitative claim in `reports/cjsj_submission/JillellamudiSanjay_paper.docx` with the source section and writes `reports/cjsj_34_paper_check.csv`
(MATCH / MISMATCH / UNVERIFIABLE / SUPERSEDED, with the source cited per row).

## Caveats

- The 138 negatives are ETH/USD moves of 3-5% or more measured on one ETH pool, while 23 of 24 attacks use ETH/USD as a fallback instrument: class membership is partly recoverable from how the row was measured.
  Results are labelled accordingly in every section; only the verified-label reruns (9 positives) are flagged as such.
- With 9 verified attacks the smallest AUC distinguishable from chance (80% power) is 0.745; no classifier result on the verified set is claimed to be significant.
- Random-forest results depend on training-row order as well as on the seed; sections 41 and 44 quantify this.
