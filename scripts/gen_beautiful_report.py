#!/usr/bin/env python3
"""生成深色玻璃态主题的 AI 算力链多票分析报告 HTML。

设计语言（参照 reports/ 里的旧 cross-signals 报告）：
- 深色渐变背景 (#0a0e27 -> #1a1f3a -> #0f1729)
- 玻璃态卡片 (rgba + backdrop-blur)
- conic-gradient 评分环
- 信号徽章 (绿/黄/红)
- 力道横条 (DMI 风格)
- 多 Chart.js 图表 (折线 / 柱状 / 雷达 / 环形)
- 颜色: 牛 #22c55e / 熊 #ef4444 / 中性 #facc15 / 强调 #a855f7
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


# ==================== 数据加载 ====================
def load_data() -> dict:
    p = PROJECT_ROOT / "reports" / "long_form_data_20260603.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


# ==================== 颜色与工具 ====================
BULL = "#22c55e"
BULL_LIGHT = "#4ade80"
BEAR = "#ef4444"
BEAR_LIGHT = "#f87171"
NEUTRAL = "#facc15"
NEUTRAL_LIGHT = "#fbbf24"
PURPLE = "#a855f7"
BLUE = "#3b82f6"
CYAN = "#06b6d4"


def fmt_pct(v: float, sign: bool = True) -> str:
    if v is None:
        return "—"
    s = f"{v:+.2f}%" if sign else f"{v:.2f}%"
    return s


def fmt_亿(v: float) -> str:
    if v is None:
        return "—"
    return f"{v / 1e8:.1f} 亿"


# ==================== 评分计算 ====================
def calc_alignment_score(s: dict) -> dict:
    """给每只票算跨域对齐度评分（业绩×资金×估值三角）。"""
    fs = s.get("finance_summary", {}).get("head", [])
    ni_yoy = 0
    rev_yoy = 0
    if len(fs) >= 2:
        # 比较最新年报 vs 第一期（2024 全年 vs 2025 Q1 累计，估算 YoY）
        last = fs[-1]
        first = fs[0]
        ni_last = _f(last.get("NPParentCompanyOwnersTTM"))
        ni_first = _f(first.get("NPParentCompanyOwnersTTM"))
        rev_last = _f(last.get("TotalOperatingRevenueTTM"))
        rev_first = _f(first.get("TotalOperatingRevenueTTM"))
        if ni_first > 0:
            ni_yoy = (ni_last - ni_first) / ni_first * 100
        if rev_first > 0:
            rev_yoy = (rev_last - rev_first) / rev_first * 100

    cons = s.get("consensus", {})
    tp = cons.get("target_price")
    k = s.get("kline", {}).get("head", [])
    cur = _f(k[0].get("close")) if k else 0
    upside = ((tp - cur) / cur * 100) if (tp and cur > 0) else 0

    # 评分（每个维度 0-100）
    score_perf = min(100, max(0, 50 + ni_yoy))  # 净利 0% → 50 分
    score_valuation = min(100, max(0, 50 + upside))  # 上行空间 0% → 50 分
    rep_count = len(s.get("reports", {}).get("head", []))
    score_flow = min(100, rep_count * 20)  # 5 篇研报 = 100 分

    total = round(score_perf * 0.4 + score_valuation * 0.35 + score_flow * 0.25)
    return {
        "perf": round(score_perf),
        "valuation": round(score_valuation),
        "flow": round(score_flow),
        "total": total,
        "ni_yoy": ni_yoy,
        "rev_yoy": rev_yoy,
        "upside": upside,
        "tp": tp,
        "cur": cur,
    }


# ==================== 评分环 SVG ====================
def score_ring(pct: int, color: str) -> str:
    """生成 conic-gradient 评分环 HTML。"""
    return f"""
    <div class="score-circle" style="background: conic-gradient({color} 0%, {color} {pct}%, #1e293b {pct}%, #1e293b 100%);">
      <div class="score-inner">
        <div class="num" style="color:{color}">{pct}</div>
        <div class="total">/ 100</div>
        <div class="label" style="color:{color}">{pct_to_label(pct)}</div>
      </div>
    </div>
    """


def pct_to_label(pct: int) -> str:
    if pct >= 80:
        return "极强信号"
    if pct >= 60:
        return "强信号"
    if pct >= 40:
        return "中性"
    if pct >= 20:
        return "弱信号"
    return "极弱"


# ==================== HTML 模板 ====================
HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI 算力链多票横向分析 · 2026-06-03</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 50%, #0f1729 100%);
  color: #e0e6f1; min-height: 100vh; padding: 24px; line-height: 1.6;
}
.container { max-width: 1400px; margin: 0 auto; }

/* ============ Header ============ */
.header {
  background: linear-gradient(135deg, rgba(99,102,241,0.18), rgba(168,85,247,0.10), rgba(245,158,11,0.10));
  border: 1px solid rgba(168,85,247,0.3);
  border-radius: 24px; padding: 40px 50px; margin-bottom: 24px;
  position: relative; overflow: hidden; backdrop-filter: blur(20px);
}
.header::before {
  content: ''; position: absolute; top: -50%; right: -10%;
  width: 500px; height: 500px;
  background: radial-gradient(circle, rgba(168,85,247,0.3), transparent 70%);
  border-radius: 50%;
}
.header::after {
  content: ''; position: absolute; bottom: -30%; left: -10%;
  width: 400px; height: 400px;
  background: radial-gradient(circle, rgba(99,102,241,0.2), transparent 70%);
  border-radius: 50%;
}
.header-content { position: relative; z-index: 1; }
.stock-tag {
  display: inline-block; padding: 6px 14px;
  background: rgba(168,85,247,0.2); border: 1px solid rgba(168,85,247,0.4);
  border-radius: 20px; font-size: 13px; color: #ddd6fe;
  font-weight: 600; margin-bottom: 16px;
}
.header h1 {
  font-size: 38px; font-weight: 800;
  background: linear-gradient(135deg, #60a5fa, #a855f7, #f59e0b);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  margin-bottom: 12px; letter-spacing: 1px;
}
.header .subtitle { color: #94a3b8; font-size: 16px; margin-bottom: 20px; }
.header-meta { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 20px; }
.header-meta .item {
  background: rgba(15,23,42,0.6); padding: 12px 18px;
  border-radius: 12px; border: 1px solid rgba(148,163,184,0.15);
  min-width: 110px;
}
.header-meta .item .label { font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; }
.header-meta .item .value { font-size: 20px; font-weight: 700; color: #f1f5f9; margin-top: 4px; }
.header-meta .item.green .value { color: #4ade80; }
.header-meta .item.red .value { color: #f87171; }
.header-meta .item.yellow .value { color: #facc15; }

/* ============ Sections ============ */
.section {
  background: rgba(30,41,59,0.5);
  border: 1px solid rgba(148,163,184,0.15);
  border-radius: 20px; padding: 32px; margin-bottom: 24px;
  backdrop-filter: blur(10px);
}
.section-title {
  font-size: 22px; font-weight: 700; color: #f1f5f9;
  margin-bottom: 6px; display: flex; align-items: center; gap: 12px;
}
.section-title .num {
  background: linear-gradient(135deg, #6366f1, #a855f7);
  color: white; width: 36px; height: 36px; border-radius: 10px;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 16px; font-weight: 800;
}
.section-desc { color: #94a3b8; font-size: 14px; margin-bottom: 20px; }

/* ============ Score Section ============ */
.score-row {
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 24px; margin-top: 16px;
}
.score-card {
  background: rgba(15,23,42,0.6);
  border: 1px solid rgba(148,163,184,0.15);
  border-radius: 18px; padding: 24px;
  display: flex; align-items: center; gap: 20px;
}
.score-circle-wrap { position: relative; width: 130px; height: 130px; flex-shrink: 0; }
.score-circle {
  width: 130px; height: 130px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  position: relative;
}
.score-circle::before {
  content: ''; position: absolute; inset: 10px;
  background: #0f1729; border-radius: 50%;
}
.score-inner { position: relative; text-align: center; z-index: 1; }
.score-inner .num { font-size: 32px; font-weight: 900; line-height: 1; }
.score-inner .total { font-size: 11px; color: #94a3b8; margin-top: 2px; }
.score-inner .label { font-size: 10px; margin-top: 6px; font-weight: 700; letter-spacing: 0.5px; }
.score-info h3 { font-size: 17px; color: #f1f5f9; margin-bottom: 8px; }
.score-info .dim { color: #94a3b8; font-size: 12px; }
.score-info .badge {
  display: inline-block; padding: 2px 8px; border-radius: 6px;
  font-size: 11px; font-weight: 700; margin-right: 4px; margin-top: 4px;
}

/* ============ Comparison Table ============ */
.matrix {
  width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 12px;
}
.matrix th {
  background: rgba(99,102,241,0.15); color: #c7d2fe;
  padding: 12px 14px; text-align: left; font-weight: 600;
  border-bottom: 2px solid rgba(99,102,241,0.3);
}
.matrix th:first-child { border-top-left-radius: 10px; }
.matrix th:last-child { border-top-right-radius: 10px; }
.matrix td {
  padding: 11px 14px; border-bottom: 1px solid rgba(148,163,184,0.1);
  color: #cbd5e1;
}
.matrix tr:hover td { background: rgba(99,102,241,0.05); }
.matrix td:first-child { color: #f1f5f9; font-weight: 600; }
.matrix .v { text-align: right; }
.matrix .pos { color: #4ade80; font-weight: 600; }
.matrix .neg { color: #f87171; font-weight: 600; }
.matrix .neu { color: #facc15; font-weight: 600; }

/* ============ Signal Badges ============ */
.badge {
  display: inline-block; padding: 4px 10px; border-radius: 8px;
  font-size: 11px; font-weight: 700; letter-spacing: 0.5px;
}
.badge.bull { background: rgba(34,197,94,0.2); color: #4ade80; border: 1px solid rgba(34,197,94,0.4); }
.badge.bear { background: rgba(239,68,68,0.2); color: #f87171; border: 1px solid rgba(239,68,68,0.4); }
.badge.neut { background: rgba(234,179,8,0.2); color: #facc15; border: 1px solid rgba(234,179,8,0.4); }
.badge.purple { background: rgba(168,85,247,0.2); color: #c084fc; border: 1px solid rgba(168,85,247,0.4); }

/* ============ Indicator Grid ============ */
.indicator-grid {
  display: grid; grid-template-columns: repeat(5, 1fr);
  gap: 10px; margin-top: 12px;
}
.indicator-card {
  background: rgba(15,23,42,0.6); border-radius: 10px;
  padding: 12px 8px; text-align: center;
  border: 1px solid rgba(148,163,184,0.15);
}
.indicator-card.bull { border-color: rgba(34,197,94,0.5); background: rgba(34,197,94,0.05); }
.indicator-card.bear { border-color: rgba(239,68,68,0.5); background: rgba(239,68,68,0.05); }
.indicator-card.neut { border-color: rgba(234,179,8,0.5); background: rgba(234,179,8,0.05); }
.indicator-card .name { font-size: 11px; color: #94a3b8; }
.indicator-card .value { font-size: 18px; font-weight: 800; color: #f1f5f9; margin: 4px 0; }
.indicator-card .status { font-size: 10px; font-weight: 700; }
.indicator-card.bull .status { color: #4ade80; }
.indicator-card.bear .status { color: #f87171; }
.indicator-card.neut .status { color: #facc15; }

/* ============ Stock Detail Cards (3 columns) ============ */
.stock-cards {
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 20px; margin-top: 16px;
}
.stock-card {
  background: rgba(15,23,42,0.6);
  border: 1px solid rgba(148,163,184,0.15);
  border-radius: 16px; padding: 20px;
  display: flex; flex-direction: column; gap: 10px;
}
.stock-card.bull { border-color: rgba(34,197,94,0.4); background: linear-gradient(135deg, rgba(34,197,94,0.08), rgba(15,23,42,0.6)); }
.stock-card.bear { border-color: rgba(239,68,68,0.4); background: linear-gradient(135deg, rgba(239,68,68,0.08), rgba(15,23,42,0.6)); }
.stock-card.neut { border-color: rgba(234,179,8,0.4); background: linear-gradient(135deg, rgba(234,179,8,0.08), rgba(15,23,42,0.6)); }
.stock-card h3 { font-size: 17px; color: #f1f5f9; display: flex; justify-content: space-between; align-items: center; }
.stock-card .code { font-size: 12px; color: #94a3b8; font-weight: 400; }
.stock-card .price-row { display: flex; align-items: baseline; gap: 12px; padding: 8px 0; }
.stock-card .price { font-size: 32px; font-weight: 900; }
.stock-card .chg { font-size: 14px; font-weight: 700; }
.stock-card .chg.pos { color: #4ade80; }
.stock-card .chg.neg { color: #f87171; }
.stock-card .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 8px; }
.stock-card .stat { background: rgba(0,0,0,0.2); padding: 8px 10px; border-radius: 8px; }
.stock-card .stat .l { font-size: 10px; color: #94a3b8; text-transform: uppercase; }
.stock-card .stat .v { font-size: 16px; font-weight: 700; color: #f1f5f9; margin-top: 2px; }
.stock-card .narrative { font-size: 12px; color: #cbd5e1; line-height: 1.6; padding-top: 8px; border-top: 1px solid rgba(148,163,184,0.15); }

/* ============ Chart Container ============ */
.chart-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.chart-grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
.chart-box {
  background: rgba(15,23,42,0.6); border-radius: 14px;
  padding: 20px; height: 360px; position: relative;
  border: 1px solid rgba(148,163,184,0.1);
}
.chart-box h4 { color: #cbd5e1; font-size: 13px; margin-bottom: 12px; font-weight: 600; }
.chart-box canvas { max-height: 300px; }

/* ============ Timeline (News) ============ */
.timeline { position: relative; padding-left: 28px; margin-top: 12px; }
.timeline::before {
  content: ''; position: absolute; left: 8px; top: 8px; bottom: 8px;
  width: 2px; background: linear-gradient(180deg, #6366f1, #a855f7, transparent);
}
.timeline-item {
  position: relative; padding: 12px 0 12px 8px;
  border-bottom: 1px dashed rgba(148,163,184,0.1);
}
.timeline-item:last-child { border-bottom: none; }
.timeline-item::before {
  content: ''; position: absolute; left: -24px; top: 18px;
  width: 12px; height: 12px; border-radius: 50%;
  background: #6366f1; border: 3px solid #0f1729;
  box-shadow: 0 0 0 2px #6366f1;
}
.timeline-item .time { font-size: 11px; color: #64748b; }
.timeline-item .title { font-size: 13px; color: #f1f5f9; margin-top: 2px; }
.timeline-item .src { font-size: 11px; color: #94a3b8; margin-top: 2px; }

/* ============ Narrative Box ============ */
.narrative-box {
  background: linear-gradient(135deg, rgba(99,102,241,0.10), rgba(168,85,247,0.06));
  border-left: 4px solid #a855f7;
  border-radius: 10px; padding: 18px 22px; margin-top: 14px;
  color: #cbd5e1; font-size: 13px; line-height: 1.7;
}
.narrative-box b { color: #f1f5f9; }
.narrative-box.warn { background: linear-gradient(135deg, rgba(239,68,68,0.10), rgba(15,23,42,0.6)); border-color: #ef4444; }

/* ============ Strategy Cards (4 type) ============ */
.op-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 18px; margin-top: 16px; }
.op-card {
  background: rgba(15,23,42,0.6); border-radius: 14px; padding: 22px;
  border: 1px solid; border-left-width: 5px;
}
.op-card.bull { border-color: rgba(34,197,94,0.5); border-left-color: #22c55e; }
.op-card.bear { border-color: rgba(239,68,68,0.5); border-left-color: #ef4444; }
.op-card.neut { border-color: rgba(234,179,8,0.5); border-left-color: #facc15; }
.op-card.purple { border-color: rgba(168,85,247,0.5); border-left-color: #a855f7; }
.op-card h3 { font-size: 16px; color: #f1f5f9; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
.op-card .tag { padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; }
.op-card.bull .tag { background: rgba(34,197,94,0.2); color: #4ade80; }
.op-card.bear .tag { background: rgba(239,68,68,0.2); color: #f87171; }
.op-card.neut .tag { background: rgba(234,179,8,0.2); color: #facc15; }
.op-card.purple .tag { background: rgba(168,85,247,0.2); color: #c084fc; }
.op-card ul { list-style: none; padding: 0; margin-top: 8px; }
.op-card li { font-size: 12px; color: #cbd5e1; padding: 4px 0; display: flex; justify-content: space-between; }
.op-card li b { color: #f1f5f9; font-weight: 600; }
.op-card li .v { color: #fbbf24; font-weight: 700; }

/* ============ Disclaimer ============ */
.disclaimer {
  background: rgba(239,68,68,0.05); border: 1px solid rgba(239,68,68,0.2);
  border-radius: 14px; padding: 20px 28px; color: #fca5a5;
  font-size: 13px; margin-top: 30px; line-height: 1.8;
}
.disclaimer b { color: #fef2f2; }

/* ============ Responsive ============ */
@media (max-width: 1100px) {
  .score-row, .stock-cards, .chart-grid-3 { grid-template-columns: 1fr 1fr; }
  .op-grid, .chart-grid-2 { grid-template-columns: 1fr; }
  .indicator-grid { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 700px) {
  .score-row, .stock-cards, .chart-grid-3 { grid-template-columns: 1fr; }
  .indicator-grid { grid-template-columns: repeat(2, 1fr); }
  .header h1 { font-size: 26px; }
  .header-meta .item { min-width: 80px; }
}
</style>
</head>
<body>
<div class="container">
"""

