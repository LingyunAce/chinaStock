"""A-share backtest timing, execution constraints, costs, and metrics."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from strategies.base import BacktestConfig, run_backtest


def bars(opens, closes, volumes=None, symbol="SH600000"):
    rows = len(opens)
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2026-01-05", periods=rows).strftime("%Y-%m-%d"),
            "open": opens,
            "high": [max(o, c) + 0.5 for o, c in zip(opens, closes)],
            "low": [min(o, c) - 0.5 for o, c in zip(opens, closes)],
            "close": closes,
            "volume": volumes or [10_000] * rows,
            "symbol": [symbol] * rows,
        }
    )


NO_COST = BacktestConfig(
    initial_cash=100_000,
    commission_rate=0,
    minimum_commission=0,
    stamp_duty_rate=0,
    slippage=0,
)


def test_close_signal_executes_at_next_session_open():
    data = bars([10, 9, 10.5], [10, 10, 10.5])
    signal_date = data.iloc[1]["date"]

    result = run_backtest({signal_date: 1}, data, config=NO_COST)

    assert result["trades"][0]["date"] == data.iloc[2]["date"]
    assert result["trades"][0]["price"] == 10.5


def test_buy_quantity_is_a_board_lot():
    data = bars([10, 10, 10], [10, 10, 10])

    result = run_backtest({data.iloc[1]["date"]: 1}, data, config=NO_COST)

    assert result["trades"][0]["shares"] % 100 == 0


def test_limit_up_buy_is_rejected_and_recorded():
    data = bars([10, 10, 11], [10, 10, 11])

    result = run_backtest({data.iloc[1]["date"]: 1}, data, config=NO_COST)

    assert result["trades"] == []
    assert result["rejected_orders"][0]["reason"] == "limit_up"


def test_zero_volume_does_not_fill():
    data = bars([10, 10, 10], [10, 10, 10], volumes=[1000, 1000, 0])

    result = run_backtest({data.iloc[1]["date"]: 1}, data, config=NO_COST)

    assert result["trades"] == []
    assert result["rejected_orders"][0]["reason"] == "suspended_or_no_volume"


def test_sell_happens_after_buy_day_and_charges_stamp_duty():
    data = bars([10, 10, 10, 12, 12], [10, 10, 11, 12, 12])
    config = replace(NO_COST, stamp_duty_rate=0.0005)
    signals = {data.iloc[0]["date"]: 1, data.iloc[2]["date"]: -1}

    result = run_backtest(signals, data, config=config)

    buy, sell = result["trades"]
    assert sell["date"] > buy["date"]
    assert sell["stamp_duty"] > 0


def test_short_sample_does_not_annualize():
    result = run_backtest({}, bars([10] * 10, [10] * 10), config=NO_COST)

    assert result["annual_return"] is None
    assert result["sharpe"] is None


def test_no_closed_trade_has_no_win_rate_or_profit_loss_ratio():
    data = bars([10, 10, 10.5], [10, 10, 10.5])

    result = run_backtest({data.iloc[0]["date"]: 1}, data, config=NO_COST)

    assert result["win_rate"] is None
    assert result["profit_loss_ratio"] is None


def test_result_exposes_benchmark_excess_and_config():
    result = run_backtest({}, bars([10, 11], [10, 12]), config=NO_COST)

    assert result["buy_hold_return"] is not None
    assert result["excess_return"] == pytest.approx(
        result["total_return"] - result["buy_hold_return"], abs=0.01
    )
    assert result["config"]["lot_size"] == 100


def test_insufficient_cash_is_recorded():
    data = bars([1000, 1000], [1000, 1000])
    config = replace(NO_COST, initial_cash=50_000)

    result = run_backtest({data.iloc[0]["date"]: 1}, data, config=config)

    assert result["trades"] == []
    assert result["rejected_orders"][0]["reason"] == "insufficient_cash"


def test_backtest_metric_formatter_marks_none_as_insufficient_sample():
    from scripts.run_backtest import format_metric

    assert format_metric(None, suffix="%") == "样本不足"
