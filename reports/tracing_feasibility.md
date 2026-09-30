# Transaction-tracing feasibility probe: can we see atomic, self-reversing manipulation?

**No code changed, no model touched, no new production feature computed** —
this is a pure feasibility probe, exactly as scoped.

**Test transactions, and a disclosure up front**: the task referred to "these
two transactions" without naming them in this message. No two were specified
elsewhere in reach of this probe, so I picked the two clearest, best-
documented atomic round-trip cases from the incidents dropped during the
reserve_skew resolution work (`reports/manipulation_candidates_phase2.md`'s
addendum) — **MetaPool** (`0x57ee419a...5fd1fa69`, block 22,722,911) and
**MahaLend** (`0x2881e839...557a4a2cc`, block 18,544,605) — both confirmed at
the time as genuine atomic exploits with real fund flows that net to zero by
block-end. If different transactions were intended, the method here transfers
directly; these two happen to also be a useful contrast case (§3).

## 1. Access: does trace-level RPC work on our current tier? **No — confirmed directly, not inferred.**

Tested against our actual production endpoint (Alchemy, `fetch_chainlink.py`'s
`MAINNET_RPC_URL`) with four different trace-level JSON-RPC methods, on both
transactions:

| Method | Result |
|---|---|
| `debug_traceTransaction` (`callTracer`) | **Rejected**: *"debug_traceTransaction is not available on the Free tier - upgrade to Pay As You Go, or Enterprise for access."* |
| `debug_traceTransaction` (default `structLog`) | Same rejection, identical message |
| `trace_transaction` | Same rejection, identical message |
| `trace_replayTransaction` | Same rejection, identical message |

**This is unambiguous and settles the question for our current setup**: every
trace-level method Alchemy exposes is gated behind a paid tier. Plain
`eth_getTransactionReceipt`/`eth_call`/`eth_getBalance`-style point-in-time
reads (everything this project has used so far) remain free; anything that
replays a transaction's internal execution does not.

**Checked whether a free alternative exists, so this isn't reported as a dead
end without looking**: tried `debug_traceTransaction` against four public
mainnet RPC endpoints (`llamarpc.com`, `publicnode.com`, `ankr.com/eth`,
`drpc.org`). Every one either doesn't implement the method, requires its own
paid/authenticated key, or times out on its free plan. **Trace-level RPC
access is not available through any zero-cost channel tested.**

**One free-tier alternative exists but was not tested here, flagged for a
future pilot, not claimed as working**: Etherscan's own API offers a
`txlistinternal` endpoint (free API key, rate-limited) that returns the
internal ETH transfers Etherscan itself computes server-side — this is not a
full opcode/storage trace, but it is a real, structured, programmatically
fetchable call-level trace, and it's how §2 below was actually produced
(via Etherscan's public web view, a close cousin of that API). Registering a
free key and hitting that endpoint directly (rather than scraping the web
page) is the most concrete "try this next" if trace data is wanted without
an Alchemy tier upgrade.

## 2. Signal visibility: does the transient distortion show up? **Yes, clearly, for both — even at the call-trace level, no opcode trace needed.**

Since direct RPC tracing is blocked (§1), this used Etherscan's free web-based
internal-transactions view (`etherscan.io/tx/<hash>`) as a workaround —
**explicitly not our production data pipeline**, and itself a lossy
intermediary (see the caveat at the end of this section). Real, structured
data came back for both transactions.

### MetaPool: a clean, single-peak transient hold, invisible to block-boundary reads

| Step | Internal transfer | Running balance at the exploit contract (`0xC3D10bd8`) |
|---|---|---|
| 1 | WETH → contract: 107 ETH | +107 ETH |
| 2 | contract → mpETH token: 107 ETH | 0 (converted to mpETH position) |
| 3-5 | mpETH-related unwind, ~106.9 ETH-equivalent back to contract | ~+106.9 ETH-equivalent |
| 6 | contract → WETH: 105.89 ETH (loan repayment) | ~+1 ETH-equivalent |
| 7-8 | 8.89 ETH in, then out to the exploiter (profit) | 0 |

**The peak transient hold is ~107 ETH of value the contract briefly controlled
and does not hold before or after the transaction.** Our existing block-level
reads for this exact venue (`data/processed/features.parquet`, computed
earlier this project) show `baseline=0.0, now=0.0` WETH/mpETH at the pool
address 300 blocks apart — genuinely, correctly zero at both boundaries. The
trace confirms *why*: the ~107 ETH exposure exists **only within this single
transaction**, between internal calls 1 and 6, invisible to any read anchored
to a block boundary. This is a direct, concrete confirmation that the
signal this project's block-level `reserve_skew` metric structurally cannot
see does exist and is recoverable from trace-level (or even call-level) data.

### MahaLend: the same conclusion, at much larger scale and different shape

Etherscan reports **273 internal transactions** for this transaction — far
too many to hand-verify, but the aggregate shape is clear: a 13.9M USDC
flash loan from Balancer, then **~136 repeated round-trip transfer pairs**
(1,160,272.59 / 1,160,852.73 USDC alternating) between the exploit contract
and an mUSDC-style vault, before the flash loan is fully repaid. Our
block-level read for this venue showed `baseline=0.0, now=0.0` USDC —
again correct at both boundaries, and again explained by the trace: the
entire 13.9M USDC exposure, and the ~136-step exchange-rate-inflation loop it
funds, happens and fully unwinds within this one transaction.

**Caveat on the method used here, stated plainly**: Etherscan's page was
fetched and summarized by WebFetch's own HTML→markdown→small-model pipeline,
which explicitly may summarize rather than exhaustively enumerate large
pages — confirmed here, since MahaLend's ~136 repeated pairs were reported as
an approximate count ("~136"), not individually listed. This was adequate for
answering *whether* the signal is visible (yes), but would **not** be a
reliable extraction method for a real feature pipeline — a production
implementation would need the raw JSON from a real trace call or Etherscan's
API directly, not a scraped-and-summarized web page.

## 3. Extraction difficulty: one method, or bespoke per pattern? **Genuinely mixed — this is the most important finding for the recommendation below.**

**MetaPool's shape is generic and plausibly capturable by one general
algorithm**: flash-loan-in → deposit/swap through a few hops → peak
transient balance → unwind → repay → extract profit. A reasonably simple,
protocol-agnostic method — *walk the ordered list of internal transfers,
maintain a running per-(address, token) balance, record the maximum absolute
deviation from the pre-transaction balance at any point* — would correctly
identify this exploit's ~107 ETH transient exposure without needing to know
anything MetaPool-specific. This is a real, implementable, generalizable
algorithm in principle, not just a hopeful description.

**MahaLend's shape breaks that same generic method's usefulness, even though
it would technically still run.** The *raw balance* deviation at the vault
address largely reflects the 13.9M USDC flash loan passing through — but the
actual manipulated quantity is not a token balance at all, it's an **implied
exchange rate or share price** that gets inflated by the repeated donation
loop. A max-balance-deviation algorithm would report a large number for the
right *reason* (something unusual happened here) but the wrong *quantity*
(loan size, not exchange-rate distortion) — correctly flagging "this
transaction is anomalous" is not the same as correctly measuring "how
manipulated was the price." Extracting the real signal here would require
understanding this specific protocol's accounting (reading the right storage
slot or computing `totalAssets / totalSupply`-style ratio at multiple points
in the trace), which is bespoke, protocol-specific parsing work, not a
generic pattern.

