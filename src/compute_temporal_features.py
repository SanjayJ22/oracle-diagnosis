"""Compute temporal (trajectory-derived) features for all 165 incidents, turning
`reports/temporal_trajectories.md`'s standalone 3-incident finding into real,
model-facing features -- the first time trajectory data feeds `features.parquet`.

Uses each incident's own `oracle_feed` (from build_features.py's INCIDENTS list --
every incident has one, giving 100% coverage by construction for the underlying
data pull, though not every incident yields enough ROUNDS in the window to compute
every feature -- see coverage reporting below) and `src/fetch_chainlink.py`'s
existing `get_feed_update_history()` (same helper, same on-disk cache as every
other Chainlink round-history pull in this project) to walk BACKWARD from each
incident's own anchor round across a fixed 24h trailing window.

STRICTLY NO LOOKAHEAD BY CONSTRUCTION: `get_feed_update_history` walks backward
from `start_round_id` (the round in effect AT the incident block, from
`get_round_data_at_block`) and stops at `min_timestamp` -- every row it returns
has `updated_at <= ` the incident round's own `updated_at`. This is the same
backward-walk convention already used by `reports/temporal_trajectories.md`'s
standalone analysis and by `src/mine_malfunctions_phase1.py`'s window mining.

Four features, chosen to be non-redundant with each other and non-redundant with
the existing static features (price_dev, heartbeat_elapsed are single SNAPSHOTS;
these are trajectory-shaped statistics over a window):

  temporal_deviation_persistence (seconds): how long, counting backward
    CONTIGUOUSLY from the incident's own anchor round, the price stayed beyond a
    5% deviation from the window's own median (same 5% convention as
    RESERVE_SKEW_THRESHOLD / CROSS_VENUE_TOLERANCE / FIXED_THRESHOLDS elsewhere in
    this project). 0.0 if the price is not currently deviated at all.

  temporal_slope (fractional change per hour): (last price - first price) /
    first price / window duration in hours -- net directional rate of change
    across the whole trailing window.

  temporal_step_change_count (count): number of round-to-round price moves
    exceeding 1% within the window -- a change-point-count proxy, directly
    targeting the standalone analysis's finding that manipulation shows multiple
    distinct step-changes while volatility tends toward one smooth move.

  temporal_gap_trend (seconds per round, signed): linear-regression slope of
    consecutive update gaps (gap_seconds) against round order within the window --
    positive means the oracle is updating progressively SLOWER leading up to the
    incident (malfunction-suggestive, matching stETH's staircase-lag finding),
    negative means it's tightening (volatility-crash-suggestive, matching Aug
    2024's "gap tightens right at the trough" finding).

HONEST DEVIATION FROM THE ORIGINAL PROPOSAL: "recovery time (how fast it returns
to baseline)" was proposed as a fourth candidate but is dropped in favor of
temporal_gap_trend above. Recovery time, taken literally, requires looking PAST
the incident block to see when the price returns to baseline -- exactly the
lookahead this task explicitly prohibits ("compute them with strictly trailing
windows, no lookahead"). Rather than silently violate no-lookahead, or silently
drop a requested feature, temporal_gap_trend is substituted: it is the most
directly analogous trailing-only signal available (it captures onset/momentum of
an anomaly's *cadence* dynamics, the same qualitative thing "recovery" would
capture about its price dynamics, just measured going into the incident rather
than coming out of it), and it is independently motivated by the standalone
trajectory analysis's own documented findings. Flagged here explicitly rather
than assumed acceptable.
"""

import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from build_features import INCIDENTS
from fetch_chainlink import get_feed_update_history, get_round_data_at_block, get_web3

FEATURES_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "features.parquet"
WINDOW_SECONDS = 24 * 3600  # 24h trailing window -- long enough to see >=1 round even for a
                            # daily-heartbeat feed (stETH/ETH), short enough to stay anchored
                            # to the incident rather than washing it out in unrelated history
DEVIATION_THRESHOLD = 0.05  # 5%, this project's established "meaningful deviation" convention
STEP_THRESHOLD = 0.01       # 1%, finer-grained than DEVIATION_THRESHOLD, for counting individual steps
MAX_ROUNDS = 500


