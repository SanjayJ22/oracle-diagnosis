# Testing one candidate edge from structure learning: price_dev_d → congestion_d

**Verdict: does essentially nothing — not a clear win, no change made.** Adding
this single edge to the current production structure leaves accuracy and every
per-class recall figure **bit-for-bit identical** (154/165, 83.3%/33.3%/96.4%)
and produces only a negligible, likely noise-level calibration nudge (Brier
0.1330→0.1314, ECE 0.0450→0.0439, log-loss 0.3354→0.3331 — third-decimal-place
differences). The mechanistic story behind the edge is plausible, but the data
needed to actually test it is severely thin for exactly the two classes this
project cares most about separating — the honest read is "untestable with
current data," not "tested and found false."

## 1. Setup, and a correction made before running anything

`price_dev_d → congestion_d` was added to the current production `BN_EDGES` (7
static + 3 temporal features, `"fixed"` discretization default — `reports/
production_baseline_fixed.md`), keeping every other edge unchanged. Implemented
by temporarily appending the one edge to `models.BN_EDGES` and restoring it in a
`finally` block (the same safe monkey-patch pattern already used for
`BN_STATE_NAMES` in `src/temporal_features_eval.py`) — no permanent code change
in this pass.

**Correction, verified before running the comparison**: the task description
assumed `congestion_d` currently has one parent (`label_d`) and would gain a
second. Checked directly instead of assumed: `congestion_d`'s *only* edge in the
current production structure is `congestion_d → heartbeat_elapsed_d` — it is a
**root node with zero parents**, not a child of `label_d`. The star only
connects `label_d` to the *other* 9 discretized features; `congestion` was
deliberately left exogenous, entering the model only as `heartbeat_elapsed`'s
second parent. Adding the new edge therefore takes `congestion_d` from **0
parents to 1**, not 1 to 2 — a real but smaller data-split than the task
description anticipated. Reported here rather than silently corrected, since it
changes how severe the "spreading data thin" risk actually is.

## 2. Full LOOCV comparison, n=165

| Metric | Baseline (current production) | Extended (+ price_dev_d → congestion_d) |
|---|---|---|
| Accuracy | 93.3% (154/165) | 93.3% (154/165) — **identical** |
| Manipulation recall | 83.3% (20/24) | 83.3% (20/24) — **identical** |
| Malfunction recall | 33.3% (1/3) | 33.3% (1/3) — **identical** |
| Volatility recall | 96.4% (133/138) | 96.4% (133/138) — **identical** |
| Brier | 0.1330 | 0.1314 |
| ECE | 0.0450 | 0.0439 |
| Log-loss | 0.3354 | 0.3331 |

**Not one single incident's classification changes.** Every per-class recall
figure is identical to four significant figures, meaning the hard decision
(argmax of the posterior) is unchanged for all 165 held-out incidents. Only the
underlying probabilities shift slightly, and only enough to move the calibration
metrics in the third decimal place — the kind of movement that would need a
formal significance test (not attempted here, single dataset, no resampling) to
distinguish from noise, but is far too small to act on either way.

## 3. The data-thinning concern is real and severe — quantified directly

| | Rows with `congestion` present (0-parent baseline) | Rows with BOTH `price_dev` AND `congestion` present (1-parent extended) |
|---|---|---|
| Large volatility event | 135 | 135 (unaffected) |
| **Manipulation** | 23 | **3** |
| **Malfunction** | 3 | **1** |

Adding this one parent collapses the usable manipulation sample for
`congestion_d`'s CPD from 23 down to **3**, and malfunction from 3 down to
**1** — almost all of it driven by `price_dev`'s pre-existing, already-
documented missingness pattern (missing for most non-ETH-denominated
manipulation incidents and structurally hard to compute for malfunction). This
is exactly the risk flagged before running anything, and it is confirmed real
and severe for the two rarer classes specifically — not a hypothetical concern.

**Yet it doesn't visibly hurt.** Two plausible reasons, not fully distinguished
by this test: (a) `BayesianEstimator`'s BDeu prior smooths sparse cells toward
an uninformative default rather than overfitting to 1-3 real examples, so a
thin cell contributes little either way; (b) `congestion_d` was already a
comparatively weak, non-determinative feature for the classification decision
even as a root node, so making its distribution conditional on `price_dev_d`
— even badly, from too little data — doesn't move the overall posterior enough
to flip any decision.

## 4. Mechanistic plausibility: a real phenomenon, but not one this dataset can currently exploit

**The causal story is genuinely plausible, not a stretch.** Large price moves
are well-documented to trigger cascades of on-chain activity — liquidations of
undercollateralized positions, arbitrageurs racing to close DEX/CEX price gaps,
MEV searchers competing for the resulting opportunities — all of which compete
for block space and raise gas usage. This is a known Ethereum market-
microstructure phenomenon (the March 2020 "Black Thursday" crash's congestion
spike is a famous real-world instance of exactly this mechanism), not
something invented for this test.

**But plausible ≠ detected here, and the reason is data, not mechanism.** With
only 3 manipulation and 1 malfunction incident ever contributing to this edge's
CPD, this dataset cannot currently distinguish "the mechanism is real but too
weak to matter for classification" from "the mechanism is real but there isn't
enough data to see it yet." The honest characterization is **untestable with
current data**, not **tested and found not to hold** — a materially different,
more accurate claim than "the edge doesn't help," which could be misread as
evidence against the mechanism itself.

## 5. Leakage / no-lookahead check, including an instructive false alarm

Checked directly: excluding `TOPBPool` vs. excluding `Harvest Finance` from
training produces a **byte-identical** `congestion_d` CPD — worth explaining
rather than treating as a red flag. Both incidents individually have a missing
value between `price_dev` and `congestion` (`TOPBPool`: `price_dev` is `NaN`;
`Harvest Finance`: `congestion` is `NaN`) — **neither one was ever a complete-
case contributor to this specific CPD in the first place**, whether present in
training or not, so removing either one changes nothing about the CPD by
construction, not by a leakage bug. Confirmed genuine sensitivity elsewhere:
excluding a volatility incident that *does* have both features present ("Nov
2022 FTX collapse", one of the 135 complete-case volatility rows) produces a
CPD with visibly different values (`0.24632 → 0.24453` in one cell) — the model
is refitting correctly per fold; the earlier identical result was a real,
explainable consequence of which specific incidents were excluded, not a
caching or leakage problem. Every held-out incident confirmed absent from its
own fold's training set, consistent with every prior verification in this
project.

## 6. Malfunction n=3 — explicit, and this test could not meaningfully touch it

Malfunction recall is bit-for-bit unchanged (1/3) with or without this edge —
unsurprising given only 1 of the 3 malfunction incidents ever contributes to
the new edge's CPD at all. Any claim about this edge's effect on malfunction
specifically would be a claim about a single data point, and none is made
here. This mirrors every prior caveat in this project's history: nothing about
this test — or any single structural change tested at n=165 — can meaningfully
move a 3-example class's numbers into something trustworthy on its own.

## 7. Recommendation

**No change to `src/models.py`.** The edge does not clearly help — bit-for-bit
identical classification decisions and a calibration shift too small to
distinguish from noise. Per instruction, this is not flagged for a switch
decision (that's reserved for a clear win). Worth keeping on record for a
future revisit specifically if the manipulation class grows enough that
`price_dev` coverage for it meaningfully improves (currently 3 of 24
manipulation incidents have both features present) — the mechanism remains
plausible, and this result reflects a data-availability ceiling on this test,
not a settled negative finding about the underlying phenomenon.
