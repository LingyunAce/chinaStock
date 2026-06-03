#!/usr/bin/env python3
"""每日收盘后自动执行的 MACD 信号监控脚本。

用法:
    python scripts/daily_signal.py                     # 检查默认股票
    python scripts/daily_signal.py --symbols SH601138 SZ002463  # 指定股票

输出:
    - 每只票的 MACD DIF/DEA 值
    - 金叉/死叉/无信号判断
    - 次日操作建议（买入/卖出/持有）

设计原则:
    - 只用 westock CLI（本地，不依赖网络）
    - 只计算 MACD 5/13/5（回测最优参数）
    - 输出简洁，适合终端/邮件/微信通知
    - 不做任何自动交易，只给信号
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

from src.data_layer.symbols import to_westock  # noqa: E402
from src.data_sources.westock_source import (  # noqa: E402
    _call_westock,
    _parse_markdown_table,
)

# 默认监控股票（全部沪市主板/深市主板）
DEFAULT_WATCHLIST = [
    ("SH601138", "工业富联"),
    ("SZ002463", "沪电股份"),
]

# MACD 参数（回测最优：强趋势板块年化 +291%）
MACD_FAST = 5
MACD_SLOW = 13
MACD_SIGNAL = 5

# 信号阈值
RSI_OVERBOUGHT = 80  # RSI > 80 视为超买
RSI_OVERSOLD = 20    # RSI < 20 视为超卖


def get_daily_kline(symbol: str, days: int = 60) -> pd.DataFrame:
    """拉取日 K 线。"""
    code = to_westock(symbol)
    text = _call_westock(
        ["kline", code, "--period", "daily", "--limit", str(days)],
        timeout=20,
    )
    df = _parse_markdown_table(text)
    if df.empty:
        return df
    df = df.rename(columns={"last": "close"})
    for col in ("open", "close", "high", "low", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values("date").reset_index(drop=True)
    return df


def compute_macd_signal(df: pd.DataFrame) -> dict:
    """计算 MACD 5/13/5 信号。

    返回 dict:
      - signal: 1 (金叉) / -1 (死叉) / 0 (无信号)
      - dif, dea, macd_hist: 最新值
      - dif_prev, dea_prev: 前一日值
      - signal_desc: 中文描述
    """
    if df.empty or len(df) < MACD_SLOW + MACD_SIGNAL:
        return {"signal": 0, "error": "数据不足"}

    df = df.copy()
    df["ema_fast"] = df["close"].ewm(span=MACD_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=MACD_SLOW, adjust=False).mean()
    df["dif"] = df["ema_fast"] - df["ema_slow"]
    df["dea"] = df["dif"].ewm(span=MACD_SIGNAL, adjust=False).mean()
    df["macd_hist"] = (df["dif"] - df["dea"]) * 2

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    dif = float(latest["dif"])
    dea = float(latest["dea"])
    dif_prev = float(prev["dif"])
    dea_prev = float(prev["dea"])

    # 判断信号
    if dif_prev <= dea_prev and dif > dea:
        signal = 1
        desc = "金叉（DIF 上穿 DEA）"
    elif dif_prev >= dea_prev and dif < dea:
        signal = -1
        desc = "死叉（DIF 下穿 DEA）"
    else:
        signal = 0
        if dif > dea:
            desc = "金叉持续中（DIF > DEA，无新信号）"
        else:
            desc = "死叉持续中（DIF < DEA，无新信号）"

    return {
        "signal": signal,
        "signal_desc": desc,
        "dif": round(dif, 4),
        "dea": round(dea, 4),
        "macd_hist": round(float(latest["macd_hist"]), 4),
        "dif_prev": round(dif_prev, 4),
        "dea_prev": round(dea_prev, 4),
        "close": float(latest["close"]),
        "date": latest["date"],
    }


def compute_rsi(df: pd.DataFrame, period: int = 6) -> float | None:
    """计算 RSI。"""
    if df.empty or len(df) < period + 1:
        return None
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(period).mean().iloc[-1]
    avg_loss = loss.rolling(period).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def compute_ma_trend(df: pd.DataFrame) -> str:
    """MA5/MA10/MA20 方向判断。"""
    if df.empty or len(df) < 20:
        return "unknown"
    close = df["close"]
    ma5 = close.rolling(5).mean().iloc[-1]
    ma10 = close.rolling(10).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    cur = close.iloc[-1]
    if cur > ma5 > ma10 > ma20:
        return "多头排列"
    elif cur < ma5 < ma10 < ma20:
        return "空头排列"
    else:
        return "震荡"


def get_operation_advice(signal: int, rsi: float | None, ma_trend: str) -> str:
    """根据信号 + RSI + MA 趋势给出操作建议。"""
    if signal == 1:
        if rsi and rsi > RSI_OVERBOUGHT:
            return "金叉但 RSI 超买，建议等回调再买"
        if ma_trend == "空头排列":
            return "金叉但均线空头，信号弱，小仓位试探"
        return "金叉买入信号，次日开盘买入"
    elif signal == -1:
        if rsi and rsi < RSI_OVERSOLD:
            return "死叉但 RSI 超卖，可能有反弹，谨慎卖出"
        return "死叉卖出信号，次日开盘卖出"
    else:
        if rsi and rsi > RSI_OVERBOUGHT:
            return "无信号但 RSI 超买，注意回调风险"
        if rsi and rsi < RSI_OVERSOLD:
            return "无信号但 RSI 超卖，可能有反弹机会"
        return "无信号，继续持有或观望"


def check_stock(symbol: str, name: str) -> dict:
    """检查单只票的信号状态。"""
    result = {
        "symbol": symbol,
        "name": name,
        "date": "",
        "close": 0,
        "macd": {},
        "rsi": None,
        "ma_trend": "",
        "advice": "",
    }

    try:
        df = get_daily_kline(symbol, days=60)
        if df.empty:
            result["advice"] = "数据拉取失败"
            return result

        result["date"] = df.iloc[-1]["date"]
        result["close"] = float(df.iloc[-1]["close"])

        # MACD 信号
        macd = compute_macd_signal(df)
        result["macd"] = macd

        # RSI
        result["rsi"] = compute_rsi(df)

        # MA 趋势
        result["ma_trend"] = compute_ma_trend(df)

        # 操作建议
        result["advice"] = get_operation_advice(
            macd["signal"], result["rsi"], result["ma_trend"]
        )

    except Exception as e:
        result["advice"] = f"检查失败: {e}"

    return result


def format_report(results: list[dict], date: str) -> str:
    """格式化终端报告。"""
    lines = []
    lines.append("")
    lines.append("=" * 60)
    lines.append(f"  每日信号报告 — {date}")
    lines.append("=" * 60)

    for r in results:
        macd = r["macd"]
        signal = macd.get("signal", 0)
        icon = "🟢" if signal > 0 else ("🔴" if signal < 0 else "⚪")

        lines.append("")
        lines.append(f"  {icon} {r['symbol']} {r['name']}")
        lines.append(f"  {'─' * 40}")
        lines.append(f"  收盘价: {r['close']:.2f}  日期: {r['date']}")
        lines.append(f"  MACD:  DIF={macd.get('dif', 0):.4f}  DEA={macd.get('dea', 0):.4f}  HIST={macd.get('macd_hist', 0):.4f}")
        lines.append(f"  信号:  {macd.get('signal_desc', '未知')}")
        lines.append(f"  RSI6:  {r['rsi']}")
        lines.append(f"  均线:  {r['ma_trend']}")
        lines.append(f"  建议:  {r['advice']}")

    lines.append("")
    lines.append("=" * 60)

    # 汇总
    signals = [r for r in results if r["macd"].get("signal") != 0]
    if signals:
        lines.append(f"  ⚡ {len(signals)} 只票有信号，需要操作！")
    else:
        lines.append("  ✅ 无信号，继续持有或观望。")
    lines.append("=" * 60)
    lines.append("")

    return "\n".join(lines)


def save_report(results: list[dict], date: str) -> Path:
    """保存 JSON 报告到 results/ 目录。"""
    out_dir = PROJECT_ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"daily_signal_{date.replace('-', '')}.json"
    out_file.write_text(
        json.dumps({"date": date, "signals": results}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return out_file


def main():
    parser = argparse.ArgumentParser(description="每日收盘后 MACD 信号监控")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="股票列表 (如 SH601138 SZ002463)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="只输出 JSON（适合程序调用）",
    )
    args = parser.parse_args()

    watchlist = DEFAULT_WATCHLIST
    if args.symbols:
        # 用户指定的股票，名称未知
        watchlist = [(s, s) for s in args.symbols]

    today = datetime.today().strftime("%Y-%m-%d")
    results = []

    for symbol, name in watchlist:
        result = check_stock(symbol, name)
        results.append(result)

    # 保存 JSON
    out_file = save_report(results, today)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    else:
        report = format_report(results, today)
        print(report)
        print(f"  报告已保存: {out_file}")


if __name__ == "__main__":
    main()
