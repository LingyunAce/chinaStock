"""测试 src.data_layer.normalize 字段归一化。"""

from __future__ import annotations

import pandas as pd

from src.data_layer.normalize import (
    normalize_lhb,
    normalize_limit_up,
    normalize_sector_constituents,
    normalize_sector_ohlcv,
)


class TestNormalizeLhb:
    def test_empty_input(self):
        assert normalize_lhb(pd.DataFrame()).empty
        assert normalize_lhb(None).empty  # type: ignore[arg-type]

    def test_chinese_columns_renamed(self):
        df = pd.DataFrame(
            [
                {
                    "代码": "600519",
                    "名称": "贵州茅台",
                    "上榜日期": "2025-12-15",
                    "涨跌幅": 10.0,
                    "净买入额": 12345.6,
                }
            ]
        )
        out = normalize_lhb(df)
        assert "code" in out.columns
        assert "name" in out.columns
        assert "pct_change" in out.columns
        assert "net_buy_amount" in out.columns

    def test_symbol_added_with_prefix(self):
        df = pd.DataFrame([{"代码": "600519", "上榜日期": "2025-12-15"}])
        out = normalize_lhb(df)
        assert out["symbol"].iloc[0] == "SH600519"

    def test_sz_symbol(self):
        df = pd.DataFrame([{"代码": "000001", "上榜日期": "2025-12-15"}])
        out = normalize_lhb(df)
        assert out["symbol"].iloc[0] == "SZ000001"

    def test_date_normalized(self):
        df = pd.DataFrame([{"代码": "600519", "上榜日期": "20251215"}])
        out = normalize_lhb(df)
        assert out["date"].iloc[0] == "2025-12-15"

    def test_int_code_padded(self):
        df = pd.DataFrame([{"代码": 1, "上榜日期": "2025-12-15"}])
        out = normalize_lhb(df)
        assert out["symbol"].iloc[0] == "SZ000001"  # 0 开头 → SZ


class TestNormalizeLimitUp:
    def test_empty(self):
        assert normalize_limit_up(pd.DataFrame()).empty

    def test_rename_chinese(self):
        df = pd.DataFrame(
            [
                {
                    "代码": "600519",
                    "名称": "贵州茅台",
                    "涨跌幅": 10.01,
                    "最新价": 1500.0,
                    "成交额": 1e9,
                    "封板资金": 5e8,
                    "炸板次数": 0,
                    "连板数": 3,
                }
            ]
        )
        out = normalize_limit_up(df)
        for col in (
            "symbol",
            "name",
            "pct_change",
            "price",
            "amount",
            "sealed_amount",
            "broken_count",
            "consecutive_boards",
        ):
            assert col in out.columns, f"missing column: {col}"

    def test_symbol_with_prefix(self):
        df = pd.DataFrame([{"代码": "300750", "连板数": 2}])
        out = normalize_limit_up(df)
        assert out["symbol"].iloc[0] == "SZ300750"


class TestNormalizeSectorOHLCV:
    def test_empty(self):
        assert normalize_sector_ohlcv(pd.DataFrame()).empty

    def test_rename(self):
        df = pd.DataFrame(
            [
                {
                    "日期": "2025-12-15",
                    "开盘": 100.0,
                    "收盘": 105.0,
                    "最高": 106.0,
                    "最低": 99.0,
                    "涨跌幅": 5.0,
                    "成交量": 1e6,
                    "成交额": 1e8,
                }
            ]
        )
        out = normalize_sector_ohlcv(df)
        for col in (
            "date",
            "open",
            "close",
            "high",
            "low",
            "pct_change",
            "volume",
            "amount",
        ):
            assert col in out.columns

    def test_date_format(self):
        df = pd.DataFrame([{"日期": "20251215", "开盘": 1, "收盘": 1}])
        out = normalize_sector_ohlcv(df)
        assert out["date"].iloc[0] == "2025-12-15"


class TestNormalizeSectorConstituents:
    def test_empty(self):
        assert normalize_sector_constituents(pd.DataFrame()).empty

    def test_rename_with_symbol(self):
        df = pd.DataFrame(
            [{"代码": "300750", "名称": "宁德时代", "最新价": 200.0, "涨跌幅": 5.0}]
        )
        out = normalize_sector_constituents(df)
        assert "symbol" in out.columns
        assert "name" in out.columns
        assert "price" in out.columns
        assert out["symbol"].iloc[0] == "SZ300750"
