"""Standalone US ETF accounting and execution engine.

Trades use prior-known signals and valid source opening prices.
Transaction costs and CPI close-exit events are accounted for.
"""
from dataclasses import dataclass
from pathlib import Path
import contextlib
import io
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent


def load_definitions(stem):
    path = next((ROOT / 'pipeline').rglob(stem + '.ipynb'))
    namespace = {'__name__': 'pipeline_module'}
    with contextlib.redirect_stdout(io.StringIO()):
        for cell in json.loads(path.read_text(encoding='utf-8'))['cells']:
            if cell['cell_type'] == 'code' and 'pipeline-entry' not in cell.get('metadata', {}).get('tags', []):
                exec(compile(''.join(cell['source']), str(path), 'exec'), namespace)
    return namespace


ENGINE = load_definitions('00_engine')
INITIAL_SG_SHARE = 0.10
# Historical IS/OOS are reporting windows on one continuous account.
HISTORICAL_START = ENGINE['IS_START']
# October tracking is a separately funded experiment, not historical continuation.
LIVE_START = '2026-10-01'
LIVE_END = '2026-10-20'
LIVE_CAPITAL = 100000.0
PERIODS = [('IS', ENGINE['IS_START'], ENGINE['IS_END']),
           ('OOS', ENGINE['OOS_START'], ENGINE['OOS_END']),
           ('OOS ex-2020', '2021-01-01', ENGINE['OOS_END'])]


@dataclass
class Market:
    name: str
    currency: str
    opens: pd.DataFrame
    closes: pd.DataFrame
    fx: pd.Series  # local currency units per USD; USD sleeve uses ones


def _check_dates(frame, label):
    if frame.empty or frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError(f'{label}: expected nonempty, unique, ascending dates.')





def load_us_market(csv_path=None):
    """Load US ETF adjusted market prices."""
    opens, _, _, closes = ENGINE['prep'](csv_path)
    return Market(
        name='US',
        currency='USD',
        opens=opens,
        closes=closes,
        fx=pd.Series(1.0, index=closes.index),
    )


def read_weights(filename, columns):
    path = ROOT / 'results/signals' / filename
    frame = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
    _check_dates(frame, filename)
    if not set(columns).issubset(frame.columns):
        raise ValueError(f'{filename}: missing weight columns.')
    frame = frame.loc[:, columns].astype(float)
    # Warmup rows can be absent, but exported signal rows must be complete.
    if not np.isfinite(frame.to_numpy()).all() or (frame < -1e-10).any().any() or (frame.sum(axis=1) > 1 + 1e-8).any():
        raise ValueError(f'{filename}: invalid or incomplete target weights.')
    return frame





def us_strategy_weights(strategy='v2'):
    """Load US-only V0, V1 or V2 target weights."""
    files = {
        'v0': 'ensemble_weights_history.csv',
        'v1': 'risk_adjusted_weights.csv',
        'v2': 'v2_weights_history.csv',
    }
    if strategy not in files:
        raise ValueError(f"Unknown US strategy: {strategy}")

    filename = files[strategy]
    exported = pd.read_csv(
        ROOT / 'results/signals' / filename, nrows=1
    ).columns[1:]

    names = [ticker for ticker in ENGINE['TICKS'] if ticker in exported]

    if not names:
        raise ValueError(f"No US ETF columns found in {filename}")

    return read_weights(filename, names)


def _asof(series, date, strict=False):
    pos = series.index.searchsorted(pd.Timestamp(date), side='left' if strict else 'right') - 1
    if pos < 0:
        raise ValueError(f'No prior observation available at {date}.')
    return series.index[pos], float(series.iloc[pos])


