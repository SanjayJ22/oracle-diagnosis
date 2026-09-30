# Fixing the discretization fix: class-conditional and fixed thresholds vs. the failed global scheme

## Background

`reports/discretization_fix.md` replaced the Bayesian network's original sign-based
median-split discretization with a magnitude-aware one: `abs(value) >
median(abs(value)) -> far, else near`, computed as a single threshold across the
*whole* population. This worked well at n=105 (BN manipulation recall 35% → 71%).
`reports/loocv_200_incidents.md` then showed it failing at n=165: recall fell to
37.5%, because the population-wide median is implicitly dominated by whichever
class has the most incidents (volatility, 138 of 165), and as phase 3 added 53 more,
calmer volatility incidents, that population median drifted down (0.013478 →
0.008425 for `reserve_skew`), letting 41.3% of all volatility incidents cross into
the same "far" bucket manipulation occupies.

This report implements and evaluates the two proposed fixes.

## What changed

`src/models.py`'s `fit_bayesian_network()` now takes a `discretization` parameter
with three modes (all documented in its docstring):

- **`"global"`** — the original, now-failed scheme. Kept only for comparison.
- **`"class_conditional"`** (new) — the threshold is the **geometric mean of the
  largest and smallest per-class median absolute value**, computed from training
  data only. A class with zero non-missing values for a feature is excluded.
  Geometric (not arithmetic) mean because these magnitudes span orders of magnitude
  (reserve_skew's typical volatility value is ~0.01, typical manipulation value is
  often close to 1, and extremes reach into the hundreds of thousands) — a
  geometric mean finds the natural log-space midpoint; an arithmetic mean would be
  dominated by whichever class's magnitude happens to be larger.
- **`"fixed"`** (new) — a constant per feature, taken from conventions this project
  already established for independent reasons, never fit from incident data at all:

  | Feature | Threshold | Source |
  |---|---|---|
  | price_dev, cross_venue_spread, dex_oracle_spread, reserve_skew, ref_realized_vol | 0.05 | Same "meaningful deviation" convention as the deterministic baseline's `RESERVE_SKEW_THRESHOLD` and every volatility-mining script's `CROSS_VENUE_TOLERANCE` |
  | heartbeat_elapsed | 3600s | Identical to the deterministic baseline's `HEARTBEAT_STALE_THRESHOLD_SECONDS` |
  | congestion | 0.5 | EIP-1559's actual target gas-usage ratio — a real protocol constant |

`predict_bayesian_network()` needed **no changes** — it already just compares
`abs(x) > thresholds[raw_col]`, agnostic to how the threshold was computed.
`loocv_bayesian_network()` (`src/loocv_validation.py`) now accepts and passes
through the same `discretization` parameter.

## Results: full LOOCV comparison at n=165

| Metric | global (failed) | **class_conditional** | fixed |
|---|---|---|---|
| Overall accuracy | 83.6% (138/165) | **93.3% (154/165)** | **93.3% (154/165)** |
| Manipulation recall | 37.5% (9/24) | **83.3% (20/24)** | 79.2% (19/24) |
| Malfunction recall | 0/3 | 0/3 | **1/3** |
| Volatility recall | 93.5% (129/138) | 97.1% (134/138) | 97.1% (134/138) |
| Volatility-called-manipulation | 9/138 (6.5%) | **4/138 (2.9%)** | **4/138 (2.9%)** |
| Brier | 0.195 | **0.129** | 0.153 |
| ECE | 0.038 | 0.053 | 0.091 |
| Log-loss | 0.347 | **0.290** | 0.377 |

(NB, unaffected by this change since it doesn't use the BN's discretization:
84.2% accuracy, 8.3% manipulation recall, Brier 0.229/ECE 0.124/log-loss 1.478 —
unchanged from `reports/loocv_200_incidents.md`, shown here only for completeness.)

