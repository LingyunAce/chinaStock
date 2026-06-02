"""龙虎榜集成：异动归因的"身份证"。

用法：
    from src.integrations.lhb import get_lhb, explain_anomaly
    df = get_lhb("SH600519", "2025-12-15")              # 单只票当日龙虎榜
    report = explain_anomaly("SH600519", "2025-12-15")  # 异动归因报告
"""

from __future__ import annotations

import pandas as pd

from src.data_layer.cache import cached_call
from src.data_sources.akshare_source import AkShareSource
from src.data_sources.base import DataSource, SourceRole

# 缓存 TTL：龙虎榜日内不再更新，6h 足够
_LHB_TTL_HOURS: float = 6.0


def get_lhb(
    symbol: str | None,
    date: str,
    *,
    source: DataSource | None = None,
    ttl_hours: float = _LHB_TTL_HOURS,
    force: bool = False,
) -> pd.DataFrame:
    """龙虎榜数据。

    :param symbol: `SH600519` / None（None 查全市场）
    :param date: `YYYY-MM-DD`
    :param source: 数据源实例（默认 `AkShareSource`）
    :param ttl_hours: 缓存 TTL（小时）
    :param force: 强制刷新
    :return: 归一化 DataFrame，列：`date, symbol, name, net_buy_amount, ...`
    """
    src = source or AkShareSource()
    if src.role == SourceRole.SUPPLEMENTARY:
        cache_name = "akshare.lhb"
    else:
        cache_name = f"{src.name}.lhb"
    params = {"symbol": symbol, "date": date}
    return cached_call(
        cache_name,
        params,
        fetcher=lambda: src.get_lhb(symbol, date),
        ttl_hours=ttl_hours,
        force=force,
    )


def explain_anomaly(symbol: str, date: str) -> dict:
    """异动归因报告：调用方拿到 `symbol + date` 时，一键产出背景信息。

    当前实现：仅返回该票当日的龙虎榜记录（如果有）。后续会扩展到
    板块共振 / 北向资金 / 业绩预告等。
    """
    df = get_lhb(symbol, date)
    return {
        "symbol": symbol,
        "date": date,
        "on_lhb": not df.empty,
        "lhb_records": df.to_dict(orient="records") if not df.empty else [],
    }


__all__ = ["get_lhb", "explain_anomaly"]
