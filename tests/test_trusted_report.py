"""Report advice rendering is guarded by snapshot trust."""

from __future__ import annotations

from src.analysis.advice import Advice, AdviceAction
from src.analysis.trust import AnalysisTrust, SourceEvidence, TrustStatus
from src.data_layer.quality import QualityIssue
from scripts.gen_single_report import (
    _trust_from_snapshot,
    render_advice_section,
    render_trust_banner,
)


def test_legacy_snapshot_without_trust_is_blocked():
    trust = _trust_from_snapshot({})

    assert trust.status is TrustStatus.BLOCKED
    assert any(issue.code == "missing_trust" for issue in trust.issues)


def test_blocked_report_section_has_no_action_conclusion():
    trust = AnalysisTrust(
        TrustStatus.BLOCKED,
        (QualityIssue("kline_failed", "timeout"),),
        (),
        "2026-07-10T16:00:00+08:00",
    )

    rendered = render_advice_section(None, trust)

    assert "数据不足，禁止形成买卖结论" in rendered
    assert 'data-advice-action="none"' in rendered
    assert 'data-advice-action="buy"' not in rendered


def test_trusted_report_section_contains_evidence_and_manifest():
    trust = AnalysisTrust(
        TrustStatus.TRUSTED,
        (),
        (
            SourceEvidence(
                "akshare",
                "kline",
                "2026-07-10",
                "2026-07-10T16:00:00+08:00",
                "ok",
                80,
                "qfq",
            ),
        ),
        "2026-07-10T16:00:00+08:00",
    )
    advice = Advice(
        AdviceAction.BUY,
        "2026-07-10",
        ("综合评分 72/100",),
        (),
        ("综合评分跌破 60",),
    )

    rendered = render_advice_section(advice, trust) + render_trust_banner(trust)

    assert 'data-advice-action="buy"' in rendered
    assert "支持证据" in rendered
    assert "失效条件" in rendered
    assert "qfq" in rendered
    assert "不构成收益保证" in rendered
