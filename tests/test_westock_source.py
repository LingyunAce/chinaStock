"""测试 src.data_sources.westock_source 的 markdown 解析与字段映射。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_sources.westock_source import (
    WestockSource,
    _parse_markdown_table,
    _to_number,
    _westock_available,
)


class TestParseMarkdownTable:
    def test_basic(self):
        text = """| a | b |
| --- | --- |
| 1 | 2 |
| 3 | 4 |
"""
        df = _parse_markdown_table(text)
        assert list(df.columns) == ["a", "b"]
        assert df.shape == (2, 2)
        assert df["a"].tolist() == ["1", "3"]

    def test_with_noise_lines(self):
        text = """**机构榜** (46只)

| 代码 | 名称 | 净买入额 |
| --- | --- | --- |
| sh600519 | 茅台 | 1.5亿 |
| sz000001 | 平安 | 2000万 |
"""
        df = _parse_markdown_table(text)
        assert df.shape == (2, 3)
        assert df["净买入额"].tolist() == ["1.5亿", "2000万"]

    def test_no_table(self):
        df = _parse_markdown_table("not a table")
        assert df.empty

    def test_empty(self):
        df = _parse_markdown_table("")
        assert df.empty


class TestToNumber:
    def test_yi(self):
        assert _to_number("1.5亿") == 1.5e8

    def test_wan(self):
        assert _to_number("2000万") == 2e7

    def test_qian(self):
        assert _to_number("3千") == 3000.0

    def test_pct(self):
        assert _to_number("5.5%") == 5.5

    def test_plain(self):
        assert _to_number("123.45") == 123.45

    def test_empty(self):
        assert _to_number("") is None
        assert _to_number("-") is None
        assert _to_number(None) is None

    def test_garbage(self):
        # 解析失败返回原字符串
        assert _to_number("abc") == "abc"


class TestWestockSource:
    def test_get_lhb_parses_markdown(self):
        sample = """**机构榜** (46只)

| 代码 | 名称 | 上榜天数 | 机构买入席位 | 机构买入额 | 买入占比 | 总买入额 | 净买入额 | 净占比 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sh600519 | 贵州茅台 | 3 | 5 | 1.5亿 | 4.48% | 2亿 | 8000万 | 9.52% |
"""
        with patch("src.data_sources.westock_source._call_westock", return_value=sample):
            src = WestockSource()
            df = src.get_lhb(symbol=None, date="2025-12-15")
            assert not df.empty
            assert "symbol" in df.columns
            assert "net_buy_amount" in df.columns
            assert df["symbol"].iloc[0] == "SH600519"
            assert df["net_buy_amount"].iloc[0] == 8e7

    def test_get_lhb_filters_by_symbol(self):
        sample = """| 代码 | 名称 | 净买入额 |
| --- | --- | --- |
| sh600519 | 茅台 | 1.5亿 |
| sz000001 | 平安 | 2000万 |
"""
        with patch("src.data_sources.westock_source._call_westock", return_value=sample):
            src = WestockSource()
            df = src.get_lhb(symbol="SH600519", date="2025-12-15")
            assert len(df) == 1
            assert df["symbol"].iloc[0] == "SH600519"

    def test_get_limit_up_pool_returns_empty(self):
        """westock 没有严格意义的涨停池，应返回空 DataFrame 让上层 fallback。"""
        src = WestockSource()
        assert src.get_limit_up_pool("2025-12-15").empty

    def test_get_quote_for_validation_renames_last_to_close(self):
        sample = """| date | open | last | high | low | volume | amount |
| --- | --- | --- | --- | --- | --- | --- |
| 2025-12-15 | 100 | 105 | 110 | 99 | 1000 | 100000 |
"""
        with patch("src.data_sources.westock_source._call_westock", return_value=sample):
            src = WestockSource()
            df = src.get_quote_for_validation("SH600519", "2025-12-15")
            assert "close" in df.columns  # 'last' 已重命名
            assert df["close"].iloc[0] == 105
            assert df["symbol"].iloc[0] == "SH600519"
