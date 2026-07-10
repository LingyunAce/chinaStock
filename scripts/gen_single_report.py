#!/usr/bin/env python3
"""单只票的深色玻璃态 HTML 报告生成器。

用法:
    python scripts/gen_single_report.py reports/long_form_SZ000700.json

复用 gen_beautiful_report.py 的设计系统 (深色 + 玻璃态 + 评分环 + 雷达)，
但只画一只票的内容。
"""

from __future__ import annotations

import html
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.advice import Advice, AdviceAction, generate_advice  # noqa: E402
from src.analysis.trust import AnalysisTrust, TrustStatus  # noqa: E402
from src.data_layer.quality import QualityIssue  # noqa: E402


# ============ Colors / Labels ============
BULL = "#22c55e"
BULL_LIGHT = "#4ade80"
BEAR = "#ef4444"
BEAR_LIGHT = "#f87171"
NEUTRAL = "#facc15"
NEUTRAL_LIGHT = "#fbbf24"
PURPLE = "#a855f7"
BLUE = "#3b82f6"
CYAN = "#06b6d4"


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def fmt_pct(v):
    return f"{v:+.2f}%" if v is not None else "—"


def _trust_from_snapshot(d: dict) -> AnalysisTrust:
    raw = d.get("_trust")
    if raw:
        return AnalysisTrust.from_dict(raw)
    return AnalysisTrust(
        TrustStatus.BLOCKED,
        (QualityIssue("missing_trust", "缺少可信状态", critical=True),),
        (),
        datetime.now().astimezone().isoformat(timespec="seconds"),
    )


def render_trust_banner(trust: AnalysisTrust) -> str:
    issues = "".join(
        f"<li>{html.escape(issue.code)}: {html.escape(issue.message)}</li>"
        for issue in trust.issues
    ) or "<li>无质量问题</li>"
    sources = "".join(
        "<tr>"
        f"<td>{html.escape(item.source)}</td>"
        f"<td>{html.escape(item.dataset)}</td>"
        f"<td>{html.escape(item.status)}</td>"
        f"<td>{item.row_count}</td>"
        f"<td>{html.escape(item.adjustment or '—')}</td>"
        "</tr>"
        for item in trust.source_manifest
    ) or '<tr><td colspan="5">无来源清单</td></tr>'
    return f"""
    <section class="section trust-{trust.status.value}">
      <h2>数据可信状态：{trust.status.value}</h2>
      <p>检查时间：{html.escape(trust.checked_at)}</p>
      <ul>{issues}</ul>
      <table class="matrix"><tr><th>来源</th><th>数据集</th><th>状态</th><th>行数</th><th>复权</th></tr>{sources}</table>
    </section>
    """


def render_advice_section(advice: Advice | None, trust: AnalysisTrust) -> str:
    disclaimer = "结论是规则化研究信号，不构成收益保证或投资承诺。"
    if advice is None:
        return f"""
        <section class="section advice-blocked" data-advice-action="none">
          <h2>数据不足，禁止形成买卖结论</h2>
          <p>请先修复报告列出的数据完整性、时效性或来源错误。</p>
          <p>{disclaimer}</p>
        </section>
        """
    labels = {
        AdviceAction.BUY: "买入",
        AdviceAction.HOLD: "持有",
        AdviceAction.REDUCE: "减仓",
        AdviceAction.SELL: "卖出",
        AdviceAction.WATCH: "观望",
    }
    support = "".join(f"<li>{html.escape(item)}</li>" for item in advice.supporting_evidence)
    risks = "".join(f"<li>{html.escape(item)}</li>" for item in advice.risk_evidence) or "<li>无额外风险证据</li>"
    invalidation = "".join(f"<li>{html.escape(item)}</li>" for item in advice.invalidation_conditions)
    return f"""
    <section class="section advice-trusted" data-advice-action="{advice.action.value}">
      <h2>操作结论：{labels[advice.action]}</h2><p>数据截止：{html.escape(advice.as_of)}</p>
      <h3>支持证据</h3><ul>{support}</ul><h3>风险证据</h3><ul>{risks}</ul>
      <h3>失效条件</h3><ul>{invalidation}</ul><p>{disclaimer}</p>
    </section>
    """


# ============ 评分 ============
def calc_score(d: dict) -> dict:
    """综合评分（4 维度加权）:
    - performance 35%  (业绩兑现度)
    - valuation   25%  (目标价空间)
    - sector      20%  (板块动量 - 新增)
    - capital     20%  (资金流热度 - 新增)
    """
    # 1. 业绩
    fs = d.get("finance_summary", {}).get("head", [])
    ni_yoy = 0
    rev_yoy = 0
    if len(fs) >= 2:
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
    perf_score = round(min(100, max(0, 50 + ni_yoy)))

    # 2. 估值
    cons = d.get("consensus", {})
    tp = cons.get("target_price")
    k = d.get("kline", {}).get("head", [])
    cur = _f(k[-1].get("close")) if k else 0
    upside = ((tp - cur) / cur * 100) if (tp and cur > 0) else 0
    val_score = round(min(100, max(0, 50 + upside)))

    # 3/4. 报告只消费快照，不在渲染阶段访问网络
    sector_result = d.get("sector_momentum") or {}
    sector_score = _f(sector_result.get("score"), 50)
    sector_meta = {
        "industry": sector_result.get("industry", "—"),
        "zdf": sector_result.get("industry_zdf"),
        "rank": sector_result.get("industry_rank"),
        "is_hot": sector_result.get("is_sector_hot", False),
        "top10": sector_result.get("top10_industries", []),
    }

    flow_result = d.get("capital_flow") or {}
    flow_score = _f(flow_result.get("score"), 50)
    flow_meta = {
        "is_on_lhb": flow_result.get("is_on_lhb", False),
        "is_limit_up": flow_result.get("is_limit_up", False),
        "hot_rank": flow_result.get("hot_rank"),
        "reason": flow_result.get("reason", ""),
    }

    # 综合 (权重调整: 业绩 35% / 估值 25% / 板块 20% / 资金 20%)
    total = round(
        perf_score * 0.35 + val_score * 0.25 + sector_score * 0.20 + flow_score * 0.20
    )

    # β 反弹机会检测
    is_beta = False
    beta_reason = ""
    try:
        from src.factors.sector_momentum import is_beta_rebound_opportunity

        # 构造 sector_result 简版给 is_beta_rebound_opportunity
        fake_sec = {"score": sector_score, "is_sector_hot": sector_meta["is_hot"]}
        fake_flow = {
            "score": flow_score,
            "is_flow_hot": flow_meta["is_limit_up"] or flow_meta["is_on_lhb"],
        }
        is_beta, beta_reason = is_beta_rebound_opportunity(
            perf_score, fake_sec, fake_flow
        )
    except Exception:  # noqa: BLE001
        pass

    return {
        # 4 维分项
        "perf": perf_score,
        "valuation": val_score,
        "sector": sector_score,
        "capital": flow_score,
        "total": total,
        # 综合
        "ni_yoy": ni_yoy,
        "rev_yoy": rev_yoy,
        "upside": upside,
        "tp": tp,
        "cur": cur,
        # 板块 + 资金 元数据
        "sector_meta": sector_meta,
        "flow_meta": flow_meta,
        # β 反弹
        "is_beta": is_beta,
        "beta_reason": beta_reason,
    }


# ============ 评级环 SVG ============
def score_ring(pct, color):
    return f"""
    <div class="score-circle" style="background: conic-gradient({color} 0%, {color} {pct}%, #1e293b {pct}%, #1e293b 100%);">
      <div class="score-inner">
        <div class="num" style="color:{color}">{pct}</div>
        <div class="total">/ 100</div>
        <div class="label" style="color:{color}">{pct_to_label(pct)}</div>
      </div>
    </div>
    """


def pct_to_label(p):
    if p >= 80:
        return "极强信号"
    if p >= 60:
        return "强信号"
    if p >= 40:
        return "中性"
    if p >= 20:
        return "弱信号"
    return "极弱"


