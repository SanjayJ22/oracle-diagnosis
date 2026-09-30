# Oracle Malfunction Candidates — Ethereum Mainnet

Broadened definition (per direction): any non-manipulation, non-exploit case where a mainnet Chainlink
feed's on-chain price diverged from reality, whether by staleness/lag, a permanent freeze, or a
pause/deprecation. Documented-incident sourcing, verified on-chain via `fetch_chainlink.py` — same
standard applied to the manipulation incidents (a claim only counts once the specific feed's own round
history confirms it).

**Honest count: 1 new *incident* found (UST/Terra), not 2 — see note below the table before treating this
as "4 confirmed."** It does verify as two separate frozen aggregator contracts, so it's written up as two
rows since both are independently checkable on-chain, but they're the same underlying collapse, not two
unrelated malfunctions. rETH/ETH, cbETH/ETH, and WBTC/BTC were all checked in full for a second
depeg-lag case (matching the stETH pattern) and none ever genuinely depegged — no second case of that
type exists to report.

## Confirmed

| # | Case | Feed | Address | Block | Gap | Price Before | Price After | Confidence |
|---|------|------|---------|-------|-----|---------------|-------------|------------|
| 1 | FTT/USD pause/deprecation, Nov 2022 | FTT/USD | `0x398381563cc93A0Cd62534D775F2207a307e9aDD` | 16,069,381 | **Permanent** — no update since; round 1826 confirmed empty (`startedAt=0, updatedAt=0`), still frozen as of 2026-07-29 (~3.6 years) | 1.316792 (round 1824, Nov 28 09:10:47 UTC) | 1.289601 (round 1825, Nov 28 15:27:59 UTC — final) | **High** *(locked)* |
| 2 | stETH/ETH heartbeat lag, June 2022 depeg | STETH/ETH | `0x86392dC19c0b719886221c78AB11eb8Cf5c52812` | 14,984,168 | 86,428s (~24h) — matches the feed's *own* median/max throughout the whole window, i.e. this is its constant behavior, not a spike | 0.937752 (block 14,978,345, June 17 09:09:10 UTC) | 0.935019 (block 14,984,168, June 18 09:09:38 UTC) | **Moderate** *(locked)* |
| 3 | UST/USD (Terra) feed freeze, June 2022 collapse | UST/USD (old aggregator) | `0x5EDd5F803b831b47715aD3e11a90dD244F0cD0a9` | 14,942,628 | **Permanent** — round 20283 confirmed empty; frozen since 2022-06-11 (~4 years) | 0.010038 (round 20281, June 11 05:27:44 UTC) | 0.010007 (round 20282, June 11 05:43:34 UTC — final) | **High** |
| 4 | *(same case, part 2)* UST/USD replacement feed, later freeze | UST/USD (new aggregator) | `0x01b87e7fF78022A70394d3C6Dd127D0c709e3beA` | 20,267,648 | **Permanent** — round 14527 confirmed empty; frozen since 2024-07-09 (~2 years) | 0.015401 (round 14525, July 8 08:08:23 UTC) | 0.015519 (round 14526, July 9 08:08:35 UTC — final) | **High** |

### Case 1 detail — FTT/USD

Confirmed via the Chainlink Feed Registry (`getFeed(FTT, USD)` at historical blocks) that this address
was the live FTT/USD feed through at least Oct 2022, then a *different* address took over the registry
slot by Jan 2023 — that replacement feed also stopped updating permanently, on 2023-04-25. Round-by-round
inspection of rounds 1820–1825 (Nov 27 00:29 → Nov 28 15:27 UTC) shows update cadence visibly degrading
from the feed's ~9-minute median (mined Oct 15 – Nov 28 window) to 6–12 hours between rounds in its final
39 hours, before stopping entirely. **This is a hard stop, not a lag-then-recover** — flagging per your
instruction, since the failure signature differs from every other candidate here: there is no "after"
price in the normal sense, just a frozen value that has never been updated since.

### Case 2 detail — stETH/ETH

Full round-by-round data, June 5–24, 2022 (21 rounds):

```
2022-06-05 17:41:16  0.979455   (baseline, gap n/a)
2022-06-10 13:20:22  0.953386   (gap 70,709s — a rare deviation-triggered update)
2022-06-13 08:42:44  0.940975   (gap 69,759s)
2022-06-13 21:01:45  0.962272   (gap 44,341s — two updates same day as depeg accelerated)
2022-06-14 09:07:04  0.941992   (gap 43,519s)
2022-06-16 09:08:56  0.938969   (gap 86,499s)
2022-06-17 09:09:10  0.937752   (gap 86,414s)
2022-06-18 09:09:38  0.935019   (gap 86,428s)  <- trough
...
2022-06-24 09:10:42  0.960789   (gap 86,413s — recovering)
```

This confirms your hypothesis mechanism exactly: a wide deviation threshold means most day-to-day
depeg movement (2–6%) does *not* trigger an early update, so the feed falls back to its ~24h heartbeat
almost every day — visible above as gaps clustering tightly around 86,400–86,500s even while the
underlying price was actively falling. Between June 17 09:09 and June 18 09:09, Curve spot was moving
continuously while the Chainlink price sat frozen at 0.9378. **This is not an anomalous stall — the
feed behaved exactly as it does throughout the entire window** — so "confidence" here means confidence
that the described lag mechanism is real and on-chain-verified, not confidence that something broke.