HTML_FOOT = """
</div>
<script>
{js}
</script>
</body>
</html>
"""

DISCLAIMER = """
<div class="disclaimer">
<b>⚠️ 重要免责声明</b><br>
本分析基于截至 <b>2026-06-03</b> 的腾讯自选股（westock-data）公开数据，
结合 westock 一致预期 / 评级 / 研报 / 新闻交叉生成。<br>
<b>不构成证券投资建议</b>。AI 算力链估值处于历史高位，
任何标的都需结合最新行情与自身风险承受能力做决策。<b>市场有风险，决策需谨慎。</b>
</div>
"""


# ==================== 各 Section 渲染 ====================
def render_header(scores: list[dict]) -> str:
    # 整体打分
    avg = round(sum(s["total"] for s in scores) / len(scores))
    sentiment_color = BULL if avg >= 60 else (NEUTRAL if avg >= 40 else BEAR)
    sentiment_label = "强信号" if avg >= 60 else ("中性" if avg >= 40 else "弱信号")
    return f"""
    <div class="header">
      <div class="header-content">
        <span class="stock-tag">🤖 AI 算力链多票分析框架 v1.0 · 2026-06-03</span>
        <h1>AI 算力链 — 三只票横向诊断</h1>
        <p class="subtitle">沪电股份 002463 · 长电科技 600584 · 工业富联 601138  |  跨域信号交叉验证</p>
        <div class="header-meta">
          <div class="item"><div class="label">整体信号</div><div class="value" style="color:{sentiment_color}">{avg} 分 · {sentiment_label}</div></div>
          <div class="item"><div class="label">数据源</div><div class="value">westock + LLM</div></div>
          <div class="item"><div class="label">窗口</div><div class="value">60 日</div></div>
          <div class="item"><div class="label">报告类型</div><div class="value">长文分析</div></div>
        </div>
      </div>
    </div>
    """


