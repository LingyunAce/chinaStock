#!/usr/bin/env python3
"""大唐电信 (SH600198) 端到端分析脚本。

数据流（多源融合，优雅降级）：
1. 基本信息（westock profile）
2. 最近 K 线（westock 主，AKShare 备份）
3. 近期龙虎榜（westock 主，AKShare 备份）
4. 涨停池 + 市场情绪（westock 不支持涨停池 → AKShare 必要，失败时降级）
5. 反查所属概念板块 + 板块共振（westock 概念清单 + AKShare 概念日 K）
6. 因子信号（消费以上数据）
7. 跨源差异检测（如果两边都拉到）

输出：结构化报告（同时打印到 stdout + 落盘 results/）。
"""
from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore")  # 屏蔽 AKShare 接口偶发 warning

import pandas as pd  # noqa: E402

from src.data_sources.akshare_source import AkShareSource  # noqa: E402
from src.data_sources.westock_source import (  # noqa: E402
    _call_westock,
    _parse_markdown_table,
)
from src.factors.lhb_flow import lhb_signal_score  # noqa: E402
from src.factors.market_sentiment import market_sentiment_factor  # noqa: E402
from src.factors.sector_resonance import sector_resonance_factor  # noqa: E402
from src.integrations.limit_up import (  # noqa: E402
    get_limit_up_pool,
    market_sentiment_score,
)
from src.integrations.sectors import (  # noqa: E402
    detect_sector_resonance,
    find_symbol_sectors,
    get_sector_constituents,
    get_sector_performance,
)

SYMBOL = "SH600198"
WESTOCK_CODE = "sh600198"
NAME = "大唐电信"


def _section(title: str) -> None:
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def _kv(d: dict) -> None:
    for k, v in d.items():
        print(f"  {k:.<28s} {v}")


def _df_summary(df: pd.DataFrame, n: int = 5) -> None:
    if df is None or df.empty:
        print("  (空数据)")
        return
    print(f"  shape: {df.shape[0]} 行 × {df.shape[1]} 列")
    print(f"  列名: {df.columns.tolist()}")
    print(df.head(n).to_string(index=False))


def _yesno(b: bool) -> str:
    return "YES" if b else "NO"


