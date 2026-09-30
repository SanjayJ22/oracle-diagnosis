"""Plot the three trajectory analyses and attempt a per-trajectory HMM regime fit.

Reads data/processed/trajectories/*.csv (written by temporal_trajectories.py).
Writes reports/trajectory_manipulation.png, trajectory_malfunction.png,
trajectory_volatility.png, and prints an explicit state-transition description plus
an honest report on whether a 2-state Gaussian HMM converges sensibly on each
trajectory's key signal.

This is a standalone analysis -- it does not touch features.parquet or models.py.
"""

import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "processed" / "trajectories"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


def load_all():
    return {
        "harvest_curve": pd.read_csv(DATA_DIR / "harvest_curve.csv", parse_dates=["timestamp"]),
        "harvest_eth": pd.read_csv(DATA_DIR / "harvest_eth.csv", parse_dates=["timestamp"]),
        "steth_chainlink": pd.read_csv(DATA_DIR / "steth_chainlink.csv", parse_dates=["timestamp"]),
        "steth_dex": pd.read_csv(DATA_DIR / "steth_dex.csv", parse_dates=["timestamp"]),
        "aug2024_chainlink": pd.read_csv(DATA_DIR / "aug2024_chainlink.csv", parse_dates=["timestamp"]),
        "aug2024_cex": pd.read_csv(DATA_DIR / "aug2024_cex.csv", parse_dates=["timestamp"]),
        "aug2024_dex": pd.read_csv(DATA_DIR / "aug2024_dex.csv", parse_dates=["timestamp"]),
    }