### Cases 3 & 4 detail — UST/USD (Terra collapse)

Found via the same registry-lookup trick that found FTT: `getFeed(UST/USTC token, USD)` at historical
blocks. The registry pointed at two different aggregators in succession:

- **Old aggregator** (`0x5EDd...cD0a9`): live through at least March 2022. The registry itself switched
  away from this address at **block 14,769,103 (2022-05-13 18:57:36 UTC)** — right in the middle of the
  UST depeg (which began ~May 9). But the old aggregator contract *itself* kept receiving updates for
  almost another month after that (some integrations may have still pointed at it directly), tracking
  UST's price down to ~$0.01, until its last-ever update on **2022-06-11 05:43:34 UTC**. Round 20283
  confirmed empty — permanent freeze at $0.010007, ~4 years and counting.
- **New aggregator** (`0x01b8...3beA`): took over the registry slot the same block the old one stopped
  being referenced, and kept tracking Terra Classic's residual value (~$0.01–0.02) for **two more years**
  before it, too, stopped permanently on **2024-07-09 08:08:35 UTC** (round 14527 confirmed empty).

Net effect: an asset that's been functionally worthless since May 2022 had two successive Chainlink
feeds report a live-looking price for it, one for another month, the other for another two years, before
each was permanently abandoned. Both freezes are independently verified on-chain (separate addresses,
separate final rounds, separate empty-next-round confirmations) — hence two rows above — but they are
one underlying incident (UST/Terra), not two unrelated malfunctions.

## Checked, not confirmed (rejected)

| Candidate | Feeds checked | Finding |
|---|---|---|
| Secondary feed stalls, May 19 2021 congestion | LINK/USD, DAI/USD | LINK: 980 updates over the 10-day window, 183 of them *on May 19 itself* — actively tracking the crash. DAI: the one ~24h gap found lands on May 17/19 but is DAI's normal stablecoin heartbeat (median gap for DAI in this window is ~1h when volatile, ~24h when calm) — not anomalous. |
| Secondary feed stalls, May 19 2021 (supplemental) | UNI/USD, COMP/USD, MATIC/USD, SNX/USD, AAVE/USD | All 5 updated 162–226 times *on May 19 alone*, max within-day gap 51–93 minutes — indistinguishable from normal deviation-triggered activity during a volatile day. No stall on any of the 7 feeds checked for this event. |
| ETH/USD + BTC/USD multi-block delays, Aug 27 2021 Geth split | ETH/USD, BTC/USD | Both feeds: max gap in the Aug 20–Sep 4 window was 60–62 min (only 1.7–2.4x each feed's own median). No anomaly around Aug 27 specifically. |
| Widespread staleness, Nov 11 2020 Infura outage | ETH/USD, BTC/USD | ETH/USD updated continuously all day Nov 11 (dozens of updates, largest gap ~1h, fully normal). BTC/USD showed a mildly elevated gap (6,002s / 1.67h) at 10:35 UTC on Nov 11 — but Nov 10 (5,852s) and Nov 13 (3,754s) are in the same range, so this isn't clearly distinguishable from ordinary day-to-day variance. |
| LUNA (Wormhole), CEL (Celsius) frozen-feed search | Registry lookups, base + historical blocks | Neither token has ever had a registered Chainlink feed on this registry (checked latest and 4 historical blocks spanning their respective collapses) — no feed exists to check, not a rejected finding. |
| Second liquid-staking/wrapped-asset depeg-lag case | rETH/ETH, cbETH/ETH, WBTC/BTC (full history each) | All three are remarkably stable across their *entire* history: max single-round price move under 4.3% (rETH) / 2.9% (cbETH) / 1.3% (WBTC/BTC), and max gap always ≈ their own ~24h median — never an anomaly. None of the three has ever genuinely depegged on-chain. No second stETH-style case exists among these. |

## Notes

- Every "confirmed" number above (prices, timestamps, round emptiness) was read directly from the
  feed's own on-chain round data via `fetch_chainlink.py` — not taken from news sources.
- LUNA minAnswer, XAU weekend, and OCR/Dexodus/FastGas cases were excluded per your instruction (different
  failure modes, not feed staleness) and were not investigated.
- Fixed a real bug in `fetch_chainlink.py` while mining rETH/ETH: a feed that has only ever lived on
  phase 1 (rETH, stETH) would, at its genesis, try to cross into "phase 0" — which doesn't exist and
  reverts *persistently*, not transiently — burning all retries and crashing instead of stopping cleanly.
  Guard changed from `phase > 0` to `phase > 1`.
- **Honest tally: 3 distinct incidents confirmed (FTT, stETH, UST), one of which yields 2 independently
  verifiable rows.** Whether that counts as "4" for labeling purposes is your call — I'd lean toward
  treating the two UST rows as one label with two supporting on-chain data points, since they share a
  root cause, but they're both real and both usable if you want 4 separate training rows.
