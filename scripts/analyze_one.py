#!/usr/bin/env python3
"""单只票端到端分析 — 数据拉取 + 漂亮 HTML 报告。

用法:
    python scripts/analyze_one.py SZ000700 模塑科技
    python scripts/analyze_one.py SH600519 贵州茅台
"""

from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

from src.data_sources.westock_source import (  # noqa: E402
    _call_westock,
    _parse_markdown_table,
)

if len(sys.argv) >= 3:
    SYMBOL = sys.argv[1].upper()
    NAME = sys.argv[2]
else:
    SYMBOL = "SZ000700"
    NAME = "模塑科技"
WESTOCK_CODE = SYMBOL.lower().replace("sh", "sh").replace("sz", "sz")
LOOKBACK_DAYS = 60


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
    snap = {
        "symbol": SYMBOL,
        "name": NAME,
        "pulled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    errors = []

    # K 线
    try:
        end = datetime.today()
        start = end - timedelta(days=LOOKBACK_DAYS)
        text = _call_westock(
            [
                "kline",
                WESTOCK_CODE,
                "--period",
                "daily",
                "--start",
                start.strftime("%Y%m%d"),
                "--end",
                end.strftime("%Y%m%d"),
            ]
        )
        kline = _parse_markdown_table(text).rename(columns={"last": "close"})
        for col in ("open", "close", "high", "low", "volume", "amount"):
            if col in kline.columns:
                kline[col] = pd.to_numeric(kline[col], errors="coerce")
        snap["kline"] = _df_summary(kline, n=60)
    except Exception as e:
        errors.append(f"kline: {e}")
        snap["kline"] = _df_summary(pd.DataFrame())

    # 技术指标
    for grp in ("ma", "macd", "rsi", "kdj", "boll", "dmi"):
        try:
            snap[f"technical_{grp}"] = _df_summary(
                _call_westock_args_safe(["technical", WESTOCK_CODE, "--group", grp]),
                n=20,
            )
        except Exception as e:
            errors.append(f"technical_{grp}: {e}")
            snap[f"technical_{grp}"] = _df_summary(pd.DataFrame())

    # 财务
    for ftype in ("summary", "lrb", "zcfz", "xjll"):
        try:
            text = _call_westock(
                ["finance", WESTOCK_CODE, "--type", ftype, "--num", "4"]
            )
            snap[f"finance_{ftype}"] = _df_summary(_parse_markdown_table(text), n=10)
        except Exception as e:
            errors.append(f"finance_{ftype}: {e}")
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
    except Exception as e:
        errors.append(f"consensus: {e}")
        snap["consensus"] = {"target_price": None, "forecasts": []}

    try:
        text = _call_westock(["rating", WESTOCK_CODE])
        snap["rating"] = _df_summary(_parse_markdown_table(text), n=5)
    except Exception as e:
        errors.append(f"rating: {e}")
        snap["rating"] = _df_summary(pd.DataFrame())

    # 研报 / 新闻 / 公告
    for cmd, key, limit in [
        (["report", WESTOCK_CODE, "--limit", "5"], "reports", 5),
        (["news", WESTOCK_CODE, "--limit", "8"], "news", 8),
        (["notice", WESTOCK_CODE, "--limit", "5"], "notices", 5),
    ]:
        try:
            text = _call_westock(cmd)
            snap[key] = _df_summary(_parse_markdown_table(text), n=limit)
        except Exception as e:
            errors.append(f"{key}: {e}")
            snap[key] = _df_summary(pd.DataFrame())

    # profile
    try:
        text = _call_westock(["profile", WESTOCK_CODE])
        df = _parse_markdown_table(text)
        snap["profile"] = df.iloc[0].to_dict() if not df.empty else {}
    except Exception as e:
        errors.append(f"profile: {e}")
        snap["profile"] = {}

    if errors:
        snap["_errors"] = errors
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
