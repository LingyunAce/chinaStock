"""Analysis trust aggregation and serialization tests."""

from __future__ import annotations

from src.analysis.trust import (
    AnalysisTrust,
    SourceEvidence,
    TrustStatus,
    build_analysis_trust,
)
from src.data_layer.quality import QualityIssue


def evidence(status: str = "ok") -> SourceEvidence:
    return SourceEvidence(
        source="akshare",
        dataset="kline",
        as_of="2026-07-10",
        fetched_at="2026-07-10T16:00:00+08:00",
        status=status,
        row_count=60,
        adjustment="qfq",
    )


def test_no_issues_is_trusted_and_serializable():
    trust = build_analysis_trust(
        [], [evidence()], checked_at="2026-07-10T16:01:00+08:00"
    )

    assert trust.status is TrustStatus.TRUSTED
    assert trust.can_advise
    assert AnalysisTrust.from_dict(trust.to_dict()) == trust


def test_noncritical_issue_is_partial():
    trust = build_analysis_trust(
        [QualityIssue("optional_missing", "ratings unavailable", critical=False)],
        [evidence()],
        checked_at="2026-07-10T16:01:00+08:00",
    )

    assert trust.status is TrustStatus.PARTIAL
    assert not trust.can_advise


def test_non_ok_source_is_partial_without_explicit_issue():
    trust = build_analysis_trust(
        [], [evidence("empty")], checked_at="2026-07-10T16:01:00+08:00"
    )

    assert trust.status is TrustStatus.PARTIAL
    assert not trust.can_advise


def test_critical_issue_is_blocked():
    trust = build_analysis_trust(
        [QualityIssue("stale_data", "latest date is stale", critical=True)],
        [evidence("stale")],
        checked_at="2026-07-10T16:01:00+08:00",
    )

    assert trust.status is TrustStatus.BLOCKED
    assert not trust.can_advise
