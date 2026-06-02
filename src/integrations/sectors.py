"""板块/概念集成：主线确认器。

用法：
    from src.integrations.sectors import (
        get_sector_constituents, get_sector_performance, detect_sector_resonance,
    )
    members = get_sector_constituents("机器人")
    perf = get_sector_performance("机器人", "2025-11-01", "2025-12-15")
"""
from __future__ import annotations

import pandas as pd

from src.data_layer.cache import cached_call
from src.data_layer.symbols import to_chinastock
from src.data_sources.akshare_source import AkShareSource
from src.data_sources.base import DataSource, SourceRole

# 缓存 TTL：板块日 K 当日不再变化，24h
_SECTOR_TTL_HOURS: float = 24.0
# 成分股可能调整，1 天即可
_CONSTITUENT_TTL_HOURS: float = 24.0


def get_sector_constituents(
    sector: str,
    *,
    source: DataSource | None = None,
    ttl_hours: float = _CONSTITUENT_TTL_HOURS,
    force: bool = False,
) -> pd.DataFrame:
    """板块/概念成分股。

    :param sector: 概念名（中文，如 "机器人" / "锂电池" / "人工智能"）
    :return: DataFrame，列：`symbol, name`
    """
    src = source or AkShareSource()
    cache_name = (
        "akshare.sector_constituents"
        if src.role == SourceRole.SUPPLEMENTARY
        else f"{src.name}.sector_constituents"
    )
    params = {"sector": sector}
    return cached_call(
        cache_name,
        params,
        fetcher=lambda: src.get_sector_constituents(sector),
        ttl_hours=ttl_hours,
        force=force,
    )


def get_sector_performance(
    sector: str,
    start: str,
    end: str,
    *,
    source: DataSource | None = None,
    ttl_hours: float = _SECTOR_TTL_HOURS,
    force: bool = False,
) -> pd.DataFrame:
    """板块/概念日 K 线。

    :return: DataFrame，列：`date, open, close, high, low, volume, amount, pct_change`
    """
    src = source or AkShareSource()
    cache_name = (
        "akshare.sector_perf"
        if src.role == SourceRole.SUPPLEMENTARY
        else f"{src.name}.sector_perf"
    )
    params = {"sector": sector, "start": start, "end": end}
    return cached_call(
        cache_name,
        params,
        fetcher=lambda: src.get_sector_perf(sector, start, end),
        ttl_hours=ttl_hours,
        force=force,
    )


def find_symbol_sectors(
    symbol: str,
    *,
    source: DataSource | None = None,
) -> list[str]:
    """给定一只票，反向查找它所属的概念板块（多次探测常见概念名）。"""
    # 此接口较重，需要遍历所有概念。当前 MVP 不实现，给出接口占位。
    raise NotImplementedError(
        "find_symbol_sectors 需要遍历全概念列表，AKShare 接口 "
        "`ak.stock_board_concept_name_em()` 较慢；建议通过 westock/neodata 实现。"
    )


def detect_sector_resonance(
    symbol: str,
    date: str,
    *,
    min_count: int = 3,
    source: DataSource | None = None,
) -> list[dict]:
    """板块共振检测：异动票所属概念板块内，5 日内异动股数 ≥ `min_count`。

    当前实现：仅占位。完整版需要 `find_symbol_sectors` 先反向查板块。
    """
    raise NotImplementedError(
        "detect_sector_resonance 依赖 find_symbol_sectors；待主源（westock/neodata）"
        "接入后实现。"
    )


__all__ = [
    "get_sector_constituents",
    "get_sector_performance",
    "find_symbol_sectors",
    "detect_sector_resonance",
]
