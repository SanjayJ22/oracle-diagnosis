# Malfunction (Staleness) Candidates — Phase 1 Broadened Search

Extends `reports/malfunction_candidates.md`'s search beyond what it already covered. Read-only: does not touch `build_features.py`, `models.py`, or `features.parquet`. Feed addresses were resolved via the Chainlink Feed Registry's own `getFeed(base, quote)` (registry `0x47Fb2585D2C56Fe188D0E6ec628a38b74fCeeeDf`) at a recent block, never hardcoded from memory — each token contract's `symbol()` was checked on-chain first, and any address that failed that check was rejected rather than used.

## Part A — targeted-window gap-mining (feeds only spot-checked before)

Method note: an initial attempt walked each feed's FULL history backward from "latest" (mine_malfunctions.py's exact method), but these majors update every ~30-60 minutes continuously, so a 3000-round cap only reached back 2-4 months -- discovered empirically on a first run, not assumed, and abandoned as infeasible (full multi-year history at this cadence is ~50,000-100,000+ rounds/feed). Revised to: anchor a bounded backward walk (300 rounds via `get_feed_update_history`'s `start_round_id`) at a block a few days after each of 6 known historical stress windows' core move (2020 COVID crash through the 2026-02 crash) -- the same 'look where a malfunction is most likely to show up' logic the original FTT/USD and UST/USD discoveries used, applied to more feeds and more windows. A gap is flagged if it's >= max(6x the feed's own median gap FOR THAT WINDOW, 4h) -- computed per-window, not globally, since a feed's update cadence can differ across eras. Gaps within 2000 blocks of any of the 20 already-locked incidents (all three classes, not just manipulation) are excluded. This trades full-history completeness for covering the periods a staleness event is actually likely to matter in, within a tractable RPC budget -- calm periods between stress windows were not checked, so this is not an exhaustive history scan the way the original ETH/USD, BTC/USD, USDC/USD, USDT/USD full-history mining was.

### Feed resolution

| Candidate | Token verified? | Feed found? | Feed address |
|---|---|---|---|
| LINK/USD | yes | yes | `0x96d6e33B411dc1f4E3F1e894A5A5d9CE0F96738D` |
| DAI/USD | yes | yes | `0x709783ab12b65fD6cd948214EEe6448f3BdD72A3` |
| UNI/USD | yes | yes | `0xdEf8C51d7c1040637A198efFc39613865B32EA51` |
| COMP/USD | yes | yes | `0x24e3c657c27DfC7ea6f9f58e86387D846b3BaA59` |
| MATIC/USD | yes | yes | `0xC1e7D47ECfbb15B99a4B5F69E6931587000DD0b0` |
| SNX/USD | yes | yes | `0xc778E9686F0fde6Fe4D7d8fE4B481463Fce898fD` |
| AAVE/USD | yes | yes | `0xd8B9aA6E811c935eF63e877CFA7Be276931293DA` |
| CRV/USD | yes | yes | `0xdA0DA298550E8E449b935CEA865c8100F3cA1b73` |
| MKR/USD | yes | yes | `0xe9a6BCCdE4875F8c1228975F9c84598558a75AC8` |
| LDO/USD | yes | no — not registered | `—` |
| FXS/USD | yes | yes | `0xc1c54D09554Cf65d74a289805c2731cf6EA57373` |
| YFI/USD | yes | yes | `0x525B031c1eE01502c113500a2d1A999cD3F9C98F` |
| SUSHI/USD | yes | yes | `0x658Aa21601C8c0bB511C21999F7cad35B6A15192` |
| 1INCH/USD | yes | yes | `0x6AD3961c0348906504ff4125722e4Aa5146ff529` |
| FRAX/USD | yes | yes | `0x8F73090a7c58B8BDcC9A93cBB6816e5cC4f01E8c` |
| LUSD/USD | yes | yes | `0x36A0448c46AaE145dD5BC320D5153426a2a586F5` |
| sUSD/USD | yes | no — not registered | `—` |
| USDe/USD | yes | yes | `0xcC16f670129f965b396f2e81312F6e339FFDB18e` |
| PYUSD/USD | yes | yes | `0x39E31761911b9aaBAEF5fb81B18Fd1C24a60E884` |

### New candidates found (after exclusion)

