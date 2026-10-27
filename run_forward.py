"""Forward simulation of the US V2 + CPI strategy."""

from pathlib import Path
import argparse
import pandas as pd
import portfolio_accounting as pa

ROOT = Path(__file__).resolve().parent
FORWARD_START = pd.Timestamp("2026-10-01")
HISTORICAL_START = pd.Timestamp("2012-08-01")
CAPITAL = 100000.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--update-data",
        action="store_true",
        help="Download fresh US ETF prices before forward tracking",
    )
    args = parser.parse_args()

    # Use a non-interactive plotting backend for automatic runs.
    import os
    os.environ["MPLBACKEND"] = "Agg"

    from cpi_check import check_cpi
    check_cpi()

    if args.update_data:
        print("Updating US ETF data...")
        updater = pa.load_definitions("01_data_update")
        updater["main"](download=True)

        # Rebuild signals from the updated ETF prices.
        from run_all import execute_notebook
        for name in [
            "02_parameter_ensemble",
            "05_risk_allocation",
            "06_bsv_volatility_targeting",
        ]:
            print(f"Rebuilding {name}...")
            execute_notebook(name)

    us = pa.load_us_market()
    timeline = us.closes.index[
        (us.closes.index >= HISTORICAL_START)
    ]

    weights = pa.us_strategy_weights("v2")
    cpi = pa.load_definitions("09_cpi_overlay")

    overlay_weights, close_events, events, hedge_rows = cpi["overlay_for"](
        us, weights
    )

    result = pa.run_sleeve(
        market=us,
        weights=overlay_weights,
        timeline=timeline,
        capital=CAPITAL,
        rebalance="daily",
        close_events=close_events,
    )

    equity = result["daily"].equity.sort_index()
    anchor = equity[equity.index < FORWARD_START]

    if anchor.empty:
        raise RuntimeError("No September 2026 account value available.")

    start_value = float(anchor.iloc[-1])
    forward = equity[equity.index >= FORWARD_START]

    if forward.empty:
        raise RuntimeError("No forward data available from 2026-10-01.")

    output = ROOT / "results" / "forward"
    output.mkdir(parents=True, exist_ok=True)

    table = pd.DataFrame({
        "AccountEquity": forward,
        "NormalizedEquity": forward / start_value,
        "CumulativeReturn": forward / start_value - 1,
    })
    table.index.name = "Date"
    table.to_csv(output / "forward_daily_equity.csv")

    # Save forward-period simulated trades.
    trades = result["trades"].copy()
    if not trades.empty:
        date_col = next(
            (c for c in trades.columns if "date" in c.lower()),
            None,
        )
        if date_col:
            trade_dates = pd.to_datetime(trades[date_col])
            trades = trades.loc[trade_dates >= FORWARD_START].copy()

    trades.to_csv(output / "forward_trades.csv", index=False)

    # Save latest strategy target weights.
    latest_weights = overlay_weights.loc[
        overlay_weights.index <= table.index[-1]
    ].iloc[-1]

    latest_weights.rename("TargetWeight").to_csv(
        output / "latest_target_weights.csv",
        header=True,
    )

    # Refresh portfolio allocation visualizations.
    import subprocess
    import sys
    subprocess.run(
        [sys.executable, str(ROOT / "plot_weights.py")],
        check=True,
        cwd=ROOT,
    )

    # Generate the HTML dashboard automatically.
    from forward_report import main as generate_report
    generate_report()

    # open_new_charts_after_run
    import subprocess
    import sys
    if sys.platform == "darwin":
        subprocess.run(
            ["open", str(ROOT / "results/figures/final_strategy_weights_monthly.png")],
            check=True,
        )
        subprocess.run(
            ["open", str(ROOT / "results/figures/latest_target_weights.png")],
            check=True,
        )

    latest = table.iloc[-1]

    print("\n=== Forward Performance ===")
    print(f"Start: {FORWARD_START.date()}")
    print(f"Latest available trading day: {table.index[-1].date()}")
    print(f"Starting account value: ${start_value:,.2f}")
    print(f"Latest account value: ${latest.AccountEquity:,.2f}")
    print(f"Cumulative return: {latest.CumulativeReturn:.2%}")
    print(f"Forward trading days: {len(table)}")
    print(f"CPI triggers (full history): {int(events['trigger'].sum())}")
    print(f"\nSaved: {output / 'forward_daily_equity.csv'}")


if __name__ == "__main__":
    main()
