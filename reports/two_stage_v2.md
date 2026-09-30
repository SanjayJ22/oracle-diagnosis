# Two-stage architecture, re-tested on the current production model (n=165, fixed discretization)

**Refreshed as part of `reports/refresh_summary.md`'s staleness pass.** This
report previously ran on class-conditional discretization (the production
default at the time it was first written); production has since switched to
`"fixed"` discretization (`reports/discretization_robustness.md`,
`reports/production_baseline_fixed.md`). Re-running under the current default
changes the picture **materially, not just numerically** — the calibration
advantage that was this analysis's headline finding has essentially
evaporated. `src/two_stage_v2.py` was updated to support `discretization=
"fixed"` (now its default; `"class_conditional"` remains available for
comparison) rather than being hardcoded to the old scheme.

**Verdict, updated: still mixed, but the mix changed shape.** Two-stage now
**ties** the flat BN on manipulation recall (83.3% vs. 83.3%, up from a
-8.3-point gap under class-conditional discretization) and **loses** on
malfunction recall (0/3 vs. flat's 1/3, a new gap that didn't exist before).
Its calibration advantage — previously "wins decisively on all three
metrics" — is now close to parity on Brier (0.132 vs. 0.133) and log-loss
(0.317 vs. 0.335, a much smaller edge than before), and has **flipped to a
loss** on ECE (0.069 vs. flat's 0.045). Production stays unchanged; this still
doesn't clearly win.

## 1. What changed, and why this refresh matters beyond updated numbers

The original two-stage test (`src/two_stage_analysis.py`, ~45 incidents) lost
outright. The first re-test (`src/two_stage_v2.py`'s initial run, 165
incidents, **class-conditional** discretization) found a genuine, if partial,
recovery: two-stage lost on accuracy/manipulation recall but won decisively on
all three calibration metrics. **That finding turns out to have been
substantially an artifact of which discretization scheme was compared
against**, not a stable property of the two-stage architecture itself — with
the production default now `"fixed"`, most of the calibration edge is gone.
This is exactly the kind of dependency this project's own discretization
history should have made unsurprising in retrospect (`reports/
discretization_robustness.md` already showed `class_conditional` and `fixed`
disagree substantially under compositional differences) — but it hadn't
previously been checked for the two-stage architecture specifically, and now
has been.

## 2. Full LOOCV comparison, n=165, fixed discretization

| Metric | Flat 3-class BN (production) | Two-stage | Two-stage under class_conditional (prior run, for reference) |
|---|---|---|---|
| End-to-end accuracy | **93.3% (154/165)** | 92.7% (153/165) | 92.7% |
| Manipulation recall | 83.3% (20/24) | **83.3% (20/24) — now tied** | 75.0% |
| Malfunction recall | **33.3% (1/3)** | 0/3 — now a new gap | 0/3 |
| Volatility recall | 96.4% (133/138) | 96.4% (133/138) — tied | 96.4% |
| Brier | 0.1330 | 0.132 — **near parity** | 0.080 |
| ECE | **0.0450** | 0.069 — **now a loss** | 0.026 |
| Log-loss | 0.3354 | **0.317 — still slightly better, smaller margin** | 0.135 |
| Fit failures | 0/165 | 1/165 (Stage 2, one fold) | — |

**Stage-level detail** (Stage 1: oracle-failure vs. volatility, all 165 folds;
Stage 2: manipulation vs. malfunction, evaluated on the 27 true oracle-failure
incidents using Stage 2's own prediction regardless of what Stage 1 said):

- **Stage 1 accuracy: 92.7% (153/165)** — 133/138 volatility correct, 20/27
  oracle-failure correct (7 misrouted to volatility).
- **Stage 2 accuracy (isolated): 92.3% (24/26, 1 fit failure)** — 22/24
  manipulation correct, 2/3 malfunction correct (UST/USD and one other) —
  still notably better than the flat model's 1/3 malfunction recall *when
  judged in isolation*, echoing the original finding, but this no longer
  translates into an end-to-end win (§4).

## 3. Why end-to-end still underperforms on manipulation despite now tying flat: the same Stage-1-gate mechanism

The mechanism identified in the original run still holds, verified fresh: Stage
1 acts as a gate that a correct Stage 2 call cannot override, because the
final posterior is `P(oracle_failure) × P(manipulation | oracle_failure)` — a
low first factor drags the product down regardless of the second. What
changed is the *frequency* of this happening: under `class_conditional`, this
mechanism cost two-stage ~8 points of manipulation recall relative to flat;
under `fixed`, Stage 1 apparently misroutes fewer manipulation incidents (or
Stage 2 corrects for more of them), closing the gap to zero. This is a real
improvement specific to how `fixed` discretization happens to draw Stage 1's
boundary, not evidence the underlying architectural limitation (Stage 1 as an
unrecoverable gate) has been resolved — it would need to be re-checked again
under any future discretization change.

## 4. Malfunction: the isolated Stage 2 advantage still doesn't survive Stage 1's gate

| Incident | Stage 1 predicted | Stage 2 predicted (computed regardless) | Final (chain-rule) | Confidence |
|---|---|---|---|---|
| stETH/ETH heartbeat lag | large volatility event (misrouted) | malfunction (correct, in isolation) | large volatility event | 0.931 |
| FTT/USD pause/deprecation | oracle_failure (correct) | manipulation (wrong) | manipulation | 0.522 |
| UST/USD feed freeze | large volatility event (misrouted) | manipulation (wrong) | large volatility event | 0.994 |

**A genuine change from the prior run**: Stage 2 now gets UST/USD wrong too
(previously correct in isolation) — meaning the "Stage 2 catches malfunction
that the flat model can't" finding, while still true in the abstract (Stage 2
alone: 2/3 malfunction correct), narrowed from 1-clean-case to a messier
picture where the ONE case that reaches Stage 2 correctly routed (FTT/USD)
still gets the wrong Stage-2 answer. **End-to-end malfunction recall is 0/3**
— unchanged in outcome from the prior run, but now *worse* relative to the
flat model, which independently gained a correct malfunction call (1/3) under
the same discretization switch that this analysis didn't benefit from in the
same way.

## 5. Stage 2's data scarcity — unchanged caveat, still real

Stage 2 trains on only ~26-27 incidents per fold, with malfunction
contributing at most 3 (2 when a malfunction incident is itself held out).
This hasn't changed with the discretization switch, and the ~1/165 fit-failure
rate (one Stage-2 CPD with zero complete training rows in one fold) persists
as a direct symptom of it. Every finding in this report involving the
malfunction class should be read as a statement about 3 specific points,
exactly as throughout this project's history.

## 6. Leakage / no-lookahead check

Re-verified for the fixed-discretization configuration specifically (not just
assumed inherited from the prior class-conditional check): the `"fixed"`
scheme's thresholds are constants by construction (confirmed `0.05` for
`reserve_skew` regardless of training fold, identical to the flat model's own
verification in `reports/production_baseline_fixed.md`), and Stage 2's
training subset genuinely excludes the held-out incident and genuinely varies
in size/composition per fold (the same `train = df.drop(df.index[i])`
control-flow guarantee as every prior verification in this project, unchanged
by the discretization-scheme edit).

## 7. Recommendation

**No change to `src/models.py`.** If anything, this refresh weakens the case
for two-stage relative to the previous version of this report: the
calibration advantage that was its strongest selling point is now marginal
(log-loss) or reversed (ECE), while it picked up a new loss (malfunction
recall) that didn't exist before. The one genuine improvement — manipulation
recall now tying rather than trailing the flat model — isn't enough on its own
to flag this for a decision. This result is a useful reminder, not just for
two-stage but for any future architectural comparison in this project: **a
verdict computed under one discretization scheme should not be assumed stable
under another** without being explicitly re-checked, exactly what this refresh
did.