def render_score_section(stocks: list[dict], scores: list[dict]) -> str:
    cards = []
    for s, sc in zip(stocks, scores):
        pct = sc["total"]
        if pct >= 60:
            color = BULL
            cls = "bull"
            label = "强"
        elif pct >= 40:
            color = NEUTRAL
            cls = "neut"
            label = "中性"
        else:
            color = BEAR
            cls = "bear"
            label = "弱"
        cards.append(f"""
        <div class="score-card">
          <div class="score-circle-wrap">
            {score_ring(pct, color)}
          </div>
          <div class="score-info">
            <h3>{html.escape(s["symbol"])} {html.escape(s["name"])}</h3>
            <div class="dim">{html.escape(label)} · 综合诊断</div>
            <div>
              <span class="badge bull">业绩 {sc["perf"]}</span>
              <span class="badge {cls}">估值 {sc["valuation"]}</span>
              <span class="badge neut">资金 {sc["flow"]}</span>
            </div>
            <div class="dim" style="margin-top:6px">
              YoY 净利 {sc["ni_yoy"]:+.1f}% · 上行空间 {sc["upside"]:+.1f}%
            </div>
          </div>
        </div>
        """)
    return f"""
    <div class="section">
      <h2 class="section-title"><span class="num">1</span>综合诊断评分（业绩×估值×资金三角）</h2>
      <p class="section-desc">每只票按业绩兑现 (40%) + 估值空间 (35%) + 研报资金 (25%) 加权打分，满分 100</p>
      <div class="score-row">
        {"".join(cards)}
      </div>
    </div>
    """


