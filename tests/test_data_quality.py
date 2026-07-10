"""Pure OHLCV quality validation tests."""

from __future__ import annotations

import pandas as pd

from src.data_layer.quality import validate_kline


def valid_bars(rows: int = 60) -> pd.DataFrame:
    dates = pd.bdate_range(end="2026-07-10", periods=rows)
    close = pd.Series(range(10, 10 + rows), dtype=float)
    return pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1_000,
        }
    )


def codes(issues):
    return {issue.code for issue in issues}


def test_valid_kline_has_no_issues():
    assert (
        validate_kline(valid_bars(), as_of="2026-07-10", adjustment="qfq") == []
    )


def test_missing_columns_and_adjustment_are_critical():
    issues = validate_kline(
        pd.DataFrame({"date": ["2026-07-10"]}),
        as_of="2026-07-10",
        adjustment=None,
    )
    assert {"missing_columns", "missing_adjustment"} <= codes(issues)
    assert all(issue.critical for issue in issues)


def test_invalid_ohlc_duplicate_and_future_are_detected():
    bars = valid_bars()
    bars.loc[0, "high"] = bars.loc[0, "low"] - 1
    bars.loc[1, "date"] = bars.loc[0, "date"]
    bars.loc[len(bars) - 1, "date"] = "2026-07-11"

    issues = validate_kline(bars, as_of="2026-07-10", adjustment="qfq")

    assert {"invalid_ohlc", "duplicate_date", "future_date"} <= codes(issues)


def test_short_and_stale_history_are_detected():
    bars = valid_bars(20)
    bars["date"] = pd.bdate_range(end="2026-06-01", periods=20).strftime(
        "%Y-%m-%d"
    )

    issues = validate_kline(bars, as_of="2026-07-10", adjustment="qfq")

    assert {"insufficient_history", "stale_data"} <= codes(issues)


def test_unsorted_dates_are_detected():
    bars = valid_bars()
    bars.loc[[0, 1], "date"] = bars.loc[[1, 0], "date"].to_numpy()

    issues = validate_kline(bars, as_of="2026-07-10", adjustment="qfq")

    assert "unsorted_date" in codes(issues)


def test_non_numeric_ohlcv_is_detected():
    bars = valid_bars()
    bars["close"] = bars["close"].astype(object)
    bars.loc[0, "close"] = "not-a-number"

    issues = validate_kline(bars, as_of="2026-07-10", adjustment="qfq")

    assert "non_numeric_ohlcv" in codes(issues)


def test_negative_volume_is_detected():
    bars = valid_bars()
    bars.loc[0, "volume"] = -1

    issues = validate_kline(bars, as_of="2026-07-10", adjustment="qfq")

    assert "negative_volume" in codes(issues)
