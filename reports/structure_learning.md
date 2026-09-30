# Structure learning: Chow-Liu and Hill-Climbing vs. the hand-drawn Bayesian network

**Verdict up front, since it's unambiguous: the hand-drawn structure wins clearly.**
Neither learned structure beats it on accuracy, manipulation recall, Brier, or
log-loss. Chow-Liu's manipulation recall (12.5%) is catastrophically worse than
hand-drawn's (83.3%), and this is mechanistically explained, not just observed
(§4). Hill-climbing does better than Chow-Liu but still underperforms hand-drawn
on every metric except ECE. **No change made to `src/models.py`'s default
structure** — this result doesn't call for one, and even if it had, the
instruction was to flag rather than switch silently.

## 1. Method

Implemented in `src/structure_learning.py` (new file, does not modify `models.py`).
Structure is learned **per LOOCV fold, from training data only** — for each of the
165 folds, the held-out incident is excluded before either (a) class-conditional
discretization thresholds are computed (reusing `models.py`'s
`_class_conditional_threshold` unchanged) or (b) a structure is learned from the
resulting discretized training data. Two algorithms:

- **Chow-Liu** (`pgmpy.estimators.TreeSearch`, `estimator_type="chow-liu"`,
  rooted at `label_d`): produces a maximum-mutual-information spanning **tree**,
  oriented outward from the label.
- **Hill-Climbing + BDeu score** (`pgmpy.estimators.HillClimbSearch` with
  `pgmpy.estimators.BDeu(equivalent_sample_size=2)`, matching the equivalent
  sample size already used for CPD fitting throughout this project, `max_indegree=3`
  to keep resulting CPD tables fittable from ~164 training rows): produces a
  **general DAG**, unconstrained in which nodes may have edges to which — including
  the possibility of features causing the label, or edges between two features
  the hand-drawn star assumes are independent, which is exactly what this
  comparison is for.

All three structures (hand-drawn, Chow-Liu, hill-climbing) are then evaluated
through the **exact same CPD-fitting and prediction code** (per-node
`dropna()`, `BayesianEstimator` with a BDeu prior, `VariableElimination`) —
identical to `models.py`'s `fit_bayesian_network`/`predict_bayesian_network`,
just parameterized by a different edge list. This was verified directly: running
the hand-drawn structure through this harness reproduces `reports/
discretization_v2.md`'s exact numbers (93.3% accuracy, 83.3% manipulation recall,
Brier 0.129, ECE 0.053, log-loss 0.290) — confirming the comparison is fair and
not an artifact of a different harness.

## 2. A methodological fix that had to happen first: missingness collapses the training data

Chow-Liu and Hill-Climbing both need one complete data matrix (no per-cell NaNs),
unlike CPD-fitting, which already tolerates missingness via per-node `dropna()`.
**Naively dropping any row with a missing feature leaves only 1 manipulation
incident and ZERO malfunction incidents** in the data available to learn structure
from — checked directly before running anything. `price_dev`, `cross_venue_spread`,
and `dex_oracle_spread` are missing *together* for 81-96% of the incidents where
any of them is missing (mostly non-ETH-denominated manipulation and all 3
malfunction incidents, which structurally lack a clean CEX/DEX comparison price):

| Pair | Both missing | Either missing | Overlap |
|---|---|---|---|
| price_dev & cross_venue_spread | 22 | 26 | 85% |
| price_dev & dex_oracle_spread | 21 | 26 | 81% |
| cross_venue_spread & dex_oracle_spread | 25 | 26 | 96% |

**Fixed by encoding "missing" as its own explicit discrete state
(`f"{prefix}_missing"`) for the structure-learning step only** — CPD fitting and
prediction, for all three structures, still use the original 2-state (low/high,
NaN skipped) encoding, unchanged from production. This lets structure learning see
all 165 incidents including all 3 malfunction cases, but it has a real, diagnosed
side effect described next.

## 3. The missingness confound: several learned edges reflect co-missingness, not co-variation

Because `price_dev`, `cross_venue_spread`, and `dex_oracle_spread` are missing
together so often, their `_missing` states are highly correlated with **each
other** — both structure-learning algorithms pick this up as strong mutual
information, and both produce a dense cluster of edges directly connecting these
three features to each other:

- Chow-Liu: `cross_venue_spread_d → price_dev_d` (100% of folds), `cross_venue_spread_d
  → dex_oracle_spread_d` (99%).
- Hill-Climbing: the same two edges (99%, 96%), plus `heartbeat_elapsed_d →
  dex_oracle_spread_d` (95%) and `heartbeat_elapsed_d → price_dev_d` (95%) —
  heartbeat_elapsed itself is never missing, so these two edges are more likely
  picking up a genuine class-correlated pattern routed through the missingness
  cluster, but this can't be fully disentangled from the confound without a
  dedicated follow-up (not attempted here).

