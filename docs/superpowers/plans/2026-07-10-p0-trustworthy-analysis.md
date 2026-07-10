# P0 Trustworthy Stock Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make chinaStock emit buy/sell conclusions only from validated, fresh data and remove look-ahead bias from A-share backtests.

**Architecture:** Keep existing provider and report entry points, but insert three small boundaries: structured source errors, immutable data-quality/trust models, and a trust-gated advice engine. Replace same-day signal execution with a pending-order simulator that executes at the next tradable open and records A-share costs, limits, rejections, benchmark return, and sample warnings.

**Tech Stack:** Python 3.10+, pandas, NumPy, dataclasses, pytest, Ruff, existing westock-data and AKShare adapters.

## Global Constraints

- Only `TrustStatus.TRUSTED` may produce an `Advice`; `PARTIAL` and `BLOCKED` must return `None`.
- A close-derived signal on day T may execute no earlier than the next tradable open after T.
- Buy quantities are multiples of 100 shares; suspended/no-volume rows and price-limit rows cannot fill.
- Default costs are commission `0.0003`, minimum commission `5.0`, sell stamp duty `0.0005`, and slippage `0.0005`; every result exposes the actual configuration.
- Annualized return and Sharpe are `None` for fewer than 60 trading days.
- No live-network dependency in unit tests.
- Do not broaden P0 into a full `DataSource` capability refactor, database, service, or legacy-script cleanup.
- Preserve the main worktree's existing empty-rating-list fix in `scripts/gen_single_report.py` and numeric cross-source conversion fix in `scripts/analyze_sh600198.py`.

---

## File Map

- `src/data_sources/base.py`: shared structured provider exception.
- `src/data_sources/akshare_source.py`: distinguish provider failures from valid empty results and expose adjusted K-line retrieval.
- `src/factors/capital_flow.py`, `src/factors/sector_momentum.py`: propagate westock failures instead of manufacturing neutral values.
- `src/data_layer/quality.py`: pure OHLCV validation and issue codes.
- `src/analysis/trust.py`: trust status, source evidence, JSON serialization, and status aggregation.
- `src/analysis/advice.py`: deterministic advice that cannot bypass the trust gate.
- `strategies/base.py`: next-session A-share order simulator and trustworthy metrics.
- `scripts/analyze_one.py`: build a source manifest and trustworthy snapshot metadata.
- `scripts/gen_single_report.py`: consume snapshot trust/advice without live network calls.
- `scripts/run_backtest.py`: expose costs, benchmark, rejection reasons, and insufficient-sample metrics.
- `tests/test_data_source_errors.py`, `tests/test_data_quality.py`, `tests/test_analysis_trust.py`, `tests/test_advice.py`, `tests/test_backtest.py`, `tests/test_analyze_one.py`, `tests/test_trusted_report.py`: P0 regression coverage.

---

### Task 1: Structured Data-Source Failures

**Files:**
- Modify: `src/data_sources/base.py:15-78`
- Modify: `src/data_sources/akshare_source.py:20-47`
- Modify: `src/factors/capital_flow.py:18-101`
- Modify: `src/factors/sector_momentum.py:20-58`
- Create: `tests/test_data_source_errors.py`

**Interfaces:**
- Produces: `DataSourceError(source: str, operation: str, detail: str)` with `.source`, `.operation`, and `.detail`.
- Produces: `_safe_call()` returns an empty DataFrame for a successful `None` result and raises `DataSourceError` for an exception.
- Consumed later by: `scripts/analyze_one.py` and `src/analysis/trust.py`.

- [ ] **Step 1: Write failing provider-error tests**

```python
from __future__ import annotations

import pandas as pd
import pytest
from unittest.mock import patch

from src.data_sources.akshare_source import _safe_call
from src.data_sources.base import DataSourceError
from src.factors.capital_flow import fetch_hot_stock
from src.factors.sector_momentum import fetch_industry_snapshot


def test_akshare_none_result_is_valid_empty_frame():
    assert _safe_call(lambda: None).empty


def test_akshare_exception_is_not_converted_to_empty_frame():
    def fail():
        raise TimeoutError("upstream timeout")

    with pytest.raises(DataSourceError) as exc_info:
        _safe_call(fail)
    error = exc_info.value
    assert error.source == "akshare"
    assert error.operation == "fail"
    assert error.detail == "upstream timeout"


def test_akshare_dataframe_is_returned_unchanged():
    expected = pd.DataFrame({"value": [1]})
    assert _safe_call(lambda: expected).equals(expected)


def test_capital_flow_westock_failure_is_propagated():
    with patch(
        "src.factors.capital_flow._call_westock",
        side_effect=RuntimeError("westock unavailable"),
    ):
        with pytest.raises(DataSourceError) as exc_info:
            fetch_hot_stock(force=True)
    assert exc_info.value.operation == "hot_stock"


def test_sector_westock_failure_is_propagated():
    with patch(
        "src.factors.sector_momentum._call_westock",
        side_effect=RuntimeError("westock unavailable"),
    ):
        with pytest.raises(DataSourceError) as exc_info:
            fetch_industry_snapshot(force=True)
    assert exc_info.value.operation == "hot_board"
```

- [ ] **Step 2: Run the tests and confirm RED**

Run: `pytest tests/test_data_source_errors.py -v`

