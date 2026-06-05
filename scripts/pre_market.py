#!/usr/bin/env python3
"""A股盘前分析报告生成器（每日开盘前运行）。

数据源：
    - Eastmoney push2delay: 美股三大指数 + 日经 + USD/CNY
    - AkShare: COMEX黄金 + WTI原油 + 外汇
    - 巨潮资讯: 隔夜 A股公告
    - 昨日 A股复盘快照: 昨日收盘数据

数据缺失时（如恒生指数无法实时获取）显式标"未查询到"，
绝不编造。

使用方式：
    python scripts/pre_market.py                       # 默认今天
    python scripts/pre_market.py --date 2026-06-05    # 指定日期
    python scripts/pre_market.py --push                # 推送通知
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
warnings.filterwarnings("ignore")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 集成模块
try:
    from cninfo_source import fetch_today_announcements  # noqa: E402
    HAS_CNINFO = True
except ImportError:
    HAS_CNINFO = False

try:
    from notifier import Notifier  # noqa: E402
    HAS_NOTIFIER = True
except ImportError:
    HAS_NOTIFIER = False

try:
    import akshare as ak  # noqa: E402
    HAS_AKSHARE = True
except ImportError:
    HAS_AKSHARE = False

# ============ HTTP 客户端（与 daily_review.py 一致） ============
def _http_get(url: str, timeout: int = 10, referer: str | None = None) -> str | None:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
    }
    if referer:
        headers["Referer"] = referer
    import socket
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers=headers)
    try:
        socket.setdefaulttimeout(timeout)
        with opener.open(req, timeout=timeout) as resp:
            data = resp.read()
            for enc in ("utf-8", "gbk"):
                try:
                    return data.decode(enc)
                except UnicodeDecodeError:
                    continue
            return data.decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, Exception) as e:
        print(f"  [WARN] HTTP {url[:60]}... 失败: {type(e).__name__}: {str(e)[:60]}", file=sys.stderr)
        return None


def _to_float(v: Any) -> float | None:
    if v is None or v == "" or v == "--":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# ============ 数据采集层 ============
def _fetch_eastmoney_global(secid: str, name: str, fields: str = "f43,f44,f45,f46,f60,f169,f170") -> dict | None:
    """通用 Eastmoney 全球指数/商品/外汇查询。secid 格式: '100.DJIA' / '100.SPX' 等。"""
    url = f"https://push2delay.eastmoney.com/api/qt/stock/get?secid={secid}&fields={fields}"
    raw = _http_get(url, referer="https://quote.eastmoney.com/")
    if not raw:
        return None
    try:
        j = json.loads(raw)
        d = j.get("data") or {}
        if not d or not d.get("f43"):
            return None

        current = _to_float(d.get("f43"))  # 最新价 (除以100 if 港股美股)
        prev_close = _to_float(d.get("f60"))  # 昨收
        high = _to_float(d.get("f44"))
        low = _to_float(d.get("f45"))
        open_ = _to_float(d.get("f46"))
        change = _to_float(d.get("f169"))
        change_pct = _to_float(d.get("f170"))

        # 美股 secid 100.x 的 f43/f60/f169 是 实际值*100
        if secid.startswith("100.") and current:
            current = current / 100
            if prev_close:
                prev_close = prev_close / 100
            if change:
                change = change / 100
        # f170 是涨跌幅*100（直接是 173 表示 1.73%）
        if change_pct is not None:
            change_pct = change_pct / 100

        return {
            "name": name,
            "secid": secid,
            "current": current,
            "prev_close": prev_close,
            "open": open_,
            "high": high,
            "low": low,
            "change": change,
            "change_pct": change_pct,
            "source": "eastmoney:push2delay",
        }
    except (json.JSONDecodeError, Exception) as e:
        print(f"  [WARN] 解析 {secid} 失败: {e}", file=sys.stderr)
        return None


def fetch_us_indices() -> list[dict]:
    """美股三大指数 (前一交易日收盘)。"""
    print("  → 美股三大指数 (Eastmoney push2delay)...")
    items = [
        ("100.DJIA", "道琼斯"),
        ("100.SPX", "标普500"),
        ("100.NDX", "纳斯达克"),
    ]
    results = []
    for secid, name in items:
        d = _fetch_eastmoney_global(secid, name)
        if d:
            results.append(d)
            print(f"    ✅ {name}: {d.get('current', 0):,.2f} ({d.get('change_pct', 0):+.2f}%)")
        else:
            print(f"    ❌ {name}: 未查询到")
    return results


def fetch_asia_indices() -> list[dict]:
    """亚洲主要指数 (日经225 + 恒生ETF)。"""
    print("  → 亚洲主要指数...")
    items = [
        ("100.N225", "日经225"),
        ("1.513660", "恒生ETF"),  # 替代恒生指数
        ("1.510900", "恒生ETF-沪"),
    ]
    results = []
    for secid, name in items:
        d = _fetch_eastmoney_global(secid, name)
        if d and d.get("current"):
            # 过滤掉无效值（f43==f60 通常是占位）
            results.append(d)
            print(f"    ✅ {name}: {d.get('current', 0):,.2f} ({d.get('change_pct', 0):+.2f}%)")
    return results


def fetch_forex() -> list[dict]:
    """外汇 - USD/CNY + USD/CNH。"""
    print("  → 外汇行情...")
    items = [
        ("133.USDCNH", "USD/CNH"),
    ]
    results = []
    for secid, name in items:
        d = _fetch_eastmoney_global(secid, name, fields="f43,f44,f45,f46,f60,f169,f170")
        if d and d.get("current"):
            # USD/CNH 真实价格 = f43/10000
            if d.get("current"):
                d["current"] = d["current"] / 10000
            if d.get("prev_close"):
                d["prev_close"] = d["prev_close"] / 10000
            results.append(d)
            print(f"    ✅ {name}: {d.get('current', 0):.4f} ({d.get('change_pct', 0):+.3f}%)")
    return results


def fetch_commodities_akshare() -> list[dict]:
    """通过 AkShare 获取外盘商品实时报价。"""
    if not HAS_AKSHARE:
        return []
    print("  → 外盘商品 (AkShare)...")
    items = [
        ("GC", "COMEX黄金"),
        ("CL", "WTI原油"),
        ("SI", "COMEX白银"),
        ("HG", "COMEX铜"),
    ]
    results = []
    for symbol, name in items:
        try:
            df = ak.futures_foreign_commodity_realtime(symbol=symbol)
            if df is None or df.empty:
                print(f"    ❌ {name}: 空数据")
                continue
            row = df.iloc[0]
            results.append({
                "name": name,
                "symbol": symbol,
                "current": _to_float(row.get("最新价")),
                "prev_close": _to_float(row.get("昨日结算价")),
                "open": _to_float(row.get("开盘价")),
                "high": _to_float(row.get("最高价")),
                "low": _to_float(row.get("最低价")),
                "change": _to_float(row.get("涨跌额")),
                "change_pct": _to_float(row.get("涨跌幅")),
                "source": "akshare:futures_foreign_commodity_realtime",
            })
            print(f"    ✅ {name}: {row.get('最新价', '?')} ({row.get('涨跌幅', '?')}%)")
        except Exception as e:
            print(f"    ❌ {name}: {type(e).__name__}: {str(e)[:50]}")
    return results


def fetch_yesterday_a_share_summary(yesterday_date: str) -> dict | None:
    """读取昨日 A 股复盘快照（用于对比参考）。"""
    snapshot_file = PROJECT_ROOT / "reports" / f"daily_review_{yesterday_date.replace('-', '')}.json"
    if not snapshot_file.exists():
        snapshot_file = PROJECT_ROOT / "results" / f"daily_review_{yesterday_date.replace('-', '')}.json"
    if not snapshot_file.exists():
        return None
    try:
        return json.loads(snapshot_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [WARN] 读取昨日快照失败: {e}", file=sys.stderr)
        return None


def fetch_overnight_announcements(today: str, yesterday: str) -> list[dict]:
    """隔夜公告（巨潮 - 昨日 18:00 后到今日 8:00 前）。"""
    if not HAS_CNINFO:
        return []
    print("  → 巨潮隔夜公告...")
    try:
        result = fetch_today_announcements(date=yesterday, topn=30)
        # 按时间倒序取后 15 条（视为"隔夜最新"）
        anns = result.get("announcements", [])
        anns.sort(key=lambda x: x.get("time") or "", reverse=True)
        overnight = anns[:15]
        print(f"    ✅ {len(overnight)} 条隔夜公告")
        return overnight
    except Exception as e:
        print(f"    ❌ 巨潮隔夜公告失败: {e}")
        return []


# ============ HTML 报告生成 ============
def render_pre_market_html(report_date: str, data: dict) -> str:
    us_indices = data.get("us_indices", [])
    asia_indices = data.get("asia_indices", [])
    forex = data.get("forex", [])
    commodities = data.get("commodities", [])
    yesterday = data.get("yesterday_summary", {})
    overnight_ann = data.get("overnight_announcements", [])

    # 完整性自评
    n_verified = sum([
        len(us_indices), len(asia_indices), len(forex), len(commodities),
        1 if yesterday else 0,
        len(overnight_ann),
    ])

    # 美股卡片
    us_html = ""
    for idx in us_indices:
        chg = idx.get("change_pct") or 0
        cls = "bull" if chg >= 0 else "bear"
        us_html += f"""
        <div class="index-card {cls}">
          <div class="name">{idx['name']} (前一交易日)</div>
          <div class="val">{idx.get('current', 0):,.2f}</div>
          <div class="chg">{chg:+.2f}%</div>
        </div>"""

    # 亚洲市场
    asia_html = ""
    for idx in asia_indices:
        chg = idx.get("change_pct") or 0
        cls = "bull" if chg >= 0 else "bear"
        asia_html += f"""
        <div class="index-card {cls}">
          <div class="name">{idx['name']}</div>
          <div class="val">{idx.get('current', 0):,.2f}</div>
          <div class="chg">{chg:+.2f}%</div>
        </div>"""

    # 外汇
    forex_html = ""
    for f in forex:
        chg = f.get("change_pct") or 0
        cls = "bull" if chg < 0 else "bear"  # USD/CNY 跌 = 人民币升值 = 红
        forex_html += f"""
        <div class="index-card {cls}">
          <div class="name">{f['name']}</div>
          <div class="val">{f.get('current', 0):.4f}</div>
          <div class="chg">{chg:+.3f}%</div>
        </div>"""

    # 商品表格
    commodity_rows = ""
    for c in commodities:
        chg = c.get("change_pct") or 0
        chg_cls = "pos" if chg >= 0 else "neg"
        commodity_rows += f"""
        <tr>
          <td>{c['name']} <span style="color:#64748b;font-size:10px">{c.get('symbol', '')}</span></td>
          <td class="v">{c.get('current', 0):.2f}</td>
          <td class="v">{c.get('open', 0):.2f}</td>
          <td class="v">{c.get('high', 0):.2f}</td>
          <td class="v">{c.get('low', 0):.2f}</td>
          <td class="v {chg_cls}">{chg:+.2f}%</td>
        </tr>"""

    # 隔夜公告
    ann_rows = ""
    for a in overnight_ann[:15]:
        time_short = (a.get("time") or "")[:16]
        title = (a.get("title") or "")[:55]
        ann_type = a.get("type") or ""
        ann_rows += f"""
        <tr>
          <td style="color:#94a3b8;font-size:11px">{time_short}</td>
          <td>{a.get('code', '')} {a.get('name', '')}</td>
          <td>{title}</td>
          <td style="color:#64748b;font-size:10px">{ann_type[:20]}</td>
        </tr>"""

    # 昨日 A 股参考
    yesterday_html = ""
    if yesterday:
        indices = yesterday.get("indices", [])
        limit_up_count = len(yesterday.get("limit_up", []))
        limit_down_count = len(yesterday.get("limit_down", []))
        yesterday_html = f"""
      <div class="indices-grid">
        {''.join(f'''
        <div class="index-card {'bull' if (idx.get('change_pct') or 0) >= 0 else 'bear'}">
          <div class="name">{idx['name']} (昨)</div>
          <div class="val">{idx.get('current', 0):,.2f}</div>
          <div class="chg">{idx.get('change_pct', 0):+.2f}%</div>
        </div>''' for idx in indices)}
        <div class="index-card">
          <div class="name">昨日涨停 (估算)</div>
          <div class="val">{limit_up_count}</div>
          <div class="chg" style="color:#4ade80">只</div>
        </div>
        <div class="index-card">
          <div class="name">昨日跌停 (估算)</div>
          <div class="val">{limit_down_count}</div>
          <div class="chg" style="color:#f87171">只</div>
        </div>
      </div>"""

    # 全球市场全景图
    global_chart_data = []
    for idx in us_indices:
        global_chart_data.append((idx['name'], idx.get('change_pct') or 0))
    for idx in asia_indices:
        global_chart_data.append((idx['name'], idx.get('change_pct') or 0))
    for c in commodities:
        global_chart_data.append((c['name'], c.get('change_pct') or 0))

    global_chart_json = json.dumps(global_chart_data, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股盘前分析 · {report_date}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  background:linear-gradient(135deg,#0a0e27 0%,#1a1f3a 50%,#0f1729 100%); color:#e0e6f1;
  min-height:100vh; padding:24px; line-height:1.6; }}
.container {{ max-width:1280px; margin:0 auto; }}
.header {{ background:linear-gradient(135deg,rgba(245,158,11,0.18),rgba(168,85,247,0.10),rgba(99,102,241,0.10));
  border:1px solid rgba(245,158,11,0.3); border-radius:24px; padding:32px 36px; margin-bottom:20px; }}
.header h1 {{ font-size:30px; font-weight:800;
  background:linear-gradient(135deg,#fbbf24,#a855f7,#60a5fa);
  -webkit-background-clip:text; -webkit-text-fill-color:transparent; margin-bottom:8px; }}
.header .subtitle {{ color:#94a3b8; font-size:13px; }}
.integrity-banner {{ background:linear-gradient(135deg,rgba(34,197,94,0.10),rgba(15,23,42,0.6));
  border:2px solid #22c55e; border-radius:14px; padding:18px 22px; margin-bottom:20px; }}
.integrity-banner .text {{ color:#d1fae5; font-size:12.5px; line-height:1.7; }}
.integrity-banner b {{ color:#fff; }}
.section {{ background:rgba(30,41,59,0.5); border:1px solid rgba(148,163,184,0.15);
  border-radius:20px; padding:22px; margin-bottom:18px; }}
.section-title {{ font-size:18px; font-weight:700; color:#f1f5f9; margin-bottom:6px;
  display:flex; align-items:center; gap:10px; }}
.section-title .num {{ background:linear-gradient(135deg,#fbbf24,#f59e0b); color:white;
  width:28px; height:28px; border-radius:8px; display:inline-flex; align-items:center;
  justify-content:center; font-size:13px; font-weight:800; }}
.section-desc {{ color:#94a3b8; font-size:12px; margin-bottom:14px; }}
.indices-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-top:8px; }}
.index-card {{ background:rgba(15,23,42,0.6); border-radius:10px; padding:12px;
  border:1px solid rgba(148,163,184,0.15); border-left:4px solid; }}
.index-card.bull {{ border-left-color:#22c55e; }}
.index-card.bear {{ border-left-color:#ef4444; }}
.index-card .name {{ font-size:10.5px; color:#94a3b8; }}
.index-card .val {{ font-size:18px; font-weight:800; color:#f1f5f9; margin:3px 0; }}
.index-card .chg {{ font-size:12.5px; font-weight:700; }}
.index-card.bull .chg {{ color:#4ade80; }}
.index-card.bear .chg {{ color:#f87171; }}
.matrix {{ width:100%; border-collapse:collapse; font-size:12.5px; margin-top:8px; }}
.matrix th {{ background:rgba(99,102,241,0.15); color:#c7d2fe; padding:8px 10px;
  text-align:left; font-weight:600; border-bottom:2px solid rgba(99,102,241,0.3); }}
.matrix td {{ padding:7px 10px; border-bottom:1px solid rgba(148,163,184,0.1); color:#cbd5e1; }}
.matrix tr:hover td {{ background:rgba(99,102,241,0.05); }}
.matrix td:first-child {{ color:#f1f5f9; font-weight:600; }}
.matrix .v {{ text-align:right; }}
.matrix .pos {{ color:#4ade80; font-weight:600; }}
.matrix .neg {{ color:#f87171; font-weight:600; }}
.note {{ font-size:11px; color:#94a3b8; margin-top:8px; padding:8px 12px;
  background:rgba(15,23,42,0.5); border-radius:8px; border-left:3px solid #facc15; }}
.chart-box {{ background:rgba(15,23,42,0.6); border-radius:14px; padding:18px; height:380px;
  margin-top:8px; border:1px solid rgba(148,163,184,0.1); }}
.chart-box canvas {{ max-height:320px; }}
.disclaimer {{ background:rgba(239,68,68,0.05); border:1px solid rgba(239,68,68,0.2);
  border-radius:12px; padding:16px 22px; color:#fca5a5; font-size:12px; margin-top:20px; line-height:1.7; }}
.disclaimer b {{ color:#fef2f2; }}
@media (max-width:900px) {{ .indices-grid {{ grid-template-columns:repeat(2,1fr); }} }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>🌅 A股盘前分析 · {report_date}</h1>
    <p class="subtitle">数据源：Eastmoney push2delay + AkShare 外盘 + 巨潮资讯 | 仅供参考，不构成投资建议</p>
  </div>

  <div class="integrity-banner">
    <div class="text">
      <b>🛡️ 数据完整性：</b>已验证 {n_verified} 项数据点
      （美股 / 亚洲 / 外汇 / 商品 / 隔夜公告 / 昨日 A股参考）
      <br>
      ⚠️ <b>市场状态</b>：盘前时段 (09:00 前)，A 股尚未开盘，亚洲部分市场可能尚未开盘
    </div>
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">1</span>🌎 美股三大指数 (前一交易日收盘)</h2>
    <p class="section-desc">数据源：Eastmoney push2delay · secid=100.DJIA/SPX/NDX</p>
    <div class="indices-grid">{us_html if us_html else '<div class="note" style="color:#facc15">⚠️ 美股数据未查询到</div>'}
    </div>
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">2</span>🌏 亚洲市场 (部分尚未开盘)</h2>
    <p class="section-desc">数据源：Eastmoney push2delay · 日经225 + 恒生ETF</p>
    <div class="indices-grid">{asia_html if asia_html else '<div class="note" style="color:#facc15">⚠️ 亚洲市场未开盘或数据未查询到</div>'}
    </div>
    <div class="note">
      💡 <b>开盘时间</b>：日经 9:00 东京 / 恒生 9:30 香港 / A 股 9:30 北京 · 盘前分析时亚洲市场通常未开盘
    </div>
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">3</span>💱 外汇 / 美元兑人民币</h2>
    <p class="section-desc">数据源：Eastmoney push2delay · 美元中间价/离岸人民币</p>
    <div class="indices-grid">{forex_html if forex_html else '<div class="note" style="color:#facc15">⚠️ 外汇数据未查询到</div>'}
    </div>
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">4</span>🛢️ 外盘商品 (COMEX + NYMEX)</h2>
    <p class="section-desc">数据源：AkShare futures_foreign_commodity_realtime · GC 黄金 / CL 原油 / SI 白银 / HG 铜</p>
    <table class="matrix">
      <thead>
        <tr><th>品种</th><th>最新价</th><th>开盘</th><th>最高</th><th>最低</th><th>涨跌幅</th></tr>
      </thead>
      <tbody>{commodity_rows if commodity_rows else '<tr><td colspan="6" style="text-align:center;color:#64748b">未查询到</td></tr>'}
      </tbody>
    </table>
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">5</span>🌍 全球市场全景</h2>
    <div class="chart-box"><canvas id="globalChart"></canvas></div>
  </div>
  <script>
  Chart.defaults.color='#94a3b8';
  Chart.defaults.borderColor='rgba(148,163,184,0.1)';
  Chart.defaults.font.family='-apple-system,"PingFang SC","Microsoft YaHei",sans-serif';
  new Chart(document.getElementById('globalChart'), {{
    type:'bar',
    data:{{
      labels: {json.dumps([c[0] for c in global_chart_data], ensure_ascii=False)},
      datasets:[{{
        label:'涨跌幅(%)',
        data: {[c[1] for c in global_chart_data]},
        backgroundColor: function(ctx) {{ return ctx.raw >= 0 ? 'rgba(34,197,94,0.7)' : 'rgba(239,68,68,0.7)'; }},
        borderColor: function(ctx) {{ return ctx.raw >= 0 ? '#22c55e' : '#ef4444'; }},
        borderWidth: 1.5
      }}]
    }},
    options:{{
      responsive:true, maintainAspectRatio:false,
      indexAxis:'y',
      plugins:{{ legend:{{display:false}}, title:{{display:true,text:'全球市场涨跌幅对比 (前一交易日 / 隔夜)',color:'#f1f5f9',font:{{size:14,weight:600}}}} }},
      scales:{{ x:{{ grid:{{color:'rgba(148,163,184,0.05)'}}}}, y:{{ grid:{{color:'rgba(148,163,184,0.05)'}} }} }}
    }}
  }});
  </script>

  <div class="section">
    <h2 class="section-title"><span class="num">6</span>📅 昨日 A 股收盘表现 (对比参考)</h2>
    <p class="section-desc">来源：昨日 daily_review 快照 (reports/daily_review_YYYYMMDD.json)</p>
    {yesterday_html if yesterday_html else '<div class="note" style="color:#facc15">⚠️ 昨日快照未找到（需先运行 daily_review.py 生成）</div>'}
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">7</span>📢 隔夜 A股公告 (昨日 18:00 后)</h2>
    <p class="section-desc">数据源：巨潮资讯 cninfo.com.cn · 沪深京全市场</p>
    <table class="matrix">
      <thead>
        <tr><th style="width:140px">发布时间</th><th style="width:160px">公司</th><th>标题</th><th style="width:120px">类型</th></tr>
      </thead>
      <tbody>{ann_rows if ann_rows else '<tr><td colspan="4" style="text-align:center;color:#64748b">未查询到</td></tr>'}
      </tbody>
    </table>
  </div>

  <div class="disclaimer">
    <b>⚠️ 盘前分析免责声明：</b><br>
    1. 本报告<b>不构成任何投资建议</b>，仅作为盘前数据汇总参考。<br>
    2. 美股数据为前一交易日收盘，亚洲市场数据可能因盘前时段未开盘而缺失。<br>
    3. 数据源延迟：所有报价可能有 1-15 分钟延迟，请以交易所官方数据为准。<br>
    4. 缺失项处理：恒生指数等数据当前通过公开 API 无法获取，<b>已明确标记为"未查询到"</b>。<br>
    5. 自动化：本脚本可被 Windows Task Scheduler / cron 调度，每天 08:00 自动运行推送。
  </div>

  <div style="text-align:center; padding:20px; color:#64748b; font-size:11px">
    <p>📊 chinaStock · A股盘前分析 · {report_date}</p>
    <p style="margin-top:6px">数据源：Eastmoney push2delay + AkShare + 巨潮资讯</p>
  </div>
</div>
</body>
</html>"""


