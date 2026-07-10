"""Single-stock snapshots carry fail-closed trust evidence."""

from __future__ import annotations

import pandas as pd
import pytest

import scripts.analyze_one as analyze_one
from src.data_sources.base import DataSourceError


def valid_kline() -> pd.DataFrame:
    dates = pd.bdate_range(end="2026-07-10", periods=80)
    close = pd.Series(range(20, 20 + len(dates)), dtype=float)
    return pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1000,
            "symbol": "SH600000",
        }
    )


@pytest.fixture
def complete_sources(monkeypatch):
    monkeypatch.setattr(analyze_one, "SYMBOL", "SH600000")
    monkeypatch.setattr(analyze_one, "NAME", "浦发银行")
    monkeypatch.setattr(analyze_one, "WESTOCK_CODE", "sh600000")
    monkeypatch.setattr(
        analyze_one.AkShareSource,
        "get_kline",
        lambda *args, **kwargs: valid_kline(),
    )
    markdown = """| code | industry | value |
| --- | --- | --- |
| sh600000 | 银行 | 1 |
"""
    monkeypatch.setattr(analyze_one, "_call_westock", lambda *args, **kwargs: markdown)
    monkeypatch.setattr(
        analyze_one,
        "evaluate_sector",
        lambda profile: {"score": 70, "industry": "银行", "is_sector_hot": True},
    )
    monkeypatch.setattr(
        analyze_one,
        "evaluate_flow",
        lambda code: {"score": 65, "is_flow_hot": True, "reason": "fixture"},
    )


def test_pull_writes_trusted_manifest_for_complete_snapshot(complete_sources):
    snapshot = analyze_one.pull()

    assert snapshot["_trust"]["status"] == "trusted"
    assert snapshot["kline"]["adjustment"] == "qfq"
    assert snapshot["kline"]["head"][-1]["date"] == "2026-07-10"
    assert any(
        item["dataset"] == "kline"
        for item in snapshot["_trust"]["source_manifest"]
    )


def test_kline_failure_blocks_snapshot(complete_sources, monkeypatch):
    def fail(*args, **kwargs):
        raise DataSourceError("akshare", "get_kline", "timeout")

    monkeypatch.setattr(analyze_one.AkShareSource, "get_kline", fail)

    snapshot = analyze_one.pull()

    assert snapshot["_trust"]["status"] == "blocked"


def test_optional_failure_makes_snapshot_partial(complete_sources, monkeypatch):
    def fail(*args, **kwargs):
        raise DataSourceError("westock", "hot_board", "timeout")

    monkeypatch.setattr(analyze_one, "evaluate_sector", fail)

    snapshot = analyze_one.pull()

    assert snapshot["_trust"]["status"] == "partial"