Expected: collection/import failure because `DataSourceError` does not exist, or failure because `_safe_call()` returns an empty frame for `TimeoutError`.

- [ ] **Step 3: Add the structured exception**

Add to `src/data_sources/base.py` before `DataSource`:

```python
class DataSourceError(RuntimeError):
    """External provider failed; this is not a successful empty dataset."""

    def __init__(self, source: str, operation: str, detail: str):
        self.source = source
        self.operation = operation
        self.detail = detail
        super().__init__(f"{source}.{operation}: {detail}")
```

Export it with `__all__ = ["DataSource", "DataSourceError", "SourceRole"]`.

Replace `_safe_call()` in `src/data_sources/akshare_source.py` with:

```python
from src.data_sources.base import DataSource, DataSourceError, SourceRole


def _safe_call(func, *args, **kwargs) -> pd.DataFrame:
    try:
        result = func(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - converted to a typed boundary error
        raise DataSourceError("akshare", func.__name__, str(exc)) from exc
    if result is None:
        return pd.DataFrame()
    if isinstance(result, pd.DataFrame):
        return result
    return pd.DataFrame(result)
```

Remove `import warnings` and update the module description so it says failures raise `DataSourceError`.

- [ ] **Step 4: Propagate westock factor failures**

In both factor modules, remove `warnings.filterwarnings("ignore")`. Replace each `_call_westock()` error branch with:

```python
from src.data_sources.base import DataSourceError

try:
    text = _call_westock(args, timeout=15)
except Exception as exc:  # noqa: BLE001 - normalize provider boundary
    raise DataSourceError("westock", operation, str(exc)) from exc
```

Use exact operations `hot_stock`, `lhb`, and `hot_board`. Do not catch these exceptions inside `evaluate()`; the snapshot orchestrator decides whether a failed dataset is critical or optional.

- [ ] **Step 5: Run focused tests**

Run: `pytest tests/test_data_source_errors.py tests/test_westock_source.py tests/test_factors.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/data_sources/base.py src/data_sources/akshare_source.py src/factors/capital_flow.py src/factors/sector_momentum.py tests/test_data_source_errors.py
git commit -m "fix: preserve data source failure semantics"
```

---

### Task 2: OHLCV Quality and Analysis Trust Models

**Files:**
- Create: `src/data_layer/quality.py`
- Create: `src/analysis/__init__.py`
- Create: `src/analysis/trust.py`
- Create: `tests/test_data_quality.py`
- Create: `tests/test_analysis_trust.py`

**Interfaces:**
- Produces: `validate_kline(df, *, as_of, min_rows=60, max_age_days=7, adjustment) -> list[QualityIssue]`.
- Produces: `TrustStatus`, `QualityIssue`, `SourceEvidence`, `AnalysisTrust`, `build_analysis_trust()`.
- Produces: `AnalysisTrust.to_dict()` and `AnalysisTrust.from_dict()`.

- [ ] **Step 1: Write failing quality tests**

```python
from __future__ import annotations

import pandas as pd

from src.data_layer.quality import validate_kline


def valid_bars(rows: int = 60) -> pd.DataFrame:
    dates = pd.bdate_range(end="2026-07-10", periods=rows)
    close = pd.Series(range(10, 10 + rows), dtype=float)
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 1_000,
    })


def codes(issues):
    return {issue.code for issue in issues}


def test_valid_kline_has_no_issues():
    assert validate_kline(valid_bars(), as_of="2026-07-10", adjustment="qfq") == []


def test_missing_columns_and_adjustment_are_critical():
    issues = validate_kline(
        pd.DataFrame({"date": ["2026-07-10"]}),
        as_of="2026-07-10",
        adjustment=None,
    )
    assert {"missing_columns", "missing_adjustment"} <= codes(issues)
    assert all(issue.critical for issue in issues)


def test_invalid_ohlc_duplicate_and_future_are_detected():
    bars = valid_bars()
    bars.loc[0, "high"] = bars.loc[0, "low"] - 1
    bars.loc[1, "date"] = bars.loc[0, "date"]
    bars.loc[len(bars) - 1, "date"] = "2026-07-11"
    issues = validate_kline(bars, as_of="2026-07-10", adjustment="qfq")
    assert {"invalid_ohlc", "duplicate_date", "future_date"} <= codes(issues)


def test_short_and_stale_history_are_detected():
    bars = valid_bars(20)
    bars["date"] = pd.bdate_range(end="2026-06-01", periods=20).strftime("%Y-%m-%d")
    issues = validate_kline(bars, as_of="2026-07-10", adjustment="qfq")
    assert {"insufficient_history", "stale_data"} <= codes(issues)
```

- [ ] **Step 2: Run quality tests and confirm RED**

Run: `pytest tests/test_data_quality.py -v`

Expected: import failure because `src.data_layer.quality` does not exist.

- [ ] **Step 3: Implement pure K-line validation**

