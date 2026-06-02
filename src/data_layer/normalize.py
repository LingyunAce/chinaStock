"""AKShare 字段归一化：中文列名 → chinaStock snake_case。

约定（来自 README）：
- 列名：`{category}_{name}` 形式（snake_case）
- 代码：带前缀大写（`SH600519`）
- 日期：`YYYY-MM-DD`

每个 `normalize_*` 函数对 DataFrame 做三件事：
1. 重命名列为 snake_case
2. 把代码列（`code` / `代码`）转为 `SH600519`
3. 把日期列归一为 `YYYY-MM-DD` 字符串
"""
from __future__ import annotations

import pandas as pd

from src.data_layer.symbols import to_chinastock


# ----------------------------- 龙虎榜 -----------------------------
LHB_RENAME: dict[str, str] = {
    "代码": "code",
    "名称": "name",
    "上榜日期": "date",
    "解读": "interpretation",
    "买方营业部": "buyer_branch",
    "卖方营业部": "seller_branch",
    "净买入额": "net_buy_amount",
    "买入金额": "buy_amount",
    "卖出金额": "sell_amount",
    "成交金额": "trade_amount",
    "涨跌幅": "pct_change",
    "上榜后1日": "rank_after_1d",
    "上榜后2日": "rank_after_2d",
    "上榜后5日": "rank_after_5d",
    "上榜后10日": "rank_after_10d",
}


def normalize_lhb(df: pd.DataFrame) -> pd.DataFrame:
    """龙虎榜字段归一化。

    输入：AKShare 龙虎榜接口返回的 DataFrame（中文列名）
    输出：snake_case 列名，`symbol` 列，`date` 列为 YYYY-MM-DD
    """
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.rename(columns=LHB_RENAME)
    if "code" in out.columns:
        out["symbol"] = out["code"].apply(
            lambda x: to_chinastock(str(x).zfill(6)) if pd.notna(x) else None
        )
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return out


# ----------------------------- 涨停池 -----------------------------
LIMIT_UP_RENAME: dict[str, str] = {
    "序号": "rank",
    "代码": "code",
    "名称": "name",
    "涨跌幅": "pct_change",
    "最新价": "price",
    "成交额": "amount",
    "流通市值": "float_mcap",
    "总市值": "total_mcap",
    "换手率": "turnover",
    "封板资金": "sealed_amount",
    "首次封板时间": "first_seal_time",
    "最后封板时间": "last_seal_time",
    "炸板次数": "broken_count",
    "涨停统计": "limit_up_streak",
    "连板数": "consecutive_boards",
    "所属行业": "industry",
    "概念": "concept",
}


def normalize_limit_up(df: pd.DataFrame) -> pd.DataFrame:
    """涨停池字段归一化。"""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.rename(columns=LIMIT_UP_RENAME)
    if "code" in out.columns:
        out["symbol"] = out["code"].apply(
            lambda x: to_chinastock(str(x).zfill(6)) if pd.notna(x) else None
        )
    return out


# ----------------------------- 板块/概念 -----------------------------
SECTOR_RENAME: dict[str, str] = {
    "日期": "date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "涨跌幅": "pct_change",
    "涨跌额": "change_amount",
    "成交量": "volume",
    "成交额": "amount",
    "换手率": "turnover",
    "代码": "code",
    "名称": "name",
}


def normalize_sector_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """板块/概念日 K 线字段归一化。"""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.rename(columns=SECTOR_RENAME)
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return out


SECTOR_CONSTITUENT_RENAME: dict[str, str] = {
    "代码": "code",
    "名称": "name",
    "最新价": "price",
    "涨跌幅": "pct_change",
    "涨跌额": "change_amount",
    "成交额": "amount",
    "流通市值": "float_mcap",
    "总市值": "total_mcap",
    "换手率": "turnover",
}


def normalize_sector_constituents(df: pd.DataFrame) -> pd.DataFrame:
    """板块/概念成分股字段归一化。"""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.rename(columns=SECTOR_CONSTITUENT_RENAME)
    if "code" in out.columns:
        out["symbol"] = out["code"].apply(
            lambda x: to_chinastock(str(x).zfill(6)) if pd.notna(x) else None
        )
    return out


__all__ = [
    "LHB_RENAME",
    "LIMIT_UP_RENAME",
    "SECTOR_RENAME",
    "SECTOR_CONSTITUENT_RENAME",
    "normalize_lhb",
    "normalize_limit_up",
    "normalize_sector_ohlcv",
    "normalize_sector_constituents",
]