**This is flagged as a real limitation of what these learned structures mean, not
swept under the rug**: an edge between two of these three features should not be
read as "these features' values are related" — it is at least partly, and
possibly mostly, "these features are absent for the same incidents."
`price_dev_d → congestion_d` (99% of Chow-Liu folds, 6% of Hill-Climbing folds) is
the one recurring cross-feature edge in this project's variable set that does
**not** involve the missingness cluster or the label (`price_dev` and `congestion`
have 0% missingness overlap) — the one candidate in this analysis for a
potentially genuine, previously-unmodeled feature dependency, worth a dedicated
follow-up rather than acted on here.

## 4. Does the learned structure recover `congestion_d → heartbeat_elapsed_d`? No — 0/165, either algorithm, either direction

Checked explicitly across all 330 fold-structure-learning runs (165 folds ×
2 algorithms): **the hand-added `congestion_d → heartbeat_elapsed_d` edge (or its
reverse) never appears, not once.** This is a clean, direct answer, not a close
call. Two honest readings are possible, and this analysis cannot fully
distinguish them: (a) the hand-added edge doesn't reflect a strong enough
statistical dependency for either algorithm's scoring criterion to prefer it over
competing structures, or (b) `heartbeat_elapsed`'s missingness-free, wide-range
distribution and `congestion`'s own near-uniform spread give this specific pair
low mutual information / BDeu-score improvement relative to other candidate edges,
regardless of whatever domain reasoning motivated adding it by hand. Either way,
**this hand-added edge is not validated by structure learning** — worth knowing
even though (§6) the overall hand-drawn structure still wins decisively, meaning
this one edge is not pulling much weight either way (see the ablation-style
finding in `reports/project_summary.md` §6, where dropping `heartbeat_elapsed`
hurt more than dropping `congestion` alone).

## 5. Which hand-drawn edges are kept, dropped, or contradicted

The hand-drawn structure is a star: `label_d → {price_dev_d, cross_venue_spread_d,
dex_oracle_spread_d, reserve_skew_d, ref_realized_vol_d, heartbeat_elapsed_d}`,
plus `congestion_d → heartbeat_elapsed_d`.

**Kept by both learned structures, most folds**: `label_d → cross_venue_spread_d`
(100% Chow-Liu, 98% Hill-Climbing), `label_d → heartbeat_elapsed_d` (99% / 24% —
Hill-Climbing usually flips this to `heartbeat_elapsed_d → label_d` instead, 75%
of folds — see below), `label_d → ref_realized_vol_d` (98% / 79%).

**The single most consequential drop, and the reason Chow-Liu's manipulation
recall collapses**: `label_d → reserve_skew_d` — the edge this project's own
ablation work (`reports/project_summary.md` §6) already identified as one of
the two features NB relies on for manipulation — appears in only **5/165 (3%) of
Chow-Liu folds**. Chow-Liu's tree constraint forces every non-root node to have
exactly one parent; mutual-information-wise, `reserve_skew_d` connects more
strongly to `price_dev_d` (96% of folds) than directly to the label, so the tree
routes it through `price_dev_d` instead. Because `price_dev_d` is itself missing
for most manipulation incidents (and entangled with the missingness cluster, §3),
this indirect routing loses most of `reserve_skew`'s direct discriminating power
for manipulation — a mechanistic, not just correlational, explanation for why
Chow-Liu's manipulation recall (12.5%) is so much worse than hand-drawn's (83.3%).
**Hill-Climbing, not being tree-constrained, keeps `label_d → reserve_skew_d` in
87% of folds** — much closer to the hand-drawn structure on this specific edge —
yet still underperforms hand-drawn overall (§6), most likely because it also
frequently gives `reserve_skew_d` two or three *additional* parents
(`price_dev_d` 95%, `dex_oracle_spread_d` 82%, `ref_realized_vol_d` 13%), and
fitting a CPD with up to 3 binary/ternary parents from ~23 training-fold
manipulation incidents spreads them thin across up to 8+ parent-state
combinations, diluting the learned signal toward the BDeu prior's near-uniform
default in cells with few or no examples.

**A genuinely new structural finding, present in both algorithms**:
Hill-Climbing prefers `heartbeat_elapsed_d → label_d` (75% of folds) over the
hand-drawn `label_d → heartbeat_elapsed_d` (only 24%). This should not be
over-read as a causal claim — correlational data alone often cannot distinguish
which orientation is "correct" in the causal sense, and BDeu scoring is sensitive
to each node's own state-count and prior — but it is a real, repeated preference
in the data as scored, not a one-off fold artifact, and is reported here as an
interesting structural observation rather than either accepted or dismissed.

**No hand-drawn edge is directly contradicted** (i.e., no learned structure
found an edge running in a way that positively excludes a hand-drawn dependency)
— every divergence is either an added edge (mostly missingness-cluster
connections, §3) or a dropped/rerouted one (`reserve_skew`'s connection to label,
above).

## 6. Full LOOCV comparison, n=165, class-conditional discretization

