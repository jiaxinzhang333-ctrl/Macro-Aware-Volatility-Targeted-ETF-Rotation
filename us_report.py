"""Generate a standalone US ETF strategy performance report."""
from pathlib import Path
import html
import pandas as pd

ROOT = Path(__file__).resolve().parent
TABLES = ROOT / "results" / "tables"
OUTPUT = ROOT / "results" / "US_Strategy_Report.html"


def main():
    metrics = pd.read_csv(TABLES / "us_strategy_metrics.csv")
    equity = pd.read_csv(
        TABLES / "us_strategy_equity.csv",
        index_col=0,
        parse_dates=True,
    )

    if metrics.empty or equity.empty:
        raise ValueError("Backtest results are empty.")

    oos = metrics.loc[metrics["Period"] == "OOS"].copy()

    percent_cols = ["CAGR", "Vol", "MDD"]
    for col in percent_cols:
        oos[col] = oos[col].map(lambda x: f"{x:.2%}")

    for col in ["Sharpe", "Sortino", "Calmar"]:
        oos[col] = oos[col].map(lambda x: f"{x:.3f}")

    table = oos.to_html(index=False, escape=True)

    latest = equity.index.max().strftime("%Y-%m-%d")

    document = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>US ETF Rotation Strategy Report</title>
<style>
body {{
    font-family: system-ui, sans-serif;
    max-width: 1100px;
    margin: 45px auto;
    padding: 0 24px;
    color: #24364b;
}}
h1, h2 {{ color: #183b63; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #dbe2ea; padding: 12px; text-align: left; }}
th {{ background: #edf3f8; }}
.note {{ color: #64748b; }}
a {{ color: #2463a0; }}
</style>
</head>
<body>
<h1>Macro-Aware Volatility-Targeted ETF Rotation Strategy</h1>
<p>Standalone US ETF Strategy | Historical Backtest</p>

<h2>Out-of-Sample Performance</h2>
<p class="note">2020-01-01 to 2026-09-30</p>
{table}

<h2>Strategy Overview</h2>
<p><strong>V0:</strong> Parameter-ensemble ETF rotation.</p>
<p><strong>V1:</strong> 60-day inverse-volatility weighting.</p>
<p><strong>V2:</strong> 30% annualized volatility targeting with BSV.</p>
<p><strong>Final:</strong> V2 with a CPI-triggered tactical hedge.</p>

<h2>Data and Results</h2>
<p>Latest available equity observation: {html.escape(latest)}</p>
<p><a href="tables/us_strategy_metrics.csv">Download performance metrics</a></p>
<p><a href="tables/us_strategy_equity.csv">Download equity curves</a></p>

<p class="note">Historical simulation, not live broker performance.
Results depend on market data, execution assumptions and transaction costs.
The 30% target is not a guarantee of realized volatility.
CPI rule parameters may have been selected using historical observations.</p>
</body>
</html>"""

    OUTPUT.write_text(document, encoding="utf-8")
    print(f"Report generated: {OUTPUT}")


if __name__ == "__main__":
    main()