def render_3_stock_cards(stocks: list[dict], scores: list[dict]) -> str:
    cards = []
    narratives = [
        "PCB 龙头，AI 算力高景气受益方。5/22 见顶后回吐，KDJ/RSI 短线超买。**估值已透支 5.5%**，等回踩 MA10 确认。",
        "封测三巨头之一，**业绩 -6.7% YoY 唯一负增长**。5/20-5/22 急跌后弱反，行业 beta 而非个股 alpha。等 Q1 2026 业绩拐点。",
        "**AI 算力链主升浪**。业绩 +45.5% YoY 全场最猛，6/2 英伟达合作催化大涨 +8.49%。RSI=82 已超买但趋势完好。",
    ]
    types = ["neut", "bear", "bull"]
    for s, sc, narr, t in zip(stocks, scores, narratives, types):
        sym = s["symbol"]
        name = s["name"]
        k = s.get("kline", {}).get("head", [])
        if not k:
            continue
        latest = k[0]
        prev5 = k[4] if len(k) > 4 else k[-1]
        prev20 = k[19] if len(k) > 19 else k[-1]
        price = _f(latest.get("close"))
        day_chg = (
            (price / _f(latest.get("open")) - 1) * 100 if _f(latest.get("open")) else 0
        )
        chg_5d = (price / _f(prev5.get("close")) - 1) * 100
        chg_20d = (price / _f(prev20.get("close")) - 1) * 100
        ma = s.get("technical_ma", {}).get("head", [{}])[0]
        ma5 = _f(ma.get("ma.MA_5"))
        ma20 = _f(ma.get("ma.MA_20"))
        rs = s.get("technical_rsi", {}).get("head", [{}])[0]
        rsi6 = _f(rs.get("rsi.RSI_6"))
        kdj = s.get("technical_kdj", {}).get("head", [{}])[0]
        kdj_k = _f(kdj.get("kdj.KDJ_K"))
        fs = s.get("finance_summary", {}).get("head", [])
        last = fs[-1] if fs else {}
        ni = _f(last.get("NPParentCompanyOwnersTTM"))
        rev = _f(last.get("TotalOperatingRevenueTTM"))
        cons = s.get("consensus", {})
        tp = cons.get("target_price") or 0
        cards.append(f"""
        <div class="stock-card {t}">
          <h3>{sym} <span class="code">{name}</span></h3>
          <div class="price-row">
            <div class="price">{price:.2f}</div>
            <div class="chg {("pos" if day_chg >= 0 else "neg")}">{day_chg:+.2f}%</div>
          </div>
          <div class="stats">
            <div class="stat"><div class="l">5 日</div><div class="v" style="color:{"#4ade80" if chg_5d >= 0 else "#f87171"}">{chg_5d:+.2f}%</div></div>
            <div class="stat"><div class="l">20 日</div><div class="v" style="color:{"#4ade80" if chg_20d >= 0 else "#f87171"}">{chg_20d:+.2f}%</div></div>
            <div class="stat"><div class="l">MA5</div><div class="v">{ma5:.1f}</div></div>
            <div class="stat"><div class="l">MA20</div><div class="v">{ma20:.1f}</div></div>
            <div class="stat"><div class="l">RSI6</div><div class="v" style="color:{"#f87171" if rsi6 >= 70 else ("#4ade80" if rsi6 <= 30 else "#cbd5e1")}">{rsi6:.0f}</div></div>
            <div class="stat"><div class="l">KDJ-K</div><div class="v" style="color:{"#f87171" if kdj_k >= 80 else ("#4ade80" if kdj_k <= 20 else "#cbd5e1")}">{kdj_k:.0f}</div></div>
            <div class="stat"><div class="l">2025 营收</div><div class="v">{rev / 1e8:.0f}亿</div></div>
            <div class="stat"><div class="l">2025 净利</div><div class="v">{ni / 1e8:.1f}亿</div></div>
            <div class="stat"><div class="l">目标价</div><div class="v" style="color:{"#4ade80" if tp > price else "#f87171"}">{tp:.1f}</div></div>
            <div class="stat"><div class="l">上行空间</div><div class="v" style="color:{"#4ade80" if tp > price else "#f87171"}">{(tp / price - 1) * 100:+.1f}%</div></div>
          </div>
          <div class="narrative">{narr}</div>
        </div>
        """)
    return f"""
    <div class="section">
      <h2 class="section-title"><span class="num">2</span>三只票核心指标卡</h2>
      <p class="section-desc">技术 (MA/RSI/KDJ) + 基本面 (营收/净利) + 估值 (目标价) 一卡看全</p>
      <div class="stock-cards">
        {"".join(cards)}
      </div>
    </div>
    """


