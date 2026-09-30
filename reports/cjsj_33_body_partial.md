Sampled estimate (see docstring): (A) 3 windows x 250 consecutive rounds per quarter, (B) +-1 h around each of the 138 volatility incidents.

#### 33a. Phases (aggregator contracts behind the proxy)

| Phase | first update (UTC) | last sampled update (UTC) | rounds | first price |
|---|---|---|---|---|
| 3 | 2020-08-06 | 2021-12-23 | 26614 | 391.79 |
| 4 | 2021-03-11 | 2021-05-20 | 5056 | 1747.40 |
| 5 | 2021-05-11 | 2023-05-11 | 45034 | 4081.11 |
| 6 | 2023-04-05 | 2024-09-30 | 23751 | 1908.19 |
| 7 | 2024-09-18 | 2026-09-30 | 34203 | 2317.87 |

#### 33b. Update gaps by quarter (seconds) and heartbeat_elapsed of incidents

| Quarter | A: median gap, all rounds | A: p90 gap | A: share of gaps >= 3000 s | A: median |price change| per update | A: rounds | B: median gap during >=3% moves | B: gaps | dataset heartbeat_elapsed, volatility incidents (median, n) |
|---|---|---|---|---|---|---|---|---|
| 2020Q4 | 752 | 3646 | 0.18 | 0.21% | 604 | - | 0 | - (0) |
| 2021Q1 | 949 | 4891 | 0.23 | 0.50% | 541 | - | 0 | - (0) |
| 2021Q2 | 632 | 2608 | 0.08 | 0.52% | 720 | 98 | 82 | 186 (2) |
| 2021Q3 | 578 | 3009 | 0.10 | 0.53% | 622 | 761 | 30 | 292 (5) |
| 2021Q4 | 808 | 2692 | 0.08 | 0.52% | 578 | 720 | 26 | 284 (5) |
| 2022Q1 | 1819 | 3627 | 0.32 | 0.34% | 463 | 788 | 32 | 256 (5) |
| 2022Q2 | 984 | 3556 | 0.15 | 0.51% | 532 | 246 | 61 | 255 (7) |
| 2022Q3 | 818 | 2769 | 0.09 | 0.51% | 733 | 422 | 33 | 260 (4) |
| 2022Q4 | 2424 | 3600 | 0.43 | 0.24% | 695 | 210 | 64 | 270 (8) |
| 2023Q1 | 1380 | 3600 | 0.30 | 0.46% | 696 | 570 | 30 | 246 (8) |
| 2023Q2 | 3576 | 3612 | 0.61 | 0.17% | 654 | 900 | 32 | 276 (9) |
| 2023Q3 | 3600 | 7536 | 0.71 | 0.17% | 338 | 1788 | 10 | 264 (6) |
| 2023Q4 | 1860 | 3612 | 0.39 | 0.31% | 665 | 660 | 50 | 276 (9) |
| 2024Q1 | 1638 | 3600 | 0.32 | 0.37% | 682 | 996 | 49 | 276 (9) |
| 2024Q2 | 1956 | 3624 | 0.38 | 0.38% | 558 | 744 | 48 | 282 (8) |
| 2024Q3 | 1950 | 3612 | 0.39 | 0.35% | 642 | 168 | 84 | 264 (9) |
| 2024Q4 | 2640 | 3636 | 0.45 | 0.51% | 581 | 324 | 45 | 546 (6) |
| 2025Q1 | 3060 | 3684 | 0.51 | 0.51% | 516 | 216 | 44 | 492 (5) |
| 2025Q2 | 1680 | 3636 | 0.34 | 0.52% | 604 | 240 | 76 | 402 (6) |
| 2025Q3 | 3552 | 3650 | 0.55 | 0.50% | 500 | 798 | 28 | 1140 (5) |
| 2025Q4 | 1800 | 4044 | 0.40 | 0.53% | 577 | 132 | 83 | 606 (6) |
| 2026Q1 | 1344 | 3636 | 0.33 | 0.52% | 579 | 132 | 89 | 960 (8) |
| 2026Q2 | 3612 | 5042 | 0.59 | 0.39% | 548 | 492 | 23 | 1068 (5) |
| 2026Q3 | 2034 | 5910 | 0.42 | 0.52% | 396 | 192 | 19 | 564 (3) |

#### 33c. Validation of the dataset feature

Recomputed elapsed (block timestamp minus last update at or before the block) equals the dataset's `heartbeat_elapsed` within 1 s for 80% of the 138 volatility incidents and within 30 s for 83%; Spearman 0.744.

#### 33d. Does the feed's own update behavior explain the 2025-2026 rise? (computed)

- Median gap between updates, all rounds: before 2024 (quarterly medians) 578-3600 s; 2025-2026 1344-3612 s (sampled).
- Median gap during >=3% moves (B): before 2024 98-1788 s; 2025-2026 132-798 s.
- Dataset heartbeat_elapsed of volatility incidents (quarterly medians): before 2024 186-292 s; 2025-2026 402-1140 s.