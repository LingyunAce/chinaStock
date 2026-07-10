"""Pure data-quality checks used before analysis or advice generation."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

REQUIRED_KLINE_COLUMNS = ("date", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class QualityIssue:
    """A machine-readable reason why analysis data is not fully trustworthy."""

    code: str
    message: str
    source: str | None = None
    critical: bool = True


def validate_kline(
    df: pd.DataFrame,
    *,
    as_of: str,
    adjustment: str | None,
    min_rows: int = 60,
    max_age_days: int = 7,
) -> list[QualityIssue]:
    """Validate minimum OHLCV integrity without mutating the input frame."""

    issues: list[QualityIssue] = []
    missing = [column for column in REQUIRED_KLINE_COLUMNS if column not in df.columns]
    if missing:
        issues.append(QualityIssue("missing_columns", f"missing: {', '.join(missing)}"))
    if not adjustment:
        issues.append(QualityIssue("missing_adjustment", "adjustment is required"))
    if missing:
        return issues

    if len(df) < min_rows:
        issues.append(
            QualityIssue("insufficient_history", f"rows={len(df)} < {min_rows}")
        )

    parsed_dates = pd.to_datetime(df["date"], errors="coerce")
    if parsed_dates.isna().any():
        issues.append(QualityIssue("invalid_date", "one or more dates are invalid"))
        return issues
    if parsed_dates.duplicated().any():
        issues.append(QualityIssue("duplicate_date", "dates must be unique"))
    if not parsed_dates.is_monotonic_increasing:
        issues.append(QualityIssue("unsorted_date", "dates must be ascending"))

    cutoff = pd.Timestamp(as_of).normalize()
    if (parsed_dates.dt.normalize() > cutoff).any():
        issues.append(QualityIssue("future_date", "data contains a future date"))
    latest = parsed_dates.max().normalize()
    if cutoff - latest > pd.Timedelta(days=max_age_days):
        issues.append(QualityIssue("stale_data", f"latest={latest.date()}"))

    numeric = df[["open", "high", "low", "close", "volume"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if numeric.isna().any().any():
        issues.append(
            QualityIssue(
                "non_numeric_ohlcv", "OHLCV contains null/non-numeric values"
            )
        )
        return issues
    if (numeric["volume"] < 0).any():
        issues.append(QualityIssue("negative_volume", "volume must be non-negative"))

    invalid = (
        (numeric["high"] < numeric[["open", "close"]].max(axis=1))
        | (numeric["low"] > numeric[["open", "close"]].min(axis=1))
        | (numeric["high"] < numeric["low"])
    )
    if invalid.any():
        issues.append(
            QualityIssue("invalid_ohlc", "OHLC price relationship is invalid")
        )
    return issues


__all__ = ["QualityIssue", "REQUIRED_KLINE_COLUMNS", "validate_kline"]
