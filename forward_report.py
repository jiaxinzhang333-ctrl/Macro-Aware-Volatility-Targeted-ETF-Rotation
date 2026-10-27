"""Create a standalone HTML dashboard for US ETF forward simulation."""

from pathlib import Path
from io import BytesIO
import base64
import html

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "results/forward/forward_daily_equity.csv"
REPORT = ROOT / "results/Forward_Performance.html"


def chart(series, ylabel):
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(series.index, series.values, linewidth=2)
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=150)
    plt.close(fig)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def main():
    if not DATA.exists():
        raise FileNotFoundError("Run python3 run_forward.py --update-data first.")

    df = pd.read_csv(DATA, index_col=0, parse_dates=True).sort_index()
    if df.empty:
        raise ValueError("No forward observations.")

    equity = df["NormalizedEquity"].astype(float)
    drawdown = equity / equity.cummax().clip(lower=1.0) - 1.0
    daily_returns = df["AccountEquity"].astype(float).pct_change().dropna()

    total_return = equity.iloc[-1] - 1
    max_drawdown = drawdown.min()
    last_date = df.index[-1].strftime("%Y-%m-%d")
    start_date = "2026-10-01"
    observations = len(df)

    equity_image = chart(equity, "Normalized Equity")
    drawdown_image = chart(drawdown * 100, "Drawdown (%)")

    recent = df.tail(15).copy()
    recent.index = recent.index.strftime("%Y-%m-%d")
    recent["CumulativeReturn"] = recent["CumulativeReturn"].map(
        lambda v: f"{v:+.2%}"
    )
    recent["AccountEquity"] = recent["AccountEquity"].map(
        lambda v: f"${v:,.2f}"
    )
    recent = recent[["AccountEquity", "CumulativeReturn"]]
    recent.columns = ["Simulated Account Value", "Cumulative Return"]
    recent.index.name = "Date"

    trades_file = ROOT / "results/forward/forward_trades.csv"
    weights_file = ROOT / "results/forward/latest_target_weights.csv"

    trades = pd.read_csv(trades_file) if trades_file.exists() else pd.DataFrame()
    weights = pd.read_csv(weights_file) if weights_file.exists() else pd.DataFrame()

    trades_html = (
        trades.tail(20).to_html(index=False, border=0)
        if not trades.empty else "<p>No simulated trades recorded.</p>"
    )
    weights_html = (
        weights.to_html(index=False, border=0)
        if not weights.empty else "<p>No target weights available.</p>"
    )

    content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>US ETF Forward Performance</title>
<style>
body {{font-family:Arial,sans-serif;background:#f5f7fb;color:#162338;
max-width:1100px;margin:35px auto;padding:0 20px;}}
h1 {{margin-bottom:5px;}}
.subtitle {{color:#64748b;margin-bottom:25px;}}
.cards {{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:15px;}}
.card,.panel {{background:white;border-radius:12px;padding:20px;
box-shadow:0 2px 12px #0000000a;margin-bottom:20px;}}
.value {{font-size:26px;font-weight:bold;margin-top:10px;}}
.label {{color:#64748b;font-size:13px;}}
img {{max-width:100%;height:auto;}}
table {{border-collapse:collapse;width:100%;font-size:14px;}}
td,th {{padding:10px;border-bottom:1px solid #e2e8f0;text-align:right;}}
td:first-child,th:first-child {{text-align:left;}}
.note {{color:#64748b;font-size:13px;line-height:1.6;}}
</style>
</head>
<body>
<h1>US ETF Forward Performance</h1>
<div class="subtitle">V2 + CPI Overlay | Paper Simulation | {start_date} to {html.escape(last_date)}</div>
<div class="cards">
<div class="card"><div class="label">Cumulative Return</div>
<div class="value">{total_return:+.2%}</div></div>
<div class="card"><div class="label">Maximum Drawdown</div>
<div class="value">{max_drawdown:.2%}</div></div>
<div class="card"><div class="label">Latest Account Value</div>
<div class="value">${df["AccountEquity"].iloc[-1]:,.2f}</div></div>
<div class="card"><div class="label">Trading Observations</div>
<div class="value">{observations}</div></div>
</div>
<div class="panel"><h2>Normalized Equity Curve</h2>
<img src="data:image/png;base64,{equity_image}"></div>
<div class="panel"><h2>Forward Drawdown</h2>
<img src="data:image/png;base64,{drawdown_image}"></div>
<div class="panel"><h2>Recent Account History</h2>
{recent.to_html(classes="history", border=0)}
</div>
<div class="panel"><h2>Recent Simulated Trades</h2>
{trades_html}</div>
<div class="panel"><h2>Latest Target Weights</h2>
{weights_html}</div>
<div class="panel note">
<strong>Important:</strong> Simulated performance, not actual brokerage execution.
The account continues from the historical simulation; forward returns are
normalized relative to the last pre-October account value.
Trading costs follow the backtest engine assumptions.
The report covers the latest complete market date available in the local dataset.
CPI release inputs require separate freshness checks.
</div>
</body></html>"""

    REPORT.write_text(content, encoding="utf-8")
    print(f"Forward HTML report generated: {REPORT}")
    print(f"Period: {start_date} to {last_date}")
    print(f"Cumulative return: {total_return:+.2%}")
    print(f"Max drawdown: {max_drawdown:.2%}")


if __name__ == "__main__":
    main()