| Feed | Window | Block | Gap (s) | Price Before | Price After | Updated At (UTC) |
|---|---|---|---|---|---|---|
| PYUSD/USD | 2024-08 carry-trade unwind | 19,870,620 | 604896 | 0.9991 | 0.9993 | 2024-05-14 20:31:11+00:00 |
| PYUSD/USD | 2024-08 carry-trade unwind | 20,070,995 | 604836 | 0.9993 | 0.9978 | 2024-06-11 20:32:59+00:00 |
| PYUSD/USD | 2024-08 carry-trade unwind | 20,020,866 | 604836 | 0.9991 | 0.9993 | 2024-06-04 20:32:23+00:00 |
| PYUSD/USD | 2024-08 carry-trade unwind | 19,820,581 | 604836 | 0.9997 | 0.9991 | 2024-05-07 20:29:35+00:00 |
| PYUSD/USD | 2024-08 carry-trade unwind | 19,920,685 | 604824 | 0.9993 | 1.0004 | 2024-05-21 20:31:35+00:00 |
| PYUSD/USD | 2024-08 carry-trade unwind | 20,171,108 | 604824 | 0.9986 | 0.9992 | 2024-06-25 20:33:35+00:00 |
| PYUSD/USD | 2024-08 carry-trade unwind | 19,770,514 | 604824 | 0.9992 | 0.9997 | 2024-04-30 20:28:59+00:00 |
| PYUSD/USD | 2024-08 carry-trade unwind | 20,263,748 | 604812 | 0.9993 | 0.9992 | 2024-07-08 19:02:47+00:00 |
| PYUSD/USD | 2024-08 carry-trade unwind | 20,121,051 | 604812 | 0.9978 | 0.9986 | 2024-06-18 20:33:11+00:00 |
| PYUSD/USD | 2024-08 carry-trade unwind | 19,970,770 | 604812 | 1.0004 | 0.9991 | 2024-05-28 20:31:47+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,596,924 | 86469 | 28.6517 | 28.6305 | 2022-04-16 14:38:50+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,739,809 | 86461 | 22.5607 | 22.2562 | 2022-05-09 02:31:46+00:00 |
| FXS/USD | 2024-08 carry-trade unwind | 20,497,218 | 86436 | 1.9151 | 1.8957 | 2024-08-10 09:08:47+00:00 |
| FXS/USD | 2023-03 SVB/banking crisis | 16,716,959 | 86436 | 10.3671 | 10.4109 | 2023-02-27 03:48:47+00:00 |
| FXS/USD | 2024-08 carry-trade unwind | 20,349,455 | 86424 | 2.5897 | 2.6002 | 2024-07-20 18:12:35+00:00 |
| FXS/USD | 2024-08 carry-trade unwind | 20,420,207 | 86412 | 2.2954 | 2.2914 | 2024-07-30 15:16:47+00:00 |
| FXS/USD | 2024-08 carry-trade unwind | 20,377,756 | 86412 | 2.2992 | 2.3102 | 2024-07-24 17:00:47+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,603,296 | 85102 | 28.6305 | 29.2204 | 2022-04-17 14:17:12+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,672,990 | 81823 | 27.6552 | 27.0975 | 2022-04-28 12:58:41+00:00 |
| FXS/USD | 2023-03 SVB/banking crisis | 16,765,356 | 77820 | 9.8527 | 9.6542 | 2023-03-05 23:07:23+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,643,715 | 77262 | 29.9730 | 30.5733 | 2022-04-23 22:19:47+00:00 |
| FXS/USD | 2024-08 carry-trade unwind | 20,477,201 | 67332 | 1.8127 | 1.7757 | 2024-08-07 14:09:59+00:00 |
| FXS/USD | 2024-08 carry-trade unwind | 20,399,839 | 66840 | 2.2993 | 2.2519 | 2024-07-27 19:01:35+00:00 |
| FXS/USD | 2023-03 SVB/banking crisis | 16,839,895 | 66192 | 8.1307 | 8.2986 | 2023-03-16 10:44:11+00:00 |
| FXS/USD | 2024-08 carry-trade unwind | 20,394,298 | 65844 | 2.2516 | 2.2993 | 2024-07-27 00:27:35+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,678,506 | 65634 | 26.5445 | 26.0033 | 2022-04-29 09:58:04+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,812,900 | 65136 | 0.4384 | 0.4331 | 2023-03-12 15:41:11+00:00 |
| FXS/USD | 2024-08 carry-trade unwind | 20,385,406 | 62316 | 2.1667 | 2.1201 | 2024-07-25 18:38:35+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,687,728 | 62276 | 24.4567 | 23.9590 | 2022-04-30 20:28:27+00:00 |
| SNX/USD | 2024-08 carry-trade unwind | 20,502,688 | 60480 | 1.3183 | 1.3324 | 2024-08-11 03:28:35+00:00 |
| FXS/USD | 2023-03 SVB/banking crisis | 16,704,088 | 59736 | 10.1653 | 10.3850 | 2023-02-25 08:22:11+00:00 |
| FXS/USD | 2026-02 crash | 24,409,719 | 59688 | 0.7533 | 0.7358 | 2026-02-08 04:32:11+00:00 |
| FXS/USD | 2024-08 carry-trade unwind | 20,300,493 | 59436 | 2.4032 | 2.3551 | 2024-07-13 22:13:35+00:00 |
| FXS/USD | 2023-03 SVB/banking crisis | 16,754,593 | 59436 | 10.0783 | 9.8712 | 2023-03-04 10:49:59+00:00 |
| FXS/USD | 2024-08 carry-trade unwind | 20,295,571 | 59136 | 2.3554 | 2.4032 | 2024-07-13 05:42:59+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,731,942 | 59019 | 24.5968 | 24.1015 | 2022-05-07 20:35:07+00:00 |
| FXS/USD | 2026-02 crash | 24,418,022 | 58968 | 0.7196 | 0.7048 | 2026-02-09 08:29:35+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,702,251 | 58785 | 22.5170 | 22.9700 | 2022-05-03 03:22:11+00:00 |
| 1INCH/USD | 2022-11 FTX collapse | 15,880,445 | 58596 | 0.6101 | 0.6039 | 2022-11-02 06:07:47+00:00 |
| FXS/USD | 2023-03 SVB/banking crisis | 16,783,465 | 58056 | 9.2572 | 9.4455 | 2023-03-08 12:14:11+00:00 |
| FXS/USD | 2023-03 SVB/banking crisis | 16,697,571 | 56976 | 10.8134 | 10.5909 | 2023-02-24 10:21:47+00:00 |
| 1INCH/USD | 2024-08 carry-trade unwind | 20,504,460 | 55860 | 0.2764 | 0.2792 | 2024-08-11 09:24:59+00:00 |
| FXS/USD | 2023-03 SVB/banking crisis | 16,606,317 | 54180 | 10.2461 | 10.4586 | 2023-02-11 15:08:47+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,790,566 | 53930 | 8.3185 | 8.4850 | 2022-05-17 05:02:10+00:00 |
| 1INCH/USD | 2022-11 FTX collapse | 15,807,179 | 53808 | 0.5666 | 0.5723 | 2022-10-23 00:18:59+00:00 |
| 1INCH/USD | 2022-11 FTX collapse | 15,825,905 | 52464 | 0.5724 | 0.5782 | 2022-10-25 15:10:59+00:00 |
| FXS/USD | 2024-08 carry-trade unwind | 20,334,078 | 51264 | 2.5819 | 2.5293 | 2024-07-18 14:43:23+00:00 |
| FXS/USD | 2023-03 SVB/banking crisis | 16,633,660 | 49320 | 10.0250 | 10.2331 | 2023-02-15 10:50:47+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,615,383 | 48806 | 34.8758 | 33.9852 | 2022-04-19 11:58:54+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,756,749 | 47724 | 0.5242 | 0.5189 | 2023-03-04 18:06:35+00:00 |
| FXS/USD | 2023-03 SVB/banking crisis | 16,730,457 | 47172 | 11.4142 | 11.6569 | 2023-03-01 01:18:11+00:00 |
| FXS/USD | 2024-08 carry-trade unwind | 20,356,599 | 47028 | 2.5467 | 2.4937 | 2024-07-21 18:07:35+00:00 |
| CRV/USD | 2023-03 SVB/banking crisis | 16,790,962 | 46872 | 0.8965 | 0.9058 | 2023-03-09 13:31:47+00:00 |
| FXS/USD | 2024-08 carry-trade unwind | 20,504,394 | 46668 | 1.9342 | 1.9740 | 2024-08-11 09:11:47+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,590,519 | 46125 | 29.2803 | 28.6517 | 2022-04-15 14:37:41+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,750,607 | 45480 | 0.5249 | 0.5191 | 2023-03-03 21:21:23+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,628,816 | 45231 | 35.3603 | 36.1000 | 2022-04-21 14:25:55+00:00 |
| 1INCH/USD | 2022-11 FTX collapse | 15,794,894 | 44964 | 0.5610 | 0.5553 | 2022-10-21 07:09:47+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,796,468 | 44731 | 8.3101 | 8.1354 | 2022-05-18 03:27:43+00:00 |
| FXS/USD | 2024-08 carry-trade unwind | 20,484,488 | 44148 | 1.8037 | 1.8401 | 2024-08-08 14:33:11+00:00 |
| FXS/USD | 2024-08 carry-trade unwind | 20,413,058 | 43932 | 2.3465 | 2.2954 | 2024-07-29 15:16:35+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,770,077 | 43248 | 0.5228 | 0.5280 | 2023-03-06 15:02:59+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,763,837 | 42912 | 0.5222 | 0.5170 | 2023-03-05 18:00:23+00:00 |
| FXS/USD | 2024-08 carry-trade unwind | 20,363,434 | 41100 | 2.5494 | 2.4972 | 2024-07-22 17:02:47+00:00 |
| FXS/USD | 2023-03 SVB/banking crisis | 16,797,194 | 41088 | 8.3430 | 8.1750 | 2023-03-10 10:39:35+00:00 |
| 1INCH/USD | 2022-11 FTX collapse | 15,958,203 | 40284 | 0.5097 | 0.5149 | 2022-11-13 02:45:23+00:00 |
| FXS/USD | 2024-08 carry-trade unwind | 20,500,532 | 39912 | 1.8957 | 1.9342 | 2024-08-10 20:13:59+00:00 |
| 1INCH/USD | 2024-08 carry-trade unwind | 20,448,780 | 39672 | 0.3163 | 0.3131 | 2024-08-03 15:01:59+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,805,382 | 39566 | 7.1867 | 7.0345 | 2022-05-19 14:10:44+00:00 |
| FXS/USD | 2024-08 carry-trade unwind | 20,352,698 | 39072 | 2.6002 | 2.5467 | 2024-07-21 05:03:47+00:00 |
| 1INCH/USD | 2022-11 FTX collapse | 15,884,037 | 38712 | 0.5971 | 0.6040 | 2022-11-02 18:10:35+00:00 |
| FXS/USD | 2026-02 crash | 24,439,665 | 38400 | 0.6369 | 0.6235 | 2026-02-12 09:00:59+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,660,757 | 38198 | 28.2381 | 27.6600 | 2022-04-26 14:48:48+00:00 |
| 1INCH/USD | 2022-05 Terra collapse onset | 14,792,281 | 38175 | 0.9400 | 0.9495 | 2022-05-17 11:30:52+00:00 |
| FXS/USD | 2024-08 carry-trade unwind | 20,424,988 | 38172 | 2.2892 | 2.3372 | 2024-07-31 07:17:35+00:00 |
| FXS/USD | 2026-02 crash | 24,412,837 | 37956 | 0.7358 | 0.7200 | 2026-02-08 15:04:47+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,655,336 | 36811 | 27.6169 | 28.1700 | 2022-04-25 18:19:08+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,666,945 | 36466 | 28.2303 | 27.6552 | 2022-04-27 14:14:58+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,793,179 | 36002 | 8.4850 | 8.3101 | 2022-05-17 15:02:12+00:00 |
| YFI/USD | 2026-02 crash | 24,411,043 | 35832 | 2981.3853 | 3019.2124 | 2026-02-08 09:00:47+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,799,006 | 34645 | 8.1354 | 7.9717 | 2022-05-18 13:05:08+00:00 |
| 1INCH/USD | 2022-11 FTX collapse | 15,871,375 | 34512 | 0.6178 | 0.6115 | 2022-10-31 23:38:59+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,697,923 | 34494 | 22.9781 | 22.5170 | 2022-05-02 11:02:26+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,647,793 | 34354 | 29.9517 | 29.3500 | 2022-04-24 13:43:47+00:00 |
| 1INCH/USD | 2022-11 FTX collapse | 15,801,378 | 34020 | 0.5666 | 0.5609 | 2022-10-22 04:52:59+00:00 |
| 1INCH/USD | 2022-11 FTX collapse | 15,789,949 | 33708 | 0.5679 | 0.5737 | 2022-10-20 14:37:23+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,618,891 | 33386 | 33.9974 | 34.6900 | 2022-04-20 00:57:40+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,727,647 | 33339 | 25.1000 | 24.5968 | 2022-05-07 04:11:28+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,587,114 | 33028 | 29.8800 | 29.2803 | 2022-04-15 01:48:56+00:00 |
| 1INCH/USD | 2026-02 crash | 24,431,124 | 31692 | 0.0948 | 0.0938 | 2026-02-11 04:24:59+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,637,995 | 31578 | 30.6295 | 29.9730 | 2022-04-23 00:52:05+00:00 |
| YFI/USD | 2026-02 crash | 24,427,287 | 31476 | 3023.0600 | 3060.2267 | 2026-02-10 15:31:47+00:00 |
| SNX/USD | 2024-08 carry-trade unwind | 20,483,887 | 30996 | 1.2543 | 1.2713 | 2024-08-08 12:32:23+00:00 |
| SNX/USD | 2022-11 FTX collapse | 15,957,711 | 30732 | 1.6043 | 1.6219 | 2022-11-13 01:06:35+00:00 |
| YFI/USD | 2026-02 crash | 24,439,949 | 30684 | 3049.5600 | 3084.3037 | 2026-02-12 09:57:59+00:00 |
| FXS/USD | 2026-02 crash | 24,426,005 | 30168 | 0.7188 | 0.7040 | 2026-02-10 11:14:11+00:00 |
| FXS/USD | 2026-02 crash | 24,400,672 | 29748 | 0.7867 | 0.8029 | 2026-02-06 22:09:11+00:00 |
| FXS/USD | 2022-05 Terra collapse onset | 14,683,128 | 29721 | 24.9602 | 24.4567 | 2022-04-30 03:10:31+00:00 |
| 1INCH/USD | 2022-11 FTX collapse | 15,874,392 | 29604 | 0.6176 | 0.6238 | 2022-11-01 09:49:23+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,783,946 | 29352 | 0.4948 | 0.4890 | 2023-03-08 13:50:59+00:00 |
| 1INCH/USD | 2022-11 FTX collapse | 15,850,116 | 29088 | 0.6158 | 0.6222 | 2022-10-29 00:23:11+00:00 |
| 1INCH/USD | 2022-11 FTX collapse | 15,912,771 | 28524 | 0.6566 | 0.6500 | 2022-11-06 18:28:47+00:00 |
| 1INCH/USD | 2024-08 carry-trade unwind | 20,453,762 | 28032 | 0.3000 | 0.2966 | 2024-08-04 07:41:59+00:00 |
| 1INCH/USD | 2022-11 FTX collapse | 15,852,526 | 27912 | 0.6154 | 0.6216 | 2022-10-29 08:28:47+00:00 |
| 1INCH/USD | 2022-11 FTX collapse | 15,864,980 | 27876 | 0.6136 | 0.6074 | 2022-10-31 02:13:23+00:00 |
| CRV/USD | 2026-02 crash | 24,409,526 | 27816 | 0.2572 | 0.2545 | 2026-02-08 03:52:59+00:00 |
| FXS/USD | 2026-02 crash | 24,423,066 | 27432 | 0.7198 | 0.7343 | 2026-02-10 01:22:35+00:00 |
| FXS/USD | 2026-02 crash | 24,320,321 | 27336 | 0.8043 | 0.8210 | 2026-01-26 16:53:11+00:00 |
| 1INCH/USD | 2022-11 FTX collapse | 15,829,620 | 27276 | 0.5842 | 0.5901 | 2022-10-26 03:40:47+00:00 |
| YFI/USD | 2026-02 crash | 24,423,235 | 27276 | 3059.4015 | 3091.8332 | 2026-02-10 01:57:35+00:00 |
| CRV/USD | 2026-02 crash | 24,383,090 | 26976 | 0.2840 | 0.2811 | 2026-02-04 11:08:11+00:00 |
| SUSHI/USD | 2026-02 crash | 24,427,246 | 26556 | 0.1982 | 0.2003 | 2026-02-10 15:23:23+00:00 |
| SNX/USD | 2024-08 carry-trade unwind | 20,448,875 | 25488 | 1.5313 | 1.5104 | 2024-08-03 15:20:59+00:00 |
| SNX/USD | 2026-02 crash | 24,411,445 | 25464 | 0.2939 | 0.2907 | 2026-02-08 10:22:59+00:00 |
| FXS/USD | 2026-02 crash | 24,431,417 | 25464 | 0.7288 | 0.7141 | 2026-02-11 05:24:11+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,824,039 | 25440 | 0.5015 | 0.5068 | 2023-03-14 05:13:47+00:00 |
| FXS/USD | 2026-02 crash | 24,420,787 | 25356 | 0.7055 | 0.7198 | 2026-02-09 17:45:23+00:00 |
| 1INCH/USD | 2024-08 carry-trade unwind | 20,494,566 | 25212 | 0.2737 | 0.2764 | 2024-08-10 00:16:23+00:00 |
| CRV/USD | 2023-03 SVB/banking crisis | 16,811,210 | 25152 | 0.8636 | 0.8543 | 2023-03-12 09:59:35+00:00 |
| 1INCH/USD | 2024-08 carry-trade unwind | 20,498,701 | 24732 | 0.2736 | 0.2708 | 2024-08-10 14:07:23+00:00 |
| SNX/USD | 2026-02 crash | 24,430,419 | 24324 | 0.2828 | 0.2860 | 2026-02-11 02:03:35+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,796,307 | 24132 | 0.4341 | 0.4387 | 2023-03-10 07:37:23+00:00 |
| YFI/USD | 2026-02 crash | 24,431,519 | 23808 | 3004.8500 | 2974.3357 | 2026-02-11 05:44:35+00:00 |
| 1INCH/USD | 2024-08 carry-trade unwind | 20,440,947 | 23796 | 0.3348 | 0.3310 | 2024-08-02 12:46:11+00:00 |
| YFI/USD | 2026-02 crash | 24,360,859 | 23724 | 2879.5462 | 2912.2022 | 2026-02-01 08:36:11+00:00 |
| FXS/USD | 2026-02 crash | 24,443,085 | 23664 | 0.6227 | 0.6353 | 2026-02-12 20:29:23+00:00 |
| MATIC/USD | 2026-02 crash | 24,433,784 | 23628 | 0.0886 | 0.0896 | 2026-02-11 13:19:35+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,779,290 | 23496 | 0.5057 | 0.5003 | 2023-03-07 22:08:23+00:00 |
| SUSHI/USD | 2026-02 crash | 24,430,080 | 23484 | 0.1979 | 0.1999 | 2026-02-11 00:55:23+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,740,961 | 23472 | 0.5628 | 0.5570 | 2023-03-02 12:44:23+00:00 |
| MATIC/USD | 2026-02 crash | 24,422,849 | 22920 | 0.0940 | 0.0950 | 2026-02-10 00:39:11+00:00 |
| SNX/USD | 2026-02 crash | 24,440,829 | 22908 | 0.2871 | 0.2841 | 2026-02-12 12:54:47+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,742,818 | 22716 | 0.5570 | 0.5628 | 2023-03-02 19:02:59+00:00 |
| SUSHI/USD | 2026-02 crash | 24,408,586 | 22692 | 0.2137 | 0.2115 | 2026-02-08 00:40:47+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,781,461 | 22656 | 0.5054 | 0.4999 | 2023-03-08 05:28:11+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,744,675 | 22572 | 0.5628 | 0.5565 | 2023-03-03 01:19:11+00:00 |
| 1INCH/USD | 2022-05 Terra collapse onset | 14,801,672 | 22550 | 0.9157 | 0.9053 | 2022-05-18 23:30:20+00:00 |
| FXS/USD | 2026-02 crash | 24,369,606 | 22476 | 0.8025 | 0.7864 | 2026-02-02 13:55:23+00:00 |
| SNX/USD | 2026-02 crash | 24,433,921 | 22428 | 0.2713 | 0.2740 | 2026-02-11 13:46:59+00:00 |
| 1INCH/USD | 2022-05 Terra collapse onset | 14,776,453 | 22313 | 0.9320 | 0.9420 | 2022-05-14 23:07:45+00:00 |
| FXS/USD | 2026-02 crash | 24,352,360 | 22308 | 0.8528 | 0.8344 | 2026-01-31 04:07:47+00:00 |
| CRV/USD | 2024-08 carry-trade unwind | 20,507,384 | 22272 | 0.2521 | 0.2495 | 2024-08-11 19:13:23+00:00 |
| YFI/USD | 2026-02 crash | 24,433,498 | 21924 | 2944.5900 | 2978.9992 | 2026-02-11 12:21:59+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,818,015 | 21876 | 0.4801 | 0.4749 | 2023-03-13 08:54:47+00:00 |
| MATIC/USD | 2026-02 crash | 24,410,928 | 21696 | 0.0966 | 0.0976 | 2026-02-08 08:37:23+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,771,844 | 21516 | 0.5280 | 0.5220 | 2023-03-06 21:01:35+00:00 |
| CRV/USD | 2026-02 crash | 24,423,702 | 21456 | 0.2529 | 0.2501 | 2026-02-10 03:31:23+00:00 |
| MATIC/USD | 2026-02 crash | 24,426,453 | 21432 | 0.0928 | 0.0918 | 2026-02-10 12:44:23+00:00 |
| CRV/USD | 2024-08 carry-trade unwind | 20,503,180 | 21336 | 0.2573 | 0.2601 | 2024-08-11 05:07:23+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,831,761 | 21300 | 0.5337 | 0.5283 | 2023-03-15 07:16:35+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,864,023 | 21240 | 0.5558 | 0.5614 | 2023-03-19 20:06:23+00:00 |
| CRV/USD | 2023-03 SVB/banking crisis | 16,824,036 | 21132 | 0.9741 | 0.9844 | 2023-03-14 05:13:11+00:00 |
| FXS/USD | 2026-02 crash | 24,373,214 | 21108 | 0.8019 | 0.8185 | 2026-02-03 02:01:23+00:00 |
| CRV/USD | 2023-03 SVB/banking crisis | 16,860,142 | 20832 | 1.0130 | 1.0028 | 2023-03-19 06:59:47+00:00 |
| 1INCH/USD | 2026-02 crash | 24,426,412 | 20832 | 0.0956 | 0.0946 | 2026-02-10 12:35:59+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,853,390 | 20508 | 0.5391 | 0.5331 | 2023-03-18 08:15:47+00:00 |
| MATIC/USD | 2026-02 crash | 24,438,881 | 20220 | 0.0902 | 0.0911 | 2026-02-12 06:23:35+00:00 |
| 1INCH/USD | 2026-02 crash | 24,438,831 | 20136 | 0.0935 | 0.0945 | 2026-02-12 06:13:35+00:00 |
| 1INCH/USD | 2024-08 carry-trade unwind | 20,482,397 | 19572 | 0.2603 | 0.2575 | 2024-08-08 07:33:23+00:00 |
| CRV/USD | 2026-02 crash | 24,419,644 | 19416 | 0.2501 | 0.2474 | 2026-02-09 13:56:11+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,849,764 | 19212 | 0.5012 | 0.5066 | 2023-03-17 20:00:47+00:00 |
| CRV/USD | 2023-03 SVB/banking crisis | 16,869,223 | 19044 | 1.0012 | 0.9910 | 2023-03-20 13:36:35+00:00 |
| FXS/USD | 2026-02 crash | 24,382,226 | 18876 | 0.8537 | 0.8350 | 2026-02-04 08:14:47+00:00 |
| SUSHI/USD | 2026-02 crash | 24,423,581 | 18720 | 0.2055 | 0.2033 | 2026-02-10 03:07:11+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,765,379 | 18696 | 0.5170 | 0.5117 | 2023-03-05 23:11:59+00:00 |
| FXS/USD | 2026-02 crash | 24,326,502 | 18576 | 0.8042 | 0.7845 | 2026-01-27 13:34:59+00:00 |
| 1INCH/USD | 2022-05 Terra collapse onset | 14,807,478 | 18252 | 0.9230 | 0.9137 | 2022-05-19 22:22:50+00:00 |
| MATIC/USD | 2026-02 crash | 24,408,121 | 18180 | 0.0977 | 0.0966 | 2026-02-07 23:06:35+00:00 |
| CRV/USD | 2023-03 SVB/banking crisis | 16,817,847 | 18132 | 0.9593 | 0.9496 | 2023-03-13 08:20:59+00:00 |
| 1INCH/USD | 2022-05 Terra collapse onset | 14,788,680 | 17989 | 0.9212 | 0.9304 | 2022-05-16 21:45:31+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,791,191 | 17928 | 0.4786 | 0.4835 | 2023-03-09 14:18:23+00:00 |
| 1INCH/USD | 2024-08 carry-trade unwind | 20,483,885 | 17916 | 0.2575 | 0.2615 | 2024-08-08 12:31:59+00:00 |
| 1INCH/USD | 2024-08 carry-trade unwind | 20,455,210 | 17388 | 0.2966 | 0.2998 | 2024-08-04 12:31:47+00:00 |
| 1INCH/USD | 2026-02 crash | 24,409,537 | 17244 | 0.0994 | 0.0984 | 2026-02-08 03:55:23+00:00 |
| FXS/USD | 2026-02 crash | 24,404,790 | 17196 | 0.7688 | 0.7533 | 2026-02-07 11:57:23+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,845,872 | 16992 | 0.5020 | 0.5073 | 2023-03-17 06:51:59+00:00 |
| CRV/USD | 2026-02 crash | 24,410,917 | 16920 | 0.2545 | 0.2570 | 2026-02-08 08:34:59+00:00 |
| CRV/USD | 2023-03 SVB/banking crisis | 16,844,278 | 16896 | 0.9059 | 0.9150 | 2023-03-17 01:30:11+00:00 |
| 1INCH/USD | 2022-05 Terra collapse onset | 14,779,582 | 16848 | 0.9324 | 0.9421 | 2022-05-15 11:04:05+00:00 |
| FXS/USD | 2026-02 crash | 24,435,947 | 16800 | 0.6666 | 0.6527 | 2026-02-11 20:34:11+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,844,303 | 16740 | 0.4920 | 0.4970 | 2023-03-17 01:35:11+00:00 |
| 1INCH/USD | 2026-02 crash | 24,440,207 | 16572 | 0.0945 | 0.0955 | 2026-02-12 10:49:47+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,870,037 | 16488 | 0.5351 | 0.5290 | 2023-03-20 16:21:11+00:00 |
| 1INCH/USD | 2026-02 crash | 24,410,888 | 16428 | 0.0984 | 0.0994 | 2026-02-08 08:29:11+00:00 |
| 1INCH/USD | 2023-03 SVB/banking crisis | 16,788,134 | 16428 | 0.4739 | 0.4788 | 2023-03-09 04:00:47+00:00 |
| YFI/USD | 2026-02 crash | 24,375,375 | 16404 | 2924.1625 | 2892.1104 | 2026-02-03 09:15:59+00:00 |
| SNX/USD | 2024-08 carry-trade unwind | 20,469,723 | 16296 | 1.2848 | 1.2719 | 2024-08-06 13:06:47+00:00 |
| CRV/USD | 2024-08 carry-trade unwind | 20,504,529 | 16296 | 0.2601 | 0.2574 | 2024-08-11 09:38:59+00:00 |
| FXS/USD | 2026-02 crash | 24,440,999 | 16080 | 0.6235 | 0.6103 | 2026-02-12 13:28:59+00:00 |
| FXS/USD | 2026-02 crash | 24,353,689 | 15984 | 0.8344 | 0.8168 | 2026-01-31 08:34:11+00:00 |
| FXS/USD | 2026-02 crash | 24,434,335 | 15936 | 0.6980 | 0.6803 | 2026-02-11 15:10:11+00:00 |
| CRV/USD | 2022-11 FTX collapse | 15,956,427 | 15888 | 0.6238 | 0.6175 | 2022-11-12 20:48:59+00:00 |
| SUSHI/USD | 2026-02 crash | 24,433,508 | 15816 | 0.1928 | 0.1948 | 2026-02-11 12:23:59+00:00 |
| 1INCH/USD | 2022-05 Terra collapse onset | 14,797,687 | 15758 | 0.9262 | 0.9368 | 2022-05-18 08:03:54+00:00 |
| 1INCH/USD | 2026-02 crash | 24,436,066 | 15720 | 0.0927 | 0.0937 | 2026-02-11 20:57:59+00:00 |
| MATIC/USD | 2026-02 crash | 24,404,818 | 15672 | 0.0953 | 0.0965 | 2026-02-07 12:02:59+00:00 |
| FXS/USD | 2026-02 crash | 24,428,580 | 15636 | 0.7494 | 0.7660 | 2026-02-10 19:52:23+00:00 |
| YFI/USD | 2026-02 crash | 24,390,302 | 15552 | 2782.8334 | 2754.9684 | 2026-02-05 11:22:11+00:00 |
| FXS/USD | 2026-02 crash | 24,343,737 | 15360 | 0.8157 | 0.7988 | 2026-01-29 23:15:59+00:00 |
| CRV/USD | 2023-03 SVB/banking crisis | 16,839,599 | 15348 | 0.9069 | 0.9169 | 2023-03-16 09:43:59+00:00 |
| YFI/USD | 2026-02 crash | 24,369,306 | 15324 | 2805.6684 | 2834.2065 | 2026-02-02 12:54:59+00:00 |
| 1INCH/USD | 2024-08 carry-trade unwind | 20,507,436 | 15312 | 0.2649 | 0.2621 | 2024-08-11 19:23:47+00:00 |
| CRV/USD | 2023-03 SVB/banking crisis | 16,813,424 | 15108 | 0.8653 | 0.8770 | 2023-03-12 17:27:11+00:00 |
| CRV/USD | 2024-08 carry-trade unwind | 20,498,192 | 15096 | 0.2548 | 0.2574 | 2024-08-10 12:25:23+00:00 |
| SUSHI/USD | 2026-02 crash | 24,412,945 | 15096 | 0.2105 | 0.2080 | 2026-02-08 15:27:11+00:00 |
| SUSHI/USD | 2026-02 crash | 24,410,747 | 15048 | 0.2092 | 0.2086 | 2026-02-08 08:00:59+00:00 |
| MATIC/USD | 2026-02 crash | 24,419,867 | 14988 | 0.0927 | 0.0939 | 2026-02-09 14:40:47+00:00 |
| YFI/USD | 2026-02 crash | 24,404,852 | 14856 | 2884.2861 | 2913.9233 | 2026-02-07 12:09:47+00:00 |
| SNX/USD | 2024-08 carry-trade unwind | 20,467,496 | 14856 | 1.3006 | 1.3160 | 2024-08-06 05:39:59+00:00 |
| CRV/USD | 2023-03 SVB/banking crisis | 16,795,840 | 14796 | 0.8306 | 0.8393 | 2023-03-10 06:01:59+00:00 |
| SNX/USD | 2022-11 FTX collapse | 15,954,157 | 14676 | 1.7186 | 1.7002 | 2022-11-12 13:13:11+00:00 |
| CRV/USD | 2022-11 FTX collapse | 15,973,698 | 14640 | 0.6183 | 0.6120 | 2022-11-15 06:38:47+00:00 |
| MATIC/USD | 2026-02 crash | 24,412,966 | 14604 | 0.0976 | 0.0966 | 2026-02-08 15:31:23+00:00 |
| YFI/USD | 2026-02 crash | 24,371,521 | 14580 | 2956.4428 | 2925.3874 | 2026-02-02 20:20:35+00:00 |
| 1INCH/USD | 2026-02 crash | 24,375,376 | 14580 | 0.1145 | 0.1132 | 2026-02-03 09:16:11+00:00 |
| CRV/USD | 2026-02 crash | 24,421,697 | 14496 | 0.2533 | 0.2559 | 2026-02-09 20:47:59+00:00 |

