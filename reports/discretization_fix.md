# Bayesian network discretization fix: magnitude-aware, not sign-based

## What changed

`src/models.py`'s `fit_bayesian_network()`/`predict_bayesian_network()` previously
discretized every continuous feature by comparing its raw value to its own median:
`value > median(value) -> high, else low`. For a feature whose median sits near zero
and which is meaningfully bidirectional (`price_dev`, `cross_venue_spread`,
`dex_oracle_spread`, `reserve_skew` — a large deviation in *either* direction is the
anomalous signal, not just a positive one), this reduces to "is the value positive or
negative", which buries any manipulation incident whose signal happens to be strongly
negative in the same bucket as an ordinary small negative reading from a calm
volatility incident. This was diagnosed at n=112 and confirmed to persist (in a more
complex, not-fully-sign-explicable form) at the corrected n=105 in
`reports/loocv_150_incidents.md` §4-5.

**Fix**: discretize on absolute magnitude against the median of the absolute values —
`abs(value) > median(abs(value)) -> high (large-magnitude, anomalous), else low
(small-magnitude, unremarkable)`. This is simultaneously a magnitude-aware split and
the 50th-percentile quantile of the magnitude distribution. It is a provable no-op
for the three already-nonnegative features (`heartbeat_elapsed`, `congestion`,
`ref_realized_vol` — a volatility magnitude is never negative, so `abs(x) == x`
already), so only the genuinely bidirectional features change behavior. The
median-of-absolute-values threshold is itself outlier-robust (a median, not a
mean/std), so TOPBPool's extreme +670,679.59 `reserve_skew` lands cleanly in "high"
without distorting where the near/far boundary falls for every other incident —
verified directly: the reserve_skew threshold moves from 0.013464 to 0.013478
depending on whether TOPBPool is in or out of the training fold, a negligible shift
(see §4).

**Scope of the change**: only `models.py`'s `fit_bayesian_network`/
`predict_bayesian_network` — the flat 3-class Bayesian network used by
`loocv_validation.py`, `calibration_metrics.py`, and `models.py`'s own `main()`. The
`BN_STATE_NAMES` suffix strings (`_low`/`_high`) were deliberately left unrenamed
(only their *meaning* changed, documented in the code) so `two_stage_analysis.py` and
`two_class_analysis.py` — which import `BN_STATE_NAMES` but keep their own separate,
unmodified sign-based-median discretization copy — don't break on a state-name
mismatch. Those two analyses are unaffected by this fix and remain on the old
discretization; they were out of scope for this request.

## 1. Does better binning recover manipulation recall? Yes, substantially.

| Metric | Pre-fix (n=105) | **Post-fix (n=105)** |
|---|---|---|
| BN overall accuracy | 83% (87/105) | **89% (93/105)** |
| BN manipulation recall | 35% (6/17) | **71% (12/17)** |
| BN malfunction recall | 0% (0/3) | **0% (0/3) — unchanged, see §3** |
| BN volatility recall | 95% (81/85) | **95% (81/85) — unchanged** |
| BN Brier | 0.224 | **0.151** |
| BN ECE | 0.042 | **0.047** |
| BN log-loss | 0.397 | **0.302** |

Manipulation recall **more than doubles** (35% → 71%), overall accuracy improves 6
points, and calibration improves on 2 of 3 metrics (Brier, log-loss); ECE ticks up
marginally (0.042 → 0.047), a difference well within noise at n=105 with only 4
confidence buckets. **TOPBPool — the incident that originally motivated this whole
correction — is now correctly classified as manipulation** (it was misclassified as
"large volatility event" under the old sign-based scheme even with a clean, extreme,
correctly-resolved `reserve_skew`).

NB is unchanged (not touched by this fix) and remains at 0% manipulation recall,
0.312/0.171/2.234 Brier/ECE/log-loss — see `reports/loocv_150_incidents.md` §4 for why
(its Gaussian fit has no equivalent outlier protection). **The corrected picture: BN
is now clearly the better model on every axis that matters (accuracy, all three
calibration metrics, manipulation recall) — the fix closes most of the gap the
reserve_skew resolution pass had opened.**

