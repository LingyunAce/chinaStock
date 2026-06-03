#!/usr/bin/env python3
"""长文分析数据拉取器 - 3只票完整画像。"""

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
    WestockSource,
    _call_westock,
    _parse_markdown_table,
    to_westock,
)

STOCKS = [
    ("SZ002463", "沪电股份"),
    ("SH600584", "长电科技"),
    ("SH601138", "工业富联"),
]
LOOKBACK_DAYS = 60


def _df_to_records(df):
    if df is None or df.empty:
        return []
    return df.fillna(value=pd.NA).to_dict(orient="records")


def _df_summary(df, n=5):
    if df is None or df.empty:
        return {"shape": [0, 0], "columns": [], "head": []}
    return {
        "shape": list(df.shape),
        "columns": df.columns.tolist(),
        "head": _df_to_records(df.head(n)),
    }


def pull_one(symbol, name, ws):
    print(f"  - {symbol} {name} ...")
    snap = {
        "symbol": symbol,
        "name": name,
        "pulled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    errors = []

    # K 线（直接调模块级函数，避免私有方法名错位）
    try:
        end = datetime.today()
        start = end - timedelta(days=LOOKBACK_DAYS)
        text = _call_westock(
            [
                "kline",
                to_westock(symbol),
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

    # 技术指标
    for grp in ("ma", "macd", "rsi", "kdj", "boll"):
        try:
            snap[f"technical_{grp}"] = _df_summary(ws.get_technical(symbol, grp), n=20)
        except Exception as e:
            errors.append(f"technical_{grp}: {e}")

    # 财务
    for ftype in ("summary", "lrb", "zcfz", "xjll"):
        try:
            snap[f"finance_{ftype}"] = _df_summary(
                ws.get_finance(symbol, ftype, num=4), n=10
            )
        except Exception as e:
            errors.append(f"finance_{ftype}: {e}")

    # 一致预期 + 评级
    try:
        cons = ws.get_consensus(symbol)
        snap["consensus"] = {
            "target_price": cons.get("target_price"),
            "forecasts": _df_to_records(cons.get("forecasts", pd.DataFrame())),
        }
    except Exception as e:
        errors.append(f"consensus: {e}")
    try:
        snap["rating"] = _df_summary(ws.get_rating(symbol), n=5)
    except Exception as e:
        errors.append(f"rating: {e}")

    # 研报 / 新闻 / 公告
    try:
        snap["reports"] = _df_summary(ws.get_report(symbol, limit=5), n=5)
    except Exception as e:
        errors.append(f"reports: {e}")
    try:
        snap["news"] = _df_summary(ws.get_news(symbol, limit=8), n=8)
    except Exception as e:
        errors.append(f"news: {e}")
    try:
        snap["notices"] = _df_summary(ws.get_notice(symbol, limit=5), n=5)
    except Exception as e:
        errors.append(f"notices: {e}")

    # 投资日历
    try:
        snap["calendar"] = _df_summary(ws.get_calendar(limit=10), n=10)
    except Exception as e:
        errors.append(f"calendar: {e}")

    if errors:
        snap["_errors"] = errors
    return snap


def main():
    print(f"拉取 {len(STOCKS)} 只票的完整画像 ...")
    ws = WestockSource()
    data = {
        "pulled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "lookback_days": LOOKBACK_DAYS,
        "stocks": [pull_one(s, n, ws) for s, n in STOCKS],
    }

    # 板块排行
    for key, list_code, sort, limit in [
        ("sector_rank_industry_5d", "concept_list_industry", "chg5Days", 30),
        ("sector_rank_industry_20d", "concept_list_industry", "chg20Days", 30),
        ("sector_rank_sw1_5d", "industry_list_sw1", "chg5Days", 31),
    ]:
        try:
            data[key] = _df_to_records(ws.get_sector_rank(list_code, sort, limit))
            print(f"  - {key} ({len(data[key])} 行) ...")
        except Exception as e:
            data[key] = []
            print(f"  ! {key} failed: {e}")

    out_dir = PROJECT_ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"long_form_data_{datetime.today().strftime('%Y%m%d')}.json"
    out_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\n画像已落盘: {out_file}")
    print(f"文件大小: {out_file.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
