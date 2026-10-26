"""Historical backtest of standalone US ETF strategies."""

from pathlib import Path
import pandas as pd
import portfolio_accounting as pa

ROOT = Path(__file__).resolve().parent

PERIODS = {
    "IS": ("2012-08-01", "2019-12-31"),
    "OOS": ("2020-01-01", "2026-09-30"),
    "OOS ex-2020": ("2021-01-01", "2026-09-30"),
}


def main():
    us = pa.load_us_market()

    start = pd.Timestamp("2012-08-01")
    end = pd.Timestamp("2026-09-30")
    timeline = us.closes.index[
        (us.closes.index >= start) &
        (us.closes.index <= end)
    ]

    output = ROOT / "results" / "tables"
    output.mkdir(parents=True, exist_ok=True)

    rows = []
    equity_curves = {}

    for strategy in ["v0", "v1", "v2"]:
        weights = pa.us_strategy_weights(strategy)

        result = pa.run_sleeve(
            market=us,
            weights=weights,
            timeline=timeline,
            capital=100000.0,
            rebalance="daily",
        )

        equity_curves[strategy.upper()] = result["daily"].equity

        for period, a, b in (
            (name, *dates) for name, dates in PERIODS.items()
        ):
            metrics = pa.performance(result["daily"].equity, a, b)
            rows.append({
                "Strategy": strategy.upper(),
                "Period": period,
                **metrics
            })

    # Final US strategy: V2 plus the CPI-triggered hedge.
    cpi = pa.load_definitions("09_cpi_overlay")
    w_v2 = pa.us_strategy_weights("v2")

    w_overlay, close_events, events, hedge_rows = cpi["overlay_for"](
        us, w_v2
    )

    final_result = pa.run_sleeve(
        market=us,
        weights=w_overlay,
        timeline=timeline,
        capital=100000.0,
        rebalance="daily",
        close_events=close_events,
    )

    equity_curves["V2 + CPI Overlay"] = final_result["daily"].equity

    for period, (a, b) in PERIODS.items():
        metrics = pa.performance(final_result["daily"].equity, a, b)
        rows.append({
            "Strategy": "V2 + CPI Overlay",
            "Period": period,
            **metrics,
        })

    print("CPI triggers:", int(events["trigger"].sum()))
    print("CPI hedge records:", len(hedge_rows))

    metrics_df = pd.DataFrame(rows)
    metrics_df.to_csv(output / "us_strategy_metrics.csv", index=False)

    equity_df = pd.DataFrame(equity_curves)
    equity_df.to_csv(output / "us_strategy_equity.csv")

    print(metrics_df.to_string(index=False))
    print("\nSaved US-only backtest results.")


if __name__ == "__main__":
    main()