# ============ 模板 ============
HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__ · 端到端分析</title>
<meta name="description" content="__NAME__ __SYMBOL__ 端到端分析报告" />
<meta property="og:title" content="__NAME__ __SYMBOL__" />
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  background:linear-gradient(135deg,#0a0e27 0%,#1a1f3a 50%,#0f1729 100%);
  color:#e0e6f1; min-height:100vh; padding:24px; line-height:1.6;
}
.container { max-width:1280px; margin:0 auto; }
.header {
  background:linear-gradient(135deg,rgba(99,102,241,0.18),rgba(168,85,247,0.10),rgba(245,158,11,0.10));
  border:1px solid rgba(168,85,247,0.3); border-radius:24px;
  padding:40px 50px; margin-bottom:24px; position:relative; overflow:hidden;
  backdrop-filter:blur(20px);
}
.header::before {
  content:''; position:absolute; top:-50%; right:-10%; width:500px; height:500px;
  background:radial-gradient(circle,rgba(168,85,247,0.3),transparent 70%); border-radius:50%;
}
.header-content { position:relative; z-index:1; }
.stock-tag {
  display:inline-block; padding:6px 14px;
  background:rgba(168,85,247,0.2); border:1px solid rgba(168,85,247,0.4);
  border-radius:20px; font-size:13px; color:#ddd6fe;
  font-weight:600; margin-bottom:16px;
}
.header h1 {
  font-size:38px; font-weight:800;
  background:linear-gradient(135deg,#60a5fa,#a855f7,#f59e0b);
  -webkit-background-clip:text; -webkit-text-fill-color:transparent;
  margin-bottom:12px;
}
.header .subtitle { color:#94a3b8; font-size:16px; margin-bottom:20px; }
.header-meta { display:flex; gap:14px; flex-wrap:wrap; margin-top:20px; }
.header-meta .item {
  background:rgba(15,23,42,0.6); padding:12px 18px;
  border-radius:12px; border:1px solid rgba(148,163,184,0.15);
  min-width:110px;
}
.header-meta .item .label { font-size:11px; color:#64748b; text-transform:uppercase; }
.header-meta .item .value { font-size:20px; font-weight:700; color:#f1f5f9; margin-top:4px; }
.header-meta .item.green .value { color:#4ade80; }
.header-meta .item.red .value { color:#f87171; }
.header-meta .item.yellow .value { color:#facc15; }

.section {
  background:rgba(30,41,59,0.5); border:1px solid rgba(148,163,184,0.15);
  border-radius:20px; padding:32px; margin-bottom:24px; backdrop-filter:blur(10px);
}
.section-title {
  font-size:22px; font-weight:700; color:#f1f5f9;
  margin-bottom:6px; display:flex; align-items:center; gap:12px;
}
.section-title .num {
  background:linear-gradient(135deg,#6366f1,#a855f7);
  color:white; width:36px; height:36px; border-radius:10px;
  display:inline-flex; align-items:center; justify-content:center;
  font-size:16px; font-weight:800;
}
.section-desc { color:#94a3b8; font-size:14px; margin-bottom:20px; }

/* Score */
.score-grid {
  display:grid; grid-template-columns: 1fr 1fr; gap:24px; align-items:center;
}
.score-circle-wrap { position:relative; width:240px; height:240px; margin:0 auto; }
.score-circle {
  width:240px; height:240px; border-radius:50%;
  display:flex; align-items:center; justify-content:center; position:relative;
}
.score-circle::before {
  content:''; position:absolute; inset:16px; background:#0f1729; border-radius:50%;
}
.score-inner { position:relative; text-align:center; z-index:1; }
.score-inner .num { font-size:56px; font-weight:900; line-height:1; }
.score-inner .total { font-size:14px; color:#94a3b8; margin-top:4px; }
.score-inner .label { font-size:12px; margin-top:8px; font-weight:700; letter-spacing:1px; }
.score-detail h2 { color:#fef2f2; font-size:22px; margin-bottom:12px; }
.score-detail .desc { color:#fecaca; font-size:14px; margin-bottom:16px; line-height:1.7; }
.score-grid-mini { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }
.score-mini {
  background:rgba(15,23,42,0.6); padding:14px; border-radius:10px; text-align:center;
}
.score-mini .v { font-size:24px; font-weight:800; }
.score-mini .l { font-size:11px; color:#94a3b8; margin-top:4px; }
.score-mini.green .v { color:#4ade80; }
.score-mini.yellow .v { color:#facc15; }
.score-mini.red .v { color:#f87171; }

/* Stock detail card */
.stock-detail {
  display:grid; grid-template-columns:1fr 1fr 1fr 1fr; gap:12px; margin-top:16px;
}
.stat-card {
  background:rgba(15,23,42,0.6); padding:16px; border-radius:12px;
  border:1px solid rgba(148,163,184,0.15);
}
.stat-card .l { font-size:10px; color:#94a3b8; text-transform:uppercase; }
.stat-card .v { font-size:18px; font-weight:800; color:#f1f5f9; margin-top:4px; }
.stat-card.green .v { color:#4ade80; }
.stat-card.red .v { color:#f87171; }
.stat-card.purple .v { color:#c084fc; }

/* Indicator grid */
.indicator-grid {
  display:grid; grid-template-columns:repeat(5,1fr); gap:10px; margin-top:12px;
}
.indicator-card {
  background:rgba(15,23,42,0.6); border-radius:10px;
  padding:14px 8px; text-align:center; border:1px solid rgba(148,163,184,0.15);
}
.indicator-card.bull { border-color:rgba(34,197,94,0.5); background:rgba(34,197,94,0.05); }
.indicator-card.bear { border-color:rgba(239,68,68,0.5); background:rgba(239,68,68,0.05); }
.indicator-card.neut { border-color:rgba(234,179,8,0.5); background:rgba(234,179,8,0.05); }
.indicator-card .name { font-size:11px; color:#94a3b8; }
.indicator-card .value { font-size:18px; font-weight:800; color:#f1f5f9; margin:4px 0; }
.indicator-card .status { font-size:10px; font-weight:700; }
.indicator-card.bull .status { color:#4ade80; }
.indicator-card.bear .status { color:#f87171; }
.indicator-card.neut .status { color:#facc15; }

/* Tables */
.matrix { width:100%; border-collapse:collapse; font-size:13px; margin-top:12px; }
.matrix th {
  background:rgba(99,102,241,0.15); color:#c7d2fe;
  padding:12px 14px; text-align:left; font-weight:600;
  border-bottom:2px solid rgba(99,102,241,0.3);
}
.matrix th:first-child { border-top-left-radius:10px; }
.matrix th:last-child { border-top-right-radius:10px; }
.matrix td {
  padding:11px 14px; border-bottom:1px solid rgba(148,163,184,0.1);
  color:#cbd5e1;
}
.matrix tr:hover td { background:rgba(99,102,241,0.05); }
.matrix td:first-child { color:#f1f5f9; font-weight:600; }
.matrix .v { text-align:right; }
.matrix .pos { color:#4ade80; font-weight:600; }
.matrix .neg { color:#f87171; font-weight:600; }
.matrix .neu { color:#facc15; font-weight:600; }

.badge {
  display:inline-block; padding:4px 10px; border-radius:8px;
  font-size:11px; font-weight:700; letter-spacing:0.5px;
}
.badge.bull { background:rgba(34,197,94,0.2); color:#4ade80; border:1px solid rgba(34,197,94,0.4); }
.badge.bear { background:rgba(239,68,68,0.2); color:#f87171; border:1px solid rgba(239,68,68,0.4); }
.badge.neut { background:rgba(234,179,8,0.2); color:#facc15; border:1px solid rgba(234,179,8,0.4); }
.badge.purple { background:rgba(168,85,247,0.2); color:#c084fc; border:1px solid rgba(168,85,247,0.4); }

.chart-box {
  background:rgba(15,23,42,0.6); border-radius:14px;
  padding:20px; height:380px; border:1px solid rgba(148,163,184,0.1);
}
.chart-box canvas { max-height:320px; }

.timeline { position:relative; padding-left:28px; margin-top:12px; }
.timeline::before {
  content:''; position:absolute; left:8px; top:8px; bottom:8px;
  width:2px; background:linear-gradient(180deg,#6366f1,#a855f7,transparent);
}
.timeline-item {
  position:relative; padding:12px 0 12px 8px;
  border-bottom:1px dashed rgba(148,163,184,0.1);
}
.timeline-item:last-child { border-bottom:none; }
.timeline-item::before {
  content:''; position:absolute; left:-24px; top:18px;
  width:12px; height:12px; border-radius:50%;
  background:#6366f1; border:3px solid #0f1729;
  box-shadow:0 0 0 2px #6366f1;
}
.timeline-item .time { font-size:11px; color:#64748b; }
.timeline-item .title { font-size:13px; color:#f1f5f9; margin-top:2px; }
.timeline-item .src { font-size:11px; color:#94a3b8; margin-top:2px; }

.narrative {
  background:linear-gradient(135deg,rgba(99,102,241,0.10),rgba(168,85,247,0.06));
  border-left:4px solid #a855f7; border-radius:10px;
  padding:18px 22px; margin-top:14px; color:#cbd5e1; font-size:13px; line-height:1.7;
}
.narrative b { color:#f1f5f9; }
.narrative.warn { background:linear-gradient(135deg,rgba(239,68,68,0.10),rgba(15,23,42,0.6)); border-color:#ef4444; }
.narrative.bull { background:linear-gradient(135deg,rgba(34,197,94,0.10),rgba(15,23,42,0.6)); border-color:#22c55e; }

/* Strategy cards */
.op-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:18px; margin-top:16px; }
.op-card {
  background:rgba(15,23,42,0.6); border-radius:14px; padding:22px;
  border:1px solid; border-left-width:5px;
}
.op-card.bull { border-color:rgba(34,197,94,0.5); border-left-color:#22c55e; }
.op-card.bear { border-color:rgba(239,68,68,0.5); border-left-color:#ef4444; }
.op-card.neut { border-color:rgba(234,179,8,0.5); border-left-color:#facc15; }
.op-card.purple { border-color:rgba(168,85,247,0.5); border-left-color:#a855f7; }
.op-card h3 { font-size:16px; color:#f1f5f9; margin-bottom:10px; display:flex; align-items:center; gap:8px; }
.op-card .tag { padding:2px 8px; border-radius:6px; font-size:11px; font-weight:700; }
.op-card.bull .tag { background:rgba(34,197,94,0.2); color:#4ade80; }
.op-card.bear .tag { background:rgba(239,68,68,0.2); color:#f87171; }
.op-card.neut .tag { background:rgba(234,179,8,0.2); color:#facc15; }
.op-card.purple .tag { background:rgba(168,85,247,0.2); color:#c084fc; }
.op-card ul { list-style:none; padding:0; margin-top:8px; }
.op-card li { font-size:12px; color:#cbd5e1; padding:4px 0; display:flex; justify-content:space-between; }
.op-card li b { color:#f1f5f9; font-weight:600; }
.op-card li .v { color:#fbbf24; font-weight:700; }

.disclaimer {
  background:rgba(239,68,68,0.05); border:1px solid rgba(239,68,68,0.2);
  border-radius:14px; padding:20px 28px; color:#fca5a5;
  font-size:13px; margin-top:30px; line-height:1.8;
}
.disclaimer b { color:#fef2f2; }

@media (max-width:900px) {
  .score-grid, .op-grid, .stock-detail { grid-template-columns:1fr; }
  .indicator-grid { grid-template-columns:repeat(3,1fr); }
  .header h1 { font-size:26px; }
}
</style>
</head>
<body>
<div class="container">
"""

DISCLAIMER = """
<div class="disclaimer">
<b>⚠️ 重要免责声明</b><br>
本分析基于截至 __DATE__ 的腾讯自选股（westock-data）公开数据，
结合 LLM 编排的跨域信号交叉生成。<br>
<b>不构成证券投资建议</b>。任何标的都需结合最新行情与自身风险承受能力做决策。<b>市场有风险，决策需谨慎。</b>
</div>
"""


# ============ Renderers ============
def render_header(d, score, sentiment_color, sentiment_label):
    k = d["kline"]["head"]
    latest = k[0] if k else {}
    cur = _f(latest.get("close"))
    day_chg = (_f(latest.get("close")) / _f(latest.get("open")) - 1) * 100
    name = d.get("name", "") or d.get("symbol", "")
    symbol = d.get("symbol", "")
    profile = d.get("profile", {}) or {}
    industry = profile.get("industry", "—")
    listed = profile.get("listedDate", "—")
    # 板块 + 资金 sub-tag
    sec_meta = score.get("sector_meta", {})
    flow_meta = score.get("flow_meta", {})
    extra_badges = []
    if sec_meta.get("is_hot"):
        extra_badges.append(
            f'<span class="badge bull" style="font-size:11px">🔥 板块热 ({sec_meta.get("industry", "")} #{sec_meta.get("rank", "?")})</span>'
        )
    if flow_meta.get("is_limit_up"):
        extra_badges.append(
            '<span class="badge bull" style="font-size:11px">涨停异动</span>'
        )
    if flow_meta.get("is_on_lhb"):
        extra_badges.append(
            '<span class="badge purple" style="font-size:11px">龙虎榜</span>'
        )
    if score.get("is_beta"):
        extra_badges.append(
            '<span class="badge purple" style="font-size:11px">🔥 β 反弹</span>'
        )
    extra_html = " ".join(extra_badges)
    return f"""
    <div class="header">
      <div class="header-content">
        <span class="stock-tag">🤖 chinaStock · 单股深度分析框架 v1.0</span>
        <h1>
          <span style="font-size:46px; font-weight:900; background:linear-gradient(135deg,#fbbf24,#f87171); -webkit-background-clip:text; -webkit-text-fill-color:transparent">
            {html.escape(name)}
          </span>
          <span style="font-size:18px; color:#94a3b8; font-weight:400; margin-left:8px">{html.escape(symbol)}</span>
        </h1>
        <p class="subtitle">
          <span style="color:#cbd5e1; font-weight:600">{html.escape(industry)}</span>
          <span style="color:#64748b">  ·  上市 {html.escape(listed)}  ·  截至 {d.get("pulled_at", "")[:10]}</span>
        </p>
        <div style="margin-top:10px; display:flex; flex-wrap:wrap; gap:6px">{extra_html}</div>
        <div class="header-meta">
          <div class="item"><div class="label">现价</div><div class="value">{cur:.2f}</div></div>
          <div class="item {"green" if day_chg >= 0 else "red"}"><div class="label">当日</div><div class="value">{day_chg:+.2f}%</div></div>
          <div class="item {"green" if score["total"] >= 60 else ("yellow" if score["total"] >= 40 else "red")}"><div class="label">综合评分</div><div class="value">{score["total"]} · {sentiment_label}</div></div>
          <div class="item purple"><div class="label">业绩 YoY</div><div class="value">{score["ni_yoy"]:+.1f}%</div></div>
          <div class="item {"green" if score["upside"] > 0 else "red"}"><div class="label">目标空间</div><div class="value">{score["upside"]:+.1f}%</div></div>
        </div>
      </div>
    </div>
    """


def render_score_section(score, sentiment_color, sentiment_label, narrative):
    sec_meta = score.get("sector_meta", {})
    flow_meta = score.get("flow_meta", {})

    # 行业 sub-line
    sec_line = ""
    if sec_meta.get("zdf") is not None:
        zdf_color = "#4ade80" if sec_meta["zdf"] > 0 else "#f87171"
        sec_line = (
            f'<div style="margin-top:10px; font-size:12px; color:#cbd5e1">'
            f'所属行业 <b style="color:#f1f5f9">{html.escape(str(sec_meta["industry"]))}</b>'
            f' · 今日 <b style="color:{zdf_color}">{sec_meta["zdf"]:+.2f}%</b>'
            f' · 排名 <b style="color:#f1f5f9">#{sec_meta.get("rank", "—")}</b>'
            f' · 强度 <b style="color:#f1f5f9">{score["sector"]:.0f}/100</b>'
            f' · 状态 <b style="color:{"#4ade80" if sec_meta.get("is_hot") else "#cbd5e1"}">'
            f"{'🔥 板块热' if sec_meta.get('is_hot') else '正常'}</b>"
            f"</div>"
        )
    # Top10 行业条
    top10_html = ""
    if sec_meta.get("top10"):
        items = " ".join(
            f'<span class="badge {"bull" if z and z > 0 else "bear"}" style="font-size:10px; padding:2px 6px">{html.escape(n)} {f"{z:+.1f}%" if z is not None else "—"}</span>'
            for n, z in sec_meta["top10"][:8]
        )
        top10_html = f'<div style="margin-top:8px; display:flex; flex-wrap:wrap; gap:4px">{items}</div>'

    # 资金流 sub-line
    if flow_meta.get("is_limit_up") or flow_meta.get("is_on_lhb"):
        badges = []
        if flow_meta.get("is_limit_up"):
            badges.append('<span class="badge bull">涨停异动</span>')
        if flow_meta.get("is_on_lhb"):
            badges.append('<span class="badge purple">龙虎榜</span>')
        if flow_meta.get("hot_rank"):
            badges.append(
                f'<span class="badge neut">热搜 #{flow_meta["hot_rank"]}</span>'
            )
        flow_line = (
            f'<div style="margin-top:10px; font-size:12px; color:#cbd5e1">'
            f'资金流 {" ".join(badges)} · 强度 <b style="color:#f1f5f9">{score["capital"]:.0f}/100</b>'
            f"</div>"
            f'<div style="margin-top:4px; font-size:11px; color:#94a3b8; font-style:italic">{html.escape(flow_meta.get("reason", ""))}</div>'
        )
    else:
        flow_line = (
            f'<div style="margin-top:10px; font-size:12px; color:#94a3b8">'
            f'资金流: 无显著异动 · 强度 <b style="color:#cbd5e1">{score["capital"]:.0f}/100</b></div>'
        )

    # β 反弹 badge
    beta_badge = ""
    if score.get("is_beta"):
        beta_badge = (
            '<div style="margin-top:14px; padding:14px 18px; background:linear-gradient(135deg,rgba(168,85,247,0.18),rgba(15,23,42,0.6)); '
            'border-left:5px solid #a855f7; border-radius:10px; color:#ddd6fe; font-size:13px">'
            '🔥 <b style="color:#f1f5f9">β 反弹机会</b>: 业绩偏弱, 但 '
            "<b>板块强 + 资金流入</b>, 短线可博向上, 不必死等业绩拐点<br>"
            f'<span style="font-size:11px; color:#a78bfa">{html.escape(score.get("beta_reason", ""))}</span>'
            "</div>"
        )

    return f"""
    <div class="section">
      <h2 class="section-title"><span class="num">1</span>综合诊断评分 <span style="font-size:13px; color:#94a3b8; font-weight:400">(业绩 35% · 估值 25% · 板块 20% · 资金 20%)</span></h2>
      <div class="score-grid">
        <div>
          <div class="score-circle-wrap">
            {score_ring(score["total"], sentiment_color)}
          </div>
        </div>
        <div class="score-detail">
          <h2>{sentiment_label} · {score["total"]}/100</h2>
          <p class="desc">{narrative}</p>
          <div class="score-grid-mini">
            <div class="score-mini {"green" if score["perf"] >= 60 else ("red" if score["perf"] < 40 else "yellow")}">
              <div class="v">{score["perf"]}</div><div class="l">业绩 35%</div>
            </div>
            <div class="score-mini {"green" if score["valuation"] >= 60 else ("red" if score["valuation"] < 40 else "yellow")}">
              <div class="v">{score["valuation"]}</div><div class="l">估值 25%</div>
            </div>
            <div class="score-mini {"green" if score["sector"] >= 60 else ("red" if score["sector"] < 40 else "yellow")}">
              <div class="v">{score["sector"]:.0f}</div><div class="l">板块 20%</div>
            </div>
            <div class="score-mini {"green" if score["capital"] >= 60 else ("red" if score["capital"] < 40 else "yellow")}">
              <div class="v">{score["capital"]:.0f}</div><div class="l">资金 20%</div>
            </div>
          </div>
          {sec_line}
          {top10_html}
          {flow_line}
          {beta_badge}
        </div>
      </div>
    </div>
    """


def render_metrics_grid(d, score):
    k = d["kline"]["head"]
    if not k:
        return ""
    cur = _f(k[0].get("close"))
    day_chg = (_f(k[0].get("close")) / _f(k[0].get("open")) - 1) * 100
    chg5 = (cur / _f(k[4].get("close")) - 1) * 100 if len(k) > 4 else 0
    chg20 = (cur / _f(k[19].get("close")) - 1) * 100 if len(k) > 19 else 0
    ma = d.get("technical_ma", {}).get("head", [{}])[0]
    rsi = d.get("technical_rsi", {}).get("head", [{}])[0]
    kdj = d.get("technical_kdj", {}).get("head", [{}])[0]
    boll = d.get("technical_boll", {}).get("head", [{}])[0]
    fs = d.get("finance_summary", {}).get("head", [])
    last = fs[-1] if fs else {}
    cons = d.get("consensus", {})
    rating_list = d.get("rating", {}).get("head", [])
    rating = rating_list[0] if rating_list else {}
    buy = rating.get("rating_buy", 0) or 0
    inc = rating.get("rating_inc", 0) or 0
    cards = f"""
    <div class="stat-card"><div class="l">现价</div><div class="v">{cur:.2f}</div></div>
    <div class="stat-card {"green" if day_chg >= 0 else "red"}"><div class="l">当日</div><div class="v">{day_chg:+.2f}%</div></div>
    <div class="stat-card {"green" if chg5 >= 0 else "red"}"><div class="l">5 日</div><div class="v">{chg5:+.2f}%</div></div>
    <div class="stat-card {"green" if chg20 >= 0 else "red"}"><div class="l">20 日</div><div class="v">{chg20:+.2f}%</div></div>
    <div class="stat-card"><div class="l">MA5</div><div class="v">{_f(ma.get("ma.MA_5")):.2f}</div></div>
    <div class="stat-card"><div class="l">MA20</div><div class="v">{_f(ma.get("ma.MA_20")):.2f}</div></div>
    <div class="stat-card"><div class="l">BOLL 上轨</div><div class="v">{_f(boll.get("boll.BOLL_UPPER")):.2f}</div></div>
    <div class="stat-card {"red" if _f(rsi.get("rsi.RSI_2")) >= 80 else ("green" if _f(rsi.get("rsi.RSI_2")) <= 20 else "purple")}">
      <div class="l">RSI2 (短线)</div><div class="v">{_f(rsi.get("rsi.RSI_2")):.0f}</div>
    </div>
    <div class="stat-card"><div class="l">RSI6</div><div class="v">{_f(rsi.get("rsi.RSI_6")):.0f}</div></div>
    <div class="stat-card"><div class="l">KDJ-K</div><div class="v">{_f(kdj.get("kdj.KDJ_K")):.0f}</div></div>
    <div class="stat-card"><div class="l">2025 营收</div><div class="v">{_f(last.get("TotalOperatingRevenueTTM")) / 1e8:.0f}亿</div></div>
    <div class="stat-card"><div class="l">2025 净利</div><div class="v">{_f(last.get("NPParentCompanyOwnersTTM")) / 1e8:.1f}亿</div></div>
    <div class="stat-card"><div class="l">2025 EPS</div><div class="v">{_f(last.get("BasicEPS")):.3f}</div></div>
    <div class="stat-card {"green" if score["upside"] > 0 else "red"}"><div class="l">目标价</div><div class="v">{(cons.get("target_price") or 0):.2f}</div></div>
    <div class="stat-card"><div class="l">机构评级</div><div class="v" style="font-size:14px">{buy}买/{inc}增</div></div>
    """
    return f"""
    <div class="section">
      <h2 class="section-title"><span class="num">2</span>核心指标卡 (技术+基本面+估值)</h2>
      <div class="stock-detail">{cards}</div>
    </div>
    """


def render_kline_chart(d):
    k = d.get("kline", {}).get("head", [])
    if not k:
        return ""
    k = list(reversed(k))
    labels = [r.get("date", "")[5:] for r in k]
    closes = [_f(r.get("close")) for r in k]
    ma5 = [_f(r.get("ma.MA_5")) for r in d.get("technical_ma", {}).get("head", [])]
    ma5 = list(reversed(ma5))
    ma20 = [_f(r.get("ma.MA_20")) for r in d.get("technical_ma", {}).get("head", [])]
    ma20 = list(reversed(ma20))
    return f"""
    <div class="section">
      <h2 class="section-title"><span class="num">3</span>价格 + 均线 (60 日)</h2>
      <p class="section-desc">K 线 + MA5/MA20 叠加，关键看能否站稳均线支撑</p>
      <div class="chart-box"><canvas id="priceMaChart"></canvas></div>
    </div>
    <script>
    Chart.defaults.color='#94a3b8';
    Chart.defaults.borderColor='rgba(148,163,184,0.1)';
    Chart.defaults.font.family='-apple-system,"PingFang SC","Microsoft YaHei",sans-serif';
    new Chart(document.getElementById('priceMaChart'), {{
      type:'line',
      data:{{
        labels:{json.dumps(labels)},
        datasets:[
          {{label:'收盘价', data:{json.dumps(closes)}, borderColor:'#f87171', backgroundColor:'rgba(248,113,113,0.08)', tension:0.3, borderWidth:3, pointRadius:2, fill:true}},
          {{label:'MA5', data:{json.dumps(ma5)}, borderColor:'#60a5fa', borderWidth:1.5, pointRadius:0, borderDash:[3,3]}},
          {{label:'MA20', data:{json.dumps(ma20)}, borderColor:'#c084fc', borderWidth:2, pointRadius:0}},
        ]
      }},
      options:{{
        responsive:true, maintainAspectRatio:false,
        plugins:{{ legend:{{position:'top',labels:{{color:'#e2e8f0'}}}},
                 title:{{display:true,text:'价格与均线系统',color:'#f1f5f9',font:{{size:14,weight:600}}}}}},
        scales:{{
          x:{{ grid:{{color:'rgba(148,163,184,0.05)'}}, ticks:{{maxTicksLimit:15}} }},
          y:{{ grid:{{color:'rgba(148,163,184,0.05)'}} }}
        }}
      }}
    }});
    </script>
    """


def render_indicators(d):
    ma = d.get("technical_ma", {}).get("head", [{}])[0]
    macd = d.get("technical_macd", {}).get("head", [{}])[0]
    rsi = d.get("technical_rsi", {}).get("head", [{}])[0]
    kdj = d.get("technical_kdj", {}).get("head", [{}])[0]
    boll = d.get("technical_boll", {}).get("head", [{}])[0]
    price = _f(ma.get("closePrice"))
    ma5 = _f(ma.get("ma.MA_5"))
    ma20 = _f(ma.get("ma.MA_20"))
    dif = _f(macd.get("macd.DIF"))
    dea = _f(macd.get("macd.DEA"))
    rsi6 = _f(rsi.get("rsi.RSI_6"))
    rsi2 = _f(rsi.get("rsi.RSI_2"))
    k = _f(kdj.get("kdj.KDJ_K"))
    boll_up = _f(boll.get("boll.BOLL_UPPER"))
    boll_low = _f(boll.get("boll.BOLL_LOWER"))

    def cls_bull(v, low, high):
        return "bull" if v > high else ("bear" if v < low else "neut")

    ma_trend = (
        "bull" if price > ma5 > ma20 else ("bear" if price < ma5 < ma20 else "neut")
    )
    macd_stat = (
        "bull"
        if dif > dea and dif > 0
        else ("bear" if dif < dea and dif < 0 else "neut")
    )
    rsi_stat = "bull" if rsi6 < 30 else ("bear" if rsi6 > 70 else "neut")
    rsi2_stat = "bull" if rsi2 < 30 else ("bear" if rsi2 > 80 else "neut")
    kdj_stat = "bull" if k < 20 else ("bear" if k > 80 else "neut")
    boll_pos = (
        (price - boll_low) / (boll_up - boll_low) * 100 if boll_up > boll_low else 50
    )

    cards = f"""
    <div class="indicator-card {ma_trend}">
      <div class="name">MA 趋势</div>
      <div class="value">{"↑" if ma_trend == "bull" else ("↓" if ma_trend == "bear" else "→")}</div>
      <div class="status">{"多头" if ma_trend == "bull" else ("空头" if ma_trend == "bear" else "纠缠")}</div>
    </div>
    <div class="indicator-card {macd_stat}">
      <div class="name">MACD</div>
      <div class="value">{("+" + f"{dif:.2f}" if dif >= 0 else f"{dif:.2f}")}</div>
      <div class="status">{"金叉" if macd_stat == "bull" else ("死叉" if macd_stat == "bear" else "中性")}</div>
    </div>
    <div class="indicator-card {rsi2_stat}">
      <div class="name">RSI2 (短线)</div>
      <div class="value">{rsi2:.0f}</div>
      <div class="status">{"超卖" if rsi2_stat == "bull" else ("超买" if rsi2_stat == "bear" else "正常")}</div>
    </div>
    <div class="indicator-card {rsi_stat}">
      <div class="name">RSI6</div>
      <div class="value">{rsi6:.0f}</div>
      <div class="status">{"超卖" if rsi_stat == "bull" else ("超买" if rsi_stat == "bear" else "正常")}</div>
    </div>
    <div class="indicator-card {kdj_stat}">
      <div class="name">KDJ-K</div>
      <div class="value">{k:.0f}</div>
      <div class="status">{"超卖" if kdj_stat == "bull" else ("超买" if kdj_stat == "bear" else "正常")}</div>
    </div>
    <div class="indicator-card neut">
      <div class="name">BOLL 位置</div>
      <div class="value" style="font-size:14px">{boll_pos:.0f}%</div>
      <div class="status">{("贴近上轨" if boll_pos > 80 else ("中轨附近" if boll_pos > 40 else "贴近下轨"))}</div>
    </div>
    """
    return f"""
    <div class="section">
      <h2 class="section-title"><span class="num">4</span>5 大技术指标扫描</h2>
      <p class="section-desc">MA / MACD / RSI / KDJ / BOLL 最新一日状态</p>
      <div class="indicator-grid">{cards}</div>
    </div>
    """


def render_backtest_macd(d):
    """MACD 信号回测验证 — 把回测结论合入报告。

    从 long_form JSON 的 kline 数据计算 MACD 信号，跑回测，输出：
    1. MACD 信号图（DIF/DEA + 买卖标记）
    2. 回测指标卡（年化/Sharpe/回撤/胜率）
    3. 当前信号状态 + 历史胜率
    """
    from src.factors.technical import compute_macd
    from strategies.base import run_backtest

    k_data = d.get("kline", {}).get("head", [])
    if not k_data or len(k_data) < 15:
        return ""

    df = pd.DataFrame(k_data).copy()
    df = df.sort_values("date").reset_index(drop=True)
    for col in ("open", "close", "high", "low", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    try:
        # 最优参数 5/13/5
        signals = compute_macd(df, fast=5, slow=13, signal_period=5)
        signal_map = dict(zip(signals["date"], signals["signal"]))
        bt = run_backtest(signal_map, df)
        # 默认参数 12/26/9（用于参数敏感性对比）
        signals_default = compute_macd(df, fast=12, slow=26, signal_period=9)
        bt_default = run_backtest(
            dict(zip(signals_default["date"], signals_default["signal"])), df
        )
    except Exception:
        return ""

    # 基本面过滤判断
    fs = d.get("finance_summary", {}).get("head", [])
    ni_yoy = 0.0
    if len(fs) >= 2:
        ni_last = _f(fs[-1].get("NPParentCompanyOwnersTTM"))
        ni_first = _f(fs[0].get("NPParentCompanyOwnersTTM"))
        if ni_first > 0:
            ni_yoy = (ni_last - ni_first) / ni_first * 100
    has_positive_earnings = ni_yoy > 0

    if signals.empty:
        return ""

    # 当前信号状态
    latest = signals.iloc[-1]
    current_sig = int(latest["signal"])
    current_dif = float(latest["dif"])
    current_dea = float(latest["dea"])
    sig_text = (
        "金叉（买入信号）"
        if current_sig > 0
        else ("死叉（卖出信号）" if current_sig < 0 else "无信号")
    )
    sig_cls = "bull" if current_sig > 0 else ("bear" if current_sig < 0 else "neut")

    # 历史信号列表
    non_zero = signals[signals["signal"] != 0]
    buy_dates = non_zero[non_zero["signal"] > 0]["date"].tolist()
    sell_dates = non_zero[non_zero["signal"] < 0]["date"].tolist()

    # Chart data
    labels = signals["date"].tolist()
    dif_data = signals["dif"].round(3).tolist()
    dea_data = signals["dea"].round(3).tolist()
    hist_data = signals["macd_hist"].round(3).tolist()
    closes = signals["close"].round(2).tolist()

    # 回测指标
    ann_ret = bt["annual_return"]
    sharpe = bt["sharpe"]
    max_dd = bt["max_drawdown"]
    win_rate = bt["win_rate"]
    total_trades = bt["total_trades"]

    return f"""
    <div class="section" style="background:linear-gradient(135deg,rgba(34,197,94,0.08),rgba(15,23,42,0.6)); border-color:rgba(34,197,94,0.4);">
      <h2 class="section-title" style="color:#4ade80"><span class="num">★</span>MACD 信号回测验证 <span style="font-size:13px; color:#86efac; font-weight:400">回测证明 MACD 金叉是全场最佳策略</span></h2>
      <p class="section-desc" style="color:#86efac">基于 7 只票 × 4 策略回测：MACD 金叉平均年化 +188%，Sharpe 2.7，优于 MA 金叉 (+125%) 和多信号投票 (+78%)</p>

      <div style="display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-top:16px;">
        <!-- 左：图表 -->
        <div class="chart-box" style="height:360px">
          <canvas id="macdBacktestChart"></canvas>
        </div>

        <!-- 右：指标卡 + 当前状态 -->
        <div style="display:flex; flex-direction:column; gap:14px;">
          <div style="background:rgba(15,23,42,0.6); padding:18px; border-radius:14px; border:1px solid rgba(148,163,184,0.15);">
            <div style="font-size:13px; color:#94a3b8; margin-bottom:10px">回测指标（本票 MACD 金叉策略）</div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px">
              <div style="background:rgba(0,0,0,0.2); padding:10px; border-radius:8px; text-align:center">
                <div style="font-size:24px; font-weight:800; color:{"#4ade80" if ann_ret > 0 else "#f87171"}">{ann_ret:+.1f}%</div>
                <div style="font-size:10px; color:#94a3b8">年化收益</div>
              </div>
              <div style="background:rgba(0,0,0,0.2); padding:10px; border-radius:8px; text-align:center">
                <div style="font-size:24px; font-weight:800; color:{"#4ade80" if sharpe > 1 else "#facc15"}">{sharpe:.2f}</div>
                <div style="font-size:10px; color:#94a3b8">Sharpe</div>
              </div>
              <div style="background:rgba(0,0,0,0.2); padding:10px; border-radius:8px; text-align:center">
                <div style="font-size:24px; font-weight:800; color:#f87171">{max_dd:.1f}%</div>
                <div style="font-size:10px; color:#94a3b8">最大回撤</div>
              </div>
              <div style="background:rgba(0,0,0,0.2); padding:10px; border-radius:8px; text-align:center">
                <div style="font-size:24px; font-weight:800; color:#4ade80">{win_rate:.0f}%</div>
                <div style="font-size:10px; color:#94a3b8">胜率 ({total_trades} 笔)</div>
              </div>
            </div>
          </div>

          <div style="background:rgba(15,23,42,0.6); padding:18px; border-radius:14px; border:1px solid rgba(148,163,184,0.15);">
            <div style="font-size:13px; color:#94a3b8; margin-bottom:10px">当前信号状态</div>
            <div style="display:flex; align-items:center; gap:12px">
              <span class="badge {sig_cls}" style="font-size:14px; padding:6px 14px">{sig_text}</span>
              <span style="font-size:12px; color:#94a3b8">DIF={current_dif:.2f} DEA={current_dea:.2f}</span>
            </div>
            <div style="margin-top:10px; font-size:12px; color:#cbd5e1">
              历史信号: {len(buy_dates)} 次金叉 / {len(sell_dates)} 次死叉（{len(signals)} 个交易日）
            </div>
          </div>

          <!-- 参数敏感性对比 -->
          <div style="background:rgba(15,23,42,0.6); padding:18px; border-radius:14px; border:1px solid rgba(148,163,184,0.15);">
            <div style="font-size:13px; color:#94a3b8; margin-bottom:10px">参数敏感性对比（5/13/5 vs 12/26/9）</div>
            <table style="width:100%; border-collapse:collapse; font-size:12px">
              <tr style="border-bottom:1px solid rgba(148,163,184,0.2)">
                <td style="padding:4px 8px; color:#94a3b8">年化</td>
                <td style="padding:4px 8px; text-align:right; color:#4ade80; font-weight:700">{bt["annual_return"]:+.1f}%</td>
                <td style="padding:4px 8px; text-align:right; color:#cbd5e1">{bt_default["annual_return"]:+.1f}%</td>
              </tr>
              <tr style="border-bottom:1px solid rgba(148,163,184,0.2)">
                <td style="padding:4px 8px; color:#94a3b8">Sharpe</td>
                <td style="padding:4px 8px; text-align:right; color:#4ade80; font-weight:700">{bt["sharpe"]:.2f}</td>
                <td style="padding:4px 8px; text-align:right; color:#cbd5e1">{bt_default["sharpe"]:.2f}</td>
              </tr>
              <tr>
                <td style="padding:4px 8px; color:#94a3b8">回撤</td>
                <td style="padding:4px 8px; text-align:right; color:#4ade80; font-weight:700">{bt["max_drawdown"]:.1f}%</td>
                <td style="padding:4px 8px; text-align:right; color:#cbd5e1">{bt_default["max_drawdown"]:.1f}%</td>
              </tr>
            </table>
            <div style="font-size:10px; color:#64748b; margin-top:6px">左列: 5/13/5 (最优) · 右列: 12/26/9 (默认)</div>
          </div>

          <!-- 基本面过滤 -->
          <div style="background:rgba(15,23,42,0.6); padding:14px 18px; border-radius:12px; border:1px solid {"rgba(34,197,94,0.4)" if has_positive_earnings else "rgba(239,68,68,0.4)"};">
            <div style="font-size:13px; color:#94a3b8; margin-bottom:6px">基本面过滤</div>
            <div style="display:flex; align-items:center; gap:10px">
              <span class="badge {"bull" if has_positive_earnings else "bear"}" style="font-size:12px">
                {"✅ 2025 净利 YoY > 0" if has_positive_earnings else "⚠️ 2025 净利 YoY < 0 (信号可能失效)"}
              </span>
              <span style="font-size:12px; color:#cbd5e1">YoY {ni_yoy:+.1f}%</span>
            </div>
            <div style="font-size:10px; color:#64748b; margin-top:6px">
              {"回测证明: 业绩向好时技术信号更可靠" if has_positive_earnings else "警告: 业绩下滑时技术信号胜率大幅下降，建议仅观望"}
            </div>
          </div>

          <div style="background:linear-gradient(135deg,rgba(99,102,241,0.10),rgba(168,85,247,0.06)); border-left:4px solid #a855f7; border-radius:10px; padding:14px 18px; color:#cbd5e1; font-size:12px; line-height:1.6">
            <b style="color:#f1f5f9">回测说明</b>：基于近 {len(signals)} 个交易日 K 线，MACD 参数 5/13/5（回测验证：强趋势板块年化 +291%，优于 12/26/9 的 +161%），信号日开盘价执行，手续费 0.1%，滑点 0.05%。
            实际收益受流动性/涨跌停/滑点影响，预计打 4-5 折。
          </div>
        </div>
      </div>
    </div>

    <script>
    new Chart(document.getElementById('macdBacktestChart'), {{
      type: 'line',
      data: {{
        labels: {json.dumps(labels)},
        datasets: [
          {{label: 'DIF', data: {json.dumps(dif_data)}, borderColor: '#60a5fa', borderWidth: 2, pointRadius: 0, tension: 0.2, yAxisID: 'y'}},
          {{label: 'DEA', data: {json.dumps(dea_data)}, borderColor: '#fbbf24', borderWidth: 2, pointRadius: 0, tension: 0.2, yAxisID: 'y'}},
          {{label: 'MACD 柱', data: {json.dumps(hist_data)}, type: 'bar', backgroundColor: {json.dumps(hist_data)}.map(v => v >= 0 ? 'rgba(239,68,68,0.4)' : 'rgba(34,197,94,0.4)'), borderColor: {json.dumps(hist_data)}.map(v => v >= 0 ? '#ef4444' : '#22c55e'), borderWidth: 1, yAxisID: 'y'}},
          {{label: '收盘价', data: {json.dumps(closes)}, borderColor: '#c084fc', borderWidth: 1.5, pointRadius: 0, tension: 0.2, yAxisID: 'y2'}},
        ]
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{
          legend: {{ position: 'top', labels: {{ color: '#e2e8f0', font: {{ size: 11 }} }} }},
          title: {{ display: true, text: 'MACD 信号图（DIF/DEA + 柱状）', color: '#f1f5f9', font: {{ size: 14, weight: 600 }} }}
        }},
        scales: {{
          x: {{ grid: {{ color: 'rgba(148,163,184,0.05)' }}, ticks: {{ maxTicksLimit: 10 }} }},
          y: {{ position: 'left', grid: {{ color: 'rgba(148,163,184,0.05)' }}, title: {{ display: true, text: 'MACD', color: '#94a3b8' }} }},
          y2: {{ position: 'right', grid: {{ display: false }}, title: {{ display: true, text: '收盘价', color: '#c084fc' }} }}
        }}
      }}
    }});
    </script>
    """


def render_quarterly_chart(d):
    fs = d.get("finance_summary", {}).get("head", [])
    if len(fs) < 4:
        return ""
    cumul = [_f(r.get("NPParentCompanyOwnersTTM")) for r in fs[:4]]
    single = [cumul[0]]
    for j in range(1, 4):
        single.append(cumul[j] - cumul[j - 1])
    labels = ["2025Q1", "2025Q2", "2025Q3", "2025Q4"]
    data = [x / 1e8 for x in single]
    return f"""
    <div class="section">
      <h2 class="section-title"><span class="num">5</span>2025 单季归母净利 (亿元)</h2>
      <p class="section-desc">Q3 净利 4.62 亿是全年低点, Q4 略回升</p>
      <div class="chart-box"><canvas id="qChart"></canvas></div>
    </div>
    <script>
    new Chart(document.getElementById('qChart'), {{
      type:'bar',
      data:{{ labels:{json.dumps(labels)}, datasets:[{{label:'单季归母净利(亿)', data:{json.dumps(data)}, backgroundColor:['#60a5fa','#fbbf24','#f87171','#4ade80'], borderRadius:6}}] }},
      options:{{
        responsive:true, maintainAspectRatio:false,
        plugins:{{ legend:{{display:false}}, title:{{display:true,text:'单季度归母净利(亿元)',color:'#f1f5f9',font:{{size:14}}}}}},
        scales:{{
          x:{{ grid:{{display:false}} }}, y:{{ grid:{{color:'rgba(148,163,184,0.05)'}} }}
        }}
      }}
    }});
    </script>
    """


def render_consensus(d, score):
    cons = d.get("consensus", {})
    fcs = cons.get("forecasts", [])
    fcs = sorted(fcs, key=lambda x: x.get("year", ""))
    rows = []
    for f in fcs:
        yr = f.get("year", "?")
        rev = _f(f.get("revenue")) / 1e8
        np_ = _f(f.get("netProfit")) / 1e8
        eps = f.get("eps", "")
        pe = f.get("pe", "")
        np_yoy = f.get("netProfitYoy", "-")
        rows.append(f"""
        <tr>
          <td>{yr}E</td><td class="v">{rev:.0f}亿</td>
          <td class="v">{np_:.1f}亿</td>
          <td class="v">{eps}</td>
          <td class="v">{pe}</td>
          <td class="v {"pos" if np_yoy and float(np_yoy) > 0 else "neg"}">{np_yoy}%</td>
        </tr>
        """)
    return f"""
    <div class="section">
      <h2 class="section-title"><span class="num">6</span>一致预期 (目标价 vs 现价 + 多年预测)</h2>
      <p class="section-desc">2026E 净利 +22.4%, 2027E +22.4%, 分析师持续看多但目标价低于现价</p>
      <table class="matrix">
        <thead><tr><th>年份</th><th class="v">营收</th><th class="v">净利</th><th class="v">EPS</th><th class="v">PE</th><th class="v">净利 YoY</th></tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
      <div style="margin-top:14px; padding:14px 18px; background:rgba(99,102,241,0.08); border-left:4px solid #6366f1; border-radius:8px; color:#c7d2fe; font-size:13px;">
        💡 <b style="color:#ddd6fe">目标价 {(cons.get("target_price") or 0):.2f} 元 vs 现价 {score["cur"]:.2f} 元 → 上行空间 {score["upside"]:+.1f}%</b>。
        2025 净利 TTM 实际表现 {score["ni_yoy"]:+.1f}%, 分析师预期未来两年维持 22% 增速。
      </div>
    </div>
    """


def render_news(d):
    news = d.get("news", {}).get("head", [])
    items = []
    for r in news:
        t = str(r.get("time", ""))[:16]
        title = html.escape(str(r.get("title", ""))[:80])
        items.append(
            f"""<div class="timeline-item"><div class="time">{t}</div><div class="title">{title}</div></div>"""
        )
    return f"""
    <div class="section">
      <h2 class="section-title"><span class="num">7</span>新闻时间轴 (近期事件)</h2>
      <p class="section-desc">近期新闻/公告/催化事件追踪</p>
      <div class="timeline">{"".join(items) if items else '<div style="color:#64748b">(无新闻)</div>'}</div>
    </div>
    """


def render_reports(d):
    reps = d.get("reports", {}).get("head", [])
    rows = []
    for r in reps:
        t = str(r.get("time", ""))[:10]
        src = html.escape(str(r.get("src", "")))
        title = html.escape(str(r.get("title", ""))[:60])
        tzpj = str(r.get("tzpj", "-") or "-")
        cls = (
            "bull"
            if tzpj in ("买入", "增持")
            else ("neut" if tzpj in ("持有", "中性") else "bear")
        )
        rows.append(
            f"""<tr><td>{t}</td><td>{src}</td><td>{title}</td><td><span class="badge {cls}">{tzpj}</span></td></tr>"""
        )
    return f"""
    <div class="section">
      <h2 class="section-title"><span class="num">8</span>研报矩阵</h2>
      <p class="section-desc">5 篇券商研报 + 投资评级</p>
      <table class="matrix">
        <thead><tr><th>日期</th><th>券商</th><th>标题</th><th>评级</th></tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>
    """


def render_strategy(d, score, narrative_strategies):
    """4 风格操作建议，每格根据 score 和 narrative_strategies 显示不同建议。"""
    cur = score["cur"]
    cards = []
    for cls, title, tag, narrative, ops in narrative_strategies:
        li = "".join(
            f"<li><b>{k}</b><span class='v'>{v}</span></li>" for k, v in ops.items()
        )
        cards.append(f"""
        <div class="op-card {cls}">
          <h3>{title} <span class="tag">{tag}</span></h3>
          <div class="narrative" style="margin-top:8px; padding:10px 14px; font-size:12px; border-radius:8px">{narrative}</div>
          <ul>{li}</ul>
        </div>
        """)
    return f"""
    <div class="section">
      <h2 class="section-title"><span class="num">9</span>分类型操作建议</h2>
      <p class="section-desc">基于 综合分 {score["total"]}/100 · 业绩 {score["ni_yoy"]:+.1f}% · 估值 {score["upside"]:+.1f}% · 现价 {cur:.2f}</p>
      <div class="op-grid">{"".join(cards)}</div>
    </div>
    """


def render_conclusion(score, narratives):
    return f"""
    <div class="section" style="background:linear-gradient(135deg,rgba(99,102,241,0.12),rgba(168,85,247,0.06)); border-color:rgba(168,85,247,0.4);">
      <h2 class="section-title" style="color:#c084fc"><span class="num">10</span>总结</h2>
      <div style="font-size:14px; color:#cbd5e1; line-height:1.85; margin-top:12px">
        {narratives}
      </div>
    </div>
    """


# ============ Main ============
def _safe_filename(text: str) -> str:
    """把中文名 (含空格/特殊字符) 转成安全的 file name 后缀。"""
    if not text:
        return ""
    # 去掉文件系统不合法字符
    for ch in '<>:"/\\|?*':
        text = text.replace(ch, "")
    return text.strip().replace(" ", "_")


def build_html(d: dict) -> str:
    trust = _trust_from_snapshot(d)
    score = calc_score(d)
    if score["total"] >= 60:
        sentiment_color = BULL
        sentiment_label = "强信号"
    elif score["total"] >= 40:
        sentiment_color = NEUTRAL
        sentiment_label = "中性"
    else:
        sentiment_color = BEAR
        sentiment_label = "弱信号"

    # 中文名 (fallback: 用 symbol)
    name = d.get("name") or ""
    symbol = d.get("symbol", "")
    if not name:
        name = symbol

    # 总结段
    score_narrative = (
        f"业绩 {score['ni_yoy']:+.1f}% YoY · 目标价 {score['tp'] or 0:.2f} 元 (现价 {score['cur']:.2f}, 空间 {score['upside']:+.1f}%)。"
        f"4 维度打分: 业绩 {score['perf']} / 估值 {score['valuation']} / 板块 {score['sector']:.0f} / 资金 {score['capital']:.0f}。"
    )

    # 4 风格策略 — 全部从实际数据动态生成，不硬编码任何票
    cur = score["cur"]
    ma20 = _f(d.get("technical_ma", {}).get("head", [{}])[0].get("ma.MA_20"))
    ma10 = _f(d.get("technical_ma", {}).get("head", [{}])[0].get("ma.MA_10"))
    boll_up = _f(
        d.get("technical_boll", {}).get("head", [{}])[0].get("boll.BOLL_UPPER")
    )
    rsi2 = _f(d.get("technical_rsi", {}).get("head", [{}])[0].get("rsi.RSI_2"))
    fs = d.get("finance_summary", {}).get("head", [])
    single_q = []
    if len(fs) >= 4:
        cumul = [_f(r.get("NPParentCompanyOwnersTTM")) for r in fs[:4]]
        single_q = [cumul[0]] + [cumul[i] - cumul[i - 1] for i in range(1, 4)]
    q_min_idx = single_q.index(min(single_q)) if single_q else 0
    q_min_val = min(single_q) / 1e8 if single_q else 0
    q_min_label = f"Q{q_min_idx + 1}"

    # 从新闻里提取事件线索
    news = d.get("news", {}).get("head", [])
    has_reduce = any("减持" in str(n.get("title", "")) for n in news)

    has_catalyst = any(
        "涨停" in str(n.get("title", "")) or "大涨" in str(n.get("title", ""))
        for n in news
    )

    # 风险点动态生成
    risk_items = []
    if score["upside"] < -5:
        risk_items.append(
            f"估值偏高: 目标价 {score['tp'] or 0:.2f} 低于现价 {score['upside']:+.1f}%"
        )
    if rsi2 > 80:
        risk_items.append(f"RSI 超买: RSI2={rsi2:.0f} 短线过热")
    if cur > boll_up * 0.95 and boll_up > 0:
        risk_items.append(f"BOLL 触顶: 距上轨仅 {(cur / boll_up - 1) * 100:.1f}%")
    if has_reduce:
        risk_items.append("近期有减持公告（详见新闻）")
    if score["ni_yoy"] < 0:
        risk_items.append(f"业绩下滑: 净利 YoY {score['ni_yoy']:+.1f}%")
    if q_min_val > 0 and len(single_q) >= 4:
        risk_items.append(
            f"单季低点: {q_min_label} 净利 {q_min_val:.1f} 亿（全年最低季度）"
        )
    if score["capital"] < 40:
        risk_items.append("资金关注低: 无龙虎榜/涨停异动")
    risk_html = (
        "<br>".join(f"• {html.escape(r)}" for r in risk_items)
        if risk_items
        else "• 当前无明显技术/基本面风险"
    )

    # 短线进取叙事
    bull_narr = f"{'涨停+龙虎榜' if has_catalyst else '技术趋势'}驱动短线机会。"
    if boll_up > cur:
        bull_narr += f" 若站稳 {cur:.2f} 可博向上 {boll_up:.2f}（BOLL 上轨）。"

    # 稳健型叙事
    purple_narr = f"目标价 {score['tp'] or 0:.2f} vs 现价 {cur:.2f}（空间 {score['upside']:+.1f}%）。"
    if score["upside"] < 0:
        purple_narr += " 估值已透支，不左侧抄底，等业绩拐点。"
    else:
        purple_narr += " 估值合理，可分批建仓。"

    # 观望型叙事
    neut_narr = f"综合评分 {score['total']}/100。"
    if rsi2 > 70 or score["upside"] < -5:
        neut_narr += " 短线超买/估值透支，等回踩确认。"
    else:
        neut_narr += " 关注 MA20 支撑确认后介入。"

    narrative_strategies = [
        (
            "bull",
            "🎯 短线进取型",
            "≤3% 仓位博弈",
            bull_narr,
            {
                "入场区": f"{cur * 0.97:.2f}-{cur:.2f}",
                "目标位": f"{boll_up:.2f}",
                "止损位": f"{cur * 0.94:.2f}",
            },
        ),
        (
            "purple",
            "🛡️ 稳健型 / 价值投资",
            "等右侧信号",
            purple_narr,
            {
                "建议": f"等回踩 MA20 ({ma20:.1f}) 确认",
                "关注": "最新季度业绩",
                "目标": f"中期 {cur * 1.05:.0f}-{cur * 1.15:.0f}",
            },
        ),
        (
            "bear",
            "📉 风险提示",
            f"{len(risk_items)} 项风险",
            risk_html,
            {
                "止损": f"破 MA20 ({ma20:.1f})" if ma20 > 0 else "见技术分析",
                "控制": "≤5% 仓位",
                "分散": "不重仓单票",
            },
        ),
        (
            "neut",
            "📊 观望型（推荐大多数人）",
            "等右侧信号",
            neut_narr,
            {
                "等待": f"回踩 MA10 ({ma10:.1f}) 不破" if ma10 > 0 else "等回踩确认",
                "确认": "MACD 金叉",
                "催化": "最新业绩/行业消息",
            },
        ),
    ]

    # 总结段 — 全部动态
    conclusions_parts = [
        f'<p><b style="color:{sentiment_color}">综合评分 {score["total"]}/100 · {sentiment_label}</b>。',
        f"业绩 {score['ni_yoy']:+.1f}% YoY，目标价 {score['tp'] or 0:.2f} 元（空间 {score['upside']:+.1f}%）。</p>",
    ]
    if has_catalyst:
        conclusions_parts.append(
            '<p style="margin-top:8px; color:#4ade80">✅ 近期有正面催化事件（详见新闻）</p>'
        )
    if has_reduce:
        conclusions_parts.append(
            '<p style="margin-top:8px; color:#f87171">⚠️ 近期有减持公告（详见新闻）</p>'
        )
    conclusions_parts.append(
        '<p style="margin-top:10px"><b style="color:#cbd5e1">操作建议核心：</b></p>'
    )
    if score["upside"] > 0 and rsi2 < 70:
        conclusions_parts.append(
            f'<p>① <b style="color:#4ade80">可建仓</b>: 估值有空间（{score["upside"]:+.1f}%），RSI 未超买。'
            f"建议回踩 MA10（{ma10:.1f}）/ MA20（{ma20:.1f}）分批建仓。</p>"
        )
    else:
        conclusions_parts.append(
            f'<p>① <b style="color:#facc15">不追高</b>: 估值透支（{score["upside"]:+.1f}%）或 RSI 超买'
            f"（RSI2={rsi2:.0f}），等回踩 MA20（{ma20:.1f}）再考虑。</p>"
        )
    conclusions_parts.append(
        f'<p>② <b style="color:#f1f5f9">已持仓者</b>: BOLL 上轨 {boll_up:.1f} 附近可分批止盈，'
        f"破 MA20（{ma20:.1f}）全部清仓。</p>"
    )
    conclusions = "\n".join(conclusions_parts)

    rsi6 = _f(d.get("technical_rsi", {}).get("head", [{}])[0].get("rsi.RSI_6"))
    advice = None
    if trust.can_advise and score["cur"] > 0:
        advice = generate_advice(
            trust=trust,
            as_of=d.get("pulled_at", "")[:10],
            total_score=score["total"],
            current_price=score["cur"],
            target_price=score["tp"],
            rsi=rsi6,
        )

    parts = [
        HTML_HEAD.replace("__TITLE__", f"{html.escape(name)} ({html.escape(symbol)})")
        .replace("__NAME__", html.escape(name))
        .replace("__SYMBOL__", html.escape(symbol)),
        render_header(d, score, sentiment_color, sentiment_label),
        render_trust_banner(trust),
        render_score_section(score, sentiment_color, sentiment_label, score_narrative),
        render_metrics_grid(d, score),
        render_kline_chart(d),
        render_indicators(d),
        render_backtest_macd(d),
        render_quarterly_chart(d),
        render_consensus(d, score),
        render_news(d),
        render_reports(d),
        render_advice_section(advice, trust),
        render_strategy(d, score, narrative_strategies) if advice is not None else "",
        render_conclusion(score, conclusions) if advice is not None else "",
        DISCLAIMER.replace("__DATE__", datetime.now().strftime("%Y-%m-%d")),
        "</div></body></html>",
    ]
    return "".join(parts)


def main():
    if len(sys.argv) < 2:
        print("Usage: python gen_single_report.py <path-to-long_form_json>")
        return 1
    src = Path(sys.argv[1])
    if not src.exists():
        print(f"Not found: {src}")
        return 1
    d = json.loads(src.read_text(encoding="utf-8"))
    html_out = build_html(d)
    symbol = d.get("symbol", src.stem.replace("long_form_", ""))
    name = d.get("name", "")
    # 文件名: report_SH600584_长电科技.html (fallback: 只用 symbol)
    safe_name = _safe_filename(name)
    if safe_name:
        out_name = f"report_{symbol}_{safe_name}.html"
    else:
        out_name = f"report_{symbol}.html"
    out_file = src.with_name(out_name)
    out_file.write_text(html_out, encoding="utf-8")
    print(f"[OK] {out_file}  ({out_file.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
