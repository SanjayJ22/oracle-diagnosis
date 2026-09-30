# C4. Novelty re-verification (2026-09-29)

Method: 6 web searches and 3 successful page fetches (a fourth, the Springer article, redirected to a login page and was not followed) on 2026-09-29 (search tool is US-only and returns titles
and snippets; the fetch tool summarizes with a small model). **This is not a systematic review.**
Anything marked `abstract-level` was not read in full. `project_summary_final.md` section 6 should
be treated as superseded by this file for citations and novelty wording.

## 1. Corrections to the project's current text

| Existing claim (`project_summary_final.md` s6 / v2 s8) | Finding | Action |
|---|---|---|
| TOAD-ML is a binary detector and "does not distinguish manipulation from malfunction" | Partly wrong. The paper states it differentiates manipulation vs. volatility (through cross-source consistency scoring) and malfunction (through update-frequency monitoring), though its output is a binary label plus a continuous trust score and I found no 3-class evaluation | reword; read full text before citing |
| TOAD-ML is "opaque", this project is the interpretable one | Overstated. TOAD-ML's trust layer uses a "Bayesian-inspired posterior adjustment" and decomposes trust into three named components; its XGBoost classifier itself has no local explanation method | narrow the interpretability claim |
| Chockalingam et al. = "Bayesian Network Models in Cyber Security: A Systematic Review" is the attack-vs-failure precedent | **Wrong citation.** The 2017 review surveys 17 standard BN models in cyber security. The attack-vs-failure paper is a different one (below) | replace |
| "Floodgates" characterization | Correct, but it belongs to the 2021 paper | cite that paper |

## 2. Verified sources

### TOAD-ML (nearest neighbor)
- Venkatraman, D. and Kuppusamy, M. (VIT). *TOAD-ML: a trust-aware framework for validating oracle
  price feeds and detecting manipulation in decentralized finance.* Frontiers in Blockchain,
  published 3 September 2026. doi 10.3389/fbloc.2026.1903202.
- Data: DeFiHackLabs, CoinGecko, Chainlink, Uniswap V3 TWAP, DeFiLlama. 19 months, **4** documented
  oracle attacks, about 60 attack-days, **hourly** readings.
- Features: cross-source deviation, temporal instability, consistency score, update frequency,
  unified deviation score. Model: XGBoost plus a trust-calibration layer.
- Reported: accuracy 96.72%, AUC 0.97, precision 0.96, recall 0.95, F1 0.95; baselines SVM 88.42%,
  RF 91.76%, XGBoost 93.85%.
- Negative class: hourly periods where oracle, CoinGecko, Uniswap TWAP and DeFiLlama agree.
  Volatility is "handled through temporal instability indexing rather than filtering".
- Stated limits: latency not evaluated; sensitivity to Z-score threshold, tokens and periods;
  generalization to broader conditions left for future work.
- (Source for all of the above is a summarized fetch, `abstract-level` to `section-level`.)
- **Relevance to this project's audit:** its negative class is periods of multi-source agreement,
  not matched benign anomalies. That looks structurally like our C1 (class defined by the same
  signals used to classify), but I have not confirmed it from the full text, so I make no claim
  about it in the paper.

### Chockalingam et al. (methodological precedent)
- Chockalingam, S., Pieters, W., Teixeira, A., van Gelder, P. *Bayesian network model to distinguish
  between intentional attacks and accidental technical failures: a case study of floodgates.*
  Cybersecurity 4(1): 29, 2021. doi 10.1186/s42400-021-00086-6.
- Abstract-level: a BN built and validated with safety and security experts for incorrect sensor
  measurements in floodgates; the point is that mistaking an attack for a failure leaves the attack
  vector open. **Expert-constructed, not data-learned** (at abstract level).
- Related, same group: "Combining Bayesian Networks and Fishbone Diagrams to Distinguish Between
  Intentional Attacks and Accidental Technical Failures" (Springer chapter, doi 10.1007/978-3-030-15465-3_3;
  author list and venue not verified in this pass) and a water-management ICS paper (TU Delft portal
  record; details not verified).