Create `src/data_layer/quality.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

REQUIRED_KLINE_COLUMNS = ("date", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class QualityIssue:
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
    issues: list[QualityIssue] = []
    missing = [column for column in REQUIRED_KLINE_COLUMNS if column not in df.columns]
    if missing:
        issues.append(QualityIssue("missing_columns", f"missing: {', '.join(missing)}"))
    if not adjustment:
        issues.append(QualityIssue("missing_adjustment", "adjustment is required"))
    if missing:
        return issues
    if len(df) < min_rows:
        issues.append(QualityIssue("insufficient_history", f"rows={len(df)} < {min_rows}"))

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
    if cutoff - parsed_dates.max().normalize() > pd.Timedelta(days=max_age_days):
        issues.append(QualityIssue("stale_data", f"latest={parsed_dates.max().date()}"))

    numeric = df[["open", "high", "low", "close", "volume"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if numeric.isna().any().any():
        issues.append(QualityIssue("non_numeric_ohlcv", "OHLCV contains null/non-numeric values"))
        return issues
    if (numeric["volume"] < 0).any():
        issues.append(QualityIssue("negative_volume", "volume must be non-negative"))
    invalid = (
        (numeric["high"] < numeric[["open", "close"]].max(axis=1))
        | (numeric["low"] > numeric[["open", "close"]].min(axis=1))
        | (numeric["high"] < numeric["low"])
    )
    if invalid.any():
        issues.append(QualityIssue("invalid_ohlc", "OHLC price relationship is invalid"))
    return issues
```

- [ ] **Step 4: Run quality tests and confirm GREEN**

Run: `pytest tests/test_data_quality.py -v`

Expected: PASS.

- [ ] **Step 5: Write failing trust tests**

```python
from src.analysis.trust import AnalysisTrust, SourceEvidence, TrustStatus, build_analysis_trust
from src.data_layer.quality import QualityIssue


def evidence(status: str = "ok") -> SourceEvidence:
    return SourceEvidence(
        source="akshare", dataset="kline", as_of="2026-07-10",
        fetched_at="2026-07-10T16:00:00+08:00", status=status,
        row_count=60, adjustment="qfq",
    )


def test_no_issues_is_trusted_and_serializable():
    trust = build_analysis_trust([], [evidence()], checked_at="2026-07-10T16:01:00+08:00")
    assert trust.status is TrustStatus.TRUSTED
    assert trust.can_advise
    assert AnalysisTrust.from_dict(trust.to_dict()) == trust


def test_noncritical_issue_is_partial():
    trust = build_analysis_trust(
        [QualityIssue("optional_missing", "ratings unavailable", critical=False)],
        [evidence()], checked_at="2026-07-10T16:01:00+08:00",
    )
    assert trust.status is TrustStatus.PARTIAL
    assert not trust.can_advise


def test_critical_issue_is_blocked():
    trust = build_analysis_trust(
        [QualityIssue("stale_data", "latest date is stale", critical=True)],
        [evidence("stale")], checked_at="2026-07-10T16:01:00+08:00",
    )
    assert trust.status is TrustStatus.BLOCKED
    assert not trust.can_advise
```

- [ ] **Step 6: Run trust tests and confirm RED**

Run: `pytest tests/test_analysis_trust.py -v`

Expected: import failure because `src.analysis.trust` does not exist.

- [ ] **Step 7: Implement trust types and JSON round-trip**

Create `src/analysis/__init__.py` and `src/analysis/trust.py` with:

```python
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
    def from_dict(cls, value: dict) -> "AnalysisTrust":
        return cls(
            status=TrustStatus(value["status"]),
            issues=tuple(QualityIssue(**item) for item in value.get("issues", [])),
            source_manifest=tuple(SourceEvidence(**item) for item in value.get("source_manifest", [])),
            checked_at=value["checked_at"],
        )


def build_analysis_trust(
    issues: list[QualityIssue], source_manifest: list[SourceEvidence], *, checked_at: str
) -> AnalysisTrust:
    if any(issue.critical for issue in issues):
        status = TrustStatus.BLOCKED
    elif issues or any(item.status != "ok" for item in source_manifest):
        status = TrustStatus.PARTIAL
    else:
        status = TrustStatus.TRUSTED
    return AnalysisTrust(status, tuple(issues), tuple(source_manifest), checked_at)
```

- [ ] **Step 8: Run focused tests and lint**

Run: `pytest tests/test_data_quality.py tests/test_analysis_trust.py -v`

Run: `ruff check src/data_layer/quality.py src/analysis tests/test_data_quality.py tests/test_analysis_trust.py`

Expected: both commands PASS.

- [ ] **Step 9: Commit**

```powershell
git add src/data_layer/quality.py src/analysis tests/test_data_quality.py tests/test_analysis_trust.py
git commit -m "feat: add analysis trust and data quality contracts"
```

---

### Task 3: Trust-Gated Deterministic Advice

**Files:**
- Create: `src/analysis/advice.py`
- Create: `tests/test_advice.py`

**Interfaces:**
- Consumes: `AnalysisTrust.can_advise` from Task 2.
- Produces: `AdviceAction`, immutable `Advice`, and `generate_advice()`.

- [ ] **Step 1: Write failing advice tests**

