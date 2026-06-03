"""MA 金叉/死叉策略。

MA5 上穿 MA10 → 买入
MA5 下穿 MA10 → 卖出
"""

from __future__ import annotations

import pandas as pd

from src.factors.technical import compute_ma
from strategies.base import run_backtest


def backtest_ma_cross(
    data_df: pd.DataFrame, short: int = 5, long: int = 10, **kwargs
) -> dict:
    """运行 MA 金叉回测。"""
    signals = compute_ma(data_df, short=short, long=long)
    signal_map = dict(zip(signals["date"], signals["signal"]))
    return run_backtest(signal_map, data_df, **kwargs)


__all__ = ["backtest_ma_cross"]
