# Dataset scaling plan

This file did not exist prior to phase 1 — it's written here to document the plan being
executed, since it was referenced before it existed. Phase 1's spec below is the user's own
instruction, recorded verbatim in structure (not paraphrased into something weaker or
stronger); later phases are noted only as direction, not committed detail, since they
haven't been specified yet.

## Phase 1 (complete): 20 → 45 incidents

**Result: 12 manipulation (target 10-15), 30 volatility (target 25-30), 3 malfunction
(target: expect few — 0 new found, honestly).** Manipulation started at 13 (8 new) but
one (MorphoBlue) was dropped after a venue-verification pass found its root cause is a
static oracle misconfiguration with no manipulated venue at all — not a market-observable
incident, so it doesn't belong in this class. Full results, per-incident evidence, and
honest caveats in `reports/manipulation_candidates_phase1.md`,
`reports/volatility_candidates_phase1.md`, and `reports/malfunction_candidates_phase1.md`.
Data only — no model was retrained or re-evaluated this phase.

Grow the dataset from 20 incidents to roughly 50, without touching the existing 20 or
retraining/re-evaluating any model — data collection and validation only.

- **Manipulation**: pull additional Ethereum-mainnet oracle/price-manipulation incidents
  from the full DeFiHackLabs index beyond the 5 already locked, verifying each on-chain
  the same way (confirm the transaction exists on mainnet, record block, asset, and the
  actually-manipulated venue). Target roughly 10-15 total.
- **Volatility**: expand via automated sampling of large ETH/USD moves (not hand-picked
  named events, as the original 12 were), confirming each has clean cross-venue agreement
  and no oracle staleness. Target roughly 25-30 total.
- **Malfunction**: attempt to add cases but expect few — the prior finding (see
  `reports/malfunction_candidates.md`) is that clean mainnet malfunctions are structurally
  rare. Report honestly rather than padding to a target.

For every new incident: compute the full feature set (including the corrected
`dex_oracle_spread`) consistently with the existing table; keep the existing 20 incidents
intact and clearly mark which rows are new; run the same validation gates used on the
original 20 — an alignment probe on manipulation incidents (does the naive/fallback
feature set show a spike, or does it require the incident's own actually-manipulated
venue, the same question the original 5 needed answered), a no-lookahead check, and a
missing-feature report. Do not retrain or re-evaluate models in this phase.

## Phase 2 (complete, then corrected): 45 → 112 → 105 incidents (target was ~150, not fully reached)

**Result: 24 manipulation (target 40-50, short — mainnet-specific well-documented
incidents proved scarcer than hoped, verified independently, not a search-effort
shortfall), 85 volatility (target ~100, close), 3 malfunction (held, not re-searched).**
A real coverage gap was found and honestly reported, not papered over: 8 of the 12 new
manipulation incidents have no resolvable `reserve_skew` (wrong venue/token guess,
confirmed via zero balance at both the incident and baseline blocks). Full results,
per-incident evidence, and honest caveats in `reports/manipulation_candidates_phase2.md`
and `reports/volatility_candidates_phase2.md`.

**Correction pass (same session, resolved before any downstream conclusions were
finalized): of those 8, 1 (TOPBPool) was FIXED** — the configured venue was simply
wrong (absent from the attack tx's own logs); the real venue was found via direct
transaction-log decoding and now shows a genuine, extreme, persisting `reserve_skew`
(+670,679). **The other 7 (SummerFi, Raft_fi, bZxProtocol, edel-xstock,
CompounderFinance, MetaPool, MahaLend) were DROPPED entirely, not kept as a misleading
NaN or 0.0** — confirmed via direct log decoding to be either diffuse multi-venue
exploits with no single trackable balance, or exchange-rate/accounting manipulations
whose underlying token balance returns to baseline within the same transaction,
architecturally invisible to a before/after balance-ratio metric regardless of which
correct venue is used. Full writeup in `reports/manipulation_candidates_phase2.md`'s
addendum. **This brings the corrected total to 105 incidents: 17 manipulation, 85
volatility, 3 malfunction.**

Full re-evaluation across four points (20 → 45 → 112-uncorrected → 105-corrected) in
`reports/loocv_150_incidents.md` — the corrected numbers supersede the 112-incident
ones for every conclusion going forward. Headline finding, updated: closing the
reserve_skew coverage gap did NOT restore manipulation recall as the 112-incident
report had hoped — it got worse for both models, for two distinct, diagnosed reasons
(TOPBPool's genuine but astronomically large raw value blows up Naive Bayes' Gaussian
fit for reserve_skew; the Bayesian network's median-split discretization still can't
cleanly separate manipulation's now-fully-populated but still bimodal-and-diffuse
reserve_skew distribution from volatility's tight near-zero cluster). Data +
evaluation only this pass — no feature or model-structure changes.

## Phase 3 (complete): 105 → 165 incidents (target was ~200, not fully reached)

Between phase 2's correction and phase 3, `src/models.py`'s Bayesian network
discretization was fixed (magnitude-aware `abs(value) > median(abs(value))`,
replacing the sign-based `value > median(value)` scheme) — see
`reports/discretization_fix.md`. This was a real, verified improvement at n=105
(BN manipulation recall 35% → 71%), used as the baseline for phase 3's scaling.

**Result: 24 manipulation (+7, target "as far as clean incidents allow" — a wider
DeFiHackLabs keyword sweep found 12 new candidates, pre-screened for the atomic-
round-trip/diffuse-venue failure mode BEFORE integration this time, 5 dropped, 7
kept with independently-verified clean signals), 138 volatility (+53, target ~172-177
for a ~200 total, short — automated sampling at a lowered 3% threshold), 3
malfunction (held, not re-searched). 165 total, not 200.** Full sourcing in
`reports/manipulation_candidates_phase3.md` and `reports/volatility_candidates_phase3.md`.

**Central finding, and the reason this phase matters beyond the raw counts: the
magnitude-aware discretization fix does NOT hold up at this larger scale.** BN's
manipulation recall regresses from 71% (n=105) to 37.5% (n=165) — worse than even
the pre-fix n=105 number. Diagnosed directly (not just observed): the fix's
threshold is a single population-wide median of absolute values, and phase 3's 53
new (calmer, lower-threshold) volatility incidents shifted that median enough to let
41.3% of all volatility incidents cross into the same "large-magnitude" bucket
manipulation occupies (up from an implied ~4-13% at n=105), diluting the feature's
discriminative power. BN's calibration edge over Naive Bayes holds on all three
metrics regardless (Brier/ECE/log-loss all still favor BN) — the model remains
honestly calibrated even as its manipulation-detection accuracy degrades. Full
analysis, including a concrete next-step proposal (class-conditional or fixed
thresholding instead of a single global population quantile), in
`reports/loocv_200_incidents.md`. Scaling + evaluation only this phase — no further
feature or discretization changes made, per instruction.

## Phase 4+ (not yet specified)

Direction only, from the original richer_features.md discussion: growing toward "the full
corpus" eventually, at which point the richer/trajectory/liquidity features gated behind
dataset size in `reports/richer_features.md` §6 become worth adding to the modeled feature
set, and the same LOOCV/ablation discipline should be re-run on the larger incident count
rather than trusted from earlier passes. No target count, feature list, or timeline has
been set for this yet.
