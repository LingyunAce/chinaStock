"""Only trusted, complete inputs may produce deterministic advice."""

from __future__ import annotations

from src.analysis.advice import AdviceAction, generate_advice
from src.analysis.trust import AnalysisTrust, TrustStatus


def trust(status: TrustStatus) -> AnalysisTrust:
    return AnalysisTrust(status, (), (), "2026-07-10T16:00:00+08:00")


def test_blocked_and_partial_never_generate_advice():
    for status in (TrustStatus.BLOCKED, TrustStatus.PARTIAL):
        assert (
            generate_advice(
                trust=trust(status),
                as_of="2026-07-10",
                total_score=80,
                current_price=10,
                target_price=15,
                rsi=55,
            )
            is None
        )


def test_trusted_positive_evidence_generates_explainable_buy():
    advice = generate_advice(
        trust=trust(TrustStatus.TRUSTED),
        as_of="2026-07-10",
        total_score=72,
        current_price=10,
        target_price=12,
        rsi=55,
    )

    assert advice is not None
    assert advice.action is AdviceAction.BUY
    assert advice.supporting_evidence
    assert advice.invalidation_conditions


def test_trusted_overbought_signal_reduces_instead_of_buying():
    advice = generate_advice(
        trust=trust(TrustStatus.TRUSTED),
        as_of="2026-07-10",
        total_score=72,
        current_price=10,
        target_price=12,
        rsi=75,
    )

    assert advice is not None
    assert advice.action is AdviceAction.REDUCE
    assert any("RSI" in item for item in advice.risk_evidence)


def test_trusted_low_score_generates_sell():
    advice = generate_advice(
        trust=trust(TrustStatus.TRUSTED),
        as_of="2026-07-10",
        total_score=35,
        current_price=10,
        target_price=9,
        rsi=45,
    )

    assert advice is not None
    assert advice.action is AdviceAction.SELL


def test_trusted_mid_score_generates_hold():
    advice = generate_advice(
        trust=trust(TrustStatus.TRUSTED),
        as_of="2026-07-10",
        total_score=50,
        current_price=10,
        target_price=12,
        rsi=50,
    )

    assert advice is not None
    assert advice.action is AdviceAction.HOLD