- The 2017 review (kept only as background): Chockalingam, Pieters, Teixeira, van Gelder,
  *Bayesian Network Models in Cyber Security: A Systematic Review*, NordSec 2017, LNCS,
  doi 10.1007/978-3-319-70290-2_7. Identifies 17 standard BN models; notes insider threats as the
  dominant use.

### DeFiTrace (roadmap D3)
- Pratiwi, M. and Choi, Y.-H. *DeFiTrace: Event-Enriched Detection of Price Oracle Manipulation
  Across DeFi Transactions.* ACM Transactions on Privacy and Security, published online 22 May 2026.
  doi 10.1145/3817054.
- Transaction-level (event logs plus execution traces), targets multi-transaction attacks and works
  without source code. Different input modality from market-price observables; cite as related
  work, not as a competitor to this project's setting.

## 3. Other neighbors seen (titles/snippets only, not read)

All are contract-, transaction-, or code-level (static/dynamic analysis, GNNs, LLMs), not
market-observable classification:

- DeFiGuard: GNN price-manipulation detection (arXiv 2406.11157).
- AiRacleX: LLM-driven oracle-manipulation detection (arXiv 2502.06348).
- DeFiTainter (ISSTA 2023), DeFort (ISSTA 2024).
- Xiong, Liu, Li. *A Lifecycle-Oriented Detection and Defense Framework for Price Manipulation
  Attacks in DeFi* (arXiv 2608.15518, 16 Aug 2026): attack tree, fuzzy-AHP + VaR, taint-tracking
  tool; abstract reports 94.38% accuracy, 92.31% recall.
- DeFiScreener (arXiv 2607.22184), LLM-powered detection (arXiv 2510.21272), arXiv 2502.11521.

## 4. What the evidence supports about novelty

- I found **no** paper that uses a Bayesian network on market-observable features to classify
  oracle anomalies as manipulation vs. genuine volatility (or vs. malfunction). This is a
  **non-systematic negative**, from snippet-level searches.
- The overlap with TOAD-ML is larger than the current text admits: multi-source deviation features,
  a manipulation-vs-volatility claim, a malfunction signal, and a Bayesian-flavored component.
  TOAD-ML was published 26 days before this file; any submission must cite and position against it.
- A defensible narrowed claim: an **incident-level, interpretable probabilistic classifier** with
  explicit per-incident evidence contributions and calibration, evaluated on matched benign
  anomalies (after the rebuild). Whether it is *better* than XGBoost-style models is not claimed
  (the audit shows BN and RF are statistically indistinguishable on the static benchmark).
- Nothing about performance or the confound-corrected result can be claimed until A5 passes.

## 5. Remaining verification work (not done)

1. Read the **full text** of TOAD-ML (negative-class construction, evaluation split, how "manipulation
   vs. volatility" is actually evaluated, whether a malfunction class is scored).
2. Read the Chockalingam 2021 paper in full (elicitation method, validation, any data-driven
   parameter learning) and confirm the 2019 paper's authors and venue.
3. A structured search log: Google Scholar, arXiv, SSRN, ACM DL, IEEE Xplore, Semantic Scholar.
   Query families: "oracle manipulation detection" + {Bayesian, probabilistic, anomaly, market
   data, volatility}; "flash loan attack detection"; "price feed deviation"; "circuit breaker
   oracle". Record query, date, database, hits screened, inclusion decision.
4. Grey literature that practitioners would call prior art: Chainlink docs on market-manipulation
   mitigations, Chaos Labs / Gauntlet / LlamaRisk oracle-risk writeups, Maker OSM and Aave
   sanity-check designs (relevant to B10 baselines).
5. Recheck within 72 hours of any submission (field moves fast: TOAD-ML, DeFiTrace and the lifecycle paper above are all under 5 months old).

## 6. Decision needed from you

Approve replacing section 6 of `project_summary_final.md` (C5) with the corrected citations and the
narrowed claim above, or tell me to hold until the full-text reads in section 5 are done.
