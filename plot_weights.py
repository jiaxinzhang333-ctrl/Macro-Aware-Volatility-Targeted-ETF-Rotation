from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
import matplotlib.dates as mdates

ROOT = Path(__file__).resolve().parent
FIG_DIR = ROOT / "results/figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

COLORS = {
    "SPY": "#5686C5", "QQQ": "#71AFC4",
    "TQQQ": "#288B72", "UVXY": "#D16D78",
    "TECL": "#9275BC", "SPXL": "#B79A75",
    "SQQQ": "#D99AC4", "TECS": "#85909D",
    "BSV": "#D7B75E",
}

plt.rcParams.update({
    "font.size": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
})

# 1. Monthly average V0 ensemble weights
path = ROOT / "results/signals/v2_cpi_overlay_weights_history.csv"
weights = pd.read_csv(path, index_col=0, parse_dates=True)
weights = weights.apply(pd.to_numeric, errors="raise")
monthly = weights.resample("MS").mean()
monthly = monthly.loc[:, monthly.max() > 0]

fig, ax = plt.subplots(figsize=(13, 5.5))
ax.stackplot(
    monthly.index,
    *[monthly[c] for c in monthly.columns],
    labels=monthly.columns,
    colors=[COLORS.get(c, "#AAAAAA") for c in monthly.columns],
    alpha=0.9,
    linewidth=0,
)
ax.set_title("V2 + CPI Overlay | Monthly Average Allocation",
             fontsize=17, weight="bold", loc="left", pad=18)
ax.set_ylabel("Portfolio Weight")
ax.set_ylim(0, 1)
ax.yaxis.set_major_formatter(PercentFormatter(1))
ax.xaxis.set_major_locator(mdates.YearLocator(2))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
ax.grid(axis="y", alpha=0.15)
ax.set_axisbelow(True)
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12),
          ncol=5, frameon=False)
fig.tight_layout()
fig.savefig(FIG_DIR / "final_strategy_weights_monthly.png",
            dpi=200, bbox_inches="tight")
plt.close(fig)

# 2. Latest V2 + CPI target weights
path = ROOT / "results/forward/latest_target_weights.csv"
latest = pd.read_csv(path, index_col=0)
series = pd.to_numeric(latest.iloc[:, 0], errors="raise")
series = series[series > 0.0001].sort_values()

fig, ax = plt.subplots(figsize=(9, 3.8))
bars = ax.barh(
    series.index, series.values * 100,
    color=[COLORS.get(c, "#AAAAAA") for c in series.index],
    height=0.55,
)
ax.set_xlim(0, 105)
ax.set_xlabel("Target Allocation (%)")
ax.set_title("V2 + CPI Overlay | Latest Target Weights",
             fontsize=16, weight="bold", loc="left", pad=18)
ax.grid(axis="x", alpha=0.15)
ax.set_axisbelow(True)

for bar, value in zip(bars, series.values):
    ax.text(value * 100 + 1, bar.get_y() + bar.get_height()/2,
            f"{value:.1%}", va="center", fontsize=12)

fig.tight_layout()
fig.savefig(FIG_DIR / "latest_target_weights.png",
            dpi=200, bbox_inches="tight")
plt.close(fig)

print("Generated:")
print(" - results/figures/final_strategy_weights_monthly.png")
print(" - results/figures/latest_target_weights.png")
