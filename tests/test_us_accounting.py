import unittest
import numpy as np
import pandas as pd

import portfolio_accounting as pa


class TestUSAccounting(unittest.TestCase):

    def setUp(self):
        self.dates = pd.bdate_range("2024-01-02", periods=5)
        self.opens = pd.DataFrame({
            "TQQQ": [100., 102., 104., 106., 108.],
            "BSV": [80., 80., 80., 80., 80.],
        }, index=self.dates)
        self.closes = self.opens.copy()

        self.market = pa.Market(
            "US", "USD",
            self.opens,
            self.closes,
            pd.Series(1.0, index=self.dates)
        )

        self.weights = pd.DataFrame({
            "TQQQ": [1., 1., 0., 0., 0.],
            "BSV": [0., 0., 1., 1., 1.],
        }, index=self.dates)

    def test_initial_funding(self):
        result = pa.run_sleeve(
            self.market, self.weights,
            self.dates, 100000.
        )
        self.assertAlmostEqual(
            result["daily"].equity.iloc[0], 100000.
        )

    def test_trade_uses_prior_signal(self):
        result = pa.run_sleeve(
            self.market, self.weights,
            self.dates, 100000.
        )
        trades = result["trades"]
        self.assertFalse(trades.empty)
        self.assertTrue(
            (trades.signal_date < trades.exec_date).all()
        )

    def test_missing_open_blocks_trade(self):
        market = pa.Market(
            "US", "USD",
            self.opens.copy(),
            self.closes.copy(),
            pd.Series(1.0, index=self.dates)
        )
        market.opens.loc[self.dates[2], "TQQQ"] = np.nan

        result = pa.run_sleeve(
            market, self.weights,
            self.dates, 100000.
        )
        self.assertFalse(
            (result["trades"].exec_date == self.dates[2]).any()
        )

    def test_transaction_cost_recorded(self):
        result = pa.run_sleeve(
            self.market, self.weights,
            self.dates, 100000.
        )
        self.assertGreater(
            result["trades"].cost_usd.sum(), 0
        )


    def test_cpi_close_event(self):
        # Buy TQQQ first, then switch to BSV at the specified close.
        close_date = self.dates[3]
        event_weights = [0.0, 1.0]

        result = pa.run_sleeve(
            self.market,
            self.weights,
            self.dates,
            100000.0,
            close_events={
                close_date: (self.dates[2], event_weights)
            },
        )

        trades = result["trades"]

        # The close event must be recorded on its designated date.
        event_trades = trades.loc[
            (trades.exec_date == close_date) &
            (trades.signal_date == self.dates[2])
        ]

        self.assertFalse(event_trades.empty)

        # Final holdings should be concentrated in BSV.
        last = result["daily"].iloc[-1]
        self.assertGreater(last["BSV_value"], 0)
        self.assertAlmostEqual(last["TQQQ_shares"], 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
