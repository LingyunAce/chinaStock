#!/usr/bin/env python3
"""多票横向分析 + HTML 可视化报告。

输入：[(symbol, name), ...] 列表
输出：reports/multi_analysis_<YYYYMMDD>.html（内嵌 Chart.js 图表）

依赖：westock（本地 Node CLI）作为主数据源，AKShare 作为补充。
网络不可达时优雅降级，仍输出已拉到的部分。
"""
from __future__ import annotations

import html
import json
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

from src.data_sources.akshare_source import AkShareSource  # noqa: E402
from src.data_sources.westock_source import (  # noqa: E402
    _call_westock,
    _parse_markdown_table,
)
from src.integrations.limit_up import (  # noqa: E402
    get_limit_up_pool,
    market_sentiment_score,
)
from src.integrations.sectors import (  # noqa: E402
    find_symbol_sectors,
    get_sector_performance,
)

# ----------------------------- 配置 -----------------------------
STOCKS = [
    ("SZ002463", "沪电股份"),
    ("SH600584", "长电科技"),
    ("SH601138", "工业富联"),
]
LOOKBACK_DAYS = 30
WESTOCK_CODE_MAP = {
    "SZ002463": "sz002463",
    "SH600584": "sh600584",
    "SH601138": "sh601138",
}

# ----------------------------- 工具 -----------------------------
def _westock_kline(code: str, days: int) -> pd.DataFrame:
    end = datetime.today()
    start = end - timedelta(days=days)
    text = _call_westock(
        [
            "kline",
            code,
            "--period",
            "daily",
            "--start",
            start.strftime("%Y%m%d"),
            "--end",
            end.strftime("%Y%m%d"),
        ],
        timeout=20,
    )
    df = _parse_markdown_table(text)
    if df.empty:
        return df
    return df.rename(columns={"last": "close"})


def _westock_profile(code: str) -> dict:
    text = _call_westock(["profile", code], timeout=20)
    df = _parse_markdown_table(text)
    if df.empty:
        return {}
    return df.iloc[0].to_dict()


def _westock_lhb_top(date: str, n: int = 5) -> pd.DataFrame:
    try:
        text = _call_westock(
            ["lhb", "--tab", "jg", "--date", date.replace("-", "")], timeout=20
        )
        df = _parse_markdown_table(text)
        if "净买入额" in df.columns:
            df["net_buy_amount"] = df["净买入额"].apply(
                lambda x: float(str(x).replace("亿", "").replace("万", "")) * (
                    1e8 if "亿" in str(x) else (1e4 if "万" in str(x) else 1)
                )
                if pd.notna(x)
                else 0
            )
        return df.head(n)
    except Exception:
        return pd.DataFrame()