def render_kline_chart(stocks: list[dict]) -> str:
    """K线叠加图（归一化到首日=100）"""
    datasets = []
    labels = []
    palette = [BLUE, NEUTRAL, PURPLE]
    for i, s in enumerate(stocks):
        k = s.get("kline", {}).get("head", [])
        if not k:
            continue
        # reverse to oldest → newest
        k = list(reversed(k))
        closes = [_f(r.get("close")) for r in k]
        if not closes or not closes[0]:
            continue
        base = closes[0]
        normed = [c / base * 100 for c in closes]
        dates = [r.get("date", "")[5:] for r in k]  # MM-DD
        if not labels:
            labels = dates
        sym = s["symbol"]
        name = s["name"]
        datasets.append(
            {
                "label": f"{sym} {name}",
                "data": normed,
                "borderColor": palette[i],
                "backgroundColor": "rgba(99,102,241,0.05)",
                "borderWidth": 2.5,
                "pointRadius": 0,
                "tension": 0.2,
                "fill": False,
            }
        )
    return f"""
    <div class="section">
      <h2 class="section-title"><span class="num">3</span>近 60 日 K 线叠加（首日=100 归一化）</h2>
      <p class="section-desc">三只票同期对比，谁强谁弱一目了然</p>
      <div class="chart-box" style="height: 400px;">
        <canvas id="klineChart"></canvas>
      </div>
    </div>
    <script>
    Chart.defaults.color = '#94a3b8';
    Chart.defaults.borderColor = 'rgba(148,163,184,0.1)';
    Chart.defaults.font.family = '-apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    new Chart(document.getElementById('klineChart'), {{
      type: 'line',
      data: {{ labels: {json.dumps(labels)}, datasets: {json.dumps(datasets)} }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ position: 'top', labels: {{ color: '#e2e8f0', font: {{ size: 13 }} }} }},
                   title: {{ display: true, text: '归一化股价（首日=100）', color: '#f1f5f9', font: {{ size: 15, weight: 600 }} }} }},
        scales: {{
          x: {{ grid: {{ color: 'rgba(148,163,184,0.05)' }}, ticks: {{ maxTicksLimit: 15 }} }},
          y: {{ grid: {{ color: 'rgba(148,163,184,0.05)' }}, ticks: {{ callback: v => v.toFixed(0) }} }}
        }}
      }}
    }});
    </script>
    """


def render_indicators(stocks: list[dict]) -> str:
    """5x3 网格：每只票的 RSI/MACD/KDJ/BOLL/BIAS 关键值"""
    rows = []
    for s in stocks:
        sym = s["symbol"]
        name = s["name"]
        ma = s.get("technical_ma", {}).get("head", [{}])[0]
        macd = s.get("technical_macd", {}).get("head", [{}])[0]
        rs = s.get("technical_rsi", {}).get("head", [{}])[0]
        kdj = s.get("technical_kdj", {}).get("head", [{}])[0]
        boll = s.get("technical_boll", {}).get("head", [{}])[0]
        price = _f(ma.get("closePrice"))
        ma5 = _f(ma.get("ma.MA_5"))
        ma20 = _f(ma.get("ma.MA_20"))
        dif = _f(macd.get("macd.DIF"))
        dea = _f(macd.get("macd.DEA"))
        rsi6 = _f(rs.get("rsi.RSI_6"))
        k = _f(kdj.get("kdj.KDJ_K"))
        boll_up = _f(boll.get("boll.BOLL_UPPER"))
        boll_mid = _f(boll.get("boll.BOLL_MID"))
        boll_low = _f(boll.get("boll.BOLL_LOWER"))

        def cls_bull(v, low, high):
            return "bull" if v > high else ("bear" if v < low else "neut")

        # Status determination
        ma_trend = (
            "bull" if price > ma5 > ma20 else ("bear" if price < ma5 < ma20 else "neut")
        )
        macd_stat = (
            "bull"
            if dif > dea and dif > 0
            else ("bear" if dif < dea and dif < 0 else "neut")
        )
        rsi_stat = "bull" if rsi6 < 30 else ("bear" if rsi6 > 70 else "neut")
        kdj_stat = "bull" if k < 20 else ("bear" if k > 80 else "neut")

        cards = f"""
        <div class="indicator-card {ma_trend}">
          <div class="name">MA 多空</div>
          <div class="value">{("↑" if ma_trend == "bull" else ("↓" if ma_trend == "bear" else "→"))}</div>
          <div class="status">{("多头" if ma_trend == "bull" else ("空头" if ma_trend == "bear" else "纠缠"))}</div>
        </div>
        <div class="indicator-card {macd_stat}">
          <div class="name">MACD</div>
          <div class="value">{("+" + f"{dif:.2f}" if dif >= 0 else f"{dif:.2f}")}</div>
          <div class="status">{("金叉" if macd_stat == "bull" else ("死叉" if macd_stat == "bear" else "中性"))}</div>
        </div>
        <div class="indicator-card {rsi_stat}">
          <div class="name">RSI6</div>
          <div class="value">{rsi6:.0f}</div>
          <div class="status">{("超卖" if rsi_stat == "bull" else ("超买" if rsi_stat == "bear" else "正常"))}</div>
        </div>
        <div class="indicator-card {kdj_stat}">
          <div class="name">KDJ-K</div>
          <div class="value">{k:.0f}</div>
          <div class="status">{("超卖" if kdj_stat == "bull" else ("超买" if kdj_stat == "bear" else "正常"))}</div>
        </div>
        <div class="indicator-card neut">
          <div class="name">BOLL 位置</div>
          <div class="value" style="font-size:14px">{((price - boll_low) / (boll_up - boll_low) * 100 if boll_up > boll_low else 50):.0f}%</div>
          <div class="status">{(boll_up - boll_mid):.0f}/{(boll_mid - boll_low):.0f}</div>
        </div>
        """
        rows.append(f"""
        <div>
          <h4 style="color:#cbd5e1; font-size:14px; margin-bottom:10px; display:flex; align-items:center; gap:8px">
            <span>{sym}</span>
            <span style="color:#64748b; font-size:12px">{name}</span>
            <span style="margin-left:auto; font-size:11px; color:#64748b">现价 {price:.2f}</span>
          </h4>
          <div class="indicator-grid">
            {cards}
          </div>
        </div>
        """)
    return f"""
    <div class="section">
      <h2 class="section-title"><span class="num">4</span>5 大技术指标扫描</h2>
      <p class="section-desc">每只票最新一日的 MA / MACD / RSI / KDJ / BOLL 状态</p>
      <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:24px; margin-top:12px">
        {"".join(rows)}
      </div>
    </div>
    """


