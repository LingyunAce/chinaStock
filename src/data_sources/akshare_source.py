"""AKShare 数据源适配器（补充源）。

调用约定：
- 入口参数：chinaStock 内部约定（`SH600519`、`YYYY-MM-DD`）
- 内部转换：经 `src.data_layer.symbols.to_akshare` 转为 6 位代码
- AKShare 接口调用包在 try/except 中，失败时抛出结构化 DataSourceError
- 业务层不直接 import akshare，统一走此模块

注意：AKShare 接口偶发返回字段名与文档不一致（同一接口不同时间可能改字段），
归一化层（src.data_layer.normalize）做兼容；本模块不做列名假设。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.data_layer.normalize import (
    normalize_lhb,
    normalize_limit_up,
    normalize_sector_constituents,
    normalize_sector_ohlcv,
)
from src.data_layer.symbols import to_akshare
from src.data_sources.base import DataSource, DataSourceError, SourceRole

try:
    import akshare as ak
except ImportError as e:  # pragma: no cover - 由 requirements.txt 锁定
    raise ImportError("akshare 未安装，请先 `pip install -r requirements.txt`") from e


def _safe_call(func, *args, **kwargs) -> pd.DataFrame:
    """包装 AKShare 调用，区分合法空结果与外部调用失败。"""
    try:
        result = func(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - 转换为统一的数据源边界异常
        raise DataSourceError("akshare", func.__name__, str(exc)) from exc
    if result is None:
        return pd.DataFrame()
    if isinstance(result, pd.DataFrame):
        return result
    return pd.DataFrame(result)


class AkShareSource(DataSource):
    """AKShare 数据源，作为 chinaStock 的补充源。

    只实现 AKShare 覆盖度高 / westock 没有的接口：
    - 龙虎榜、涨停池、连板、板块/概念
    - 不重复实现 westock 已有的 K 线、实时价等基础接口
    """

    role: SourceRole = SourceRole.SUPPLEMENTARY
    name: str = "akshare"

    # ---------------------- 龙虎榜 ----------------------
    def get_lhb(self, symbol: str | None, date: str, **kw: Any) -> pd.DataFrame:
        """龙虎榜：symbol=None 查全市场日榜，symbol 给定查个股近期上榜记录。"""
        ymd = date.replace("-", "")
        if symbol is None:
            # 全市场日榜
            raw = _safe_call(ak.stock_lhb_stock_statistic_em, symbol="近一月")
            # 当日筛选
            if not raw.empty and "上榜日期" in raw.columns:
                raw = raw[raw["上榜日期"].astype(str).str.contains(ymd, na=False)]
        else:
            code = to_akshare(symbol)
            # 个股近期龙虎榜
            raw = _safe_call(ak.stock_lhb_stock_statistic_em, symbol=code)
        normalized = normalize_lhb(raw)
        if not normalized.empty and "date" in normalized.columns:
            normalized["date"] = ymd  # 强制为查询日
        return normalized

    # ---------------------- 涨停池 ----------------------
    def get_limit_up_pool(self, date: str, **kw: Any) -> pd.DataFrame:
        """涨停池 + 连板信息。"""
        ymd = date.replace("-", "")
        # 涨停池
        pool = _safe_call(ak.stock_zt_pool_em, date=ymd)
        pool_norm = normalize_limit_up(pool)
        # 连板
        zbgc = _safe_call(ak.stock_zt_pool_zbgc_em, date=ymd)
        if not zbgc.empty:
            zbgc_norm = normalize_limit_up(zbgc)
            # 合并连板数到涨停池
            if (
                not pool_norm.empty
                and "symbol" in pool_norm.columns
                and "symbol" in zbgc_norm.columns
                and "consecutive_boards" in zbgc_norm.columns
            ):
                streak = zbgc_norm[["symbol", "consecutive_boards"]]
                pool_norm = pool_norm.merge(streak, on="symbol", how="left")
        if not pool_norm.empty:
            pool_norm["date"] = date
        return pool_norm

    # ---------------------- 板块/概念 ----------------------
    def get_sector_constituents(self, sector: str, **kw: Any) -> pd.DataFrame:
        """概念板块成分股。"""
        raw = _safe_call(ak.stock_board_concept_cons_em, symbol=sector)
        return normalize_sector_constituents(raw)

    def get_sector_perf(
        self, sector: str, start: str, end: str, **kw: Any
    ) -> pd.DataFrame:
        """概念板块日 K 线（按 period='daily'）。"""
        start_ymd = start.replace("-", "")
        end_ymd = end.replace("-", "")
        raw = _safe_call(
            ak.stock_board_concept_hist_em,
            symbol=sector,
            period="daily",
            start_date=start_ymd,
            end_date=end_ymd,
            adjust="qfq",
        )
        return normalize_sector_ohlcv(raw)

    # ---------------------- 交叉验证 ----------------------
    def get_quote_for_validation(
        self, symbol: str, date: str, **kw: Any
    ) -> pd.DataFrame:
        """拉 AKShare 个股日 K（与 westock 同口径），用于跨源数据校验。"""
        code = to_akshare(symbol)
        end_dt = pd.Timestamp(date)
        start_dt = end_dt - pd.Timedelta(days=5)
        raw = _safe_call(
            ak.stock_zh_a_hist,
            symbol=code,
            period="daily",
            start_date=start_dt.strftime("%Y%m%d"),
            end_date=end_dt.strftime("%Y%m%d"),
            adjust="qfq",
        )
        if raw.empty:
            return raw
        # 归一化：用通用重命名（见 normalize_sector_ohlcv 的列名表已够用）
        from src.data_layer.symbols import to_chinastock

        out = raw.rename(
            columns={
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
                "振幅": "amplitude",
                "涨跌幅": "pct_change",
                "涨跌额": "change_amount",
                "换手率": "turnover",
            }
        )
        if "date" in out.columns:
            out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime(
                "%Y-%m-%d"
            )
        out["symbol"] = to_chinastock(symbol)
        return out


__all__ = ["AkShareSource"]
