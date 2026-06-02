"""连板高度分布因子。

记录当日涨停池中各连板高度的票数，用于跟踪题材炒作周期。
"""
from __future__ import annotations

import pandas as pd

from src.integrations.limit_up import get_limit_up_pool


def limit_up_streak_distribution(date: str) -> pd.DataFrame:
    """连板高度分布。

    返回列：`date, consecutive_boards, count, value`
    `value` = 该连板高度的票数（直方图）
    """
    pool = get_limit_up_pool(date)
    if pool.empty or "consecutive_boards" not in pool.columns:
        return pd.DataFrame(columns=["date", "consecutive_boards", "count", "value"])
    counts_series = pool["consecutive_boards"].fillna(0).astype(int).value_counts().sort_index()
    out = counts_series.reset_index()
    out.columns = ["consecutive_boards", "count"]
    out["date"] = date
    out["value"] = out["count"]
    return out[["date", "consecutive_boards", "count", "value"]]


__all__ = ["limit_up_streak_distribution"]