```python
from src.analysis.advice import AdviceAction, generate_advice
from src.analysis.trust import AnalysisTrust, TrustStatus


def trust(status: TrustStatus) -> AnalysisTrust:
    return AnalysisTrust(status, (), (), "2026-07-10T16:00:00+08:00")


def test_blocked_and_partial_never_generate_advice():
    for status in (TrustStatus.BLOCKED, TrustStatus.PARTIAL):
        assert generate_advice(
            trust=trust(status), as_of="2026-07-10", total_score=80,
            current_price=10, target_price=15, rsi=55,
        ) is None


def test_trusted_positive_evidence_generates_explainable_buy():
    advice = generate_advice(
        trust=trust(TrustStatus.TRUSTED), as_of="2026-07-10",
        total_score=72, current_price=10, target_price=12, rsi=55,
    )
    assert advice is not None
    assert advice.action is AdviceAction.BUY
    assert advice.supporting_evidence
    assert advice.invalidation_conditions


def test_trusted_overbought_signal_reduces_instead_of_buying():
    advice = generate_advice(
        trust=trust(TrustStatus.TRUSTED), as_of="2026-07-10",
        total_score=72, current_price=10, target_price=12, rsi=75,
    )
    assert advice is not None
    assert advice.action is AdviceAction.REDUCE
    assert any("RSI" in item for item in advice.risk_evidence)
```

- [ ] **Step 2: Run and confirm RED**

Run: `pytest tests/test_advice.py -v`

Expected: import failure because `src.analysis.advice` does not exist.

- [ ] **Step 3: Implement the advice gate and rules**

Create `src/analysis/advice.py`:

```python
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
    *, trust: AnalysisTrust, as_of: str, total_score: float,
    current_price: float, target_price: float | None, rsi: float | None,
) -> Advice | None:
    if not trust.can_advise:
        return None
    supporting = [f"综合评分 {total_score:.0f}/100"]
    risks: list[str] = []
    if target_price is not None and target_price > current_price:
        supporting.append(f"目标价高于现价 {(target_price / current_price - 1) * 100:.1f}%")
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
        action, as_of, tuple(supporting), tuple(risks), invalidation,
        target_price=target_price,
    )
```

- [ ] **Step 4: Run tests and lint**

Run: `pytest tests/test_advice.py -v`

Run: `ruff check src/analysis/advice.py tests/test_advice.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/analysis/advice.py tests/test_advice.py
git commit -m "feat: gate deterministic advice on trusted data"
```

---

### Task 4: Next-Session A-Share Backtest Simulator

**Files:**
- Replace: `strategies/base.py`
- Create: `tests/test_backtest.py`

**Interfaces:**
- Produces: immutable `BacktestConfig`.
- Preserves: `run_backtest(signal_map, data_df, initial_cash, commission, slippage, *, config=None) -> dict`.
- Result adds: `trades`, `rejected_orders`, `open_position`, `config`, `buy_hold_return`, and `excess_return`.

- [ ] **Step 1: Write the look-ahead regression test**

```python
from dataclasses import replace

import pandas as pd
import pytest

from strategies.base import BacktestConfig, run_backtest


def bars(opens, closes, volumes=None):
    rows = len(opens)
    return pd.DataFrame({
        "date": pd.bdate_range("2026-01-05", periods=rows).strftime("%Y-%m-%d"),
        "open": opens,
        "high": [max(o, c) + 0.5 for o, c in zip(opens, closes)],
        "low": [min(o, c) - 0.5 for o, c in zip(opens, closes)],
        "close": closes,
        "volume": volumes or [10_000] * rows,
        "symbol": ["SH600000"] * rows,
    })


def test_close_signal_executes_at_next_session_open():
    data = bars([10, 10, 20], [10, 11, 20])
    signal_date = data.iloc[1]["date"]
    result = run_backtest(
        {signal_date: 1}, data,
        config=BacktestConfig(
            initial_cash=100_000, commission_rate=0,
            minimum_commission=0, stamp_duty_rate=0, slippage=0,
        ),
    )
    assert result["trades"][0]["date"] == data.iloc[2]["date"]
    assert result["trades"][0]["price"] == 20
```

- [ ] **Step 2: Run and confirm RED**

Run: `pytest tests/test_backtest.py::test_close_signal_executes_at_next_session_open -v`

Expected: import failure for `BacktestConfig` or assertion failure because the current engine trades on the signal date.

- [ ] **Step 3: Add configuration and the pending-order loop**

Define in `strategies/base.py`:

```python
@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 1_000_000.0
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    stamp_duty_rate: float = 0.0005
    slippage: float = 0.0005
    lot_size: int = 100
    allocation: float = 0.95
    symbol: str | None = None
    is_st: bool = False
    min_annualization_days: int = 60
```

Keep legacy `initial_cash`, `commission`, and `slippage` parameters. If `config is None`, construct `BacktestConfig(initial_cash=initial_cash, commission_rate=commission, slippage=slippage)`.

Use this sequence in the loop:

```python
pending: dict | None = None
for index, row in df.iterrows():
    if pending is not None:
        pending = _attempt_pending_order(
            pending=pending,
            row=row,
            previous_close=df.iloc[index - 1]["close"] if index else None,
            state=state,
            config=cfg,
            trades=trades,
            rejected_orders=rejected_orders,
        )
    equity_curve.append({
        "date": row["date"],
        "equity": state.cash + state.shares * row["close"],
    })
    signal = int(signal_map.get(row["date"], 0))
    if signal:
        pending = {
            "signal_date": row["date"],
            "side": "buy" if signal > 0 else "sell",
        }
```