def render_financial_chart(stocks: list[dict]) -> str:
    """4 个季度净利柱图"""
    datasets = []
    labels = ["Q1", "Q2", "Q3", "Q4"]
    palette = [BLUE, NEUTRAL, PURPLE]
    for i, s in enumerate(stocks):
        fs = s.get("finance_summary", {}).get("head", [])
        if len(fs) < 4:
            continue
        # fs 顺序: 2025Q1, 2025Q2, 2025Q3, 2025Q4 (累计)
        # 单季度 = 当期累计 - 上期累计
        cumul = [_f(r.get("NPParentCompanyOwnersTTM")) for r in fs[:4]]
        # 注意: 第一行的 TTM = Q1 累计(因为只有 1 期)
        # 但实际上 TTM 在第一期 = 当期单季，所以 4 个数是: Q1 累计(==Q1), Q2累计, Q3累计, Q4累计
        # 单季 = 累计差分
        single = [cumul[0]]
        for j in range(1, 4):
            single.append(cumul[j] - cumul[j - 1])
        sym = s["symbol"]
        datasets.append(
            {
                "label": f"{sym} {s['name']}",
                "data": [x / 1e8 for x in single],
                "backgroundColor": palette[i],
                "borderColor": palette[i],
                "borderWidth": 1,
            }
        )
    return f"""
    <div class="section">
      <h2 class="section-title"><span class="num">5</span>2025 单季归母净利（亿元）</h2>
      <p class="section-desc">三只票 2025 四个季度的单季归母净利对比，看谁的"加速度"最猛</p>
      <div class="chart-box" style="height: 360px;">
        <canvas id="quarterChart"></canvas>
      </div>
    </div>
    <script>
    new Chart(document.getElementById('quarterChart'), {{
      type: 'bar',
      data: {{ labels: {json.dumps(labels)}, datasets: {json.dumps(datasets)} }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ position: 'top', labels: {{ color: '#e2e8f0' }} }},
                   title: {{ display: true, text: '2025 单季归母净利（亿元）', color: '#f1f5f9', font: {{ size: 14 }} }} }},
        scales: {{
          x: {{ grid: {{ color: 'rgba(148,163,184,0.05)' }} }},
          y: {{ grid: {{ color: 'rgba(148,163,184,0.05)' }} }}
        }}
      }}
    }});
    </script>
    """


def render_consensus(stocks: list[dict]) -> str:
    """目标价 vs 现价 + 预测增速"""
    rows = []
    for s in stocks:
        sym = s["symbol"]
        name = s["name"]
        k = s.get("kline", {}).get("head", [])
        price = _f(k[0].get("close")) if k else 0
        cons = s.get("consensus", {})
        tp = cons.get("target_price") or 0
        upside = (tp / price - 1) * 100 if price > 0 else 0
        fcs = cons.get("forecasts", [])
        # 按年份升序
        fcs = sorted(fcs, key=lambda x: x.get("year", ""))
        np_yoy_2026 = "—"
        np_yoy_2027 = "—"
        for f in fcs:
            if str(f.get("year", "")) == "2026" and f.get("netProfitYoy") not in (
                None,
                "-",
                "",
            ):
                np_yoy_2026 = f"{float(f['netProfitYoy']):+.1f}%"
            if str(f.get("year", "")) == "2027" and f.get("netProfitYoy") not in (
                None,
                "-",
                "",
            ):
                np_yoy_2027 = f"{float(f['netProfitYoy']):+.1f}%"

        rating_list = s.get("rating", {}).get("head", [])
        buy = inc = hold = sell = 0
        if rating_list:
            r = rating_list[0]
            buy = r.get("rating_buy", 0) or 0
            inc = r.get("rating_inc", 0) or 0
            hold = r.get("rating_hold", 0) or 0
            sell = r.get("rating_sell", 0) or 0

        upside_color = "#4ade80" if upside > 0 else "#f87171"
        rows.append(f"""
        <tr>
          <td><b>{sym}</b><br><span style="color:#64748b; font-size:11px">{name}</span></td>
          <td class="v">{price:.2f}</td>
          <td class="v">{tp:.1f}</td>
          <td class="v" style="color:{upside_color}; font-weight:700">{upside:+.1f}%</td>
          <td class="v">{np_yoy_2026}</td>
          <td class="v">{np_yoy_2027}</td>
          <td class="v">
            <span class="badge bull">{buy} 买</span>
            <span class="badge neut">{inc} 增</span>
            <span class="badge bear">{hold} 持</span>
            <span class="badge bear">{sell} 卖</span>
          </td>
        </tr>
        """)
    return f"""
    <div class="section">
      <h2 class="section-title"><span class="num">6</span>一致预期 vs 现价 + 机构评级</h2>
      <p class="section-desc">分析师 2026/2027 净利预测增速 + 目标价与现价对比</p>
      <table class="matrix">
        <thead>
          <tr><th>标的</th><th class="v">现价</th><th class="v">目标价</th><th class="v">上行空间</th><th class="v">2026E 净利</th><th class="v">2027E 净利</th><th class="v">机构评级</th></tr>
        </thead>
        <tbody>
          {"".join(rows)}
        </tbody>
      </table>
    </div>
    """


def render_news(stocks: list[dict]) -> str:
    """每只票最新 3 条新闻时间轴"""
    blocks = []
    for s in stocks:
        sym = s["symbol"]
        name = s["name"]
        news = s.get("news", {}).get("head", [])
        items = []
        for r in news[:3]:
            t = str(r.get("time", ""))[:10]
            title = html.escape(str(r.get("title", ""))[:80])
            items.append(f"""
            <div class="timeline-item">
              <div class="time">{t}</div>
              <div class="title">{title}</div>
            </div>
            """)
        blocks.append(f"""
        <div>
          <h4 style="color:#f1f5f9; font-size:14px; margin-bottom:10px">
            <b>{sym}</b> <span style="color:#64748b; font-size:12px">{name}</span>
          </h4>
          <div class="timeline">
            {"".join(items) if items else '<div style="color:#64748b; font-size:12px">(无新闻)</div>'}
          </div>
        </div>
        """)
    return f"""
    <div class="section">
      <h2 class="section-title"><span class="num">7</span>最新新闻催化（事件追踪）</h2>
      <p class="section-desc">每只票最近 3 条新闻，看资金对什么故事感兴趣</p>
      <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:24px; margin-top:12px">
        {"".join(blocks)}
      </div>
    </div>
    """