def common_timeline(markets, start, end=None):
    dates = markets[0].closes.index
    for market in markets[1:]:
        dates = dates.union(market.closes.dropna(how='all').index)
    dates = dates.sort_values()
    start = pd.Timestamp(start)
    end = pd.Timestamp(end) if end is not None else dates.max()
    preceding = dates[dates < start]
    if not len(preceding) or not ((dates >= start) & (dates <= end)).any():
        raise ValueError('Need a pre-start valuation date and at least one tracking date.')
    return dates[(dates >= preceding[-1]) & (dates <= end)]


TRADE_COLUMNS = ['exec_date', 'signal_date', 'ticker', 'sleeve', 'side', 'shares',
                 'price_local', 'price_usd', 'currency', 'notional_local', 'notional_usd',
                 'cost_local', 'cost_usd', 'cost_bps', 'weight_before', 'weight_after',
                 'fx_reference', 'fx_reference_date', 'execution_quote_date', 'note']


class _SleeveRunner:
    """One sleeve's ledger, advanced one date at a time (same maths as before).

    `step(i, d, cash_adjust)` optionally adds a cross-sleeve transfer (local
    currency) to cash immediately before that date's rebalance.

    `close_events` (optional) maps a date to (signal_date, target weights). On
    that date, after the normal opening rebalance, the sleeve is rebalanced once
    more at the SOURCE CLOSING price to the given weights, with fees on the actual
    notional. Used only for the CPI hedge exit; without it behaviour is unchanged.
    """

    def __init__(self, market, weights, timeline, capital, rebalance, close_events=None):
        if rebalance not in {'daily', 'on_change', 'buy_hold'}:
            raise ValueError('Unknown rebalance mode.')
        self.close_events = {pd.Timestamp(k): v for k, v in (close_events or {}).items()}
        _check_dates(weights, 'Weights')
        names = list(weights.columns)
        if not set(names).issubset(market.opens.columns):
            raise ValueError('Weight columns must have market prices.')
        if capital <= 0:
            raise ValueError('Capital must be positive.')
        self.market, self.weights, self.timeline = market, weights, timeline
        self.names, self.capital, self.rebalance = names, capital, rebalance
        fx_date, funding_fx = _asof(market.fx, timeline[0])
        self.funding_fx, self.funding_fx_date = funding_fx, fx_date
        self.cash = capital * funding_fx
        self.qty = np.zeros(len(names))
        self.rates = np.array([ENGINE['ONE_WAY_BPS'][t] for t in names]) / 1e4
        self.previous_executed = None
        closes = market.closes[names].where(lambda x: x > 0)
        self.marks = closes.reindex(closes.index.union(timeline)).sort_index().ffill().reindex(timeline)
        if self.marks.isna().any().any():
            raise ValueError(f'{market.name}: missing initial valuation price.')
        price_dates = pd.DataFrame(index=closes.index, columns=names)
        for t in names:
            price_dates[t] = pd.Series(closes.index, index=closes.index).where(closes[t].notna())
        self.price_dates = price_dates.reindex(price_dates.index.union(timeline)).sort_index().ffill().reindex(timeline)
        self.rows, self.trades = [], []
        self.epsilon = capital * 1e-12

    def _open_prices(self, d):
        if d not in self.market.opens.index:
            return None
        px = self.market.opens.loc[d, self.names].to_numpy(float)
        return px if (np.isfinite(px).all() and (px > 0).all()) else None

    def ready(self, i, d):
        """True when a trade (and therefore a transfer) can happen on d."""
        if i == 0 or self._open_prices(d) is None:
            return False
        return self.weights.index.searchsorted(d, side='left') - 1 >= 0

    def open_value(self, d):
        """Local-currency account value at the source opening of d."""
        px = self._open_prices(d)
        return None if px is None else float(self.cash + (self.qty * px).sum())

    def step(self, i, d, cash_adjust=0.0):
        market, names, weights = self.market, self.names, self.weights
        total_cost_usd = turnover = notional_usd = 0.0
        signal_date = pd.NaT
        px_all = self._open_prices(d) if i > 0 else None
        if i == 0:
            status = 'Initial funding; no trade'
        elif d not in market.opens.index:
            status = 'No source session; holdings unchanged; carried valuation'
        else:
            px = market.opens.loc[d, names].to_numpy(float)
            valid_open = px_all is not None
            pos = weights.index.searchsorted(d, side='left') - 1
            if not valid_open:
                status = 'Incomplete opening quote; no trade; source date shown'
            elif pos < 0:
                status = 'No signal known before this session; no trade'
            else:
                signal_date = weights.index[pos]
                w = weights.iloc[pos].to_numpy(float)
                if not np.isfinite(w).all() or (w < -1e-10).any() or w.sum() > 1 + 1e-8:
                    raise ValueError(f'{market.name}: invalid signal at {signal_date}.')
                transfer = abs(cash_adjust) > 0
                execute = transfer or self.previous_executed is None or self.rebalance == 'daily' or (
                    self.rebalance == 'on_change' and not np.allclose(w, self.previous_executed, rtol=0, atol=1e-12))
                if not execute:
                    status = 'Hold; no target-triggered trade'
                else:
                    ref_date, ref_fx = _asof(market.fx, d, strict=True)
                    self.cash += cash_adjust  # cross-sleeve transfer, settled before rebalancing
                    current = self.qty * px
                    value = self.cash + current.sum()
                    delta, costs = ENGINE['rebalance_exact'](value, current, w, self.rates)
                    target = current + delta
                    self.qty = target / px
                    self.cash = float(value - target.sum() - costs.sum())
                    if self.cash < -max(self.epsilon, 1e-8):
                        raise AssertionError('A sleeve cannot spend another sleeve\'s cash.')
                    self.cash = max(self.cash, 0.0)
                    for j in np.flatnonzero(np.abs(delta) > self.epsilon):
                        self.trades.append(dict(exec_date=d, signal_date=signal_date, ticker=names[j],
                            sleeve=market.name, side='BUY' if delta[j] > 0 else 'SELL',
                            shares=abs(delta[j]) / px[j], price_local=px[j], price_usd=px[j] / ref_fx,
                            currency=market.currency, notional_local=abs(delta[j]), notional_usd=abs(delta[j]) / ref_fx,
                            cost_local=costs[j], cost_usd=costs[j] / ref_fx, cost_bps=self.rates[j] * 1e4,
                            weight_before=current[j] / value, weight_after=w[j], fx_reference=ref_fx,
                            fx_reference_date=ref_date, execution_quote_date=d,
                            note='SGD trade; USD amounts use prior FX for reporting only' if market.currency=='SGD' else ''))
                    total_cost_usd = costs.sum() / ref_fx
                    notional_usd = np.abs(delta).sum() / ref_fx
                    turnover = np.abs(delta).sum() / value
                    self.previous_executed = w.copy()
                    status = 'Rebalanced at source opening' if notional_usd > self.epsilon else 'At target; no material trade'
                    if transfer:
                        status += '; incl. cross-sleeve transfer'
        if d in self.close_events and i > 0:
            event_signal, event_w = self.close_events[d]
            event_w = np.asarray(event_w, float)
            close_ok = d in market.closes.index
            if close_ok:
                cpx = market.closes.loc[d, names].to_numpy(float)
                close_ok = bool(np.isfinite(cpx).all() and (cpx > 0).all())
            if not close_ok:
                status += '; close exit skipped (no source closing quote)'
            else:
                if not np.isfinite(event_w).all() or (event_w < -1e-10).any() or event_w.sum() > 1 + 1e-8:
                    raise ValueError(f'{market.name}: invalid close-event weights on {d}.')
                ref_date, ref_fx = _asof(market.fx, d, strict=True)
                current = self.qty * cpx
                value = self.cash + current.sum()
                delta, costs = ENGINE['rebalance_exact'](value, current, event_w, self.rates)
                target = current + delta
                self.qty = target / cpx
                self.cash = max(float(value - target.sum() - costs.sum()), 0.0)
                for j in np.flatnonzero(np.abs(delta) > self.epsilon):
                    self.trades.append(dict(exec_date=d, signal_date=event_signal, ticker=names[j],
                        sleeve=market.name, side='BUY' if delta[j] > 0 else 'SELL',
                        shares=abs(delta[j]) / cpx[j], price_local=cpx[j], price_usd=cpx[j] / ref_fx,
                        currency=market.currency, notional_local=abs(delta[j]), notional_usd=abs(delta[j]) / ref_fx,
                        cost_local=costs[j], cost_usd=costs[j] / ref_fx, cost_bps=self.rates[j] * 1e4,
                        weight_before=current[j] / value, weight_after=event_w[j], fx_reference=ref_fx,
                        fx_reference_date=ref_date, execution_quote_date=d,
                        note='CPI hedge exit at source closing price'))
                total_cost_usd += costs.sum() / ref_fx
                notional_usd += np.abs(delta).sum() / ref_fx
                turnover += np.abs(delta).sum() / value
                self.previous_executed = event_w.copy()
                status += '; CPI hedge exit at close'
        mark_fx_date, mark_fx = _asof(market.fx, d)
        values = self.qty * self.marks.loc[d].to_numpy(float)
        nav_local = self.cash + values.sum()
        quote_date = min(pd.Timestamp(x) for x in self.price_dates.loc[d])
        row = dict(date=d, equity=nav_local / mark_fx, cash=self.cash / mark_fx, cash_local=self.cash,
                   equity_local=nav_local, quote_date=quote_date, fx=mark_fx, fx_date=mark_fx_date,
                   status=status, turnover=turnover, cost_usd=total_cost_usd,
                   traded_notional_usd=notional_usd, signal_date=signal_date)
        for j, t in enumerate(names):
            row[t+'_shares'] = self.qty[j]
            row[t+'_value'] = values[j] / mark_fx
            row[t+'_pct'] = values[j] / nav_local
            row[t+'_price_date'] = self.price_dates.loc[d, t]
        self.rows.append(row)
        return row['equity']

    def result(self):
        daily = pd.DataFrame(self.rows).set_index('date')
        trade_frame = pd.DataFrame(self.trades, columns=TRADE_COLUMNS)
        return {'daily': daily, 'trades': trade_frame, 'market': self.market, 'weights': self.weights,
                'capital': self.capital, 'funding_fx': self.funding_fx, 'funding_fx_date': self.funding_fx_date}


