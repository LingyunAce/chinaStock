"""多信号投票策略。

综合 MA + MACD + RSI + KDJ + BOLL 五个信号，
至少 min_votes 个同向信号才执行。
"""

from __future__ import annotations

import pandas as pd

from src.factors.technical import compute_vote_signal
from strategies.base import run_backtest


def backtest_multi_signal(data_df: pd.DataFrame, min_votes: int = 3, **kwargs) -> dict:
    """运行多信号投票回测。"""
    signals = compute_vote_signal(data_df, min_votes=min_votes)
    signal_map = dict(zip(signals["date"], signals["signal"]))
    return run_backtest(signal_map, data_df, **kwargs)


__all__ = ["backtest_multi_signal"]