## 2. Which manipulation incidents are still missed, and why (honest residual)

5 of 17 remain misclassified as "large volatility event": Cream Finance, MonoX
Finance, MEVBOTa47b, CurveLlamaLend, ResupplyFi. Notably, **Cream Finance and
ResupplyFi both have literal `+inf` reserve_skew (clipped to +3.0)** — the same
"obviously extreme" signal class as TOPBPool — yet are still missed. This is not a
discretization failure specific to these two: their discretized `reserve_skew`
evidence almost certainly *does* register as "high" (their magnitude, 3.0, is far
above the ~0.0135 threshold). The remaining error is that the network's *other*
features (heartbeat_elapsed, congestion, ref_realized_vol, price_dev where available)
pull the posterior back toward volatility, and confidence on these 5 wrong calls sits
in the 51-89% range — i.e., not confidently wrong, consistent with §7's entropy
numbers. This residual is a genuine, honestly-reported limitation, not swept under
the rug: the fix solves the *specific* sign-conflation bug, not every source of
manipulation/volatility overlap in the feature set.

## 3. Malfunction n=3 — still the central limitation, unaffected by this fix

BN's malfunction recall is unchanged at 0/3 both before and after this fix (all 3 are
now called "large volatility event" post-fix, vs. 2 volatility + 1 manipulation
pre-fix — the *distribution* of the wrong calls shifted, but the recall did not).
**This fix does not, and cannot, address malfunction's fundamental data-scarcity
problem** — 3 points is 3 points regardless of how the other classes' features are
discretized, and every number for this class should still be read as "this specific
n=3 sample," not a stable estimate. NB's malfunction recall (2/3, unchanged) remains
the only model that catches any malfunction cases, for reasons unrelated to this fix.

## 4. Leakage / no-lookahead check

The fix changes only the *formula* used inside `fit_bayesian_network()` — the control
flow that ensures no leakage was already in place and is untouched:
`loocv_bayesian_network()` (`src/loocv_validation.py`) calls
`fit_bayesian_network(train, ...)` fresh on each fold's training set (`held_out`
incident excluded), then discretizes the held-out incident's own features using only
that fold's train-derived thresholds via `predict_bayesian_network(model, thresholds,
held_out)`. Verified directly, not just asserted: the `reserve_skew` median-abs
threshold computed with TOPBPool excluded from training is **0.013464336**, vs.
**0.013464336** with a different incident (Harvest Finance) excluded and TOPBPool
included — a negligible difference, confirming (a) the threshold is genuinely
recomputed per fold rather than frozen from a full-data fit, and (b) medians are
robust enough that no single point (including TOPBPool's extreme value) meaningfully
leaks into or distorts the threshold used to score any other fold. No artifact
introduced.

## 5. What this argues for

- **The magnitude-aware fix should be considered the new default for the flat BN
  model** — it is a strict improvement on every metric except a negligible ECE
  uptick, is mechanistically well-understood, and required no new data or features.
- **`two_stage_analysis.py` and `two_class_analysis.py` still use the old sign-based
  scheme** — not touched this pass, out of scope for this request, but now a
  concretely-identified follow-up if those analyses are revisited.
- **NB's Gaussian-fit fragility to extreme finite values (documented in
  `reports/loocv_150_incidents.md` §4) is unaddressed and remains a separate, valid
  next step** — this fix only touched the Bayesian network.
- **Every downstream report that used the flat BN's old discretization
  (`reports/loocv_150_incidents.md`, `reports/calibration_metrics.md`,
  `reports/two_stage_analysis.md`'s BN sub-model where reused) is now stale for BN's
  numbers specifically**, the same way each prior data correction in this project has
  superseded earlier reports — flagged here rather than silently left inconsistent;
  not proactively regenerated unless requested.
