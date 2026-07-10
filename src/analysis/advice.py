"""Deterministic, trust-gated stock-analysis advice."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.analysis.trust import AnalysisTrust


class AdviceAction(str, Enum):
    BUY = "buy"
    HOLD = "hold"
    REDUCE = "reduce"
    SELL = "sell"
    WATCH = "watch"


@dataclass(frozen=True)
class Advice:
    action: AdviceAction
    as_of: str
    supporting_evidence: tuple[str, ...]
    risk_evidence: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    target_price: float | None = None
    stop_price: float | None = None


def generate_advice(
    *,
    trust: AnalysisTrust,
    as_of: str,
    total_score: float,
    current_price: float,
    target_price: float | None,
    rsi: float | None,
) -> Advice | None:
    if not trust.can_advise:
        return None

    supporting = [f"综合评分 {total_score:.0f}/100"]
    risks: list[str] = []
    if target_price is not None and target_price > current_price:
        upside = (target_price / current_price - 1) * 100
        supporting.append(f"目标价高于现价 {upside:.1f}%")
    elif target_price is not None:
        risks.append("目标价不高于现价")
    if rsi is not None and rsi >= 70:
        risks.append(f"RSI {rsi:.1f} 已进入超买区")

    if total_score >= 60 and not risks:
        action = AdviceAction.BUY
        invalidation = ("综合评分跌破 60", "RSI 升至 70 或以上")
    elif total_score < 40:
        action = AdviceAction.SELL
        invalidation = ("综合评分恢复至 40 或以上",)
    elif risks:
        action = AdviceAction.REDUCE
        invalidation = ("风险证据消失且综合评分维持 60 或以上",)
    elif total_score >= 40 and (target_price is not None or rsi is not None):
        action = AdviceAction.HOLD
        invalidation = ("综合评分跌破 40",)
    else:
        action = AdviceAction.WATCH
        invalidation = ("出现至少一个明确方向信号",)

    return Advice(
        action=action,
        as_of=as_of,
        supporting_evidence=tuple(supporting),
        risk_evidence=tuple(risks),
        invalidation_conditions=invalidation,
        target_price=target_price,
    )


__all__ = ["Advice", "AdviceAction", "generate_advice"]
