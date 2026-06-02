"""龙虎榜相关因子。

因子：
- institutional_net_buy: 个股当日机构净买入额（来自龙虎榜）
- lhb_signal_score: 龙虎榜上榜信号强度打分（多维加权）
"""
from __future__ import annotations

import pandas as pd

from src.data_sources.base import DataSource
from src.integrations.lhb import get_lhb


def institutional_net_buy(
    date: str,
    *,
    source: DataSource | None = None,
) -> pd.DataFrame:
    """个股当日龙虎榜机构/营业部净买入。

    返回列：`date, symbol, name, net_buy_amount, value`
    `value` = `net_buy_amount`（直接复制为因子值，便于下游统一处理）
    """
    df = get_lhb(symbol=None, date=date, source=source)
    if df.empty:
        return pd.DataFrame(columns=["date", "symbol", "name", "net_buy_amount", "value"])
    keep = [c for c in ("date", "symbol", "name", "net_buy_amount") if c in df.columns]
    out = df[keep].copy()
    out["value"] = pd.to_numeric(out.get("net_buy_amount", 0), errors="coerce").fillna(0)
    return out


def lhb_signal_score(
    date: str,
    *,
    source: DataSource | None = None,
    amount_threshold: float = 5_000_000.0,
) -> pd.DataFrame:
    """龙虎榜信号强度打分（0-1 之间，越大越强）。

    维度（启发式，可调）：
    - 净买入额超过 amount_threshold → +0.5
    - 涨跌幅绝对值 < 5% → +0.2（避免追高）
    - 多次上榜 → +0.3
    """
    df = get_lhb(symbol=None, date=date, source=source)
    if df.empty:
        return pd.DataFrame(columns=["date", "symbol", "name", "score", "value"])

    out = df.copy()
    out["net_buy_amount"] = pd.to_numeric(out.get("net_buy_amount", 0), errors="coerce").fillna(0)
    out["pct_change"] = pd.to_numeric(out.get("pct_change", 0), errors="coerce").fillna(0)
    out["pct_change_abs"] = out["pct_change"].abs()

    score = pd.Series(0.0, index=out.index)
    score += (out["net_buy_amount"] > amount_threshold).astype(float) * 0.5
    score += (out["pct_change_abs"] < 5.0).astype(float) * 0.2
    # 多次上榜（这里以"上榜次数"近似；AKShare 一次返回当日上榜，1 票多次出现在不同列中）
    list_counts = out.groupby("symbol").size()
    multi = out["symbol"].map(list_counts) > 1
    score += multi.astype(float) * 0.3

    out["score"] = score.clip(0, 1)
    out["value"] = out["score"]
    keep = [c for c in ("date", "symbol", "name", "score", "value") if c in out.columns]
    return out[keep]


__all__ = ["institutional_net_buy", "lhb_signal_score"]