The helper clears an order after a fill or permanent rejection. It retains an order after temporary reasons `suspended_or_no_volume`, `limit_up`, or `limit_down`. A later nonzero close signal replaces an unfilled order and records reason `replaced_by_new_signal`.

- [ ] **Step 4: Run the look-ahead test and confirm GREEN**

Run: `pytest tests/test_backtest.py::test_close_signal_executes_at_next_session_open -v`

Expected: PASS.

- [ ] **Step 5: Add failing A-share execution tests**

Add concrete tests using `bars()` and a zero-cost configuration:

```python
NO_COST = BacktestConfig(
    initial_cash=100_000, commission_rate=0,
    minimum_commission=0, stamp_duty_rate=0, slippage=0,
)


def test_buy_quantity_is_a_board_lot():
    data = bars([10, 10, 10], [10, 10, 10])
    result = run_backtest({data.iloc[1]["date"]: 1}, data, config=NO_COST)
    assert result["trades"][0]["shares"] % 100 == 0


def test_limit_up_buy_is_rejected_and_recorded():
    data = bars([10, 10, 11], [10, 10, 11])
    result = run_backtest({data.iloc[1]["date"]: 1}, data, config=NO_COST)
    assert result["trades"] == []
    assert result["rejected_orders"][0]["reason"] == "limit_up"


def test_zero_volume_does_not_fill():
    data = bars([10, 10, 10], [10, 10, 10], volumes=[1000, 1000, 0])
    result = run_backtest({data.iloc[1]["date"]: 1}, data, config=NO_COST)
    assert result["trades"] == []
    assert result["rejected_orders"][0]["reason"] == "suspended_or_no_volume"


def test_sell_happens_after_buy_day_and_charges_stamp_duty():
    data = bars([10, 10, 10, 12, 12], [10, 10, 11, 12, 12])
    config = replace(NO_COST, stamp_duty_rate=0.0005)
    signals = {data.iloc[0]["date"]: 1, data.iloc[2]["date"]: -1}
    result = run_backtest(signals, data, config=config)
    buy, sell = result["trades"]
    assert sell["date"] > buy["date"]
    assert sell["stamp_duty"] > 0
```

- [ ] **Step 6: Implement execution constraints and costs**

Add helpers:

```python
def _price_limit_pct(symbol: str | None, is_st: bool) -> float:
    if is_st:
        return 0.05
    normalized = (symbol or "").upper()
    code = normalized.removeprefix("SH").removeprefix("SZ").removeprefix("BJ")
    if normalized.startswith("BJ") or code.startswith(("4", "8", "92")):
        return 0.30
    if code.startswith(("300", "301", "688", "689")):
        return 0.20
    return 0.10


def _commission(notional: float, config: BacktestConfig) -> float:
    if notional <= 0:
        return 0.0
    return max(notional * config.commission_rate, config.minimum_commission)


def _round_lot(shares: float, lot_size: int) -> int:
    return max(0, int(shares) // lot_size * lot_size)
```

Use `Decimal(str(previous_close * (1 + limit_pct))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)` for the upper daily limit and the equivalent subtraction for the lower limit. Buy price is `open * (1 + slippage)`; sell price is `open * (1 - slippage)`. Buy cash deduction is notional plus commission. Sell cash addition is notional minus commission minus stamp duty. Store `commission`, `stamp_duty`, `signal_date`, and `date` on every fill.

- [ ] **Step 7: Add failing metric-semantics tests**

```python
def test_short_sample_does_not_annualize():
    result = run_backtest({}, bars([10] * 10, [10] * 10), config=NO_COST)
    assert result["annual_return"] is None
    assert result["sharpe"] is None


def test_no_closed_trade_has_no_win_rate_or_profit_loss_ratio():
    data = bars([10, 10, 11], [10, 10, 11])
    result = run_backtest({data.iloc[0]["date"]: 1}, data, config=NO_COST)
    assert result["win_rate"] is None
    assert result["profit_loss_ratio"] is None


def test_result_exposes_benchmark_excess_and_config():
    result = run_backtest({}, bars([10, 11], [10, 12]), config=NO_COST)
    assert result["buy_hold_return"] is not None
    assert result["excess_return"] == pytest.approx(
        result["total_return"] - result["buy_hold_return"], abs=0.01
    )
    assert result["config"]["lot_size"] == 100
```

- [ ] **Step 8: Implement trustworthy metrics**

Keep total return mark-to-market. Calculate annual return and Sharpe only when `trading_days >= cfg.min_annualization_days`. Derive win rate and profit/loss ratio only from sell fills, returning `None` without closed trades. Compute buy-and-hold with the same initial cash, first tradable open, buy commission, lot size, and final close mark-to-market. Return `excess_return = total_return - buy_hold_return`, all fills, rejected orders, serialized configuration, and current open position.

- [ ] **Step 9: Run simulator and regression tests**

Run: `pytest tests/test_backtest.py -v`

Run: `pytest tests/ -q`

Expected: all tests PASS.

- [ ] **Step 10: Lint and commit**

Run: `ruff check strategies/base.py tests/test_backtest.py`

Expected: PASS.

```powershell
git add strategies/base.py tests/test_backtest.py
git commit -m "fix: remove look-ahead bias from A-share backtests"
```

---

### Task 5: Trustworthy Single-Stock Snapshot

