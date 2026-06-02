"""测试 src.factors 因子函数（mock 数据，无网络）。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.factors.lhb_flow import institutional_net_buy, lhb_signal_score
from src.factors.limit_up_streak import limit_up_streak_distribution
from src.factors.market_sentiment import market_sentiment_factor
from src.factors.sector_resonance import sector_resonance_factor


def _mock_lhb_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2025-12-15",
                "symbol": "SH600519",
                "name": "贵州茅台",
                "net_buy_amount": 8_000_000.0,
                "pct_change": 2.0,
            },
            {
                "date": "2025-12-15",
                "symbol": "SZ000001",
                "name": "平安银行",
                "net_buy_amount": 1_000_000.0,
                "pct_change": 7.0,
            },
        ]
    )


def _mock_limit_up_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": "2025-12-15", "symbol": "SH600519", "name": "A", "consecutive_boards": 1},
            {"date": "2025-12-15", "symbol": "SH600000", "name": "B", "consecutive_boards": 2},
            {"date": "2025-12-15", "symbol": "SZ000001", "name": "C", "consecutive_boards": 2},
            {"date": "2025-12-15", "symbol": "SH601318", "name": "D", "consecutive_boards": 3},
        ]
    )


class TestInstitutionalNetBuy:
    def test_empty_lhb(self):
        with patch("src.factors.lhb_flow.get_lhb", return_value=pd.DataFrame()):
            out = institutional_net_buy("2025-12-15")
            assert out.empty

    def test_happy_path(self):
        with patch("src.factors.lhb_flow.get_lhb", return_value=_mock_lhb_df()):
            out = institutional_net_buy("2025-12-15")
            assert not out.empty
            assert "value" in out.columns
            assert out["value"].sum() == pytest.approx(9_000_000.0)


class TestLhbSignalScore:
    def test_empty(self):
        with patch("src.factors.lhb_flow.get_lhb", return_value=pd.DataFrame()):
            out = lhb_signal_score("2025-12-15")
            assert out.empty

    def test_score_in_range(self):
        with patch("src.factors.lhb_flow.get_lhb", return_value=_mock_lhb_df()):
            out = lhb_signal_score("2025-12-15")
            assert (out["score"] >= 0).all()
            assert (out["score"] <= 1).all()

    def test_score_uses_threshold(self):
        # 大额 + 小涨幅 → 高分
        df = _mock_lhb_df()
        with patch("src.factors.lhb_flow.get_lhb", return_value=df):
            out = lhb_signal_score("2025-12-15", amount_threshold=5_000_000)
            sh = out[out["symbol"] == "SH600519"].iloc[0]
            sz = out[out["symbol"] == "SZ000001"].iloc[0]
            # 茅台净买入 800 万 > 500 万，pct=2% < 5%，应得 0.5 + 0.2 = 0.7
            assert sh["score"] == pytest.approx(0.7)
            # 平安净买入 100 万 < 500 万，pct=7% > 5%，应得 0.0
            assert sz["score"] == pytest.approx(0.0)


class TestMarketSentimentFactor:
    def test_factor_shape(self):
        with patch(
            "src.factors.market_sentiment.market_sentiment_score",
            return_value={
                "date": "2025-12-15",
                "limit_up_count": 60,
                "max_consecutive": 8,
                "broken_ratio": 0.15,
                "sentiment": "overheat",
            },
        ):
            out = market_sentiment_factor("2025-12-15")
            assert len(out) == 1
            assert out["sentiment_code"].iloc[0] == 1.0
            assert out["value"].iloc[0] == 1.0

    def test_cold_sentiment(self):
        with patch(
            "src.factors.market_sentiment.market_sentiment_score",
            return_value={
                "date": "2025-12-15",
                "limit_up_count": 5,
                "max_consecutive": 1,
                "broken_ratio": 0.8,
                "sentiment": "cold",
            },
        ):
            out = market_sentiment_factor("2025-12-15")
            assert out["value"].iloc[0] == 0.0


class TestLimitUpStreakDistribution:
    def test_distribution(self):
        with patch(
            "src.factors.limit_up_streak.get_limit_up_pool",
            return_value=_mock_limit_up_df(),
        ):
            out = limit_up_streak_distribution("2025-12-15")
            # 1板 1只, 2板 2只, 3板 1只
            counts = dict(zip(out["consecutive_boards"], out["count"]))
            assert counts == {1: 1, 2: 2, 3: 1}

    def test_empty(self):
        with patch(
            "src.factors.limit_up_streak.get_limit_up_pool",
            return_value=pd.DataFrame(),
        ):
            out = limit_up_streak_distribution("2025-12-15")
            assert out.empty


class TestSectorResonanceFactor:
    def test_resonance(self):
        # sector_resonance_factor 在模块顶部 import 了 find_symbol_sectors /
        # get_sector_performance，所以 patch 必须在 factor 模块的命名空间上
        with patch(
            "src.factors.sector_resonance.find_symbol_sectors",
            return_value=["机器人", "锂电池"],
        ):
            def fake_perf(sec, start, end, **kw):
                if sec == "机器人":
                    return pd.DataFrame({"pct_change": [1.0, 1.5, 1.0]})  # 累计 3.5%
                return pd.DataFrame({"pct_change": [0.5, 0.5, 0.5]})      # 累计 1.5%

            with patch(
                "src.factors.sector_resonance.get_sector_performance",
                side_effect=fake_perf,
            ):
                out = sector_resonance_factor("SH300750", "2025-12-15", pct_threshold=3.0)
                assert out["sector_count"].iloc[0] == 2
                assert out["strong_count"].iloc[0] == 1  # 只有机器人 >= 3%
                assert out["value"].iloc[0] == pytest.approx(0.5)