### Feed/window coverage (per-window historical resolution, not "latest")

Each feed's address was re-resolved via the Feed Registry AT EACH WINDOW's own historical block, not looked up once at "latest" -- necessary because a proxy address active today may not have existed during an earlier window (Chainlink periodically migrates proxies). This is a real coverage limitation, not a bug to paper over: a window this method can't reach was never actually checked, and is reported as such below rather than silently counted as clean.

- **79/102** feed/window combinations were actually mined for gaps.
- **17/102** were unreachable because the Feed Registry contract itself did not exist yet at that window's block (true for every feed's 2020-03 COVID-crash window -- the registry wasn't deployed until sometime between 2020-03 and 2022-05, confirmed via `get_code`, not assumed).
- **6/102** were unreachable because no feed was registered for that asset/quote pair at that window's block (the asset's feed may not have existed yet, or Chainlink hadn't onboarded it to the registry yet at that time).

## Part B — depeg-lag check (newer LSD/ETH feeds)

Same method as the original rETH/ETH, cbETH/ETH, WBTC/BTC check: max single-round price move and max gap vs. the feed's own median, over its full reachable history. A genuine depeg-lag candidate needs BOTH a real large price move AND a stale gap that failed to track it in time.

| Candidate | Status | Rounds | Window | Median gap (s) | Max gap (s) | Max gap / median | Max single-round move |
|---|---|---|---|---|---|---|---|
| weETH/ETH | ok | 831 | 2024-06-28 06:13:47+00:00 -> 2026-09-13 04:26:59+00:00 | 86424 | 86496 | 1.0x | 1.43% |
| ezETH/ETH | ok | 830 | 2024-07-12 08:47:23+00:00 -> 2026-09-13 04:26:47+00:00 | 86424 | 86496 | 1.0x | 3.36% |
| osETH/ETH | no feed registered | — | — | — | — | — | — |
| sfrxETH/ETH | no feed registered | — | — | — | — | — | — |

