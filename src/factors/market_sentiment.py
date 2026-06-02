"""市场情绪因子。

把 `integrations.limit_up.market_sentiment_score` 的 dict 拍扁为 DataFrame，
方便与其他因子对齐做横截面研究。
"""

from __future__ import annotations

import pandas as pd

from src.integrations.limit_up import market_sentiment_score


def market_sentiment_factor(date: str) -> pd.DataFrame:
    """市场情绪综合因子（单行 DataFrame）。

    列：`date, limit_up_count, max_consecutive, broken_ratio, sentiment_code, value`
    `value` = 标准化后的情绪强度（0-1）
    - overheat = 1.0
    - normal   = 0.5
    - cold     = 0.0
    - unknown  = NaN
    """
    s = market_sentiment_score(date)
    sent_code = {"overheat": 1.0, "normal": 0.5, "cold": 0.0}.get(s["sentiment"], None)
    return pd.DataFrame(
        [
            {
                "date": s["date"],
                "limit_up_count": s["limit_up_count"],
                "max_consecutive": s["max_consecutive"],
                "broken_ratio": s["broken_ratio"],
                "sentiment_code": sent_code,
                "value": sent_code,
            }
        ]
    )


__all__ = ["market_sentiment_factor"]
