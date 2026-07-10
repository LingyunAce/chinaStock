"""Data provider failures must not masquerade as valid empty datasets."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from src.data_sources.akshare_source import _safe_call
from src.data_sources.base import DataSourceError
from src.factors.capital_flow import fetch_hot_stock
from src.factors.sector_momentum import fetch_industry_snapshot


def test_akshare_none_result_is_valid_empty_frame():
    assert _safe_call(lambda: None).empty


def test_akshare_exception_is_not_converted_to_empty_frame():
    def fail():
        raise TimeoutError("upstream timeout")

    with pytest.raises(DataSourceError) as exc_info:
        _safe_call(fail)

    error = exc_info.value
    assert error.source == "akshare"
    assert error.operation == "fail"
    assert error.detail == "upstream timeout"


def test_akshare_dataframe_is_returned_unchanged():
    expected = pd.DataFrame({"value": [1]})
    assert _safe_call(lambda: expected).equals(expected)


def test_capital_flow_westock_failure_is_propagated():
    with patch(
        "src.factors.capital_flow._call_westock",
        side_effect=RuntimeError("westock unavailable"),
    ):
        with pytest.raises(DataSourceError) as exc_info:
            fetch_hot_stock(force=True)

    assert exc_info.value.operation == "hot_stock"


def test_sector_westock_failure_is_propagated():
    with patch(
        "src.factors.sector_momentum._call_westock",
        side_effect=RuntimeError("westock unavailable"),
    ):
        with pytest.raises(DataSourceError) as exc_info:
            fetch_industry_snapshot(force=True)

    assert exc_info.value.operation == "hot_board"