**Files:**
- Modify: `scripts/analyze_one.py:1-191`
- Modify: `src/data_sources/akshare_source.py:49-157`
- Create: `tests/test_analyze_one.py`

**Interfaces:**
- Consumes: `DataSourceError`, `validate_kline()`, `SourceEvidence`, `QualityIssue`, and `build_analysis_trust()`.
- Produces snapshot keys: `_trust`, `sector_momentum`, `capital_flow`, and `kline.adjustment`.
- Produces: `AkShareSource.get_kline(symbol, start, end, adjust="qfq")`.

- [ ] **Step 1: Write failing snapshot tests**

Use monkeypatch fixtures for every external fetch and 60 valid business-day bars:

```python
import scripts.analyze_one as analyze_one
from src.data_sources.base import DataSourceError


def test_pull_writes_trusted_manifest_for_complete_snapshot(monkeypatch):
    snapshot = analyze_one.pull()
    assert snapshot["_trust"]["status"] == "trusted"
    assert snapshot["kline"]["adjustment"] == "qfq"
    assert any(
        item["dataset"] == "kline"
        for item in snapshot["_trust"]["source_manifest"]
    )


def test_kline_failure_blocks_snapshot(monkeypatch):
    def fail(*args, **kwargs):
        raise DataSourceError("akshare", "get_kline", "timeout")

    monkeypatch.setattr(analyze_one.AkShareSource, "get_kline", fail)
    snapshot = analyze_one.pull()
    assert snapshot["_trust"]["status"] == "blocked"


def test_optional_failure_makes_snapshot_partial(monkeypatch):
    def fail(*args, **kwargs):
        raise DataSourceError("westock", "hot_board", "timeout")

    monkeypatch.setattr(analyze_one, "evaluate_sector", fail)
    snapshot = analyze_one.pull()
    assert snapshot["_trust"]["status"] == "partial"
```

Patch module constants `SYMBOL`, `NAME`, and clock inputs for deterministic assertions.

- [ ] **Step 2: Run and confirm RED**

Run: `pytest tests/test_analyze_one.py -v`

Expected: failures because `get_kline`, `_trust`, and snapshot factor fields do not exist.

- [ ] **Step 3: Add an adjusted K-line adapter method**

Add to `AkShareSource`:

```python
from src.data_layer.symbols import to_akshare, to_chinastock


def get_kline(
    self, symbol: str, start: str, end: str, *, adjust: str = "qfq"
) -> pd.DataFrame:
    raw = _safe_call(
        ak.stock_zh_a_hist,
        symbol=to_akshare(symbol),
        period="daily",
        start_date=start.replace("-", ""),
        end_date=end.replace("-", ""),
        adjust=adjust,
    )
    if raw.empty:
        return raw
    out = normalize_sector_ohlcv(raw)
    out["symbol"] = to_chinastock(symbol)
    return out.sort_values("date").reset_index(drop=True)
```

Refactor `get_quote_for_validation()` to call `self.get_kline(symbol, start_dt.strftime("%Y-%m-%d"), date, adjust="qfq")`.

Add an adapter test with a patched `ak.stock_zh_a_hist` that asserts the call receives `adjust="qfq"`, the returned dates are ascending, and the result contains `symbol == "SH600000"`.

- [ ] **Step 4: Build evidence without suppressing warnings**

Remove `warnings.filterwarnings("ignore")` and use 180 calendar days. In `pull()`:

1. Fetch K-line through `AkShareSource.get_kline()` with `adjust="qfq"`.
2. Validate using `validate_kline(kline, as_of=end.strftime("%Y-%m-%d"), min_rows=60, adjustment="qfq")`.
3. Record every dataset as `SourceEvidence(status="ok" | "empty" | "failed")`.
4. Convert a K-line `DataSourceError` to a critical issue; convert sector, capital, rating, news, notice, report, and consensus failures to noncritical issues.
5. Evaluate sector momentum and capital flow once during snapshot creation and store their dictionaries. Report rendering must not repeat these network calls.
6. Finish with `snapshot["_trust"] = build_analysis_trust(issues, manifest, checked_at=datetime.now().astimezone().isoformat(timespec="seconds")).to_dict()`.

Validate the full K-line frame, then store the latest 120 rows in ascending order. Do not call `_df_summary(kline, n=60)` on an ascending frame because that would retain the oldest rows. Store:

```python
recent_kline = kline.tail(120).reset_index(drop=True)
snapshot["kline"] = {
    **_df_summary(recent_kline, n=len(recent_kline)),
    "adjustment": "qfq",
}
```

Use:

```python
def _evidence(
    *, source: str, dataset: str, status: str, row_count: int,
    as_of: str | None, adjustment: str | None = None,
) -> SourceEvidence:
    return SourceEvidence(
        source=source, dataset=dataset, as_of=as_of,
        fetched_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        status=status, row_count=row_count, adjustment=adjustment,
    )
```

- [ ] **Step 5: Run tests and lint**

Run: `pytest tests/test_analyze_one.py tests/test_data_source_errors.py tests/test_data_quality.py -v`

Run: `ruff check scripts/analyze_one.py src/data_sources/akshare_source.py tests/test_analyze_one.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add scripts/analyze_one.py src/data_sources/akshare_source.py tests/test_analyze_one.py
git commit -m "feat: attach trust evidence to stock snapshots"
```

