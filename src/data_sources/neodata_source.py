"""neodata-financial-search 数据源适配器（主源）— 占位符。

当前 MVP 阶段：neodata 通过 `.claude/skills/neodata-financial-search/scripts/query.py` CLI
或 HTTP 调用（不在本计划的实现范围）。本文件保留 stub 以满足 `DataSource` ABC 完整性。

后续实现计划：
- 通过 HTTP 调用 https://copilot.tencent.com/agenttool/v1/neodata
- 自然语言查询 → 结构化 DataFrame
- 实现 NLP 检索类接口（"近一年 A 股分红率最高的 10 只票"等）
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.data_sources.base import DataSource, SourceRole


class NeodataSource(DataSource):
    """neodata-financial-search 适配器（主源）— 待实现。"""

    role: SourceRole = SourceRole.PRIMARY
    name: str = "neodata"

    def _not_implemented(self, method: str) -> pd.DataFrame:
        raise NotImplementedError(
            f"NeodataSource.{method} 待实现；当前 MVP 阶段由 AKShare 提供同口径数据。"
            f"调用方应先尝试 WestockSource，失败时 fallback 到 NeodataSource / AkShareSource。"
        )

    def get_lhb(self, symbol: str | None, date: str, **kw: Any) -> pd.DataFrame:
        return self._not_implemented("get_lhb")

    def get_limit_up_pool(self, date: str, **kw: Any) -> pd.DataFrame:
        return self._not_implemented("get_limit_up_pool")

    def get_sector_constituents(self, sector: str, **kw: Any) -> pd.DataFrame:
        return self._not_implemented("get_sector_constituents")

    def get_sector_perf(self, sector: str, start: str, end: str, **kw: Any) -> pd.DataFrame:
        return self._not_implemented("get_sector_perf")

    def get_quote_for_validation(self, symbol: str, date: str, **kw: Any) -> pd.DataFrame:
        return self._not_implemented("get_quote_for_validation")


__all__ = ["NeodataSource"]
