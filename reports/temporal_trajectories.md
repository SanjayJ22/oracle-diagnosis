# Temporal Trajectory Analysis — One Incident Per Class

A separate, standalone analysis — does **not** feed into `data/processed/features.parquet`
or `src/models.py`. Goal: show that the three causes resolve differently *over time*, not
just as static feature snapshots. Built by `src/temporal_trajectories.py` (data gathering,
reusing cached data where the earlier work already covered the window) and
`src/plot_trajectories.py` (plots + explicit state descriptions + attempted HMM fits).

## Manipulation — Harvest Finance, 2020-10-26 (`trajectory_manipulation.png`)

Signal: Curve Y pool's implied yUSDC/yUSDT balance ratio (the actual manipulated venue),
sampled every ~10 blocks (~2 min) across a ±1h window, against ETH/USD (an unrelated venue)
and its own update freshness.

**This corrected an assumption going in.** I expected a single atomic spike-and-revert
(a classic flash loan). The data shows something more accurate and more interesting: **5
distinct step-changes over ~2 hours** (ratio: 1.316 → 1.271 → 1.247 [anchored incident
block] → 1.236 → 1.290), matching the post-mortem's own description of a *repeated*
attack — multiple manipulate-then-arbitrage cycles, not one transaction. Meanwhile ETH/USD
shows no corresponding move at all ($408–411, ordinary noise), and its own update cadence
stays normal throughout (gaps of 750–2250s, nothing anomalous) — the failure is entirely
localized to the exploited venue.

## Malfunction — stETH/ETH, 2022-06 depeg (`trajectory_malfunction.png`)

Signal: Chainlink STETH/ETH (updates ~1x/24h) against the wstETH/WETH Uniswap V3 pool as a
continuous real-market reference, converted to an implied stETH/ETH price via wstETH's own
`stEthPerToken()` accrual rate (~1.074–1.076 over this window) so the comparison isn't
distorted by wstETH's separate staking-yield appreciation.

The result is the cleanest of the three: a continuously-wiggling orange DEX line against a
staircase-stepping blue Chainlink line that lags behind at each flat segment, then jumps to
catch up on its next ~24h update. The bottom panel makes the heartbeat itself visible —
mostly pinned at 24h, occasionally shorter (12–20h) when a deviation threshold triggers an
early update.

## Large volatility event — Aug 5 2024 crash (`trajectory_volatility.png`)

Signal: Chainlink ETH/USD, Binance.US ETHUSDT, and the WETH/USDC Uniswap V3 pool, all three
overlaid across the ~6-day window.

All three venues move together almost indistinguishably through the entire crash
($3,200 → $2,200 and partial recovery to ~$2,500) — no lag, no localized divergence. The
freshness panel shows the oracle's update gap *tightening* right around the crash (near-zero
gaps clustered at the trough) versus the calmer days before/after (gaps up to ~1h) — the
oracle updates *more* often exactly when the price is moving fastest, the opposite of the
malfunction signature.

## HMM regime fit: attempted, honestly not usable on any of the three

A 2-state Gaussian HMM (`hmmlearn`) was attempted on each trajectory's primary signal.
None produced a trustworthy fit, for three different reasons:

| Trajectory | Points | Result |
|---|---|---|
| Harvest Y-pool ratio | 56 | Converged, but 55/56 switches with state means only 0.07 pooled-std apart — flip-flopping on noise, not a regime split. |
| stETH DEX-vs-oracle spread | 77 | Converged but degenerate (a state collapsed to near-zero variance). |
| Aug 2024 1-min log returns | 8,579 | Converged cleanly (no excessive switching), but state means only 0.04 pooled-std apart — no real 2-state structure to find, which is itself consistent with this being one continuous market move rather than discrete regimes. |

Per your instruction, these are reported as unstable/not meaningful rather than forced —
the explicit state-transition descriptions above are the trustworthy version of this
analysis on such short sequences (56–77 points for two of the three).