def render_reports(stocks: list[dict]) -> str:
    """研报矩阵"""
    rows = []
    for s in stocks:
        sym = s["symbol"]
        name = s["name"]
        reps = s.get("reports", {}).get("head", [])
        for r in reps[:3]:
            t = str(r.get("time", ""))[:10]
            src = html.escape(str(r.get("src", "")))
            title = html.escape(str(r.get("title", ""))[:60])
            tzpj = str(r.get("tzpj", "-") or "-")
            tzpj_cls = (
                "bull"
                if tzpj in ("买入", "增持")
                else ("neut" if tzpj in ("持有", "中性") else "bear")
            )
            rows.append(f"""
            <tr>
              <td>{t}</td>
              <td><b>{sym}</b> {html.escape(name)}</td>
              <td>{src}</td>
              <td>{title}</td>
              <td><span class="badge {tzpj_cls}">{tzpj}</span></td>
            </tr>
            """)
    return f"""
    <div class="section">
      <h2 class="section-title"><span class="num">8</span>券商研报矩阵（最新 9 篇）</h2>
      <p class="section-desc">机构对三只票的最新观点，评级全部跟踪</p>
      <table class="matrix">
        <thead>
          <tr><th style="width:90px">日期</th><th style="width:140px">标的</th><th style="width:130px">券商</th><th>标题</th><th style="width:90px">评级</th></tr>
        </thead>
        <tbody>
          {"".join(rows) if rows else '<tr><td colspan="5" style="text-align:center; color:#64748b">无研报数据</td></tr>'}
        </tbody>
      </table>
    </div>
    """


def render_radar(stocks: list[dict], scores: list[dict]) -> str:
    """3 票多维雷达图"""
    labels = ["业绩兑现", "估值空间", "资金抱团", "技术趋势", "事件催化", "市场情绪"]
    palette = [BLUE, NEUTRAL, PURPLE]
    datasets = []
    for i, (s, sc) in enumerate(zip(stocks, scores)):
        sym = s["symbol"]
        # 多维打分
        ni_yoy = sc["ni_yoy"]
        upside = sc["upside"]
        rep_count = len(s.get("reports", {}).get("head", []))
        ma = s.get("technical_ma", {}).get("head", [{}])[0]
        price = _f(ma.get("closePrice"))
        ma20 = _f(ma.get("ma.MA_20"))
        tech_trend = max(
            0, min(100, 50 + (price / ma20 - 1) * 200)
        )  # price/ma20 → 50 中位
        perf_score = max(0, min(100, 50 + ni_yoy))
        val_score = max(0, min(100, 50 + upside))
        flow_score = min(100, rep_count * 25)
        news_count = len(s.get("news", {}).get("head", []))
        event_score = min(100, news_count * 12)
        sentiment_score = 70 if sc["total"] >= 60 else (50 if sc["total"] >= 40 else 30)

        data = [
            perf_score,
            val_score,
            flow_score,
            tech_trend,
            event_score,
            sentiment_score,
        ]
        datasets.append(
            {
                "label": f"{sym} {s['name']}",
                "data": data,
                "borderColor": palette[i],
                "backgroundColor": f"{palette[i]}33",
                "borderWidth": 2,
                "pointBackgroundColor": palette[i],
            }
        )
    return f"""
    <div class="section">
      <h2 class="section-title"><span class="num">9</span>六维雷达对比</h2>
      <p class="section-desc">业绩/估值/资金/技术/事件/情绪 6 维度，越大越强</p>
      <div class="chart-box" style="height: 460px;">
        <canvas id="radarChart"></canvas>
      </div>
    </div>
    <script>
    new Chart(document.getElementById('radarChart'), {{
      type: 'radar',
      data: {{ labels: {json.dumps(labels)}, datasets: {json.dumps(datasets)} }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ position: 'top', labels: {{ color: '#e2e8f0', font: {{ size: 13 }} }} }},
                   title: {{ display: true, text: 'AI 算力链三票六维评分', color: '#f1f5f9', font: {{ size: 15 }} }} }},
        scales: {{
          r: {{
            angleLines: {{ color: 'rgba(148,163,184,0.1)' }},
            grid: {{ color: 'rgba(148,163,184,0.1)' }},
            pointLabels: {{ color: '#cbd5e1', font: {{ size: 12 }} }},
            ticks: {{ color: '#94a3b8', backdropColor: 'transparent', font: {{ size: 10 }} }},
            min: 0, max: 100
          }}
        }}
      }}
    }});
    </script>
    """