| Metric | Hand-drawn (current default) | Chow-Liu | Hill-Climbing |
|---|---|---|---|
| Overall accuracy | **93.3% (154/165)** | 83.6% (138/165) | 87.9% (145/165) |
| Manipulation recall | **83.3% (20/24)** | 12.5% (3/24) | 50.0% (12/24) |
| Malfunction recall | 0/3 | **1/3 (33.3%)** | 0/3 |
| Volatility recall | 97.1% (134/138) | 97.1% (134/138) | 96.4% (133/138) |
| Brier | **0.129** | 0.262 | 0.214 |
| ECE | 0.053 | 0.054 | **0.025** |
| Log-loss | **0.290** | 0.435 | 0.426 |
| CPD fit failures | 0/165 | 0/165 | 0/165 |

Zero CPD-fitting failures for any structure across all 165 folds, for all three
structures — no fold needed to be excluded or handled as a special case.

**Hill-Climbing's one real edge over hand-drawn is ECE** (0.025 vs. 0.053) — its
confidence calibration is marginally better even though its raw accuracy and
manipulation recall are both substantially worse. **Chow-Liu's one edge is
malfunction recall** (1/3 vs. hand-drawn's 0/3) — with n=3, this is one incident,
not a trend (§8).

## 7. Honest verdict

**Hand-drawn wins, decisively, not narrowly.** This is not a case where the
learned structure is "similar, validating the hand-drawn choice" (accuracy and
manipulation recall differ by 6-71 percentage points, not a rounding difference),
nor a case where a learned structure "beats" it (neither learned structure wins on
more than one of seven metrics, and that one win each — ECE for Hill-Climbing,
malfunction recall for Chow-Liu — comes with a large loss everywhere else). This
is the third named outcome: **hand-drawn domain knowledge wins on this data**, for
a mechanistically understood reason specific to Chow-Liu (the tree constraint
forces `reserve_skew` off the label and behind `price_dev`, which is itself
compromised by the missingness confound) and a data-sparsity reason for
Hill-Climbing (a less-constrained search finds more edges than ~165 rows split
three ways, with a 3-example minority class, can reliably support).

This should not be read as "structure learning failed" in some general sense —
it is a specific, diagnosed outcome of this dataset's two defining
characteristics (severe class imbalance and a large, class-correlated
missingness pattern), not a claim that Chow-Liu or Hill-Climbing are bad
algorithms. A dataset without this project's missingness asymmetry, or with more
malfunction examples, might tell a different story.

## 8. Malfunction n=3 — explicit caveat, and structure learning does not change it

Every number in §6 for the malfunction row is a statement about 3 incidents.
Chow-Liu's 1/3 and both other structures' 0/3 are each **one single incident's
outcome**, not a stable rate — flipping which one incident is held out could
plausibly flip this number entirely. Structure learning is, if anything, *more*
exposed to this instability than the hand-drawn structure: a learned DAG's shape
itself depends on which 2 of the 3 malfunction incidents happen to be in the
training fold, compounding the small-sample fragility already documented
throughout this project (`reports/loocv_150_incidents.md` onward) with a second
layer of instability in the structure itself. No conclusion in this report treats
the malfunction numbers as more than anecdotal.

## 9. Leakage / no-lookahead check

Verified directly, not just asserted correct by construction. Learned structure
genuinely depends on which incidents are in the training fold: excluding
TOPBPool vs. excluding Harvest Finance (with TOPBPool included) from Chow-Liu's
training data produces a **4-edge symmetric difference** in the learned tree
(`price_dev_d ↔ ref_realized_vol_d`, `label_d ↔ ref_realized_vol_d`, `price_dev_d
↔ reserve_skew_d`, `cross_venue_spread_d ↔ reserve_skew_d` each present in one
fold's structure and not the other). This confirms structure is recomputed fresh
per fold from training data only, the same control-flow guarantee already
verified for discretization thresholds in `reports/discretization_v2.md`. The
held-out incident's own row is never included in any `train`/`train_missing`
dataframe passed to either structure-learning or threshold-computation call
(`train = df.drop(df.index[i])`, identical to `loocv_bayesian_network`'s existing
pattern) — confirmed by direct code inspection of `structure_learning.py`'s
`run_loocv_for_structure`.

## 10. Recommendation

**No change to `src/models.py`'s default structure.** The result here doesn't
call for one — the hand-drawn structure wins clearly on the metrics that matter
most (accuracy, manipulation recall, Brier, log-loss), and its one weak point
(malfunction recall, 0/3) is not improved in any way that survives the n=3
instability caveat. Per instruction, this would only be flagged for your decision
if a learned structure had clearly won; none did, so nothing is flagged for a
switch. The one concrete, well-motivated follow-up this analysis surfaces: `price_
dev_d → congestion_d` recurred in 99% of Chow-Liu folds and is not explained by
the missingness confound (§3) — worth a dedicated, deliberate investigation into
whether this is a real dependency worth hand-adding, the same way `congestion_d →
heartbeat_elapsed_d` was added originally, rather than acted on inside this
already-large comparison.
