"""测试 src.integrations.sectors 的 find_symbol_sectors / detect_sector_resonance。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.integrations.sectors import detect_sector_resonance, find_symbol_sectors


class TestFindSymbolSectors:
    def test_no_concept_names(self):
        """AKShare 全概念列表为空时返回空 list。"""
        with patch("src.integrations.sectors._list_all_concept_names", return_value=[]):
            out = find_symbol_sectors("SH600519")
            assert out == []

    def test_match_via_constituents(self):
        """3 个概念，其中 1 个含目标票。"""
        fake_names = ["A概念", "B概念", "C概念"]

        def fake_constituents(sector, **kw):
            if sector == "B概念":
                return pd.DataFrame({"symbol": ["SH600519", "SZ000001"], "name": ["x", "y"]})
            return pd.DataFrame(columns=["symbol", "name"])

        with patch("src.integrations.sectors._list_all_concept_names", return_value=fake_names):
            with patch(
                "src.integrations.sectors.get_sector_constituents",
                side_effect=fake_constituents,
            ):
                out = find_symbol_sectors("SH600519")
                assert out == ["B概念"]

    def test_max_scan_limits(self):
        """max_scan=1 时只扫前 1 个。"""
        fake_names = ["A", "B"]
        with patch("src.integrations.sectors._list_all_concept_names", return_value=fake_names):
            with patch(
                "src.integrations.sectors.get_sector_constituents",
                return_value=pd.DataFrame(columns=["symbol", "name"]),
            ) as mock:
                find_symbol_sectors("SH600519", max_scan=1)
                assert mock.call_count == 1


class TestDetectSectorResonance:
    def test_no_sectors(self):
        with patch("src.integrations.sectors.find_symbol_sectors", return_value=[]):
            out = detect_sector_resonance("SH600519", "2025-12-15")
            assert out == []

    def test_threshold_filter(self):
        """3 个板块，仅 1 个累计涨幅过阈值。"""

        def fake_perf(sec, start, end, **kw):
            pct_map = {"A": 5.0, "B": 1.0, "C": 4.0}
            return pd.DataFrame({"pct_change": [pct_map[sec]]})

        with patch(
            "src.integrations.sectors.find_symbol_sectors",
            return_value=["A", "B", "C"],
        ):
            with patch("src.integrations.sectors.get_sector_performance", side_effect=fake_perf):
                out = detect_sector_resonance(
                    "SH600519", "2025-12-15", pct_threshold=3.0, lookback_days=5
                )
                assert len(out) == 2  # A 和 C 过线
                hit_names = sorted(h["sector"] for h in out)
                assert hit_names == ["A", "C"]
