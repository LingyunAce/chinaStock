"""板块共振因子。

识别一只票所在的多个概念板块中，N 日内板块整体强势的板块数，
作为"主线确认"信号。
"""
from __future__ import annotations

import pandas as pd

from src.data_sources.base import DataSource
from src.integrations.sectors import (
    find_symbol_sectors,
    get_sector_performance,
)


def sector_resonance_factor(
    symbol: str,
    date: str,
    *,
    lookback_days: int = 5,
    pct_threshold: float = 3.0,
    source: DataSource | None = None,
) -> pd.DataFrame:
    """板块共振因子。

    算法：
    1. 反查 symbol 所属的 N 个概念板块
    2. 每个板块取 lookback_days 日内涨跌幅
    3. 上涨超过 pct_threshold% 的板块数 = 共振强度
    4. value = 共振板块数 / 总板块数（0-1）

    返回：单行 DataFrame
    列：`date, symbol, sector_count, strong_count, value`
    """
    from datetime import datetime, timedelta

    try:
        sectors = find_symbol_sectors(symbol, source=source)
    except NotImplementedError:
        return pd.DataFrame(
            columns=["date", "symbol", "sector_count", "strong_count", "value"]
        )

    if not sectors:
        return pd.DataFrame(
            columns=["date", "symbol", "sector_count", "strong_count", "value"]
        )

    end = pd.Timestamp(date)
    start = (end - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")

    strong_count = 0
    for sec in sectors:
        perf = get_sector_performance(sec, start, end_str, source=source)
        if perf.empty or "pct_change" not in perf.columns:
            continue
        try:
            cum = float(pd.to_numeric(perf["pct_change"], errors="coerce").fillna(0).sum())
        except Exception:  # noqa: BLE001
            continue
        if cum >= pct_threshold:
            strong_count += 1

    sector_count = len(sectors)
    value = strong_count / sector_count if sector_count else 0.0
    return pd.DataFrame(
        [
            {
                "date": date,
                "symbol": symbol,
                "sector_count": sector_count,
                "strong_count": strong_count,
                "value": value,
            }
        ]
    )


__all__ = ["sector_resonance_factor"]
