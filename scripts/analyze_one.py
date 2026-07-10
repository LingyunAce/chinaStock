#!/usr/bin/env python3
"""单只票端到端分析 — 数据拉取 + 漂亮 HTML 报告。

用法:
    python scripts/analyze_one.py SZ000700 模塑科技
    python scripts/analyze_one.py SH600519 贵州茅台
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
import pandas as pd  # noqa: E402

from src.analysis.trust import SourceEvidence, build_analysis_trust  # noqa: E402
from src.data_layer.quality import QualityIssue, validate_kline  # noqa: E402
from src.data_sources.akshare_source import AkShareSource  # noqa: E402
from src.data_sources.base import DataSourceError  # noqa: E402
from src.data_sources.westock_source import (  # noqa: E402
    _call_westock,
    _parse_markdown_table,
)
from src.factors.capital_flow import evaluate as evaluate_flow  # noqa: E402
from src.factors.sector_momentum import evaluate as evaluate_sector  # noqa: E402

if len(sys.argv) >= 3:
    SYMBOL = sys.argv[1].upper()
    NAME = sys.argv[2]
else:
    SYMBOL = "SZ000700"
    NAME = "模塑科技"
WESTOCK_CODE = SYMBOL.lower().replace("sh", "sh").replace("sz", "sz")
LOOKBACK_DAYS = 180


def _df_summary(df, n=5):
    if df is None or df.empty:
        return {"shape": [0, 0], "columns": [], "head": []}
    return {
        "shape": list(df.shape),
        "columns": df.columns.tolist(),
        "head": df.fillna(value=pd.NA).head(n).to_dict(orient="records"),
    }


def pull():
    print(f"拉取 {SYMBOL} {NAME} 完整画像 ...")
    checked_at = datetime.now().astimezone().isoformat(timespec="seconds")
    snap = {
        "symbol": SYMBOL,
        "name": NAME,
        "pulled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    errors: list[str] = []
    issues: list[QualityIssue] = []
    manifest: list[SourceEvidence] = []

    def record(
        source: str,
        dataset: str,
        status: str,
        row_count: int,
        as_of: str | None,
        adjustment: str | None = None,
    ) -> None:
        manifest.append(
            SourceEvidence(
                source=source,
                dataset=dataset,
                as_of=as_of,
                fetched_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                status=status,
                row_count=row_count,
                adjustment=adjustment,
            )
        )

    def failed(dataset: str, exc: Exception, *, critical: bool) -> None:
        source = exc.source if isinstance(exc, DataSourceError) else "unknown"
        message = str(exc)
        errors.append(f"{dataset}: {message}")
        issues.append(
            QualityIssue(
                f"{dataset}_failed",
                message,
                source=source,
                critical=critical,
            )
        )
        record(source, dataset, "failed", 0, None)

    # K 线
    end = datetime.today()
    start = end - timedelta(days=LOOKBACK_DAYS)
    try:
        kline = AkShareSource().get_kline(
            SYMBOL,
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
            adjust="qfq",
        )
        for col in ("open", "close", "high", "low", "volume", "amount"):
            if col in kline.columns:
                kline[col] = pd.to_numeric(kline[col], errors="coerce")
        issues.extend(
            validate_kline(
                kline,
                as_of=end.strftime("%Y-%m-%d"),
                adjustment="qfq",
            )
        )
        recent = kline.tail(120).reset_index(drop=True)
        snap["kline"] = {**_df_summary(recent, n=len(recent)), "adjustment": "qfq"}
        status = "ok" if not kline.empty else "empty"
        record("akshare", "kline", status, len(kline), end.strftime("%Y-%m-%d"), "qfq")
    except Exception as e:
        failed("kline", e, critical=True)
        snap["kline"] = {**_df_summary(pd.DataFrame()), "adjustment": "qfq"}

    # 技术指标
    for grp in ("ma", "macd", "rsi", "kdj", "boll", "dmi"):
        try:
            snap[f"technical_{grp}"] = _df_summary(
                _call_westock_args_safe(["technical", WESTOCK_CODE, "--group", grp]),
                n=20,
            )
            rows = snap[f"technical_{grp}"]["shape"][0]
            record("westock", f"technical_{grp}", "ok" if rows else "empty", rows, end.strftime("%Y-%m-%d"))
        except Exception as e:
            failed(f"technical_{grp}", e, critical=False)
            snap[f"technical_{grp}"] = _df_summary(pd.DataFrame())

    # 财务
    for ftype in ("summary", "lrb", "zcfz", "xjll"):
        try:
            text = _call_westock(
                ["finance", WESTOCK_CODE, "--type", ftype, "--num", "4"]
            )
            frame = _parse_markdown_table(text)
            snap[f"finance_{ftype}"] = _df_summary(frame, n=10)
            record("westock", f"finance_{ftype}", "ok" if not frame.empty else "empty", len(frame), end.strftime("%Y-%m-%d"))
        except Exception as e:
            failed(f"finance_{ftype}", e, critical=False)
            snap[f"finance_{ftype}"] = _df_summary(pd.DataFrame())

    # 一致预期 + 评级
    try:
        text = _call_westock(["consensus", WESTOCK_CODE])
        cons = {"target_price": None, "forecasts": []}
        for ln in text.splitlines():
            if "目标价" in ln:
                parts = ln.split(":", 1)
                if len(parts) == 2:
                    try:
                        cons["target_price"] = float(parts[1].strip())
                    except ValueError:
                        pass
        df = _parse_markdown_table(text)
        if not df.empty:
            cons["forecasts"] = _df_summary(df)["head"]
        snap["consensus"] = cons
        record("westock", "consensus", "ok" if not df.empty else "empty", len(df), end.strftime("%Y-%m-%d"))
    except Exception as e:
        failed("consensus", e, critical=False)
        snap["consensus"] = {"target_price": None, "forecasts": []}

    try:
        text = _call_westock(["rating", WESTOCK_CODE])
        frame = _parse_markdown_table(text)
        snap["rating"] = _df_summary(frame, n=5)
        record("westock", "rating", "ok" if not frame.empty else "empty", len(frame), end.strftime("%Y-%m-%d"))
    except Exception as e:
        failed("rating", e, critical=False)
        snap["rating"] = _df_summary(pd.DataFrame())

    # 研报 / 新闻 / 公告
    for cmd, key, limit in [
        (["report", WESTOCK_CODE, "--limit", "5"], "reports", 5),
        (["news", WESTOCK_CODE, "--limit", "8"], "news", 8),
        (["notice", WESTOCK_CODE, "--limit", "5"], "notices", 5),
    ]:
        try:
            text = _call_westock(cmd)
            frame = _parse_markdown_table(text)
            snap[key] = _df_summary(frame, n=limit)
            record("westock", key, "ok" if not frame.empty else "empty", len(frame), end.strftime("%Y-%m-%d"))
        except Exception as e:
            failed(key, e, critical=False)
            snap[key] = _df_summary(pd.DataFrame())

    # profile
    try:
        text = _call_westock(["profile", WESTOCK_CODE])
        df = _parse_markdown_table(text)
        snap["profile"] = df.iloc[0].to_dict() if not df.empty else {}
        record("westock", "profile", "ok" if not df.empty else "empty", len(df), end.strftime("%Y-%m-%d"))
    except Exception as e:
        failed("profile", e, critical=False)
        snap["profile"] = {}

    try:
        snap["sector_momentum"] = evaluate_sector(snap["profile"])
        record("westock", "sector_momentum", "ok", 1, end.strftime("%Y-%m-%d"))
    except Exception as e:
        failed("sector_momentum", e, critical=False)
        snap["sector_momentum"] = None

    try:
        snap["capital_flow"] = evaluate_flow(WESTOCK_CODE)
        record("westock", "capital_flow", "ok", 1, end.strftime("%Y-%m-%d"))
    except Exception as e:
        failed("capital_flow", e, critical=False)
        snap["capital_flow"] = None

    if errors:
        snap["_errors"] = errors
    snap["_trust"] = build_analysis_trust(
        issues, manifest, checked_at=checked_at
    ).to_dict()
    return snap


def _call_westock_args_safe(args):
    text = _call_westock(args)
    return _parse_markdown_table(text)


def is_fresh(out_file: Path, max_age_hours: float = 1.0) -> bool:
    """检查已有 JSON 是否足够新鲜（pulled_at 距今 < max_age_hours）。"""
    if not out_file.exists():
        return False
    try:
        d = json.loads(out_file.read_text(encoding="utf-8"))
        pulled_at = d.get("pulled_at", "")
        if not pulled_at:
            return False
        from datetime import datetime
        pulled = datetime.strptime(pulled_at[:19], "%Y-%m-%d %H:%M:%S")
        age_h = (datetime.now() - pulled).total_seconds() / 3600
        return age_h < max_age_hours
    except Exception:
        return False


def main():
    out_dir = PROJECT_ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"long_form_{SYMBOL}.json"

    # 数据新鲜度检查：1 小时内直接复用，超过则重新拉取
    if is_fresh(out_file, max_age_hours=1.0):
        print(f"[缓存命中] {out_file} 数据新鲜 (< 1h)，跳过拉取")
        return 0

    data = pull()
    out_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"[OK] {out_file}  ({out_file.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
