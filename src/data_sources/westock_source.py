"""westock-data 数据源适配器（主源）— 占位符。

当前 MVP 阶段：westock-data 通过 `.claude/skills/westock-data/scripts/index.js` Node CLI
调用（不在本计划的实现范围）。本文件保留 stub 以满足 `DataSource` ABC 完整性，
并防止业务层误以为主源未接入。

后续实现计划：
- 通过 subprocess 调用 westock-data CLI（用 `to_westock()` 转代码格式）
- 解析 JSON stdout 为 DataFrame
- 实现 K 线/财务/分红/股东/北向等 westock 独有的接口
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.data_sources.base import DataSource, SourceRole


class WestockSource(DataSource):
    """westock-data 适配器（主源）— 待实现。"""

    role: SourceRole = SourceRole.PRIMARY
    name: str = "westock"

    def _not_implemented(self, method: str) -> pd.DataFrame:
        raise NotImplementedError(
            f"WestockSource.{method} 待实现；当前 MVP 阶段由 AKShare 提供同口径数据。"
            f"调用方应先尝试 WestockSource，失败时 fallback 到 AkShareSource。"
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


__all__ = ["WestockSource"]
