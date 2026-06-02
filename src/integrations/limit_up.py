"""涨停池 + 连板集成：情绪温度计。

用法：
    from src.integrations.limit_up import (
        get_limit_up_pool, get_limit_up_streak, market_sentiment_score,
    )
    pool = get_limit_up_pool("2025-12-15")
    streak = get_limit_up_streak("2025-12-15", min_boards=2)
    score = market_sentiment_score("2025-12-15")
"""

from __future__ import annotations

import pandas as pd

from src.data_layer.cache import cached_call
from src.data_sources.akshare_source import AkShareSource
from src.data_sources.base import DataSource, SourceRole

# 缓存 TTL：涨停池盘中频繁更新，1h 比较安全
_LIMIT_UP_TTL_HOURS: float = 1.0


def get_limit_up_pool(
    date: str,
    *,
    source: DataSource | None = None,
    ttl_hours: float = _LIMIT_UP_TTL_HOURS,
    force: bool = False,
) -> pd.DataFrame:
    """涨停池 + 连板信息。

    :return: DataFrame，列：`date, symbol, name, pct_change, consecutive_boards, ...`
    """
    src = source or AkShareSource()
    cache_name = (
        "akshare.limit_up"
        if src.role == SourceRole.SUPPLEMENTARY
        else f"{src.name}.limit_up"
    )
    params = {"date": date}
    return cached_call(
        cache_name,
        params,
        fetcher=lambda: src.get_limit_up_pool(date),
        ttl_hours=ttl_hours,
        force=force,
    )


def get_limit_up_streak(
    date: str,
    *,
    min_boards: int = 2,
    source: DataSource | None = None,
) -> pd.DataFrame:
    """连板过滤：返回 N 连板及以上的票。"""
    pool = get_limit_up_pool(date, source=source)
    if pool.empty or "consecutive_boards" not in pool.columns:
        return pool
    return pool[pool["consecutive_boards"].fillna(0) >= min_boards].copy()


def market_sentiment_score(date: str, *, source: DataSource | None = None) -> dict:
    """市场情绪综合分（三维：涨停数 / 炸板率 / 连板高度）。

    返回 dict：
    - limit_up_count: 涨停股数
    - max_consecutive: 最高连板数
    - broken_ratio: 炸板率 = 炸板股数 / (涨停股数 + 炸板股数)；无数据时 NaN
    - sentiment: "overheat" / "normal" / "cold"（启发式）
    """
    pool = get_limit_up_pool(date, source=source)
    if pool.empty:
        return {
            "date": date,
            "limit_up_count": 0,
            "max_consecutive": 0,
            "broken_ratio": None,
            "sentiment": "unknown",
        }

    limit_up_count = len(pool)
    max_consec = (
        int(pool["consecutive_boards"].fillna(0).max())
        if "consecutive_boards" in pool.columns
        else 0
    )
    broken_count = (
        int((pool["broken_count"].fillna(0) > 0).sum())
        if "broken_count" in pool.columns
        else 0
    )
    denom = limit_up_count + broken_count
    broken_ratio = round(broken_count / denom, 4) if denom > 0 else None

    # 启发式情绪判定
    if limit_up_count >= 50 or max_consec >= 7:
        sentiment = "overheat"
    elif limit_up_count <= 10 or (broken_ratio is not None and broken_ratio > 0.6):
        sentiment = "cold"
    else:
        sentiment = "normal"

    return {
        "date": date,
        "limit_up_count": limit_up_count,
        "max_consecutive": max_consec,
        "broken_ratio": broken_ratio,
        "sentiment": sentiment,
    }


__all__ = [
    "get_limit_up_pool",
    "get_limit_up_streak",
    "market_sentiment_score",
]