# ----------------------------- 单票分析 -----------------------------
def analyze_one(symbol: str, name: str, ak: AkShareSource) -> dict:
    """对单只票做端到端分析，返回 dict 供 HTML 模板使用。"""
    result = {
        "symbol": symbol,
        "name": name,
        "westock_code": WESTOCK_CODE_MAP.get(symbol, symbol.lower()),
        "profile": {},
        "kline": pd.DataFrame(),
        "on_lhb": False,
        "sectors": [],
        "metrics": {},
        "data_status": {},
    }

    # 1. 基本信息
    try:
        result["profile"] = _westock_profile(result["westock_code"])
        result["data_status"]["profile"] = "ok"
    except Exception as e:
        result["data_status"]["profile"] = f"failed: {str(e)[:60]}"

    # 2. K 线
    try:
        result["kline"] = _westock_kline(result["westock_code"], LOOKBACK_DAYS)
        result["data_status"]["kline"] = "ok"
    except Exception as e:
        result["data_status"]["kline"] = f"failed: {str(e)[:60]}"

    # 3. 异动归因（westock 龙虎榜）
    try:
        recent = (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        lhb_text = _call_westock(
            ["lhb", "--tab", "jg", "--date", recent.replace("-", "")], timeout=20
        )
        lhb_df = _parse_markdown_table(lhb_text)
        if not lhb_df.empty and "代码" in lhb_df.columns:
            result["on_lhb"] = (
                lhb_df["代码"].str.lower() == result["westock_code"]
            ).any()
        result["data_status"]["lhb"] = "ok"
    except Exception as e:
        result["data_status"]["lhb"] = f"failed: {str(e)[:60]}"

    # 4. 计算核心指标
    df = result["kline"]
    if not df.empty and "close" in df.columns:
        for col in ("open", "close", "high", "low", "volume", "amount"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["close"]).reset_index(drop=True)

        latest = df.iloc[0]
        metrics = {
            "latest_close": float(latest["close"]),
            "latest_date": str(latest["date"]),
            "day_chg_pct": (
                (float(latest["close"]) / float(latest["open"]) - 1) * 100
                if "open" in df.columns and float(latest["open"]) > 0
                else 0
            ),
        }
        if len(df) >= 5:
            close_5d_ago = float(df.iloc[4]["close"])
            metrics["chg_5d_pct"] = (metrics["latest_close"] / close_5d_ago - 1) * 100
        if len(df) >= 20:
            close_20d_ago = float(df.iloc[19]["close"])
            metrics["chg_20d_pct"] = (
                metrics["latest_close"] / close_20d_ago - 1
            ) * 100
        if "amount" in df.columns and len(df) >= 5:
            metrics["avg_amount_5d_wan"] = float(df.head(5)["amount"].mean()) / 1e4
        if "high" in df.columns and "low" in df.columns and len(df) >= 20:
            high_20d = float(df.head(20)["high"].max())
            low_20d = float(df.head(20)["low"].min())
            cur = metrics["latest_close"]
            if high_20d != low_20d:
                # 当前价在 20 日区间的位置（0=最低，1=最高）
                metrics["pos_in_20d_range"] = (cur - low_20d) / (high_20d - low_20d)
        result["metrics"] = metrics
        result["kline"] = df  # 覆盖成清洗过的

    # 5. 所属概念板块（AKShare，失败不致命）
    try:
        result["sectors"] = find_symbol_sectors(symbol, source=ak)
        result["data_status"]["sectors"] = "ok"
    except Exception as e:
        result["data_status"]["sectors"] = f"failed: {str(e)[:60]}"

    return result


# ----------------------------- HTML 模板 -----------------------------
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>AI算力链 多票横向分析 — {date}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; margin: 0; padding: 24px; background: #f6f7f9; color: #1a1a1a; }}
  .container {{ max-width: 1280px; margin: 0 auto; }}
  h1 {{ font-size: 24px; margin: 0 0 8px; }}
  h2 {{ font-size: 18px; margin: 32px 0 12px; padding-left: 12px; border-left: 4px solid #2962ff; }}
  h3 {{ font-size: 15px; margin: 16px 0 8px; color: #2962ff; }}
  .subtitle {{ color: #666; font-size: 13px; margin-bottom: 24px; }}
  .meta {{ background: #fff; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
  .meta table {{ border-collapse: collapse; width: 100%; }}
  .meta td {{ padding: 6px 12px; font-size: 13px; border-bottom: 1px solid #eee; }}
  .meta td:first-child {{ color: #666; width: 110px; }}
  .card-row {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 16px; }}
  .card {{ background: #fff; border-radius: 8px; padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
  .card .ticker {{ font-size: 18px; font-weight: 600; }}
  .card .name {{ color: #666; font-size: 13px; }}
  .card .price {{ font-size: 22px; font-weight: 700; margin-top: 8px; }}
  .card .chg.up {{ color: #d32f2f; font-size: 14px; }}
  .card .chg.down {{ color: #2e7d32; font-size: 14px; }}
  .card .metric {{ display: flex; justify-content: space-between; padding: 4px 0; font-size: 12px; color: #555; border-bottom: 1px dotted #eee; }}
  .card .metric:last-child {{ border-bottom: none; }}
  .card .metric b {{ color: #1a1a1a; }}
  .chart-box {{ background: #fff; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
  .chart-box h3 {{ margin-top: 0; }}
  canvas {{ max-height: 320px; }}
  .tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-right: 4px; }}
  .tag.on {{ background: #d32f2f; color: #fff; }}
  .tag.off {{ background: #e0e0e0; color: #666; }}
  .tag.warn {{ background: #ff9800; color: #fff; }}
  .footer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid #ddd; color: #888; font-size: 12px; }}
  table.summary {{ border-collapse: collapse; width: 100%; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.06); border-radius: 8px; overflow: hidden; }}
  table.summary th, table.summary td {{ padding: 10px 14px; text-align: right; font-size: 13px; border-bottom: 1px solid #eee; }}
  table.summary th {{ background: #fafafa; font-weight: 600; color: #555; text-align: center; }}
  table.summary td:first-child, table.summary th:first-child {{ text-align: left; }}
</style>
</head>
<body>
<div class="container">
  <h1>AI 算力链 — 多票横向分析</h1>
  <div class="subtitle">生成时间: {date}  |  窗口: 近 {lookback} 日  |  数据源: westock (主) + AKShare (补)</div>

  {sentiment_block}

  <h2>1. 横向对比卡</h2>
  <div class="card-row">
    {cards}
  </div>

  <h2>2. 近 30 日 K 线叠加</h2>
  <div class="chart-box">
    <canvas id="klineChart"></canvas>
  </div>

  <h2>3. 关键指标对比</h2>
  <table class="summary">
    <thead>
      <tr><th>指标</th>{metric_headers}</tr>
    </thead>
    <tbody>
      {metric_rows}
    </tbody>
  </table>

  <h2>4. 涨幅对比（5 日 / 20 日 / 当日）</h2>
  <div class="chart-box">
    <canvas id="returnChart"></canvas>
  </div>

  <h2>5. 20 日价格区间位置（越高越接近高点）</h2>
  <div class="chart-box">
    <canvas id="rangeChart"></canvas>
  </div>

  {sectors_block}

  <h2>7. 当日龙虎榜 TOP 5（全市场，机构榜）</h2>
  {lhb_block}

  <div class="footer">
    <p>本报告由 chinaStock 框架自动生成，仅供研究参考，不构成投资建议。</p>
    <p>数据来源：westock-data (Node CLI, 腾讯自选股) + AKShare (东方财富等公开数据源)。AKShare 网络受限时优雅降级。</p>
  </div>
</div>

<script>
{kline_js}
{return_js}
{range_js}
</script>
</body>
</html>
"""


def _card_html(r: dict) -> str:
    m = r.get("metrics", {})
    price = m.get("latest_close", 0)
    chg = m.get("day_chg_pct", 0)
    chg_class = "up" if chg >= 0 else "down"
    chg_str = f"{chg:+.2f}%"
    lhb_tag = (
        '<span class="tag on">龙虎榜</span>'
        if r.get("on_lhb")
        else '<span class="tag off">未上榜</span>'
    )
    industry = r.get("profile", {}).get("industry", "—")
    return f"""
    <div class="card">
      <div class="ticker">{html.escape(r['symbol'])} {lhb_tag}</div>
      <div class="name">{html.escape(r['name'])} · {html.escape(industry)}</div>
      <div class="price">{price:.2f}</div>
      <div class="chg {chg_class}">当日 {chg_str}</div>
      <div class="metric"><span>5 日累计</span><b style="color:{'#d32f2f' if m.get('chg_5d_pct', 0)>=0 else '#2e7d32'}">{m.get('chg_5d_pct', 0):+.2f}%</b></div>
      <div class="metric"><span>20 日累计</span><b style="color:{'#d32f2f' if m.get('chg_20d_pct', 0)>=0 else '#2e7d32'}">{m.get('chg_20d_pct', 0):+.2f}%</b></div>
      <div class="metric"><span>20 日区间位置</span><b>{m.get('pos_in_20d_range', 0)*100:.0f}%</b></div>
      <div class="metric"><span>5 日均成交额(万)</span><b>{m.get('avg_amount_5d_wan', 0):,.0f}</b></div>
      <div class="metric"><span>最新交易日</span><b>{m.get('latest_date', '—')}</b></div>
    </div>
    """


def _kline_chart_js(stocks: list[dict]) -> str:
    """生成 K 线对比 Chart.js 脚本（归一化到 100 的相对走势）。"""
    datasets = []
    colors = ["#2962ff", "#d32f2f", "#2e7d32"]
    for i, r in enumerate(stocks):
        df = r["kline"]
        if df.empty or "close" not in df.columns:
            continue
        # 归一化：首日 = 100
        closes = pd.to_numeric(df["close"], errors="coerce").dropna().tolist()
        if not closes:
            continue
        dates = df["date"].tolist()[: len(closes)]
        base = closes[0] if closes[0] else 1
        normed = [c / base * 100 for c in closes]
        # 反转让最新日期在左
        normed = list(reversed(normed))
        dates = list(reversed(dates))
        datasets.append(
            {
                "label": f"{r['symbol']} {r['name']}",
                "data": normed,
                "borderColor": colors[i % 3],
                "backgroundColor": "transparent",
                "borderWidth": 2,
                "pointRadius": 0,
                "tension": 0.1,
            }
        )
    return f"""
    const klineCtx = document.getElementById('klineChart').getContext('2d');
    new Chart(klineCtx, {{
      type: 'line',
      data: {{ labels: {json.dumps(dates)}, datasets: {json.dumps(datasets)} }},
      options: {{
        responsive: true,
        plugins: {{ legend: {{ position: 'top' }}, title: {{ display: true, text: '归一化股价（首日=100）' }} }},
        scales: {{ y: {{ ticks: {{ callback: v => v.toFixed(0) }} }} }}
      }}
    }});
    """


def _return_chart_js(stocks: list[dict]) -> str:
    labels = [f"{r['symbol']} {r['name']}" for r in stocks]
    day_chg = [r.get("metrics", {}).get("day_chg_pct", 0) for r in stocks]
    chg_5d = [r.get("metrics", {}).get("chg_5d_pct", 0) for r in stocks]
    chg_20d = [r.get("metrics", {}).get("chg_20d_pct", 0) for r in stocks]
    return f"""
    const retCtx = document.getElementById('returnChart').getContext('2d');
    new Chart(retCtx, {{
      type: 'bar',
      data: {{
        labels: {json.dumps(labels)},
        datasets: [
          {{ label: '当日', data: {json.dumps(day_chg)}, backgroundColor: '#2962ff' }},
          {{ label: '5 日', data: {json.dumps(chg_5d)}, backgroundColor: '#ff9800' }},
          {{ label: '20 日', data: {json.dumps(chg_20d)}, backgroundColor: '#9c27b0' }},
        ]
      }},
      options: {{
        responsive: true,
        plugins: {{ legend: {{ position: 'top' }} }},
        scales: {{ y: {{ ticks: {{ callback: v => v + '%' }} }} }}
      }}
    }});
    """


def _range_chart_js(stocks: list[dict]) -> str:
    labels = [f"{r['symbol']} {r['name']}" for r in stocks]
    pos = [r.get("metrics", {}).get("pos_in_20d_range", 0) * 100 for r in stocks]
    return f"""
    const rangeCtx = document.getElementById('rangeChart').getContext('2d');
    new Chart(rangeCtx, {{
      type: 'bar',
      data: {{
        labels: {json.dumps(labels)},
        datasets: [{{ label: '20 日区间位置 %', data: {json.dumps(pos)},
                       backgroundColor: pos.map(v => v > 80 ? '#d32f2f' : (v < 20 ? '#2e7d32' : '#ff9800')) }}]
      }},
      options: {{
        responsive: true,
        indexAxis: 'y',
        plugins: {{ legend: {{ display: false }} }},
        scales: {{ x: {{ min: 0, max: 100, ticks: {{ callback: v => v + '%' }} }} }}
      }}
    }});
    """


def _sectors_block(stocks: list[dict]) -> str:
    parts = ["<h2>6. 所属概念板块（每只票）</h2>"]
    for r in stocks:
        sec = r.get("sectors", [])
        sec_str = ", ".join(sec[:15]) if sec else "（AKShare 不可达，详见 westock profile 所属行业）"
        parts.append(
            f"<div class='meta'><b>{r['symbol']} {r['name']}</b> · {html.escape(sec_str)}</div>"
        )
    return "\n".join(parts)


def _lhb_block(stocks: list[dict], date: str) -> str:
    df = _westock_lhb_top(date, n=5)
    if df.empty:
        return "<div class='meta'>(westock 龙虎榜该日无数据)</div>"
    rows = []
    for _, row in df.iterrows():
        rows.append(
            f"<tr><td>{html.escape(str(row.get('代码','')))}</td>"
            f"<td>{html.escape(str(row.get('名称','')))}</td>"
            f"<td style='text-align:right'>{row.get('净买入额','-')}</td>"
            f"<td style='text-align:right'>{row.get('涨跌幅','-')}</td></tr>"
        )
    return f"""
    <table class="summary">
      <thead><tr><th style="text-align:left">代码</th><th style="text-align:left">名称</th><th>净买入额</th><th>涨跌幅</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """


def _sentiment_block(date: str, ak: AkShareSource) -> str:
    try:
        s = market_sentiment_score(date, source=ak)
        sent_class = "on" if s["sentiment"] == "overheat" else (
            "warn" if s["sentiment"] == "normal" else "off"
        )
        return f"""
        <div class="meta">
          <b>当日市场情绪:</b>
          <span class="tag {sent_class}">{s['sentiment'].upper()}</span>
          涨停 {s['limit_up_count']} 只 | 最高 {s['max_consecutive']} 连板 | 炸板率 {s['broken_ratio']*100:.1f}%
        </div>
        """
    except Exception as e:
        return f"<div class='meta'>市场情绪: AKShare 不可达 ({str(e)[:50]})</div>"


# ----------------------------- 主流程 -----------------------------
def main() -> int:
    today = datetime.today()
    recent = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    if today.weekday() == 0:
        recent = (today - timedelta(days=3)).strftime("%Y-%m-%d")

    print(f"开始分析 {len(STOCKS)} 只票 ...")
    ak = AkShareSource()
    results = []
    for symbol, name in STOCKS:
        print(f"  - {symbol} {name} ...")
        r = analyze_one(symbol, name, ak)
        results.append(r)
        m = r.get("metrics", {})
        print(
            f"      最新: {m.get('latest_close','-')}  5d: {m.get('chg_5d_pct',0):+.2f}%  "
            f"上榜: {r.get('on_lhb')}"
        )

    # 输出
    out_dir = PROJECT_ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"ai_compute_chain_{today.strftime('%Y%m%d')}.html"

    html_out = HTML_TEMPLATE.format(
        date=today.strftime("%Y-%m-%d %H:%M"),
        lookback=LOOKBACK_DAYS,
        sentiment_block=_sentiment_block(recent, ak),
        cards="\n".join(_card_html(r) for r in results),
        metric_headers="".join(f"<th>{html.escape(r['symbol'])}<br><span style='font-weight:400;color:#888'>{html.escape(r['name'])}</span></th>" for r in results),
        metric_rows="\n".join(
            f"<tr><td>{label}</td>" + "".join(
                f"<td style='color:{'#d32f2f' if v>=0 else '#2e7d32'}'>{v:+.2f}%</td>"
                for v in vals
            ) + "</tr>"
            for label, vals in [
                ("当日涨幅", [r.get("metrics", {}).get("day_chg_pct", 0) for r in results]),
                ("5 日累计", [r.get("metrics", {}).get("chg_5d_pct", 0) for r in results]),
                ("20 日累计", [r.get("metrics", {}).get("chg_20d_pct", 0) for r in results]),
            ]
        ),
        kline_js=_kline_chart_js(results),
        return_js=_return_chart_js(results),
        range_js=_range_chart_js(results),
        sectors_block=_sectors_block(results),
        lhb_block=_lhb_block(results, recent),
    )
    out_file.write_text(html_out, encoding="utf-8")
    print(f"\n报告已保存: {out_file}")
    print(f"文件大小: {out_file.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