def render_strategy(stocks: list[dict], scores: list[dict]) -> str:
    """操作策略：4 角色 × 3 票"""
    types = [
        (
            "bull",
            "🎯 短线进取型",
            "≤5% 仓位博弈",
            "bull",
            [
                {"l": "入场区", "v": "富联 75-78 区间"},
                {"l": "目标", "v": "88 (+10%)"},
                {"l": "止损", "v": "72 (-9%)"},
            ],
            [
                {"l": "入场区", "v": "沪电 118-122"},
                {"l": "目标", "v": "131 (+8%)"},
                {"l": "止损", "v": "115 (-6%)"},
            ],
            [
                {"l": "入场区", "v": "长电等 60-65"},
                {"l": "目标", "v": "75 (+15%)"},
                {"l": "止损", "v": "58 (-10%)"},
            ],
        ),
        (
            "bear",
            "🛡️ 稳健型 / 价值投资",
            "等 Q1 业绩 + 估值消化",
            "bear",
            [
                {"l": "建议", "v": "等富联回调 75-78"},
                {"l": "关注", "v": "Q1 2026 业绩"},
                {"l": "目标", "v": "中长期持有"},
            ],
            [
                {"l": "建议", "v": "暂缓 / 估值透支"},
                {"l": "关注", "v": "BOLL 中轨支撑"},
                {"l": "目标", "v": "100 附近"},
            ],
            [
                {"l": "建议", "v": "等 Q1 业绩拐点"},
                {"l": "关注", "v": "通富/华天同步"},
                {"l": "目标", "v": "封测行业反转"},
            ],
        ),
        (
            "neut",
            "📈 已持仓者",
            "顺势持有 / 滚动止盈",
            "neut",
            [
                {"l": "止盈", "v": "85-88 区间"},
                {"l": "移动止损", "v": "75 上移"},
                {"l": "逻辑", "v": "业绩兑现"},
            ],
            [
                {"l": "止盈", "v": "135-140 分批"},
                {"l": "移动止损", "v": "118 下破"},
                {"l": "逻辑", "v": "PCB 龙头"},
            ],
            [
                {"l": "止盈", "v": "78-80 反弹"},
                {"l": "移动止损", "v": "72 下破"},
                {"l": "逻辑", "v": "减亏预期"},
            ],
        ),
        (
            "purple",
            "🔍 观望型（推荐大多数人）",
            "等右侧信号",
            "purple",
            [
                {"l": "等待", "v": "MACD 红柱出现"},
                {"l": "确认", "v": "站上 80.5"},
                {"l": "催化", "v": "RUBIN 出货"},
            ],
            [
                {"l": "等待", "v": "回踩 MA10 (122)"},
                {"l": "确认", "v": "BOLL 中轨"},
                {"l": "催化", "v": "Q1 业绩超预期"},
            ],
            [
                {"l": "等待", "v": "MA5 上穿 MA10"},
                {"l": "确认", "v": "KDJ 金叉"},
                {"l": "催化", "v": "封测行业拐点"},
            ],
        ),
    ]
    grid = []
    for t in types:
        border_cls, title, tag, tag_cls, c1, c2, c3 = t
        items = "".join(
            f"<li><b>{it['l']}</b><span class='v'>{it['v']}</span></li>" for it in c1
        )
        items2 = "".join(
            f"<li><b>{it['l']}</b><span class='v'>{it['v']}</span></li>" for it in c2
        )
        items3 = "".join(
            f"<li><b>{it['l']}</b><span class='v'>{it['v']}</span></li>" for it in c3
        )
        grid.append(f"""
        <div class="op-card {border_cls}">
          <h3>{title} <span class="tag">{tag}</span></h3>
          <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:8px; margin-top:8px; font-size:11px">
            <div>
              <div style="color:#60a5fa; font-weight:700; margin-bottom:6px">富联 601138</div>
              <ul style="list-style:none; padding:0">{items}</ul>
            </div>
            <div>
              <div style="color:#facc15; font-weight:700; margin-bottom:6px">沪电 002463</div>
              <ul style="list-style:none; padding:0">{items2}</ul>
            </div>
            <div>
              <div style="color:#c084fc; font-weight:700; margin-bottom:6px">长电 600584</div>
              <ul style="list-style:none; padding:0">{items3}</ul>
            </div>
          </div>
        </div>
        """)
    return f"""
    <div class="section">
      <h2 class="section-title"><span class="num">10</span>分类型操作策略矩阵</h2>
      <p class="section-desc">4 种投资风格 × 3 只票，每格明确入场/目标/止损</p>
      <div class="op-grid">
        {"".join(grid)}
      </div>
    </div>
    """


def render_conclusion(stocks: list[dict], scores: list[dict]) -> str:
    return """
    <div class="section" style="background: linear-gradient(135deg, rgba(99,102,241,0.12), rgba(168,85,247,0.06)); border-color: rgba(168,85,247,0.4);">
      <h2 class="section-title" style="color:#c084fc"><span class="num">11</span>总结：板块内严重分化，主升 → 跟随 → 掉队</h2>
      <div style="font-size:14px; color:#cbd5e1; line-height:1.85; margin-top:12px">
        <p><b style="color:#4ade80">🔥 工业富联 601138</b> 是板块主升浪。
        业绩 +45.5% YoY 全场最猛，2026E 预期 +72%，6/2 英伟达合作直接催化 +8.49% 大涨。
        RSI 6=82 已超买，但**只要 RUBIN 出货 + AI 服务器订单两个催化剂持续，中期趋势难破**。
        <span class="badge bull">入场: 75-78</span> <span class="badge bull">目标: 88</span> <span class="badge bear">止损: 72</span>
        </p>
        <p><b style="color:#facc15">⚠️ 沪电股份 002463</b> 业绩好但股价透支。
        业绩 +34.8% YoY，2026E +50% 预期，但**目标价 123.74 < 现价 131，估值已透支 5.5%**。
        KDJ/RSI 短线超买，6/2 -9.81% 是高位回吐，**短期震荡消化估值**。
        <span class="badge bull">回踩 118-122 介入</span> <span class="badge bull">突破 137 加仓</span> <span class="badge bear">破 115 止损</span>
        </p>
        <p><b style="color:#f87171">📉 长电科技 600584</b> 行业 beta 掉队。
        业绩 -6.7% YoY **唯一负增长**，5/20-5/22 急跌 12% 后弱反，**MA 短空 + KDJ 死叉**。
        目标价 55.81 < 现价 75.35 = **分析师不看好 26%**。等 Q1 2026 业绩拐点 + 封测行业同步改善。
        <span class="badge neut">不左侧抄底</span> <span class="badge bull">等 MA5 上穿 MA10</span> <span class="badge bear">破 60 清仓</span>
        </p>
        <p style="margin-top:14px; padding-top:14px; border-top:1px dashed rgba(148,163,184,0.2)">
        <b style="color:#fde047">关键观察点</b>：
        ① 富联 Q1 2026 业绩 + RUBIN 出货节奏（板块风向标），
        ② 沪电是否能回踩 MA10 (122) 不破，
        ③ 长电和通富微电/华天科技财报是否同步（行业反转信号）。
        </p>
      </div>
    </div>
    """


# ==================== 主函数 ====================
def main():
    data = load_data()
    stocks = data["stocks"]
    scores = [calc_alignment_score(s) for s in stocks]

    parts = [
        HTML_HEAD,
        render_header(scores),
        render_score_section(stocks, scores),
        render_3_stock_cards(stocks, scores),
        render_kline_chart(stocks),
        render_indicators(stocks),
        render_financial_chart(stocks),
        render_consensus(stocks),
        render_news(stocks),
        render_reports(stocks),
        render_radar(stocks, scores),
        render_strategy(stocks, scores),
        render_conclusion(stocks, scores),
        DISCLAIMER,
        HTML_FOOT,
    ]
    out_file = PROJECT_ROOT / "reports" / "ai_compute_chain_20260603_v2.html"
    out_file.write_text("".join(parts), encoding="utf-8")
    print(f"[OK] Generated: {out_file}")
    print(f"     Size: {out_file.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
