"""板块/概念集成：主线确认器。

用法：
    from src.integrations.sectors import (
        get_sector_constituents, get_sector_performance,
        find_symbol_sectors, detect_sector_resonance,
    )
    members = get_sector_constituents("机器人")
    perf = get_sector_performance("机器人", "2025-11-01", "2025-12-15")
    sectors = find_symbol_sectors("SH600519")
"""

from __future__ import annotations

import warnings
from datetime import timedelta

import pandas as pd

from src.data_layer.cache import cached_call
from src.data_layer.symbols import to_chinastock
from src.data_sources.akshare_source import AkShareSource
from src.data_sources.base import DataSource, SourceRole

# 缓存 TTL：板块日 K 当日不再变化，24h
_SECTOR_TTL_HOURS: float = 24.0
# 成分股可能调整，1 天即可
_CONSTITUENT_TTL_HOURS: float = 24.0
# 概念名称列表变化不大，但探测开销大，TTL 设大一些
_CONCEPT_NAME_TTL_HOURS: float = 24.0


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


def _safe_akshare_call(func, *args, **kwargs) -> pd.DataFrame:
    try:
        result = func(*args, **kwargs)
        if result is None:
            return pd.DataFrame()
        return result if isinstance(result, pd.DataFrame) else pd.DataFrame(result)
    except Exception as e:  # noqa: BLE001
        warnings.warn(f"AKShare 调用 {func.__name__} 失败: {e}", stacklevel=2)
        return pd.DataFrame()


def _list_all_concept_names() -> list[str]:
    """获取所有概念板块名称（AKShare 唯一全量接口）。"""
    import akshare as ak

    def _fetch() -> list[str]:
        df = _safe_akshare_call(ak.stock_board_concept_name_em)
        if df.empty:
            return []
        # 概念名通常在 "板块名称" 或 "名称" 列
        for col in ("板块名称", "名称", "name"):
            if col in df.columns:
                names = df[col].dropna().astype(str).tolist()
                return [n for n in names if n]
        return []

    cache_key = "akshare.concept_name_list"
    # 复用 cached_call：返回 list 也能存
    df = cached_call(
        cache_key,
        {"v": 1},  # 单值 key
        fetcher=lambda: pd.DataFrame({"name": _fetch()}),
        ttl_hours=_CONCEPT_NAME_TTL_HOURS,
    )
    return df["name"].tolist() if not df.empty else []


def find_symbol_sectors(
    symbol: str,
    *,
    source: DataSource | None = None,
    max_scan: int | None = None,
) -> list[str]:
    """给定一只票，反向查找它所属的概念板块。

    算法：遍历所有概念板块名 → 调 `get_sector_constituents` 探查 → 命中则加入结果。
    开销大（~300+ 概念），但每板块结果有缓存，所以首次后很快。

    :param symbol: `SH600519`
    :param max_scan: 限制最多扫多少个板块（用于快速预筛，默认全量）
    :return: 该票所属的概念板块名列表
    """
    target = to_chinastock(symbol)
    all_names = _list_all_concept_names()
    if max_scan is not None:
        all_names = all_names[:max_scan]
    matched: list[str] = []
    for name in all_names:
        members = get_sector_constituents(name, source=source)
        if members.empty or "symbol" not in members.columns:
            continue
        if target in members["symbol"].astype(str).tolist():
            matched.append(name)
    return matched


def detect_sector_resonance(
    symbol: str,
    date: str,
    *,
    min_count: int = 3,
    lookback_days: int = 5,
    pct_threshold: float = 3.0,
    source: DataSource | None = None,
) -> list[dict]:
    """板块共振检测：异动票所属概念板块中，`lookback_days` 日内累计涨幅 ≥ `pct_threshold%` 的板块数。

    :return: 命中的板块列表，每项包含 `sector, cum_pct_change, symbol, date`
    """
    sectors = find_symbol_sectors(symbol, source=source)
    if not sectors:
        return []
    end = pd.Timestamp(date)
    start = (end - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")
    hits: list[dict] = []
    for sec in sectors:
        perf = get_sector_performance(sec, start, end_str, source=source)
        if perf.empty or "pct_change" not in perf.columns:
            continue
        try:
            cum = float(
                pd.to_numeric(perf["pct_change"], errors="coerce").fillna(0).sum()
            )
        except Exception:  # noqa: BLE001
            continue
        if cum >= pct_threshold:
            hits.append(
                {
                    "sector": sec,
                    "cum_pct_change": round(cum, 2),
                    "symbol": symbol,
                    "date": date,
                }
            )
    return hits


__all__ = [
    "get_sector_constituents",
    "get_sector_performance",
    "find_symbol_sectors",
    "detect_sector_resonance",
]
