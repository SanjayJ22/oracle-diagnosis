"""EXPERIMENTAL prototype only -- not wired into build_features.py, features.parquet,
or models.py. Does not touch the main pipeline in any way.

Computes two candidate trajectory-derived features (step-change count, deviation-
persistence duration) directly from the CSVs already cached by
src/temporal_trajectories.py, for the same 2 of its 3 representative incidents (no new
RPC calls, no new data). This exists purely to demonstrate feasibility for
reports/richer_features.md's proposal -- it is illustrative on n=2 incidents, not a
validated feature, and must not be read as evidence these features would help a
classifier (n=2 says nothing about that).
"""

from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "processed" / "trajectories"


def count_step_changes(series: pd.Series, rel_threshold: float = 0.005) -> int:
    """Count consecutive-sample jumps exceeding `rel_threshold` relative change.
    A crude proxy for 'number of distinct step-changes' -- a real version would use
    a proper change-point detector (e.g. ruptures/PELT), not a fixed threshold."""
    rel_diff = series.diff().abs() / series.shift(1).abs()
    return int((rel_diff > rel_threshold).sum())


def deviation_persistence_seconds(times: pd.Series, deviation: pd.Series, threshold: float) -> float:
    """Total wall-clock time the (absolute) deviation stays above `threshold`,
    summed across all excursions in the window -- a crude proxy for 'how long has
    this been wrong', distinct from heartbeat_elapsed (which only measures time since
    the LAST update, not how long a deviation has persisted across multiple updates)."""
    above = deviation.abs() > threshold
    if not above.any():
        return 0.0
    t = times.astype("int64") // 10**9  # unix seconds
    dt = t.diff().fillna(0)
    return float(dt[above].sum())


def prototype_harvest_step_changes():
    df = pd.read_csv(DATA_DIR / "harvest_curve.csv", parse_dates=["timestamp"])
    n_steps = count_step_changes(df["ypool_ratio"])
    print(f"Harvest Finance (manipulation) -- Curve Y-pool yUSDC/yUSDT ratio, {len(df)} samples "
          f"over {(df['timestamp'].iloc[-1] - df['timestamp'].iloc[0])}:")
    print(f"  ratio range: {df['ypool_ratio'].min():.4f} - {df['ypool_ratio'].max():.4f}")
    print(f"  step_change_count (>0.5% consecutive jump): {n_steps}")
    print("  NOTE: temporal_trajectories.md's write-up describes 5 step-changes by manual "
          "inspection of the plot; this threshold-based counter finds 11 on the same series. "
          "They disagree because a fixed relative-jump threshold also fires on noisy small "
          "wiggles the manual read collapsed into one 'plateau' -- illustrates exactly why "
          "richer_features.md flags this as needing a real change-point method (e.g. "
          "ruptures/PELT), not this placeholder threshold rule.")
    return n_steps


def prototype_steth_deviation_persistence():
    chainlink = pd.read_csv(DATA_DIR / "steth_chainlink.csv", parse_dates=["timestamp"])
    dex = pd.read_csv(DATA_DIR / "steth_dex.csv", parse_dates=["timestamp"])

    merged = pd.merge_asof(
        dex.sort_values("timestamp"), chainlink.sort_values("timestamp")[["timestamp", "answer"]],
        on="timestamp", direction="backward",
    ).dropna(subset=["answer"])
    merged["deviation"] = merged["dex_price_stETH_per_ETH"] - merged["answer"]

    print(f"\nstETH/ETH (malfunction) -- Chainlink vs wstETH/WETH-derived DEX price, "
          f"{len(merged)} aligned samples over "
          f"{(merged['timestamp'].iloc[-1] - merged['timestamp'].iloc[0])}:")
    print(f"  deviation range: {merged['deviation'].min():.5f} to {merged['deviation'].max():.5f} "
          f"(ETH-denominated)")
    for threshold in (0.001, 0.002, 0.005):
        secs = deviation_persistence_seconds(merged["timestamp"], merged["deviation"], threshold)
        print(f"  deviation_persistence_seconds (|dev| > {threshold}): {secs:,.0f}s "
              f"({secs/3600:.1f}h of the {(merged['timestamp'].iloc[-1]-merged['timestamp'].iloc[0]).total_seconds()/3600:.1f}h window)")


if __name__ == "__main__":
    prototype_harvest_step_changes()
    prototype_steth_deviation_persistence()
