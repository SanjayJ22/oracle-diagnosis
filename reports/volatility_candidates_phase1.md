# Volatility Incident Candidates — Phase 1 (Automated Sampling)

Mined via `src/mine_volatility_incidents.py`: automated sampling of ETHUSDT hourly candles (2021-01-01 onward, Binance.US), flagging every 24h window with a >=10% move, collapsing contiguous flagged runs to one event each, excluding anything within 3 days of the existing 12 volatility incidents (`reports/final_incidents.md`), then verifying each survivor fully on-chain (Chainlink ETH/USD, WETH/USDC V3 DEX price, cross-venue agreement, heartbeat staleness) exactly like the existing 12 were verified.

- Raw flagged events (contiguous-run-collapsed): 96
- After excluding dates within 3 days of an existing incident: 22
- Passed on-chain cleanliness checks (cross-venue agreement within 5%, heartbeat_elapsed <= 1800s): 20/22 attempted (2 failed cleanliness, 18 kept for the final list after downselection)
- **Final verified new candidates: 18** (target was 13-18)

## Verified, clean candidates

| # | Date (UTC) | Block | 24h Move | Chainlink ETH/USD | DEX (WETH/USDC V3) | CEX (ETHUSDT) | price_dev | cross_venue_spread | dex_oracle_spread | heartbeat_elapsed |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2021-05-24 19:00:00+00:00 | 12,498,787 | +34.7% | $2,568.71 | $2,576.74 | $2,650.37 | -0.0308 | -0.0278 | +0.0031 | 279s |
| 2 | 2021-09-08 07:00:00+00:00 | 13,183,613 | -16.2% | $3,307.45 | $3,311.20 | $3,257.50 | +0.0153 | +0.0165 | +0.0011 | 265s |
| 3 | 2021-12-04 11:00:00+00:00 | 13,739,429 | -16.1% | $3,915.13 | $3,925.79 | $3,867.14 | +0.0124 | +0.0152 | +0.0027 | 293s |
| 4 | 2022-01-21 22:00:00+00:00 | 14,051,461 | -16.9% | $2,605.40 | $2,624.52 | $2,539.72 | +0.0259 | +0.0334 | +0.0073 | 172s |
| 5 | 2022-06-19 20:00:00+00:00 | 14,992,595 | +26.1% | $1,101.02 | $1,102.89 | $1,139.62 | -0.0339 | -0.0322 | +0.0017 | 283s |
| 6 | 2022-07-18 23:00:00+00:00 | 15,169,419 | +18.2% | $1,516.20 | $1,513.69 | $1,581.25 | -0.0411 | -0.0427 | -0.0016 | 277s |
| 7 | 2022-10-26 10:00:00+00:00 | 15,831,508 | +14.3% | $1,533.10 | $1,531.12 | $1,537.81 | -0.0031 | -0.0043 | -0.0013 | 276s |
| 8 | 2023-11-09 23:00:00+00:00 | 18,537,528 | +12.3% | $2,097.80 | $2,093.89 | $2,121.32 | -0.0111 | -0.0129 | -0.0019 | 276s |
| 9 | 2024-01-11 14:00:00+00:00 | 18,984,139 | +12.3% | $2,641.12 | $2,635.71 | $2,672.76 | -0.0118 | -0.0139 | -0.0020 | 288s |
| 10 | 2024-05-21 12:00:00+00:00 | 19,918,142 | +22.6% | $3,784.20 | $3,779.17 | $3,782.72 | +0.0004 | -0.0009 | -0.0013 | 288s |
| 11 | 2024-07-05 04:00:00+00:00 | 20,237,777 | -11.4% | $2,912.09 | $2,916.17 | $2,867.22 | +0.0156 | +0.0171 | +0.0014 | 276s |
| 12 | 2024-11-07 01:00:00+00:00 | 21,132,351 | +13.1% | $2,724.24 | $2,726.46 | $2,811.00 | -0.0309 | -0.0301 | +0.0008 | 84s |
| 13 | 2025-02-03 04:00:00+00:00 | 21,763,455 | -21.0% | $2,529.11 | $2,524.92 | $2,452.38 | +0.0313 | +0.0296 | -0.0017 | 816s |
| 14 | 2025-05-09 08:00:00+00:00 | 22,444,589 | +24.8% | $2,368.81 | $2,362.57 | $2,413.02 | -0.0183 | -0.0209 | -0.0026 | 492s |
| 15 | 2025-11-21 11:00:00+00:00 | 23,846,950 | -11.2% | $2,695.88 | $2,693.01 | $2,689.01 | +0.0026 | +0.0015 | -0.0011 | 636s |
| 16 | 2026-01-31 18:00:00+00:00 | 24,356,507 | -13.4% | $2,401.99 | $2,401.53 | $2,379.96 | +0.0093 | +0.0091 | -0.0002 | 1236s |
| 17 | 2026-06-06 04:00:00+00:00 | 25,255,813 | -12.9% | $1,559.79 | $1,563.36 | $1,519.61 | +0.0264 | +0.0288 | +0.0023 | 1656s |
| 18 | 2026-08-19 21:00:00+00:00 | 25,791,702 | +19.5% | $2,213.24 | $2,220.85 | $2,285.73 | -0.0317 | -0.0284 | +0.0034 | 72s |

## Rejected — failed cleanliness checks (not included, for transparency)

| Date (UTC) | Block | 24h Move | price_dev | cross_venue_spread | heartbeat_elapsed | Reason |
|---|---|---|---|---|---|---|
| 2021-01-04 05:00:00+00:00 | 11,585,994 | +38.4% | -0.0554 | +nan | 258s | DEX pool read failed (likely predates pool deployment): RuntimeError |
| 2025-08-22 19:00:00+00:00 | 23,198,568 | +14.8% | -0.0147 | -0.0134 | 1968s | failed cross-venue/heartbeat cleanliness gate |

## Methodology notes

- **Threshold**: 10% over 24h, chosen to sit below the smallest existing incident's magnitude (Aug 2023 selloff, -15.6%) so this automated pass finds real-but-somewhat-smaller moves too, not just re-discovering the same handful of famous named crashes.
- **No lookahead**: heartbeat_elapsed is read at block-1 (strictly before the candidate's own anchor block), matching the fix in `recompute_heartbeat_elapsed.py` -- never read at the anchor block itself, which was the original anchoring-artifact bug in this project.
- **Cleanliness gate**: a candidate is kept only if Chainlink, DEX, and CEX all agree within 5% of each other AND heartbeat_elapsed <= 1800s. Failing either means the window may be malfunction- or single-venue-liquidity-contaminated, not clean market-wide volatility -- excluded, not kept and flagged.
- **Downselection**: candidates were kept if verified clean; if more than 18 passed, the largest-magnitude moves were kept (time-sorted afterward for readability). This run: see the final count above for whether downselection was actually needed.
- Every value in the table above (Chainlink/DEX/CEX prices, spreads, heartbeat) is a live on-chain or exchange-API read for this run, not estimated or interpolated.