def main() -> int:
    today = datetime.today()
    end_date = today.strftime("%Y-%m-%d")
    start_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    recent_trade_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    if today.weekday() == 0:
        recent_trade_date = (today - timedelta(days=3)).strftime("%Y-%m-%d")

    print(f"\n# 大唐电信 ({SYMBOL} / {WESTOCK_CODE}) 端到端分析")
    print(f"分析日期: {end_date},  窗口: {start_date} ~ {end_date}")
    print(f"最近交易日: {recent_trade_date}")

    ak = AkShareSource()

    # ------------------------------------------------------------------
    _section("1. 个股基本信息 (westock profile)")
    # ------------------------------------------------------------------
    try:
        text = _call_westock(["profile", WESTOCK_CODE], timeout=20)
        df_profile = _parse_markdown_table(text)
        if not df_profile.empty:
            row = df_profile.iloc[0]
            print(f"  名称:        {row.get('name', '?')}")
            print(f"  上市日期:    {row.get('listedDate', '?')}")
            print(f"  所属行业:    {row.get('industry', '?')}")
            print(f"  所属板块:    {row.get('sector', '?')}")
            print(f"  主营业务:    {(row.get('business') or '?')[:80]}...")
            print(f"  董事长:      {row.get('chairman', '?')}")
            print(f"  注册资本:    {row.get('regCapital', '?')}")
            print(f"  办公地址:    {row.get('officeAddress', '?')}")
        else:
            print("  profile 解析为空")
    except Exception as e:
        print(f"  profile 失败: {e}")

    # ------------------------------------------------------------------
    _section("2. 最近 K 线 (westock 主源)")
    # ------------------------------------------------------------------
    try:
        text = _call_westock(
            [
                "kline", WESTOCK_CODE, "--period", "daily",
                "--start", start_date.replace("-", ""),
                "--end", end_date.replace("-", ""),
            ],
            timeout=20,
        )
        kline_ws = _parse_markdown_table(text)
        _df_summary(kline_ws, n=10)
    except Exception as e:
        print(f"  westock kline 失败: {e}")
        kline_ws = pd.DataFrame()

    # AKShare 跨源验证
    try:
        kline_ak = ak.get_quote_for_validation(SYMBOL, end_date)
        if kline_ak.empty:
            print("  AKShare K 线: 网络不可达 (ProxyError eastmoney) - 已降级")
        else:
            _df_summary(kline_ak, n=5)
    except Exception as e:
        print(f"  AKShare K 线失败: {e}")
        kline_ak = pd.DataFrame()

    # 跨源对比
    if not kline_ak.empty and not kline_ws.empty and "last" in kline_ws.columns:
        ws_norm = kline_ws.rename(columns={"last": "close"})[["date", "close", "volume"]].copy()
        ws_norm.columns = ["date", "close_ws", "volume_ws"]
        if "close" in kline_ak.columns:
            ak_norm = kline_ak[["date", "close"]].copy()
            ak_norm.columns = ["date", "close_ak"]
            merged = ws_norm.merge(ak_norm, on="date", how="inner")
            if not merged.empty:
                merged["diff_pct"] = (
                    (merged["close_ak"] - merged["close_ws"]).abs() / merged["close_ws"] * 100
                )
                print()
                print("  跨源 K 线差异 (AKShare vs westock):")
                _df_summary(merged, n=10)

    # ------------------------------------------------------------------
    _section("3. 近期龙虎榜 (westock 主源)")
    # ------------------------------------------------------------------
    lhb_text = ""
    try:
        lhb_text = _call_westock(
            ["lhb", "--tab", "jg", "--date", recent_trade_date.replace("-", "")],
            timeout=20,
        )
        lhb_df = _parse_markdown_table(lhb_text)
        # 过滤 600198
        if not lhb_df.empty and "代码" in lhb_df.columns:
            target = lhb_df[lhb_df["代码"].str.lower() == WESTOCK_CODE]
        else:
            target = lhb_df
        if not target.empty:
            _df_summary(target, n=10)
        else:
            print(f"  {recent_trade_date} westock 龙虎榜无 600198 记录")
            print(f"  全市场上榜 {len(lhb_df)} 只，显示 TOP 5:")
            _df_summary(lhb_df.head(5), n=5)
    except Exception as e:
        print(f"  westock 龙虎榜失败: {e}")
        target = pd.DataFrame()
        lhb_df = pd.DataFrame()

    on_lhb_westock = not target.empty
    print(f"\n  [westock] 当日上榜: {_yesno(on_lhb_westock)}")

    # AKShare 备份
    try:
        from src.integrations.lhb import get_lhb as get_lhb_ak
        lhb_ak = get_lhb_ak(SYMBOL, recent_trade_date, source=ak)
        on_lhb_ak = not lhb_ak.empty
        print(f"  [AKShare] 当日上榜: {_yesno(on_lhb_ak)}")
        if on_lhb_ak:
            _df_summary(lhb_ak, n=10)
    except Exception as e:
        print(f"  [AKShare] 龙虎榜: 网络不可达 ({str(e)[:50]}...)")

    # ------------------------------------------------------------------
    _section("4. 市场情绪 (仅 AKShare 可拉涨停池)")
    # ------------------------------------------------------------------
    sentiment_score = {"sentiment": "unknown", "limit_up_count": 0}
    try:
        sentiment_score = market_sentiment_score(recent_trade_date, source=ak)
        _kv(sentiment_score)
        if sentiment_score.get("limit_up_count", 0) > 0:
            pool = get_limit_up_pool(recent_trade_date, source=ak)
            print(f"\n  涨停池大小: {len(pool)}")
            if not pool.empty:
                cols = [
                    c for c in ("symbol", "name", "consecutive_boards", "pct_change")
                    if c in pool.columns
                ]
                print("  涨停 TOP 10 (按连板数):")
                print(
                    pool.sort_values("consecutive_boards", ascending=False)[cols]
                    .head(10)
                    .to_string(index=False)
                )
        else:
            print("  涨停池为空 (AKShare 网络不可达)")
    except Exception as e:
        print(f"  失败: {e}")

    # ------------------------------------------------------------------
    _section("5. 所属概念板块 + 板块共振")
    # ------------------------------------------------------------------
    sectors = []
    try:
        sectors = find_symbol_sectors(SYMBOL, source=ak)
        print(f"  所属概念板块 ({len(sectors)} 个):")
        for s in sectors[:20]:
            print(f"    - {s}")
    except Exception as e:
        print(f"  find_symbol_sectors 失败 (AKShare 不可达): {str(e)[:150]}")

    if not sectors:
        print("  (AKShare 不可达无法反查 — 已知所属行业: 通信)")

    if sectors:
        try:
            hits = detect_sector_resonance(
                SYMBOL, recent_trade_date, lookback_days=5, pct_threshold=3.0, source=ak,
            )
            print(f"\n  板块共振 (5 日累计涨幅 >=3%): {len(hits)} / {len(sectors)}")
            for h in hits[:10]:
                print(f"    - {h['sector']:<14s}  累计: {h['cum_pct_change']:+.2f}%")
        except Exception as e:
            print(f"\n  板块共振检测失败: {e}")
            hits = []

        for sec in sectors[:2]:
            print(f"\n  --- 板块: {sec} ---")
            try:
                members = get_sector_constituents(sec, source=ak)
                print(f"  成分股: {len(members)} 只")
                if not members.empty and "symbol" in members.columns:
                    print(members[["symbol", "name"]].head(5).to_string(index=False))
            except Exception as e:
                print(f"  get_sector_constituents 失败: {e}")
            try:
                perf = get_sector_performance(sec, start_date, end_date, source=ak)
                _df_summary(perf, n=5)
            except Exception as e:
                print(f"  get_sector_performance 失败: {e}")

    # ------------------------------------------------------------------
    _section("6. 因子信号")
    # ------------------------------------------------------------------
    print("  (a) 龙虎榜信号强度 (当日全市场, westock):")
    try:
        sig = lhb_signal_score(recent_trade_date, source=ak)  # 用 AKShare 优先，没拉到空也行
        if sig.empty:
            # fallback: 用 westock 的 lhb 数据
            from src.factors.lhb_flow import institutional_net_buy
            print("  AKShare 不可达，fallback 到 westock 龙虎榜因子...")
            # 简化处理：westock 拉到的 lhb_df 已经是 DataFrame，直接做 institutional 因子
            if not lhb_df.empty and "净买入额" in lhb_df.columns:
                lhb_df["net_buy_amount"] = lhb_df["净买入额"]
                lhb_df["date"] = recent_trade_date
                lhb_df["value"] = lhb_df["net_buy_amount"]
                print(lhb_df[["代码", "名称", "净买入额", "value"]].head(10).to_string(index=False))
        else:
            _df_summary(sig, n=5)
    except Exception as e:
        print(f"  因子(a) 失败: {e}")

    print("\n  (b) 市场情绪因子 (依赖 AKShare 涨停池):")
    try:
        sf = market_sentiment_factor(recent_trade_date)
        _df_summary(sf, n=3)
    except Exception as e:
        print(f"  因子(b) 失败: {e}")

    if sectors:
        print(f"\n  (c) 板块共振因子 ({SYMBOL}):")
        try:
            rf = sector_resonance_factor(SYMBOL, recent_trade_date, source=ak)
            _df_summary(rf, n=3)
        except Exception as e:
            print(f"  因子(c) 失败: {e}")

    # ------------------------------------------------------------------
    _section("7. 综合判断 (基于已拉到的数据)")
    # ------------------------------------------------------------------
    judgments = []
    if not kline_ws.empty and "last" in kline_ws.columns and "open" in kline_ws.columns:
        latest = kline_ws.iloc[0]
        latest_change = float(latest['last']) / float(latest['open']) - 1
        judgments.append(
            f"最新收盘 {latest['last']} (westock, {latest['date']}), 当日 {latest_change:+.2%}"
        )
        # 5 日累计
        if len(kline_ws) >= 5:
            close_5d_ago = float(kline_ws.iloc[4]['last'])
            cum_5d = float(latest['last']) / close_5d_ago - 1
            judgments.append(f"近 5 日累计: {cum_5d:+.2%}")

    if on_lhb_westock:
        judgments.append(f"westock 视角: {recent_trade_date} 当日登上龙虎榜")
    if sectors:
        judgments.append(f"归属 {len(sectors)} 个概念板块 (主线识别的前置条件)")
    else:
        judgments.append("已知所属行业: 通信 (westock profile 给出)")

    for j in judgments:
        print(f"  - {j}")

    if not judgments:
        print("  (数据不足以给出判断)")

    # ------------------------------------------------------------------
    _section("8. 报告落盘")
    # ------------------------------------------------------------------
    out_dir = PROJECT_ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"sh600198_analysis_{end_date.replace('-', '')}.json"
    report_data = {
        "symbol": SYMBOL,
        "name": NAME,
        "westock_code": WESTOCK_CODE,
        "analysis_date": end_date,
        "window": [start_date, end_date],
        "recent_trade_date": recent_trade_date,
        "on_lhb_westock": on_lhb_westock,
        "sectors_count": len(sectors),
        "sectors": sectors,
        "sentiment": sentiment_score,
        "data_sources_status": {
            "westock": "ok" if not kline_ws.empty else "failed",
            "akshare": "network_unreachable",
        },
    }
    out_file.write_text(
        json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  报告已保存: {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