def compute_for_incident(w3, feed_address: str, incident_block: int) -> dict:
    anchor_round = get_round_data_at_block(w3, feed_address, incident_block)
    anchor_ts = int(anchor_round["updated_at"])

    hist = get_feed_update_history(
        w3, feed_address,
        min_timestamp=anchor_ts - WINDOW_SECONDS,
        max_rounds=MAX_ROUNDS,
        start_round_id=int(anchor_round["round_id"]),
    )

    n_rounds = len(hist)
    out = {
        "temporal_n_rounds": n_rounds,
        "temporal_deviation_persistence": np.nan,
        "temporal_slope": np.nan,
        "temporal_step_change_count": np.nan,
        "temporal_gap_trend": np.nan,
    }
    if n_rounds < 2:
        return out  # can't compute any trajectory statistic from <2 points

    prices = hist["answer"].to_numpy(dtype=float)
    times = hist["updated_at"].to_numpy(dtype=float)

    # --- slope ---
    duration_hours = (times[-1] - times[0]) / 3600.0
    if duration_hours > 0 and prices[0] != 0:
        out["temporal_slope"] = float(((prices[-1] - prices[0]) / prices[0]) / duration_hours)

    # --- deviation persistence (contiguous, trailing, from the anchor round backward) ---
    median_price = float(np.median(prices))
    if median_price != 0:
        dev = np.abs((prices - median_price) / median_price)
        i = len(dev) - 1
        span_start = len(dev)  # sentinel: "not currently deviated"
        while i >= 0 and dev[i] > DEVIATION_THRESHOLD:
            span_start = i
            i -= 1
        if span_start == len(dev):
            out["temporal_deviation_persistence"] = 0.0
        else:
            out["temporal_deviation_persistence"] = float(times[-1] - times[span_start])

    # --- step-change count ---
    with np.errstate(divide="ignore", invalid="ignore"):
        pct_changes = np.abs(np.diff(prices) / prices[:-1])
    pct_changes = pct_changes[np.isfinite(pct_changes)]
    out["temporal_step_change_count"] = int((pct_changes > STEP_THRESHOLD).sum())

    # --- gap trend (needs >=3 rounds: >=2 gaps to regress a slope through) ---
    if n_rounds >= 3:
        gaps = np.diff(times)
        idx = np.arange(len(gaps), dtype=float)
        # simple OLS slope, no external dependency needed for a 1D linear fit
        idx_mean, gap_mean = idx.mean(), gaps.mean()
        denom = ((idx - idx_mean) ** 2).sum()
        if denom > 0:
            slope = ((idx - idx_mean) * (gaps - gap_mean)).sum() / denom
            out["temporal_gap_trend"] = float(slope)

    return out


def main():
    warnings.filterwarnings("ignore")
    w3 = get_web3()
    df = pd.read_parquet(FEATURES_PATH)

    incident_lookup = {i["name"]: i for i in INCIDENTS}

    rows = []
    for idx, row in df.iterrows():
        name = row["incident"]
        inc = incident_lookup.get(name)
        if inc is None:
            print(f"SKIP {name}: not found in INCIDENTS")
            continue
        print(f"[{idx+1}/{len(df)}] {name} (block {inc['block']})...", flush=True)
        try:
            feats = compute_for_incident(w3, inc["oracle_feed"], inc["block"])
        except Exception as exc:
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            feats = {"temporal_n_rounds": 0, "temporal_deviation_persistence": np.nan,
                      "temporal_slope": np.nan, "temporal_step_change_count": np.nan,
                      "temporal_gap_trend": np.nan}
        feats["incident"] = name
        rows.append(feats)
        print(f"  n_rounds={feats['temporal_n_rounds']} "
              f"persistence={feats['temporal_deviation_persistence']} "
              f"slope={feats['temporal_slope']} "
              f"steps={feats['temporal_step_change_count']} "
              f"gap_trend={feats['temporal_gap_trend']}", flush=True)
        time.sleep(0.1)

    temporal_df = pd.DataFrame(rows)
    out = df.merge(temporal_df, on="incident", how="left")
    out.to_parquet(FEATURES_PATH, index=False)
    print(f"\nDone. Wrote temporal features for {len(temporal_df)} incidents to {FEATURES_PATH}")

    print("\n=== Coverage report, per class ===")
    for col in ["temporal_deviation_persistence", "temporal_slope",
                "temporal_step_change_count", "temporal_gap_trend"]:
        print(f"\n{col}:")
        print(out.groupby("label")[col].apply(lambda s: f"{s.notna().sum()}/{len(s)} non-NaN"))


if __name__ == "__main__":
    main()
