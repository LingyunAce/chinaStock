"""资金流因子 — 评估标的的资金关注度。

数据源:
- westock `lhb --tab jg/yzb/gslmr/gslxw` — 龙虎榜 (机构/游资/高胜率席位)
- westock `hot stock` — 涨停异动股 (代理主力资金净流入)
- (北向资金 / 融资融券 westock 当前版本不返回, 留接口)

判断逻辑:
1. 龙虎榜异动: 当日是否上榜 (jg/yzb/yyb) + 几次 + 净买入额
2. 涨停异动: 当日是否在 hot stock 列表 (zdf > 7%)
3. 综合评分 0-100

注意: westock 的 lhb 在非交易日会返回空表, 这是正常的。
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from src.data_sources.base import DataSourceError
from src.data_sources.westock_source import _call_westock, _parse_markdown_table

_CACHE_HOT: tuple[float, pd.DataFrame] | None = None
_CACHE_LHB: dict[str, tuple[float, pd.DataFrame]] = {}
_CACHE_TTL_SECONDS = 300


def _to_num(s: Any) -> float:
    """westock 中文数字 (1.5亿 / 2000万) → float。"""
    if s is None:
        return 0.0
    s = str(s).strip()
    if not s or s in ("-", "--", "—"):
        return 0.0
    s = s.replace(",", "").replace("%", "")
    mult = 1.0
    if s.endswith("亿"):
        mult = 1e8
        s = s[:-1]
    elif s.endswith("万"):
        mult = 1e4
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return 0.0


def fetch_hot_stock(force: bool = False) -> pd.DataFrame:
    """拉取热搜股, 解析 zdf / zxj。"""
    global _CACHE_HOT
    now = time.time()
    if (
        not force
        and _CACHE_HOT is not None
        and (now - _CACHE_HOT[0]) < _CACHE_TTL_SECONDS
    ):
        return _CACHE_HOT[1]
    try:
        text = _call_westock(["hot", "stock", "--limit", "30"], timeout=15)
    except Exception as exc:  # noqa: BLE001 - 转换为统一的数据源边界异常
        raise DataSourceError("westock", "hot_stock", str(exc)) from exc
    df = _parse_markdown_table(text)
    if df.empty:
        return df
    rename = {"code": "code", "name": "name", "zdf": "zdf", "zxj": "zxj"}
    out = df.rename(columns=rename)
    if "zdf" in out.columns:
        out["zdf"] = pd.to_numeric(out["zdf"], errors="coerce")
    if "zxj" in out.columns:
        out["zxj"] = pd.to_numeric(out["zxj"], errors="coerce")
    out["symbol"] = out["code"].apply(
        lambda x: _code_to_symbol(str(x).lower()) if pd.notna(x) else None
    )
    _CACHE_HOT = (now, out)
    return out


def fetch_lhb(westock_code: str, force: bool = False) -> pd.DataFrame:
    """拉取龙虎榜 (机构榜 jg)。"""
    now = time.time()
    if (
        not force
        and westock_code in _CACHE_LHB
        and (now - _CACHE_LHB[westock_code][0]) < _CACHE_TTL_SECONDS
    ):
        return _CACHE_LHB[westock_code][1]
    yesterday = datetime_to_yyyymmdd()
    try:
        text = _call_westock(["lhb", "--tab", "jg", "--date", yesterday], timeout=15)
    except Exception as exc:  # noqa: BLE001 - 转换为统一的数据源边界异常
        raise DataSourceError("westock", "lhb", str(exc)) from exc
    df = _parse_markdown_table(text)
    if df.empty:
        _CACHE_LHB[westock_code] = (now, df)
        return df
    if "净买入额" in df.columns:
        df["net_buy_amount"] = df["净买入额"].apply(_to_num)
    if "机构买入额" in df.columns:
        df["inst_buy_amount"] = df["机构买入额"].apply(_to_num)
    _CACHE_LHB[westock_code] = (now, df)
    return df


def datetime_to_yyyymmdd() -> str:
    """返回最近一个交易日的 yyyymmdd 字符串。

    简化: 总是返回昨天的日期 (假设 T+1 数据)
    """
    from datetime import datetime, timedelta

    yesterday = datetime.today() - timedelta(days=1)
    return yesterday.strftime("%Y%m%d")


def _code_to_symbol(westock_code: str) -> str | None:
    """sh600519 / sz000001 → SH600519 / SZ000001."""
    if not westock_code or westock_code == "-":
        return None
    code = westock_code.lower()
    if code.startswith(("sh", "sz", "bj")):
        prefix = code[:2].upper()
        digits = code[2:]
    else:
        return None
    if not digits.isdigit():
        return None
    return f"{prefix}{int(digits):06d}"


def evaluate(westock_code: str, *, force: bool = False) -> dict:
    """评估某只票的资金流热度。

    :param westock_code: westock 格式代码, e.g. 'sh600519'
    :return: dict {
        'is_on_lhb': bool,        # 当日龙虎榜上榜
        'is_limit_up': bool,      # 当日涨停 (>7% 算代理涨停)
        'lhb_net_buy': float,     # 净买入额
        'hot_rank': int | None,   # 热搜排名
        'is_flow_hot': bool,      # 综合: 上榜 OR 涨停 OR 排名 top 10
        'score': 0-100,
        'reason': str             # 解释为何打这个分
    }
    """
    symbol = _code_to_symbol(westock_code)
    result: dict[str, Any] = {
        "is_on_lhb": False,
        "is_limit_up": False,
        "lhb_net_buy": 0.0,
        "hot_rank": None,
        "is_flow_hot": False,
        "score": 50.0,
        "reason": "无显著资金异动",
    }

    # 1. 龙虎榜
    lhb = fetch_lhb(westock_code, force=force)
    if not lhb.empty and symbol and "代码" in lhb.columns:
        target = lhb[lhb["代码"].str.lower() == westock_code]
        if not target.empty:
            result["is_on_lhb"] = True
            result["lhb_net_buy"] = (
                float(target["net_buy_amount"].sum())
                if "net_buy_amount" in target.columns
                else 0
            )
            inst_buy = (
                float(target["inst_buy_amount"].sum())
                if "inst_buy_amount" in target.columns
                else 0
            )
            if result["lhb_net_buy"] > 5e6 or inst_buy > 1e7:
                result["reason"] = (
                    f"机构龙虎榜净买入 {result['lhb_net_buy'] / 1e8:.2f} 亿 (强关注)"
                )

    # 2. 涨停异动 (hot stock)
    hot = fetch_hot_stock(force=force)
    if not hot.empty and symbol and "symbol" in hot.columns:
        match = hot[hot["symbol"] == symbol]
        if not match.empty:
            row = match.iloc[0]
            zdf = float(row.get("zdf", 0))
            rank = int(row.get("rank", 99)) if "rank" in hot.columns else None
            if rank is None and "zdf" in hot.columns:
                # 没显式 rank 字段时按 zdf 排序估算
                sorted_hot = hot.sort_values("zdf", ascending=False).reset_index(
                    drop=True
                )
                rank = sorted_hot.index[sorted_hot["symbol"] == symbol].tolist()
                rank = (rank[0] + 1) if rank else 99
            result["hot_rank"] = rank
            if zdf >= 7.0:
                result["is_limit_up"] = True
                if not result["reason"].startswith("机构"):
                    result["reason"] = f"涨停异动 +{zdf:.1f}%, 热搜 #{rank}"
                else:
                    result["reason"] += f" + 涨停 +{zdf:.1f}%"

    # 3. 综合评分
    score = 50.0
    if result["is_on_lhb"]:
        score += 25
    if result["is_limit_up"]:
        score += 15
    if result["hot_rank"] and result["hot_rank"] <= 5:
        score += 10
    elif result["hot_rank"] and result["hot_rank"] <= 15:
        score += 5
    result["score"] = min(100, score)
    result["is_flow_hot"] = result["score"] >= 65
    return result


__all__ = [
    "evaluate",
    "fetch_hot_stock",
    "fetch_lhb",
]
