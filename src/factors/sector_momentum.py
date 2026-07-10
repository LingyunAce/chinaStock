"""板块动量因子 — 评估标的所属行业/概念在当下的强度。

数据源：westock `hot board`（行业 zdf 实时排名） + `sector --list`（概念清单）。

判断逻辑:
1. 取 `hot board` 拿到所有行业的当日涨跌幅
2. 取 profile 拿到标的所属行业
3. 计算:
   - industry_rank: 该行业在所有行业中的排名（数字越小越强）
   - industry_zdf: 该行业当日涨跌幅
   - sector_score: 0-100 分（基于排名 + 涨幅）

注意:
- westock 的 `sector --rank` 字段 5d/20d/60d 在该版本中为空（返回 "-"），
  所以主要用 `hot board` 的实时 zdf 排名。
- 行业纯度（标的多少业务集中在该行业）未单独计分, 用 top1 industry 代表。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.data_sources.base import DataSourceError
from src.data_sources.westock_source import _call_westock, _parse_markdown_table

_CACHE_INDUSTRY: pd.DataFrame | None = None
_CACHE_TTL_SECONDS = 300  # 5 分钟


def fetch_industry_snapshot(force: bool = False) -> pd.DataFrame:
    """拉取所有行业的当日涨跌幅（hot board）。

    返回 DataFrame, 列: rank, code, name, zdf, zxj
    """
    global _CACHE_INDUSTRY
    import time

    if (
        not force
        and _CACHE_INDUSTRY is not None
        and hasattr(_CACHE_INDUSTRY, "_fetched_at")
        and (time.time() - _CACHE_INDUSTRY._fetched_at) < _CACHE_TTL_SECONDS
    ):
        return _CACHE_INDUSTRY

    try:
        text = _call_westock(["hot", "board", "--limit", "100"], timeout=15)
    except Exception as exc:  # noqa: BLE001 - 转换为统一的数据源边界异常
        raise DataSourceError("westock", "hot_board", str(exc)) from exc
    df = _parse_markdown_table(text)
    if df.empty:
        return df
    # 重命名 + 数值化
    rename = {
        "index": "idx",
        "symbol": "code",
        "name": "name",
        "zdf": "zdf",
        "zxj": "zxj",
        "rank": "rank",
        "rankdelta": "rank_delta",
    }
    out = df.rename(columns=rename)
    if "zdf" in out.columns:
        out["zdf"] = pd.to_numeric(out["zdf"], errors="coerce")
    if "rank" in out.columns:
        out["rank"] = pd.to_numeric(out["rank"], errors="coerce")
    if "rank_delta" in out.columns:
        out["rank_delta"] = pd.to_numeric(out["rank_delta"], errors="coerce")
    out = out.sort_values("zdf", ascending=False).reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)
    out._fetched_at = time.time()  # type: ignore[attr-defined]
    _CACHE_INDUSTRY = out
    return out


def fetch_industry_5d_change(industry_name: str) -> float | None:
    """拉取指定行业近 5 日累计涨跌幅（如果 westock 返回 "-" 则 None）。

    注: 当前 westock 版本 `sector --rank concept_list_industry --sort chg5Days` 返回
    的 5d/20d 列是 "-", 所以本函数目前主要返回 None, 保留作未来版本兼容。
    """
    # 留作 future: 当 westock 修复数据时
    return None


def evaluate(
    stock_profile: dict, industry_snapshot: pd.DataFrame | None = None
) -> dict:
    """评估某只票的板块动量。

    :param stock_profile: westock profile 字典（含 'industry' 字段）
    :param industry_snapshot: 可选, 行业快照, 缺省时自动拉取
    :return: dict {
        'industry': 行业名,
        'industry_zdf': 当日行业涨跌幅 (None if 找不到),
        'industry_rank': 行业排名 (None if 找不到),
        'is_sector_hot': bool,  # top 5 算热
        'is_top_sector': bool,   # top 3 算顶
        'top10_industries': [(name, zdf), ...]  # 用于展示
        'score': 0-100 综合动量分
    }
    """
    if industry_snapshot is None:
        industry_snapshot = fetch_industry_snapshot()

    industry = (stock_profile or {}).get("industry", "").strip()
    result: dict[str, Any] = {
        "industry": industry or "未知",
        "industry_zdf": None,
        "industry_rank": None,
        "is_sector_hot": False,
        "is_top_sector": False,
        "top10_industries": [],
        "score": 50.0,  # 默认中性
    }

    if industry_snapshot.empty or not industry:
        # 仍给个 top 10 列表
        if not industry_snapshot.empty:
            result["top10_industries"] = list(
                zip(
                    industry_snapshot["name"].head(10).tolist(),
                    industry_snapshot["zdf"].head(10).tolist(),
                )
            )
        return result

    # top 10 总是给
    result["top10_industries"] = list(
        zip(
            industry_snapshot["name"].head(10).tolist(),
            industry_snapshot["zdf"].head(10).tolist(),
        )
    )

    # 找该行业（精确匹配或模糊匹配）
    match = industry_snapshot[industry_snapshot["name"] == industry]
    if match.empty:
        # 模糊: 比如 "通信" 可能在 "通信设备" / "通信服务" 中匹配
        for keyword in [industry, industry[:2]]:
            match = industry_snapshot[
                industry_snapshot["name"].str.contains(keyword, na=False, regex=False)
            ]
            if not match.empty:
                break

    if match.empty:
        return result

    row = match.iloc[0]
    rank = int(row.get("rank", 99))
    zdf = float(row.get("zdf", 0))

    result["industry_zdf"] = zdf
    result["industry_rank"] = rank
    result["is_sector_hot"] = rank <= 5
    result["is_top_sector"] = rank <= 3

    # 评分: 综合排名和涨跌幅
    # 排名越靠前分越高 (rank=1 → 100, rank=30 → 50, rank=60+ → 30)
    rank_score = max(0, min(100, 100 - (rank - 1) * 1.5))
    # 涨跌幅加成 (-5% → 30, 0% → 50, +5% → 80, +10% → 100)
    zdf_score = max(0, min(100, 50 + zdf * 5))
    # 加权
    result["score"] = round(rank_score * 0.4 + zdf_score * 0.6, 1)
    return result


def is_beta_rebound_opportunity(
    perf_score: float,
    sector_result: dict,
    capital_result: dict | None = None,
    *,
    perf_threshold: float = 40.0,  # 业绩分低于此算"差"
    sector_threshold: float = 70.0,  # 板块分高于此算"强"
    capital_threshold: float = 60.0,  # 资金分高于此算"流入"
) -> tuple[bool, str]:
    """判断是否为"β 反弹机会"。

    逻辑：业绩差 + 板块强 (+ 资金流入) = 短期反弹机会, 不需要等业绩拐点。
    """
    sector_score = sector_result.get("score", 0) if sector_result else 0
    capital_score = capital_result.get("score", 0) if capital_result else 0
    is_hot = sector_result.get("is_sector_hot", False) if sector_result else False
    is_flow = capital_result.get("is_flow_hot", False) if capital_result else False

    if perf_score >= perf_threshold:
        return False, "业绩稳定, 不属于 β 反弹场景"

    reasons = []
    if is_hot or sector_score >= sector_threshold:
        reasons.append(f"板块强度 {sector_score:.0f}/100 (强)")
    if capital_result and (is_flow or capital_score >= capital_threshold):
        reasons.append(f"资金流入 {capital_score:.0f}/100 (流入)")

    if reasons:
        return True, "β 反弹机会: " + " + ".join(reasons)
    return (
        False,
        f"板块 {sector_score:.0f}/100 + 资金 {capital_score:.0f}/100, 都不支持反弹",
    )


__all__ = [
    "evaluate",
    "fetch_industry_snapshot",
    "is_beta_rebound_opportunity",
]