---

### Task 6: Trust-Gated Single-Stock Report

**Files:**
- Modify: `scripts/gen_single_report.py:49-159`
- Modify: `scripts/gen_single_report.py:601-640`
- Modify: `scripts/gen_single_report.py:1080-1316`
- Create: `tests/test_trusted_report.py`

**Interfaces:**
- Consumes: snapshot `_trust`, `sector_momentum`, `capital_flow`, and `generate_advice()`.
- Produces: `render_trust_banner()`, `render_advice_section()`, and trust-aware `build_html()`.

- [ ] **Step 1: Write failing report-gate tests**

```python
def test_blocked_report_shows_reason_and_no_action_conclusion():
    rendered = gen_single_report.build_html(blocked_snapshot())
    assert "数据不足，禁止形成买卖结论" in rendered
    assert 'data-advice-action="buy"' not in rendered
    assert 'data-advice-action="sell"' not in rendered


def test_legacy_snapshot_without_trust_is_blocked():
    snapshot = complete_snapshot()
    snapshot.pop("_trust", None)
    rendered = gen_single_report.build_html(snapshot)
    assert "缺少可信状态" in rendered
    assert "数据不足，禁止形成买卖结论" in rendered


def test_trusted_report_contains_structured_advice_and_manifest():
    rendered = gen_single_report.build_html(trusted_snapshot(score=72, rsi=55))
    assert 'data-advice-action="buy"' in rendered
    assert "支持证据" in rendered
    assert "失效条件" in rendered
    assert "qfq" in rendered
```

- [ ] **Step 2: Run and confirm RED**

Run: `pytest tests/test_trusted_report.py -v`

Expected: failures because the current report constructs strategy narratives without a trust banner.

- [ ] **Step 3: Remove live data access from rendering**

Change `calc_score()` to read `d.get("sector_momentum")` and `d.get("capital_flow")`. If either is absent, use `None`; do not manufacture a neutral score. Compute `total` only when all four dimensions exist, otherwise return `total=None`.

K-line snapshots are ascending after Task 5. Calculate current price from `kline_rows[-1]`, never `kline_rows[0]`. Keep chart dates ascending rather than reversing them a second time.

Preserve the main-worktree rating fix exactly:

```python
rating_list = d.get("rating", {}).get("head", [])
rating = rating_list[0] if rating_list else {}
```

- [ ] **Step 4: Add the hard trust parser and advice gate**

```python
def _trust_from_snapshot(d: dict) -> AnalysisTrust:
    raw = d.get("_trust")
    if raw:
        return AnalysisTrust.from_dict(raw)
    return AnalysisTrust(
        status=TrustStatus.BLOCKED,
        issues=(QualityIssue("missing_trust", "缺少可信状态", critical=True),),
        source_manifest=(),
        checked_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )
```

In `build_html()`, call `generate_advice()` only after trust parsing and only when `score["total"]` and current price exist. Pass the returned `Advice | None` to renderers; renderers must not call the advice engine.

If snapshot trust says `trusted` but `calc_score()` returns `total=None` or current price is nonpositive, add a critical `report_input_missing` issue and rebuild trust as `blocked` before advice generation:

```python
if trust.can_advise and (score["total"] is None or score["cur"] <= 0):
    trust = build_analysis_trust(
        [*trust.issues, QualityIssue(
            "report_input_missing", "评分或现价输入不完整", critical=True
        )],
        list(trust.source_manifest),
        checked_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )
```

- [ ] **Step 5: Render trusted and blocked states**

`render_trust_banner(trust)` lists status, checked time, every issue, source, dataset, as-of date, status, row count, and adjustment. `render_advice_section(advice, trust)` returns this fixed blocked copy when `advice is None`:

```html
<section class="section advice-blocked" data-advice-action="none">
  <h2>数据不足，禁止形成买卖结论</h2>
  <p>请先修复报告列出的数据完整性、时效性或来源错误。</p>
</section>
```

For trusted advice, set `data-advice-action` to the enum value and render action, as-of time, supporting evidence, risk evidence, and invalidation conditions. Skip old `render_strategy()` and `render_conclusion()` output whenever advice is `None`.

Both trusted and blocked advice sections must include the fixed disclaimer `结论是规则化研究信号，不构成收益保证或投资承诺。`; add this assertion to `tests/test_trusted_report.py`.

- [ ] **Step 6: Run tests and lint**

Run: `pytest tests/test_trusted_report.py tests/test_advice.py tests/test_analysis_trust.py -v`

Run: `ruff check scripts/gen_single_report.py tests/test_trusted_report.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add scripts/gen_single_report.py tests/test_trusted_report.py
git commit -m "fix: block stock advice when data is untrusted"
```

---

### Task 7: Backtest Report Integration and P0 Verification

**Files:**
- Modify: `scripts/run_backtest.py:156-425`
- Modify: `scripts/analyze_sh600198.py:152-165`
- Modify: `README.md`
- Test: `tests/test_backtest.py`
- Test: `tests/test_trusted_report.py`

**Interfaces:**
- Consumes: extended backtest result from Task 4.
- Produces: reports that display configuration, benchmark, excess return, rejection reasons, and insufficient-sample text.