## Part C — is any resolved feed currently frozen/dead (live check)

Not a window-based check like Part A -- this is the same kind of live 'has this feed silently died' check that originally found FTT/USD and UST/USD (both are STILL frozen years later). Flags anything whose most recent update is suspiciously old right now, regardless of whether that shows up in any of the 6 stress windows Part A checked.

| Feed | Last update (UTC) | Age (days) | Suspicious? |
|---|---|---|---|
| LINK/USD | 2026-09-14 00:32:35+00:00 | 0.0 | no |
| DAI/USD | 2026-09-14 00:00:11+00:00 | 0.0 | no |
| UNI/USD | 2026-09-14 00:26:23+00:00 | 0.0 | no |
| COMP/USD | 2026-09-14 00:29:35+00:00 | 0.0 | no |
| MATIC/USD | 2026-09-13 22:16:23+00:00 | 0.1 | no |
| SNX/USD | 2026-09-13 22:16:47+00:00 | 0.1 | no |
| AAVE/USD | 2026-09-14 00:19:35+00:00 | 0.0 | no |
| CRV/USD | 2026-09-13 23:56:59+00:00 | 0.0 | no |
| MKR/USD | 2026-09-14 00:13:35+00:00 | 0.0 | no |
| FXS/USD | 2026-09-13 22:28:23+00:00 | 0.1 | no |
| YFI/USD | 2026-09-13 22:18:47+00:00 | 0.1 | no |
| SUSHI/USD | 2026-09-14 00:45:47+00:00 | 0.0 | no |
| 1INCH/USD | 2026-09-14 00:27:11+00:00 | 0.0 | no |
| FRAX/USD | 2026-09-14 00:09:59+00:00 | 0.0 | no |
| LUSD/USD | 2026-09-13 04:31:23+00:00 | 0.8 | no |
| USDe/USD | 2026-09-13 07:50:35+00:00 | 0.7 | no |
| PYUSD/USD | 2026-09-13 19:42:47+00:00 | 0.2 | no |
| weETH/ETH | 2026-09-13 04:26:59+00:00 | 0.8 | no |
| ezETH/ETH | 2026-09-13 04:26:47+00:00 | 0.8 | no |

## Headline finding

See tables above for anything flagged — review each individually before treating it as a genuine new malfunction (this report does not itself decide that; it surfaces raw on-chain evidence only, the same standard `malfunction_candidates.md` was held to).
