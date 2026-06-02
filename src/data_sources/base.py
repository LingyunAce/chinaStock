"""数据源抽象接口（ABC）。

业务层只依赖此接口，不直接 import 具体数据源。
新增数据源时：实现 `DataSource` 子类，标注 `role` 即可。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

import pandas as pd


class SourceRole(str, Enum):
    """数据源角色。"""

    PRIMARY = "primary"               # 主力源（westock-data, neodata）
    SUPPLEMENTARY = "supplementary"   # 补充源（AKShare）
    VALIDATION = "validation"         # 交叉验证用


class DataSource(ABC):
    """所有数据源必须实现的接口。"""

    role: SourceRole
    name: str

    # ---------------------- 龙虎榜 ----------------------
    @abstractmethod
    def get_lhb(self, symbol: str | None, date: str, **kw) -> pd.DataFrame:
        """龙虎榜。

        :param symbol: `SH600519` / None（None 表示全市场）
        :param date: `YYYY-MM-DD`
        :return: 归一化后的 DataFrame，列：date, symbol, name, net_buy_amount, ...
        """

    # ---------------------- 涨停池 ----------------------
    @abstractmethod
    def get_limit_up_pool(self, date: str, **kw) -> pd.DataFrame:
        """涨停池（含连板信息）。

        :param date: `YYYY-MM-DD`
        :return: 归一化后的 DataFrame，列：date, symbol, name, consecutive_boards, ...
        """

    # ---------------------- 板块/概念 ----------------------
    @abstractmethod
    def get_sector_constituents(self, sector: str, **kw) -> pd.DataFrame:
        """板块/概念成分股。

        :param sector: 概念名（如 "机器人" / "锂电池"）
        :return: DataFrame，列：symbol, name
        """

    @abstractmethod
    def get_sector_perf(self, sector: str, start: str, end: str, **kw) -> pd.DataFrame:
        """板块/概念日 K 线。

        :param sector: 概念名
        :param start: `YYYY-MM-DD`
        :param end: `YYYY-MM-DD`
        :return: DataFrame，列：date, open, close, high, low, volume, amount, pct_change
        """

    # ---------------------- 交叉验证 ----------------------
    @abstractmethod
    def get_quote_for_validation(self, symbol: str, date: str, **kw) -> pd.DataFrame:
        """拉取与主源同口径的 K 线，用于跨源数据校验。

        :param symbol: `SH600519`
        :param date: `YYYY-MM-DD`
        :return: DataFrame，列：date, symbol, open, close, high, low, volume, amount
        """


__all__ = ["DataSource", "SourceRole"]