**Honest answer**: a general "peak balance deviation from trace" method
would be a real, worthwhile *first pass* that correctly flags transactions
like MetaPool's, but would need to be paired with protocol-specific
accounting-ratio extraction for donation/exchange-rate-style attacks like
MahaLend's to capture their actual manipulated quantity — not because the
signal isn't there (§2 shows clearly that it is, for both), but because
"the manipulated quantity" means a different *kind* of thing depending on
the attack's mechanism. This matches a pattern already documented elsewhere
in this project (`reports/manipulation_candidates_phase2.md`'s addendum):
the atomic exploits dropped from this dataset split roughly into "balance-
based" (MetaPool-like) and "accounting/exchange-rate-based" (MahaLend-like,
also Raft_fi, bZxProtocol, CompounderFinance) categories — a full build would
need to handle both, and the second category is the harder, more bespoke
one.

## 4. Recommendation

**Not worth building right now, for a reason more fundamental than
difficulty: access is the actual blocker, and it costs real money before any
engineering work even starts.** Every trace method is unambiguously gated
behind a paid Alchemy tier (§1), and no free alternative RPC tested provides
it either. Before any extraction-method work is worth doing, this project
would need either an Alchemy tier upgrade (cost unknown, not investigated
here — out of scope for a code-only probe) or a validated free alternative
(Etherscan's `txlistinternal` API, untested but plausible, §1).

**If access were solved, the signal is real and worth recovering — this
probe confirms that, concretely, not speculatively.** Both tested incidents
show a clear, substantial, otherwise-invisible transient distortion exactly
where this project's own block-level `reserve_skew` metric already
predicted one should exist (`baseline=0, now=0` was flagged as "resolved
venue, architecturally invisible metric" at the time these were dropped, not
"nothing happened" — this probe directly confirms that characterization was
correct).

**What it would realistically recover**: not all 7 of the phase-2/3 atomic-
exploit drops equally. The balance-based subset (MetaPool-like) looks
recoverable with one reasonably general algorithm once trace data is
available. The accounting/exchange-rate-based subset (MahaLend-like, and by
the same reasoning likely Raft_fi, bZxProtocol, CompounderFinance) would need
bespoke, protocol-aware parsing per incident — realistically a multi-incident
engineering effort, not a single reusable feature, and one that would need
to be judged incident-by-incident for whether the effort is worth the
recovered signal on a dataset where these incidents are already a small
minority (7 of 165). **Recommended next step, if pursued at all**: pilot
Etherscan's free `txlistinternal` API on 2-3 incidents to validate the free
path actually works reliably and completely (not summarized/truncated, §2's
caveat), before considering any paid-tier spend.
