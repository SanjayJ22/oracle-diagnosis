"""Clean, presentation-ready versions of the three trajectory plots: one manipulated-
venue/oracle line vs one reference line per class, minimal text, large fonts, one title
each. Reads the same cached CSVs as src/plot_trajectories.py but does not touch that
script's detailed analysis output (freshness panels, HMM discussion) -- those remain
for the written analysis; these three are standalone slide images.
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "processed" / "trajectories"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"

plt.rcParams.update({
    "font.size": 18,
    "axes.titlesize": 26,
    "axes.titleweight": "bold",
    "axes.labelsize": 20,
    "xtick.labelsize": 15,
    "ytick.labelsize": 15,
    "legend.fontsize": 17,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

MANIP_COLOR = "#c0392b"
REF_COLOR = "#7f8c8d"
ORACLE_COLOR = "#2b6cb0"
DEX_COLOR = "#e67e22"


def _legend_below(fig, ax, *axes_for_lines):
    lines, labels = [], []
    for a in axes_for_lines:
        l, lb = a.get_legend_handles_labels()
        lines += l
        labels += lb
    fig.subplots_adjust(bottom=0.32)
    fig.legend(lines, labels, loc="lower center", bbox_to_anchor=(0.5, 0.0),
               ncol=2, frameon=False)


def plot_manipulation():
    curve = pd.read_csv(DATA_DIR / "harvest_curve.csv", parse_dates=["timestamp"])
    eth = pd.read_csv(DATA_DIR / "harvest_eth.csv", parse_dates=["timestamp"])
    incident_ts = curve.loc[curve["block"] == 11_129_474, "timestamp"].iloc[0]

    fig, ax1 = plt.subplots(figsize=(12, 6.5))
    ax1.plot(curve["timestamp"], curve["ypool_ratio"], color=MANIP_COLOR, linewidth=3.5,
              label="Manipulated venue (Curve Y pool)")
    ax1.axvline(incident_ts, color="black", linestyle=":", linewidth=1.5, alpha=0.5)
    ax1.set_ylabel("pool ratio", color=MANIP_COLOR)
    ax1.tick_params(axis="y", labelcolor=MANIP_COLOR)

    ax2 = ax1.twinx()
    ax2.plot(eth["timestamp"], eth["answer"], color=REF_COLOR, linewidth=2.5,
              label="Unaffected reference (ETH/USD)")
    ax2.set_ylabel("ETH/USD ($)", color=REF_COLOR)
    ax2.tick_params(axis="y", labelcolor=REF_COLOR)
    ax2.spines["top"].set_visible(False)

    ax1.set_title("Manipulation: the move is localized to one venue")
    fig.autofmt_xdate()
    _legend_below(fig, ax1, ax1, ax2)

    out = REPORTS_DIR / "trajectory_manipulation_slide.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"saved {out}")


def plot_malfunction():
    chainlink = pd.read_csv(DATA_DIR / "steth_chainlink.csv", parse_dates=["timestamp"])
    dex = pd.read_csv(DATA_DIR / "steth_dex.csv", parse_dates=["timestamp"])

    fig, ax = plt.subplots(figsize=(12, 6.5))
    ax.plot(dex["timestamp"], dex["dex_price_stETH_per_ETH"], color=DEX_COLOR, linewidth=2,
             alpha=0.9, label="Real-time reference (DEX)")
    ax.step(chainlink["timestamp"], chainlink["answer"], where="post", color=ORACLE_COLOR,
             linewidth=3.5, label="Oracle (Chainlink, ~24h updates)")
    ax.scatter(chainlink["timestamp"], chainlink["answer"], color=ORACLE_COLOR, s=45, zorder=5)

    ax.set_ylabel("ETH per stETH")
    ax.set_title("Malfunction: the oracle lags, then jumps to catch up")
    fig.autofmt_xdate()
    _legend_below(fig, ax, ax)

    out = REPORTS_DIR / "trajectory_malfunction_slide.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"saved {out}")


def plot_volatility():
    chainlink = pd.read_csv(DATA_DIR / "aug2024_chainlink.csv", parse_dates=["timestamp"])
    cex = pd.read_csv(DATA_DIR / "aug2024_cex.csv", parse_dates=["timestamp"])

    fig, ax = plt.subplots(figsize=(12, 6.5))
    ax.plot(cex["timestamp"], cex["close"], color=REF_COLOR, linewidth=1.5, alpha=0.8,
             label="Real market (Binance ETH/USDT)")
    ax.plot(chainlink["timestamp"], chainlink["answer"], color=ORACLE_COLOR, linewidth=3,
             alpha=0.95, label="Oracle (Chainlink ETH/USD)")

    ax.set_ylabel("$ / ETH")
    ax.set_title("Volatility: oracle and market move together")
    fig.autofmt_xdate()
    _legend_below(fig, ax, ax)

    out = REPORTS_DIR / "trajectory_volatility_slide.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"saved {out}")


def main():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    plot_manipulation()
    plot_malfunction()
    plot_volatility()


if __name__ == "__main__":
    main()