def try_hmm(series: np.ndarray, label: str, n_states: int = 2):
    """Attempt a Gaussian HMM fit. Returns (state_sequence or None, report string)."""
    series = series[~np.isnan(series)]
    if len(series) < 10:
        return None, f"  HMM not attempted for {label}: only {len(series)} valid points (too short)."
    try:
        from hmmlearn.hmm import GaussianHMM
        X = series.reshape(-1, 1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = GaussianHMM(n_components=n_states, covariance_type="diag", n_iter=200, random_state=0)
            model.fit(X)
            states = model.predict(X)
        means = model.means_.flatten()
        variances = model.covars_.flatten()
        n_switches = int(np.sum(np.diff(states) != 0))
        mean_gap = abs(means[0] - means[1])
        pooled_std = np.sqrt(np.mean(variances))
        separation = mean_gap / pooled_std if pooled_std > 0 else 0.0
        if not model.monitor_.converged:
            return None, f"  HMM did NOT converge for {label} ({len(series)} points) -- not using it; falling back to explicit description."
        if np.any(variances < 1e-12) or len(set(states)) < n_states:
            return None, (f"  HMM converged but degenerate for {label} (a state collapsed to near-zero "
                           f"variance, or one state never used) -- {len(series)} points is too short to "
                           f"trust this fit; falling back to explicit description.")
        if n_switches > len(series) / 4:
            return None, (f"  HMM technically converged for {label} but is NOT a meaningful 2-state fit: "
                           f"{n_switches} switches across only {len(series)} points (state means "
                           f"{means.round(6).tolist()} are only {separation:.2f} pooled-std apart) -- it's "
                           f"flip-flopping on noise, not identifying a persistent regime change. Falling "
                           f"back to explicit description rather than reporting this as a real finding.")
        if separation < 1.0:
            return None, (f"  HMM converged for {label} without excessive switching ({n_switches} switches, "
                           f"{len(series)} points), but the two state means {means.round(6).tolist()} are "
                           f"only {separation:.2f} pooled-std apart -- not practically distinguishable. This "
                           f"reads as 'no real 2-state structure', which is itself informative: falling back "
                           f"to explicit description rather than reporting two indistinguishable states as "
                           f"a finding.")
        report = (f"  HMM fit on {label} ({len(series)} points): state means={means.round(5).tolist()}, "
                  f"{n_switches} state switch(es) detected, separation={separation:.2f} pooled-std.")
        return states, report
    except Exception as e:
        return None, f"  HMM fit FAILED for {label}: {str(e)[:150]}"


def plot_manipulation(data):
    curve, eth = data["harvest_curve"], data["harvest_eth"]
    incident_row = curve[curve["block"] == 11_129_474].iloc[0]
    incident_ts = incident_row["timestamp"]

    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
    axes[0].plot(curve["timestamp"], curve["ypool_ratio"], "o-", color="crimson", markersize=3, label="Curve Y pool yUSDC/yUSDT ratio")
    axes[0].scatter([incident_ts], [incident_row["ypool_ratio"]], color="black", s=60, zorder=6, label="anchored incident block")
    axes[0].set_ylabel("implied ratio")
    axes[0].set_title("Harvest Finance (manipulation) -- the manipulated venue (never near a 1.0 peg in this window --\nthe yToken wrapper's own exchange rate dominates; watch the STEP CHANGES, not the level)")
    axes[0].legend(loc="best", fontsize=8)

    axes[1].plot(eth["timestamp"], eth["answer"], "o-", color="steelblue", markersize=3, label="ETH/USD (unrelated venue)")
    axes[1].set_ylabel("ETH/USD ($)")
    axes[1].set_title("An unaffected venue during the same window")
    axes[1].legend(loc="best", fontsize=8)

    axes[2].plot(eth["timestamp"], eth["gap_seconds"], "o-", color="seagreen", markersize=3, label="ETH/USD update gap (s)")
    axes[2].set_ylabel("seconds")
    axes[2].set_title("Oracle freshness: the reference oracle kept updating normally throughout")
    axes[2].legend(loc="best", fontsize=8)
    axes[2].set_xlabel("time (UTC)")

    for ax in axes:
        ax.axvline(incident_ts, color="black", linestyle=":", linewidth=1)
    fig.tight_layout()
    fig.savefig(REPORTS_DIR / "trajectory_manipulation.png", dpi=130)
    plt.close(fig)
    print(f"  saved {REPORTS_DIR / 'trajectory_manipulation.png'}")


def plot_malfunction(data):
    chainlink, dex = data["steth_chainlink"], data["steth_dex"]

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    axes[0].plot(dex["timestamp"], dex["dex_price_stETH_per_ETH"], "-", color="darkorange", linewidth=1, alpha=0.8,
                 label="DEX-implied stETH/ETH (wstETH/WETH pool, adjusted for wstETH's own accrual vs stETH)")
    axes[0].step(chainlink["timestamp"], chainlink["answer"], where="post", color="steelblue", linewidth=2, label="Chainlink STETH/ETH (updates ~1x/24h)")
    axes[0].scatter(chainlink["timestamp"], chainlink["answer"], color="steelblue", s=25, zorder=5)
    axes[0].set_ylabel("ETH per stETH")
    axes[0].set_title("stETH/ETH (malfunction) -- oracle lags the continuously-moving DEX price, then jumps on update")
    axes[0].legend(loc="best", fontsize=8)

    axes[1].bar(chainlink["timestamp"], chainlink["gap_seconds"] / 3600, width=0.3, color="seagreen", label="gap since last update (hours)")
    axes[1].axhline(24, color="gray", linestyle="--", linewidth=1, label="24h")
    axes[1].set_ylabel("hours")
    axes[1].set_title("Oracle freshness: the ~24h heartbeat, visible directly")
    axes[1].legend(loc="best", fontsize=8)
    axes[1].set_xlabel("time (UTC)")

    fig.tight_layout()
    fig.savefig(REPORTS_DIR / "trajectory_malfunction.png", dpi=130)
    plt.close(fig)
    print(f"  saved {REPORTS_DIR / 'trajectory_malfunction.png'}")


def plot_volatility(data):
    chainlink, cex, dex = data["aug2024_chainlink"], data["aug2024_cex"], data["aug2024_dex"]
    incident_ts = pd.Timestamp("2024-08-05 06:24:59", tz="UTC")

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    axes[0].plot(cex["timestamp"], cex["close"], "-", color="gray", linewidth=1, alpha=0.7, label="Binance.US ETHUSDT (1-min)")
    axes[0].plot(dex["timestamp"], dex["dex_price"], "o-", color="darkorange", markersize=3, alpha=0.8, label="WETH/USDC Uniswap V3 (implied)")
    axes[0].plot(chainlink["timestamp"], chainlink["answer"], "o-", color="steelblue", markersize=2, alpha=0.9, label="Chainlink ETH/USD")
    axes[0].axvline(incident_ts, color="black", linestyle=":", linewidth=1)
    axes[0].set_ylabel("$/ETH")
    axes[0].set_title("Aug 5 2024 carry-trade unwind (volatility) -- all three venues move together")
    axes[0].legend(loc="best", fontsize=8)

    axes[1].plot(chainlink["timestamp"], chainlink["gap_seconds"], "-", color="seagreen", linewidth=1, label="Chainlink update gap (s)")
    axes[1].set_ylabel("seconds")
    axes[1].set_title("Oracle freshness: rapid, frequent updates throughout the crash")
    axes[1].legend(loc="best", fontsize=8)
    axes[1].set_xlabel("time (UTC)")

    fig.tight_layout()
    fig.savefig(REPORTS_DIR / "trajectory_volatility.png", dpi=130)
    plt.close(fig)
    print(f"  saved {REPORTS_DIR / 'trajectory_volatility.png'}")


def main():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    data = load_all()

    print("=" * 78)
    print("TRAJECTORY PLOTS")
    print("=" * 78)
    plot_manipulation(data)
    plot_malfunction(data)
    plot_volatility(data)

    print("\n" + "=" * 78)
    print("EXPLICIT STATE-TRANSITION DESCRIPTIONS")
    print("=" * 78)

    curve = data["harvest_curve"].dropna(subset=["ypool_ratio"]).reset_index(drop=True)
    print("\nHarvest Finance (manipulation):")
    print("  NOTE: the ratio is never near a 1.0 peg in this window at all (yToken wrapper drift means")
    print("  ~1.3 is 'normal' here) -- so the signal is the STEP CHANGES between levels, not distance")
    print("  from any fixed reference. Detected via >1% consecutive-sample jumps:")

    pct_change = curve["ypool_ratio"].pct_change().abs()
    step_idx = curve.index[pct_change > 0.01].tolist()
    phase_starts = [0] + step_idx
    for i, start in enumerate(phase_starts):
        end = phase_starts[i + 1] - 1 if i + 1 < len(phase_starts) else len(curve) - 1
        level = curve["ypool_ratio"].iloc[start:end + 1].mean()
        t0, t1 = curve["timestamp"].iloc[start], curve["timestamp"].iloc[end]
        marker = "  <-- anchored incident block in this phase" if (curve["block"].iloc[start:end+1] == 11_129_474).any() else ""
        print(f"    phase {i+1}: {t0.strftime('%H:%M:%S')} -> {t1.strftime('%H:%M:%S')}  ratio~{level:.4f}{marker}")
    print(f"  {len(step_idx)} step-change(s) detected over ~2 hours -- consistent with the post-mortem's own")
    print("  description of a REPEATED attack (multiple manipulate-then-arbitrage cycles), not one atomic tx.")
    print("  Meanwhile ETH/USD (unrelated venue) shows no corresponding move at all in the same window.")

    steth = data["steth_chainlink"]
    print("\nstETH/ETH (malfunction):")
    print(f"  FRESH  (at each Chainlink update): oracle price briefly matches the DEX price")
    print(f"  STALE  (for ~{steth['gap_seconds'].median()/3600:.0f}h after each update, most of the time):")
    print(f"         oracle price frozen while DEX price (real market) keeps moving")
    print(f"  UPDATE (next Chainlink round): oracle jumps to catch up with wherever the DEX price now is")
    print(f"  This FRESH->STALE->UPDATE cycle repeats on a ~24h period throughout the depeg.")

    aug = data["aug2024_chainlink"]
    print("\nAug 5 2024 crash (volatility):")
    print(f"  Single continuous regime: price falls smoothly, oracle updates every "
          f"{aug['gap_seconds'].median():.0f}s median throughout (vs {steth['gap_seconds'].median():.0f}s for stETH)")
    print(f"  No lag, no localized spike-and-revert -- one sustained market-wide move, tracked continuously.")

    print("\n" + "=" * 78)
    print("ATTEMPTED HMM REGIME FIT (2-state Gaussian, per trajectory)")
    print("=" * 78)

    _, rep = try_hmm(curve["ypool_ratio"].values, "Harvest Y-pool ratio")
    print(rep)

    dex_steth = data["steth_dex"].dropna(subset=["dex_price_stETH_per_ETH"]).copy()
    merged = pd.merge_asof(dex_steth.sort_values("timestamp"), steth[["timestamp", "answer"]].sort_values("timestamp"),
                            on="timestamp", direction="backward")
    spread = (merged["dex_price_stETH_per_ETH"] - merged["answer"]).values
    _, rep = try_hmm(spread, "stETH DEX-vs-oracle spread")
    print(rep)

    cex_returns = np.log(data["aug2024_cex"]["close"]).diff().dropna().values
    _, rep = try_hmm(cex_returns, "Aug 2024 ETH/USDT 1-min log returns")
    print(rep)


if __name__ == "__main__":
    main()
