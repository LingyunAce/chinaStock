"""Aggregate data-quality evidence into an advice eligibility state."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

from src.data_layer.quality import QualityIssue


class TrustStatus(str, Enum):
    TRUSTED = "trusted"
    PARTIAL = "partial"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class SourceEvidence:
    source: str
    dataset: str
    as_of: str | None
    fetched_at: str
    status: str
    row_count: int
    adjustment: str | None = None


@dataclass(frozen=True)
class AnalysisTrust:
    status: TrustStatus
    issues: tuple[QualityIssue, ...]
    source_manifest: tuple[SourceEvidence, ...]
    checked_at: str

    @property
    def can_advise(self) -> bool:
        return self.status is TrustStatus.TRUSTED

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "issues": [asdict(item) for item in self.issues],
            "source_manifest": [asdict(item) for item in self.source_manifest],
            "checked_at": self.checked_at,
        }

    @classmethod
    def from_dict(cls, value: dict) -> AnalysisTrust:
        return cls(
            status=TrustStatus(value["status"]),
            issues=tuple(
                QualityIssue(**item) for item in value.get("issues", [])
            ),
            source_manifest=tuple(
                SourceEvidence(**item)
                for item in value.get("source_manifest", [])
            ),
            checked_at=value["checked_at"],
        )


def build_analysis_trust(
    issues: list[QualityIssue],
    source_manifest: list[SourceEvidence],
    *,
    checked_at: str,
) -> AnalysisTrust:
    if any(issue.critical for issue in issues):
        status = TrustStatus.BLOCKED
    elif issues or any(item.status != "ok" for item in source_manifest):
        status = TrustStatus.PARTIAL
    else:
        status = TrustStatus.TRUSTED
    return AnalysisTrust(status, tuple(issues), tuple(source_manifest), checked_at)


__all__ = [
    "AnalysisTrust",
    "SourceEvidence",
    "TrustStatus",
    "build_analysis_trust",
]
