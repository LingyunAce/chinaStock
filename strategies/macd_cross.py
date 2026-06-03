"""MACD 金叉/死叉策略。

DIF 上穿 DEA → 买入
DIF 下穿 DEA → 卖出
"""

from __future__ import annotations

import pandas as pd

from src.factors.technical import compute_macd
from strategies.base import run_backtest


def backtest_macd_cross(data_df: pd.DataFrame, **kwargs) -> dict:
    """运行 MACD 金叉回测。"""
    signals = compute_macd(data_df)
    signal_map = dict(zip(signals["date"], signals["signal"]))
    return run_backtest(signal_map, data_df, **kwargs)


__all__ = ["backtest_macd_cross"]