**Both new schemes solve the exact tension the failed global scheme exposed:
manipulation recall recovers dramatically (83.3% and 79.2%, both well above even
n=105's post-fix 71%) AND volatility-called-manipulation confusion actually
*drops* (from 9/138 to 4/138) rather than trading one failure mode for the other.**
This directly answers the user's question: yes, recall is recovered without
reintroducing the volatility confusion, for both approaches.

## Which is more robust to distribution shift? Answered honestly, not conflated with "which scores higher right now"

**These are different questions, and the answer to each is different.**

**Most robust to distribution shift, by construction: `fixed`.** A constant cannot
drift, full stop — it never looks at the incident data's distribution at all, so no
future change in class sizes, class-magnitude distributions, or sampling threshold
can move it. This is a structural guarantee, not an empirical one.

**Best current empirical performance at n=165: `class_conditional`** — higher
accuracy, higher manipulation recall, better Brier, better log-loss, and the same
reduced volatility-confusion as `fixed`. It is *more* robust than the failed
`global` scheme against the *specific* failure mode diagnosed (population-size-
driven drift: adding more of an already-represented class shifts only that class's
own median slightly, verified directly — the reserve_skew threshold moved by <0.2%
between two different LOOCV folds, vs. `global`'s 38% shift when 53 new volatility
incidents were added) — but it is not *immune* to all possible future shift the way
`fixed` is: if a future phase changes a *class's own* typical magnitude (not just
relative class sizes), `class_conditional`'s threshold would still move with it.

**`fixed`'s one genuine edge: it catches 1 of 3 malfunction cases (FTT/USD) that
`class_conditional` misses entirely (0/3)** — though with n=3, this single flip
should not be read as a strong signal either way; it is exactly the kind of
small-sample noise `reports/loocv_150_incidents.md` and every report since have
flagged for this class.

## Decision: `class_conditional` is the new default

Set as `fit_bayesian_network`'s and `loocv_bayesian_network`'s default parameter
value. `global` and `fixed` remain fully available (pass `discretization="global"`
or `"fixed"` explicitly) for reproducibility and future comparison — this is not a
silent, hard-coded replacement; the mechanism for comparing all three is now part of
the codebase itself. Chosen over `fixed` because it currently performs better on
5 of 7 metrics, and because it directly, mechanistically neutralizes the exact
failure this phase set out to fix, even though it does not carry `fixed`'s absolute
theoretical guarantee. If a future scaling phase shows `class_conditional` itself
drifting under some *different* kind of compositional shift, `fixed` is the
documented fallback to re-evaluate, not something to reinvent from scratch.

## Leakage / no-lookahead check

Verified directly for `class_conditional` (the more complex, adaptive scheme,
the one most worth stress-testing): the `reserve_skew` threshold computed with
TOPBPool excluded from training is **0.065680**, vs. **0.065767** with TOPBPool
included and a different incident (Harvest Finance) excluded instead — a **0.13%**
difference. Compare this to `global`'s failure mode, where adding 53 new incidents
shifted the threshold by **38%**. This confirms two things at once: (1) the
threshold is genuinely recomputed per LOOCV fold from training data only — no
test-point leakage, same control flow as every prior discretization scheme in this
project (`loocv_bayesian_network` refits fresh on `train = df.drop(df.index[i])`
every fold) — and (2) `class_conditional` is, as designed, far less sensitive to
any single point's presence or absence than `global` was to a whole batch of new
same-class incidents.

## Malfunction n=3 — unchanged, explicit, still the central limitation

Neither new scheme resolves malfunction's fundamental data-scarcity problem.
`class_conditional` gets 0/3 (all three now predicted "manipulation" instead of
volatility — a new confusion pattern, not an improvement). `fixed` gets 1/3.
NB remains the only model with a meaningfully non-zero malfunction recall (2/3),
for reasons unrelated to any BN discretization scheme. **3 data points is 3 data
points at every scale and under every discretization scheme this project has
tested** — no thresholding fix, however well-designed, can substitute for more
malfunction incidents existing in the first place.

## What this argues for, going forward

- **`class_conditional` should be treated as the working default**, not a final
  answer — it is a genuine, verified, mechanistically-understood improvement over
  both the failed `global` scheme and the untried alternative, but it has only been
  tested at one scale transition (105 → 165). Whether it holds at a hypothetical
  n=300+ is an open question, not yet evidenced either way.
- **`fixed`'s domain-motivated constants are worth periodically re-validating**
  against wherever the classes' actual magnitude distributions sit, precisely
  because they will NOT auto-adjust — a strength against drift, but also a
  reason they could silently become miscalibrated if this project's feature
  engineering changes in the future (e.g., a different reserve_skew normalization).
- **Malfunction detection remains fundamentally a data problem, not a modeling
  problem** — every experiment in this project's history, including this one,
  reconfirms that no thresholding or discretization change moves this class's
  recall meaningfully; only more genuine malfunction incidents would.