def run_sleeve(market, weights, timeline, capital, rebalance='daily', close_events=None):
    """Self-financing local-currency ledger; only genuine source openings can trade.

    A missing opening blocks sleeve rebalancing for that date. Latest prior target
    replaces any older unexecuted target. A single sleeve never transfers cash;
    the account is self-financing and does not transfer between markets.
    """
    runner = _SleeveRunner(market, weights, timeline, capital, rebalance, close_events)
    for i, d in enumerate(timeline):
        runner.step(i, d)
    return runner.result()


TRANSFER_COLUMNS = ['exec_date', 'direction', 'usd_to_sg', 'sgd_to_sg', 'fx_reference', 'fx_cost_usd',
                    'sg_share_flagged', 'flag_date', 'sg_share_at_open_before', 'target_sg_share']






def window_equity(eq, start, end):
    """Include the preceding close, so the first session return is not omitted."""
    dates = eq.loc[start:end].index
    if not len(dates):
        return eq.iloc[:0]
    preceding = eq.index[eq.index < dates[0]]
    begin = preceding[-1] if len(preceding) else dates[0]
    return eq.loc[begin:dates[-1]]


def performance(eq, start=None, end=None):
    e = window_equity(eq,start,end) if start is not None else eq
    if len(e)<2:
        return {k:np.nan for k in ['CAGR','Vol','Sharpe','Sortino','MDD','Calmar']}
    return ENGINE['metrics'](e)