- [ ] **Step 1: Write failing formatter/report tests**

```python
from scripts.run_backtest import format_metric, generate_report


def test_backtest_metric_formatter_marks_none_as_insufficient_sample():
    assert format_metric(None, suffix="%") == "样本不足"


def test_backtest_report_displays_costs_and_benchmark():
    result = {
        "symbol": "SH600000",
        "strategy": "MA5/10",
        "annual_return": None,
        "total_return": 1.0,
        "sharpe": None,
        "max_drawdown": 2.0,
        "win_rate": None,
        "profit_loss_ratio": None,
        "total_trades": 0,
        "final_value": 101_000.0,
        "buy_hold_return": 2.0,
        "excess_return": -1.0,
        "open_position": None,
        "rejected_orders": [{"date": "2026-01-06", "reason": "limit_up"}],
        "config": {
            "commission_rate": 0.0003,
            "minimum_commission": 5.0,
            "stamp_duty_rate": 0.0005,
            "slippage": 0.0005,
            "lot_size": 100,
        },
    }
    rendered = generate_report([result], ["SH600000"], num_strategies=1)
    assert "最低佣金" in rendered
    assert "买入并持有" in rendered
    assert "超额收益" in rendered
    assert "未成交原因" in rendered
```

- [ ] **Step 2: Run and confirm RED**

Run: `pytest tests/test_backtest.py -k "formatter or report" -v`

Expected: failure because `format_metric` and the new report fields do not exist.

- [ ] **Step 3: Update backtest report generation**

Add:

```python
def format_metric(value: float | None, *, suffix: str = "") -> str:
    if value is None:
        return "样本不足"
    return f"{value:.2f}{suffix}"
```

Use it for annual return, Sharpe, win rate, and profit/loss ratio. Add configuration, buy-and-hold return, excess return, open position, and rejected-order sections. Never coerce `None` to zero.

Remove `warnings.filterwarnings("ignore")`. Update console progress formatting to use `format_metric()` so a short sample does not raise on `None`. Choose the best strategy with `(annual_return if annual_return is not None else total_return)` so short samples remain comparable without pretending they are annualized.

- [ ] **Step 4: Preserve the existing numeric conversion fix**

Apply to `scripts/analyze_sh600198.py`:

```python
ws_norm["close_ws"] = pd.to_numeric(ws_norm["close_ws"], errors="coerce")
ws_norm["volume_ws"] = pd.to_numeric(ws_norm["volume_ws"], errors="coerce")
ak_norm["close_ak"] = pd.to_numeric(ak_norm["close_ak"], errors="coerce")
```

Do not include unrelated main-worktree files or report artifacts.

- [ ] **Step 5: Update README trust contract**

Document exact states, trusted-only advice, T+1-or-later execution, default costs, A-share constraints, and that legacy reports without `_trust` are blocked.

- [ ] **Step 6: Run complete verification**

Run: `pytest tests/ -v`

Expected: existing 88 tests plus all new P0 tests PASS.

Run: `ruff check src/ strategies/ tests/ scripts/analyze_one.py scripts/gen_single_report.py scripts/run_backtest.py scripts/analyze_sh600198.py`

Expected: PASS for all P0 source/test paths. Report unrelated legacy-script violations separately without broadening P0.

Run the original look-ahead reproduction:

```powershell
@'
import pandas as pd
from src.factors.technical import compute_ma
from strategies.base import run_backtest

df = pd.DataFrame({
    "date": pd.date_range("2026-01-01", periods=6).strftime("%Y-%m-%d"),
    "open": [10, 10, 10, 10, 10, 10],
    "high": [10, 10, 10, 11, 12, 13],
    "low": [10, 10, 9, 10, 10, 10],
    "close": [10, 10, 9, 11, 12, 13],
    "volume": [1000] * 6,
})
signals = compute_ma(df, short=2, long=3)
result = run_backtest(dict(zip(signals["date"], signals["signal"])), df)
print(result["trades"])
signal_date = signals.loc[signals["signal"] == 1, "date"].iloc[0]
assert not result["trades"] or result["trades"][0]["date"] > signal_date
'@ | python -
```

Expected: assertion passes; no fill date equals the close-signal date.

- [ ] **Step 7: Inspect final diff and commit**

Run: `git diff --check`

Run: `git status --short`

Expected: only P0 files are modified and `git diff --check` exits 0.

```powershell
git add scripts/run_backtest.py scripts/analyze_sh600198.py README.md tests/test_backtest.py
git commit -m "docs: expose trustworthy analysis assumptions"
```

---

## Completion Checklist

- [ ] Every production behavior was preceded by a test that failed for the expected reason.
- [ ] Critical source failure produces `blocked`; optional failure produces `partial`; valid empty remains distinct.
- [ ] Only trusted snapshots generate structured advice.
- [ ] Report rendering performs no live data fetch.
- [ ] T-day close signals never fill at T-day open.
- [ ] A-share lot, suspension, price-limit, cost, and T+1 rules are verified.
- [ ] Short samples expose `None`, not fake zero or extreme annualized values.
- [ ] Existing user changes in `gen_single_report.py` and `analyze_sh600198.py` are preserved.
- [ ] Full tests and P0 Ruff scope pass.
- [ ] Final diff contains no generated reports, cached data, or unrelated user files.