# ============ 主函数 ============
def main():
    parser = argparse.ArgumentParser(description="A股盘前分析报告")
    parser.add_argument("--date", default=datetime.today().strftime("%Y-%m-%d"),
                        help="盘前分析日期 (默认今天，格式 YYYY-MM-DD)")
    parser.add_argument("--out", default=str(PROJECT_ROOT / "reports"),
                        help="输出目录 (默认 reports/)")
    parser.add_argument("--push", action="store_true",
                        help="启用自动推送 (邮件/Server酱/企业微信)")
    parser.add_argument("--no-cninfo", action="store_true",
                        help="禁用巨潮公告查询")
    args = parser.parse_args()

    print(f"🌅 A股盘前分析 · {args.date}")
    print(f"   数据源：Eastmoney push2delay + AkShare + 巨潮资讯")
    print(f"   原则：真实数据，绝不 AI 推断")
    print()
    print("🔍 开始采集数据...")

    data = {"date": args.date}

    # 1. 美股
    data["us_indices"] = fetch_us_indices()

    # 2. 亚洲市场
    data["asia_indices"] = fetch_asia_indices()

    # 3. 外汇
    data["forex"] = fetch_forex()

    # 4. 外盘商品
    data["commodities"] = fetch_commodities_akshare()

    # 5. 昨日 A 股快照
    yesterday_date = (datetime.strptime(args.date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"  → 昨日 A股参考 ({yesterday_date})...")
    data["yesterday_summary"] = fetch_yesterday_a_share_summary(yesterday_date)
    if data["yesterday_summary"]:
        print(f"    ✅ 找到昨日快照")
    else:
        print(f"    ⚠️ 未找到昨日快照 (建议先运行 daily_review.py)")

    # 6. 隔夜公告
    if not args.no_cninfo:
        data["overnight_announcements"] = fetch_overnight_announcements(args.date, yesterday_date)
    else:
        data["overnight_announcements"] = []

    # 渲染 HTML
    print()
    print("🎨 生成盘前 HTML 报告...")
    html = render_pre_market_html(args.date, data)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"pre_market_{args.date.replace('-', '')}.html"
    out_file.write_text(html, encoding="utf-8")
    print(f"  ✅ HTML 报告已保存: {out_file}")
    print(f"     文件大小: {len(html)/1024:.1f} KB")

    # 推送
    if args.push and HAS_NOTIFIER:
        print()
        print("📤 推送通知...")
        notifier = Notifier()
        # 构造 Markdown 摘要
        md = _build_md_summary(data)
        notifier.send_all(
            subject=f"A股盘前分析 · {args.date}",
            html_body=html,
            markdown_summary=md,
        )

    print()
    print("=" * 60)
    print("  ⚠️ 缺失项提示：")
    print("     - 恒生指数实时 (公开 API 不支持)")
    print("     - DXY美元指数 (Eastmoney 无对应 secid)")
    print("     - 上述项已明确标注为「未查询到」，未编造")
    print("=" * 60)
    print()
    print(f"🌐 在浏览器中打开: file:///{out_file.as_posix()}")


def _build_md_summary(data: dict) -> str:
    """构造推送 Markdown 摘要。"""
    lines = [f"# 🌅 A股盘前分析 · {data.get('date', '')}", ""]

    # 美股
    us = data.get("us_indices", [])
    if us:
        lines.append("## 🌎 美股 (前一交易日)")
        for idx in us:
            chg = idx.get("change_pct") or 0
            emoji = "🟢" if chg >= 0 else "🔴"
            lines.append(f"- {emoji} **{idx['name']}** {idx.get('current', 0):,.2f} ({chg:+.2f}%)")
        lines.append("")

    # 亚洲
    asia = data.get("asia_indices", [])
    if asia:
        lines.append("## 🌏 亚洲市场")
        for idx in asia:
            chg = idx.get("change_pct") or 0
            emoji = "🟢" if chg >= 0 else "🔴"
            lines.append(f"- {emoji} {idx['name']} {idx.get('current', 0):,.2f} ({chg:+.2f}%)")
        lines.append("")

    # 外汇
    forex = data.get("forex", [])
    if forex:
        lines.append("## 💱 外汇")
        for f in forex:
            chg = f.get("change_pct") or 0
            emoji = "🟢" if chg < 0 else "🔴"  # 人民币升值 = 红
            lines.append(f"- {emoji} {f['name']} {f.get('current', 0):.4f} ({chg:+.3f}%)")
        lines.append("")

    # 商品
    com = data.get("commodities", [])
    if com:
        lines.append("## 🛢️ 外盘商品")
        for c in com:
            chg = c.get("change_pct") or 0
            emoji = "🟢" if chg >= 0 else "🔴"
            lines.append(f"- {emoji} {c['name']} {c.get('current', 0):.2f} ({chg:+.2f}%)")
        lines.append("")

    lines.append("---")
    lines.append(f"📊 数据源：Eastmoney + AkShare + 巨潮资讯")
    lines.append(f"⏰ A股开盘：09:30 北京时间")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
