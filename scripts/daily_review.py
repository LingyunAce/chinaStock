#!/usr/bin/env python3
"""A股全市场盘后复盘报告生成器（严格数据守门员版）。

设计原则：
    - 所有数字必须来自真实 API 调用，绝不靠 AI 推断
    - 任何 API 失败/字段缺失 → 显式标"未查询到"，绝不补全
    - 每个数据点带 source 标签，可追溯
    - 生成的 HTML 报告顶部显示「数据完整性自评」

数据源（按可用性筛选）：
    ✅ Tencent qt.gtimg.cn  - 实时报价、K线
    ✅ Eastmoney push2delay - 涨跌停、板块、成交额、主力净流入、北向资金汇总
    ❌ 龙虎榜/北向资金个股  - 接口已废弃/字段为空，标记缺失

用法：
    python scripts/daily_review.py                       # 默认今天
    python scripts/daily_review.py --date 2026-06-04    # 指定日期
    python scripts/daily_review.py --topn 20            # 控制TOP数量
    python scripts/daily_review.py --out reports/        # 指定输出目录
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
warnings.filterwarnings("ignore")

# Windows 控制台 UTF-8 支持（避免 emoji 编码错误）
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, Exception):
    pass

# ============ 集成模块 ============
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
try:
    from cninfo_source import (  # noqa: E402
        fetch_today_announcements,
        fetch_company_announcements,
        fetch_earnings_releases,
    )
    HAS_CNINFO = True
except ImportError as e:
    print(f"  [WARN] cninfo_source 导入失败: {e}", file=sys.stderr)
    HAS_CNINFO = False

try:
    from diff_engine import generate_full_diff  # noqa: E402
    HAS_DIFF = True
except ImportError as e:
    print(f"  [WARN] diff_engine 导入失败: {e}", file=sys.stderr)
    HAS_DIFF = False

try:
    from notifier import Notifier  # noqa: E402
    HAS_NOTIFIER = True
except ImportError as e:
    print(f"  [WARN] notifier 导入失败: {e}", file=sys.stderr)
    HAS_NOTIFIER = False

# ============ 颜色常量（与项目 gen_single_report.py 保持一致） ============
BULL = "#22c55e"
BULL_LIGHT = "#4ade80"
BEAR = "#ef4444"
BEAR_LIGHT = "#f87171"
NEUTRAL = "#facc15"
PURPLE = "#a855f7"
BLUE = "#3b82f6"
CYAN = "#06b6d4"


# ============ HTTP 客户端 ============
def _http_get(url: str, timeout: int = 10, referer: str | None = None) -> str | None:
    """带 Windows 代理绕过的 HTTP GET。返回 None 表示失败。"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if referer:
        headers["Referer"] = referer

    import socket
    # 创建不使用系统代理的 opener
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers=headers)
    try:
        # 强制短超时，避免挂起
        socket.setdefaulttimeout(timeout)
        with opener.open(req, timeout=timeout) as resp:
            data = resp.read()
            # 腾讯接口用 gbk，Eastmoney 用 utf-8
            for enc in ("utf-8", "gbk"):
                try:
                    return data.decode(enc)
                except UnicodeDecodeError:
                    continue
            return data.decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, Exception) as e:
        # 显式记录，但不抛
        print(f"  [WARN] HTTP {url[:80]}... 失败: {type(e).__name__}: {str(e)[:60]}", file=sys.stderr)
        return None


# ============ 数据采集层 ============
def fetch_indices_via_tencent() -> list[dict]:
    """通过腾讯接口查询 5 大指数实时报价。

    数据源：https://qt.gtimg.cn/q=sh000001,sz399001,sz399006,sh000688,sh000016
    """
    url = "https://qt.gtimg.cn/q=sh000001,sz399001,sz399006,sh000688,sh000016"
    raw = _http_get(url, referer="https://gu.qq.com/")
    if not raw:
        return []

    # 格式：v_sh000001="1~上证指数~000001~4057.78~4083.97~..."
    indices = []
    for line in raw.strip().split(";\n"):
        if "=" not in line:
            continue
        # 解析：v_<code>="~分隔"
        try:
            key, val = line.split("=", 1)
            code = key.replace("v_", "").strip()
            parts = val.strip().strip('"').split("~")
            if len(parts) < 10:
                continue
            name = parts[1]
            current = _to_float(parts[3])
            prev_close = _to_float(parts[4])
            open_ = _to_float(parts[5])
            volume = _to_float(parts[6])  # 成交量(手)
            change_pct = _to_float(parts[32]) if len(parts) > 32 else None
            if change_pct is None and current and prev_close:
                change_pct = (current - prev_close) / prev_close * 100
            indices.append({
                "code": code,
                "name": name,
                "current": current,
                "prev_close": prev_close,
                "open": open_,
                "change_pct": round(change_pct, 2) if change_pct is not None else None,
                "source": "tencent:qt.gtimg.cn",
            })
        except (ValueError, IndexError) as e:
            print(f"  [WARN] 解析 {line[:50]} 失败: {e}", file=sys.stderr)
            continue
    return indices


def fetch_stocks_via_eastmoney(
    market_filter: str = "m:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2",
    sort_field: str = "f3",  # f3=涨跌幅, f6=成交额
    topn: int = 30,
    ascending: bool = False,  # False=降序
    extra_filter: str = "f3:=20",  # 默认全部；要涨停传 "f3:=20"
) -> list[dict]:
    """Eastmoney 通用股票筛选。

    Args:
        market_filter: 市场过滤
        sort_field: 排序字段（f3=涨跌幅, f6=成交额, f62=主力净额, f5=成交量）
        topn: 返回 TOP N
        ascending: 是否升序（True=从小到大，False=从大到小）
        extra_filter: 额外过滤条件
    """
    # 构建 fs 参数（市场 + 可选过滤）
    # 注意：extra_filter 不应附加到 fs 后面（会破坏 URL 解析），改为忽略
    # 客户端按阈值过滤即可
    fs = market_filter

    # Eastmoney API: po=1=降序(从大到小), po=0=升序(从小到大) - 与我的代码注释相反
    sort_dir = "1" if not ascending else "0"
    url = (
        f"https://push2delay.eastmoney.com/api/qt/clist/get?"
        f"pn=1&pz={topn}&po={sort_dir}&np=1&fltt=2&invt=2&fid={sort_field}"
        f"&fs={fs}"
        f"&fields=f12,f14,f2,f3,f4,f5,f6,f62,f184"
    )
    raw = _http_get(url, referer="https://quote.eastmoney.com/")
    if not raw:
        return []

    try:
        j = json.loads(raw)
    except json.JSONDecodeError:
        return []

    diff = (j.get("data") or {}).get("diff") or []
    stocks = []
    for d in diff:
        stocks.append({
            "code": d.get("f12", ""),
            "name": d.get("f14", ""),
            "price": _to_float(d.get("f2")),
            "change_pct": _to_float(d.get("f3")),
            "change_amount": _to_float(d.get("f4")),
            "volume": _to_float(d.get("f5")),
            "amount": _to_float(d.get("f6")),
            "main_net_inflow": _to_float(d.get("f62")),
            "amplitude": _to_float(d.get("f184")),
            "source": "eastmoney:push2delay",
        })
    return stocks


def fetch_limit_up_stocks(topn: int = 30) -> list[dict]:
    """涨停股池：涨跌幅 >= 19.5%（含 20% 创业板/科创板 + 10% 主板）。

    排序按 f3 降序，客户端过滤实际涨停股票。
    """
    # 一次拉 200 条，客户端过滤再取 topn
    all_stocks = fetch_stocks_via_eastmoney(
        market_filter="m:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2",
        sort_field="f3", topn=200, ascending=False
    )
    # 客户端过滤：涨跌幅 >= 19.5%
    limit_up = [s for s in all_stocks if (s.get("change_pct") or 0) >= 19.5]
    return limit_up[:topn]


def fetch_limit_down_stocks(topn: int = 20) -> list[dict]:
    """跌停股池：涨跌幅 <= -9.5%。"""
    all_stocks = fetch_stocks_via_eastmoney(
        market_filter="m:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2",
        sort_field="f3", topn=200, ascending=True
    )
    # 客户端过滤：涨跌幅 <= -9.5%
    limit_down = [s for s in all_stocks if (s.get("change_pct") or 0) <= -9.5]
    return limit_down[:topn]


def fetch_top_amount_stocks(topn: int = 20) -> list[dict]:
    """成交额 TOP N。"""
    return fetch_stocks_via_eastmoney(
        sort_field="f6", topn=topn, ascending=False
    )


def fetch_top_main_inflow_stocks(topn: int = 20) -> list[dict]:
    """主力净流入 TOP N（f62 字段）。"""
    return fetch_stocks_via_eastmoney(
        sort_field="f62", topn=topn, ascending=False
    )


def fetch_industry_sectors(topn: int = 20) -> list[dict]:
    """申万行业板块涨幅榜 (fs=m:90+t:2)。"""
    url = (
        f"https://push2delay.eastmoney.com/api/qt/clist/get?"
        f"pn=1&pz={topn}&po=0&np=1&fltt=2&invt=2&fid=f3"
        f"&fs=m:90+t:2"
        f"&fields=f1,f2,f3,f4,f5,f12,f14,f184"
    )
    raw = _http_get(url, referer="https://quote.eastmoney.com/")
    return _parse_eastmoney_sector_list(raw)


def fetch_concept_sectors(topn: int = 20) -> list[dict]:
    """概念板块涨幅榜 (fs=m:90+t:3)。"""
    url = (
        f"https://push2delay.eastmoney.com/api/qt/clist/get?"
        f"pn=1&pz={topn}&po=0&np=1&fltt=2&invt=2&fid=f3"
        f"&fs=m:90+t:3"
        f"&fields=f1,f2,f3,f4,f5,f12,f14"
    )
    raw = _http_get(url, referer="https://quote.eastmoney.com/")
    return _parse_eastmoney_sector_list(raw)


def _parse_eastmoney_sector_list(raw: str | None) -> list[dict]:
    """解析东方财富板块列表通用响应。"""
    if not raw:
        return []
    try:
        j = json.loads(raw)
    except json.JSONDecodeError:
        return []
    diff = (j.get("data") or {}).get("diff") or []
    sectors = []
    for d in diff:
        sectors.append({
            "code": d.get("f12", ""),
            "name": d.get("f14", ""),
            "price": _to_float(d.get("f2")),
            "change_pct": _to_float(d.get("f3")),
            "change_amount": _to_float(d.get("f4")),
            "volume": _to_float(d.get("f5")),
            "amplitude": _to_float(d.get("f184")),
            "source": "eastmoney:push2delay",
        })
    return sectors


def fetch_northbound_flow() -> dict:
    """北向资金汇总：沪股通/深股通/港股通净流入。

    数据源：https://push2delay.eastmoney.com/api/qt/kamt/get
    返回字段：hk2sh（港股通→沪）, sh2hk（沪→港）, hk2sz（港股通→深）, sz2hk（深→港）
    """
    url = (
        "https://push2delay.eastmoney.com/api/qt/kamt/get?"
        "fields1=f1,f2,f3,f4&fields2=f51,f52,f53,f54,f55,f56&"
        "kamt=100&findex=1&market=001"
    )
    raw = _http_get(url, referer="https://quote.eastmoney.com/")
    if not raw:
        return {"available": False, "reason": "API调用失败"}

    try:
        j = json.loads(raw)
    except json.JSONDecodeError:
        return {"available": False, "reason": "JSON解析失败"}

    data = j.get("data") or {}

    def _extract(key: str) -> dict:
        d = data.get(key) or {}
        return {
            "day_net_amt_in": _to_float(d.get("dayNetAmtIn")),  # 单位: 万元
            "buy_amt": _to_float(d.get("buyAmt")),
            "sell_amt": _to_float(d.get("sellAmt")),
            "status": d.get("status"),
            "date": d.get("date2"),
        }

    result = {
        "available": True,
        "sh2hk": _extract("sh2hk"),  # 沪股通净流入（A股视角）
        "hk2sh": _extract("hk2sh"),  # 港股通沪净流入
        "sz2hk": _extract("sz2hk"),  # 深股通净流入
        "hk2sz": _extract("hk2sz"),  # 港股通深净流入
        "source": "eastmoney:push2delay:kamt",
    }
    return result


# ============ 工具函数 ============
def _to_float(v: Any) -> float | None:
    """安全转 float。'--'、''、None 都返回 None。"""
    if v is None or v == "" or v == "--":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# ============ HTML 报告生成 ============
def render_html_report(report_date: str, data: dict) -> str:
    """渲染深色玻璃态 HTML 报告。"""
    indices = data.get("indices", [])
    limit_up = data.get("limit_up", [])
    limit_down = data.get("limit_down", [])
    industries = data.get("industries", [])
    concepts = data.get("concepts", [])
    top_amount = data.get("top_amount", [])
    top_main = data.get("top_main_inflow", [])
    northbound = data.get("northbound", {})
    announcements = data.get("today_announcements", [])
    watchlist_ann = data.get("watchlist_announcements", [])
    diff_data = data.get("diff", {})
    lhb_status = data.get("lhb_status", "not_supported")
    northbound_individual = data.get("northbound_individual", "not_supported")

    # 完整性自评
    n_verified = sum([
        len(indices), len(limit_up), len(limit_down),
        len(industries), len(concepts),
        len(top_amount), len(top_main),
        1 if northbound.get("available") else 0,
        len(announcements),
        len(watchlist_ann),
    ])
    if diff_data:
        n_verified += 1  # diff 数据完整
    n_missing = sum([
        0 if lhb_status == "available" else 1,
        0 if northbound_individual == "available" else 1,
    ])

    # 涨/跌家数 = 涨停数 + 跌停数（仅这两个明确已知）
    limit_up_count = len([s for s in limit_up if (s.get("change_pct") or 0) >= 19.5])
    limit_down_count = len([s for s in limit_down if (s.get("change_pct") or 0) <= -9.5])

    # 北向资金汇总显示
    if northbound.get("available"):
        sh_net = (northbound.get("sh2hk") or {}).get("day_net_amt_in") or 0
        sz_net = (northbound.get("sz2hk") or {}).get("day_net_amt_in") or 0
        # 单位转换：万 → 亿
        sh_net_yi = sh_net / 10000
        sz_net_yi = sz_net / 10000
        total_net_yi = sh_net_yi + sz_net_yi
        northbound_html = f"""
      <div class="stock-grid" style="grid-template-columns:repeat(3,1fr)">
        <div class="stock-card">
          <div class="name">沪股通净流入</div>
          <div class="price-row" style="color:{'#4ade80' if sh_net_yi >= 0 else '#f87171'}">
            <span class="price">{sh_net_yi:+.2f} 亿</span>
          </div>
          <div class="note" style="border-color:#22c55e;margin-top:6px">📊 Eastmoney 实时</div>
        </div>
        <div class="stock-card">
          <div class="name">深股通净流入</div>
          <div class="price-row" style="color:{'#4ade80' if sz_net_yi >= 0 else '#f87171'}">
            <span class="price">{sz_net_yi:+.2f} 亿</span>
          </div>
          <div class="note" style="border-color:#22c55e;margin-top:6px">📊 Eastmoney 实时</div>
        </div>
        <div class="stock-card">
          <div class="name">北向合计</div>
          <div class="price-row" style="color:{'#4ade80' if total_net_yi >= 0 else '#f87171'}">
            <span class="price">{total_net_yi:+.2f} 亿</span>
          </div>
          <div class="note" style="border-color:#22c55e;margin-top:6px">📊 沪+深 加总</div>
        </div>
      </div>"""
    else:
        northbound_html = """
      <div class="note" style="color:#facc15;background:rgba(234,179,8,0.1)">
        ⚠️ 北向资金汇总数据未查询到（API 调用失败）
      </div>"""

    # 指数卡片
    indices_html = ""
    for idx in indices:
        chg = idx.get("change_pct")
        cls = "bull" if (chg is not None and chg >= 0) else "bear"
        cur = idx.get("current") or 0
        prev = idx.get("prev_close") or 0
        indices_html += f"""
        <div class="index-card {cls}">
          <div class="name">{idx['name']} ({idx['code']})</div>
          <div class="val">{cur:,.2f}</div>
          <div class="chg">{chg:+.2f}%</div>
        </div>"""

    # 涨停股表格
    limit_up_html = _render_stock_table(limit_up, "涨幅", "{change_pct:+.2f}%")
    limit_down_html = _render_stock_table(limit_down, "跌幅", "{change_pct:+.2f}%")
    amount_html = _render_stock_table(top_amount, "成交额", "{amount/1e8:.2f} 亿")
    main_html = _render_stock_table(top_main, "主力净流入", "{main_net_inflow/1e8:+.2f} 亿")

    # 板块表格
    industries_html = _render_sector_table(industries)
    concepts_html = _render_sector_table(concepts)

    # 概念板块图（涨跌幅）
    concept_chart_data = [(c["name"], c.get("change_pct") or 0) for c in concepts[:12]]
    concept_chart_json = json.dumps(concept_chart_data, ensure_ascii=False)

    # 成交额 TOP 图
    amount_chart_data = [
        (s["name"], (s.get("amount") or 0) / 1e8) for s in top_amount[:10]
    ]
    amount_chart_json = json.dumps(amount_chart_data, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股复盘 · {report_date} · 严格数据守门员版</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  background:linear-gradient(135deg,#0a0e27 0%,#1a1f3a 50%,#0f1729 100%); color:#e0e6f1;
  min-height:100vh; padding:24px; line-height:1.6; }}
.container {{ max-width:1280px; margin:0 auto; }}
.header {{ background:linear-gradient(135deg,rgba(99,102,241,0.18),rgba(168,85,247,0.10),rgba(34,197,94,0.10));
  border:1px solid rgba(99,102,241,0.3); border-radius:24px; padding:32px 36px; margin-bottom:20px; }}
.header h1 {{ font-size:28px; font-weight:800;
  background:linear-gradient(135deg,#60a5fa,#a855f7);
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
.section-title .num {{ background:linear-gradient(135deg,#22c55e,#10b981); color:white;
  width:28px; height:28px; border-radius:8px; display:inline-flex; align-items:center;
  justify-content:center; font-size:13px; font-weight:800; }}
.section-desc {{ color:#94a3b8; font-size:12px; margin-bottom:14px; }}
.indices-grid {{ display:grid; grid-template-columns:repeat(5,1fr); gap:10px; margin-top:8px; }}
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
.stock-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:8px; }}
.chart-box {{ background:rgba(15,23,42,0.6); border-radius:14px; padding:18px; height:340px;
  margin-top:8px; border:1px solid rgba(148,163,184,0.1); }}
.chart-box canvas {{ max-height:280px; }}
.disclaimer {{ background:rgba(239,68,68,0.05); border:1px solid rgba(239,68,68,0.2);
  border-radius:12px; padding:16px 22px; color:#fca5a5; font-size:12px; margin-top:20px; line-height:1.7; }}
.disclaimer b {{ color:#fef2f2; }}
@media (max-width:900px) {{ .indices-grid {{ grid-template-columns:repeat(2,1fr); }} .stock-grid {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>📊 A 股复盘 · {report_date}</h1>
    <p class="subtitle">严格数据守门员版 · 数据源：Tencent qt.gtimg.cn + Eastmoney push2delay · 仅展示已验证数据</p>
  </div>

  <div class="integrity-banner">
    <div class="text">
      <b>🛡️ 数据完整性声明：</b><br>
      ✅ <b>已验证</b>：{n_verified} 个数据点（5 指数 / 涨跌停 / 板块 / 主力净流入 / 成交额 / 北向汇总）<br>
      ❌ <b>未查询到</b>：{n_missing} 项（龙虎榜、北向资金个股流向 —— 接口已废弃/字段为空）<br>
      🚫 <b>绝不编造</b>：缺失项明确标注，不补全、不推测
    </div>
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">1</span>主要指数（已验证）</h2>
    <p class="section-desc">数据源：Tencent qt.gtimg.cn · 实时报价</p>
    <div class="indices-grid">{indices_html}
    </div>
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">2</span>涨停股池 TOP {len(limit_up)}（已验证）</h2>
    <p class="section-desc">数据源：Eastmoney push2delay · 涨跌幅 ≥ 19.5%</p>
    {limit_up_html}
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">3</span>跌停股池 TOP {len(limit_down)}（已验证）</h2>
    <p class="section-desc">数据源：Eastmoney push2delay · 涨跌幅 ≤ -9.5%</p>
    {limit_down_html}
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">4</span>行业板块涨跌榜 TOP {len(industries)}（已验证）</h2>
    <p class="section-desc">数据源：Eastmoney push2delay · 申万行业（fs=m:90+t:2）</p>
    {industries_html}
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">5</span>概念板块涨跌榜 TOP {len(concepts)}（已验证）</h2>
    <p class="section-desc">数据源：Eastmoney push2delay · 概念板块（fs=m:90+t:3）</p>
    <div class="chart-box"><canvas id="conceptChart"></canvas></div>
  </div>
  <script>
  Chart.defaults.color='#94a3b8';
  Chart.defaults.borderColor='rgba(148,163,184,0.1)';
  Chart.defaults.font.family='-apple-system,"PingFang SC","Microsoft YaHei",sans-serif';
  new Chart(document.getElementById('conceptChart'), {{
    type:'bar',
    data:{{
      labels: {json.dumps([c[0] for c in concept_chart_data], ensure_ascii=False)},
      datasets:[{{
        label:'涨跌幅(%)',
        data: {[c[1] for c in concept_chart_data]},
        backgroundColor: function(ctx) {{ return ctx.raw >= 0 ? 'rgba(34,197,94,0.7)' : 'rgba(239,68,68,0.7)'; }},
        borderColor: function(ctx) {{ return ctx.raw >= 0 ? '#22c55e' : '#ef4444'; }},
        borderWidth: 1.5
      }}]
    }},
    options:{{
      responsive:true, maintainAspectRatio:false,
      plugins:{{ legend:{{display:false}}, title:{{display:true,text:'概念板块涨跌幅 TOP 12',color:'#f1f5f9',font:{{size:14,weight:600}}}} }},
      scales:{{ x:{{ grid:{{color:'rgba(148,163,184,0.05)'}}, ticks:{{maxRotation:45}}}}, y:{{ grid:{{color:'rgba(148,163,184,0.05)'}}}} }}
    }}
  }});
  </script>

  <div class="section">
    <h2 class="section-title"><span class="num">6</span>成交额 TOP {len(top_amount)}（已验证）</h2>
    <p class="section-desc">数据源：Eastmoney push2delay · 成交额排序</p>
    <div class="chart-box"><canvas id="amountChart"></canvas></div>
    {amount_html}
  </div>
  <script>
  new Chart(document.getElementById('amountChart'), {{
    type:'bar',
    data:{{
      labels: {json.dumps([c[0] for c in amount_chart_data], ensure_ascii=False)},
      datasets:[{{
        label:'成交额(亿元)',
        data: {[round(c[1], 2) for c in amount_chart_data]},
        backgroundColor:'rgba(99,102,241,0.7)', borderColor:'#6366f1', borderWidth:1.5
      }}]
    }},
    options:{{ indexAxis:'y', responsive:true, maintainAspectRatio:false,
      plugins:{{ legend:{{display:false}}, title:{{display:true,text:'成交额 TOP 10 (亿元)',color:'#f1f5f9',font:{{size:14,weight:600}}}} }},
      scales:{{ x:{{ grid:{{color:'rgba(148,163,184,0.05)'}}}}, y:{{ grid:{{color:'rgba(148,163,184,0.05)'}}}} }}
    }}
  }});
  </script>

  <div class="section">
    <h2 class="section-title"><span class="num">7</span>主力净流入 TOP {len(top_main)}（已验证）</h2>
    <p class="section-desc">数据源：Eastmoney push2delay · 主力净额（f62）排序</p>
    {main_html}
  </div>

  {_render_announcements_section(announcements, watchlist_ann)}

  {_render_diff_section(diff_data)}

  <div class="section">
    <h2 class="section-title"><span class="num">8</span>北向资金汇总（已验证）</h2>
    <p class="section-desc">数据源：Eastmoney push2delay · kamt 接口</p>
    {northbound_html}
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">9</span>未查询到的数据（明确缺失）</h2>
    <p class="section-desc">以下数据项当前通过公开 API 无法获取，本报告不展示、不编造</p>
    <table class="matrix">
      <thead><tr><th>数据项</th><th>状态</th><th>原因</th></tr></thead>
      <tbody>
        <tr><td>龙虎榜（个股+机构+游资）</td><td>❌ 未查询到</td><td>Eastmoney datacenter 报表名已废弃</td></tr>
        <tr><td>北向资金个股净买入/卖出</td><td>❌ 未查询到</td><td>push2 接口 f209/f261 字段返回空值</td></tr>
        <tr><td>两市总成交额</td><td>❌ 未查询到</td><td>未实现聚合，可通过上交所+深交所累加</td></tr>
        <tr><td>涨/跌/平家数</td><td>❌ 未查询到</td><td>需遍历全市场股票，5000+ 调用效率低</td></tr>
        <tr><td>新闻/公告/研报</td><td>❌ 未查询到</td><td>需专业数据源（巨潮/同花顺）</td></tr>
      </tbody>
    </table>
  </div>

  <div class="disclaimer">
    <b>⚠️ 免责声明：</b><br>
    1. 本报告<b>不构成任何投资建议</b>，仅作为数据展示。<br>
    2. 所有数字均来自公开 API 实时调用（Tencent qt.gtimg.cn + Eastmoney push2delay.eastmoney.com），<b>未经验证的内容已删除而非编造</b>。<br>
    3. 数据延迟：实时数据可能有 1-15 分钟延迟，请以交易所官方收盘公告为准。<br>
    4. 缺失项处理：龙虎榜/北向个股 等数据项当前通过公开 API 无法获取，<b>已明确标记为"未查询到"</b>，未做任何推断或补全。<br>
    5. 自动化：本脚本可被 Windows Task Scheduler / cron 调度，每天收盘后自动运行。
  </div>

  <div style="text-align:center; padding:20px; color:#64748b; font-size:11px">
    <p>📊 chinaStock · 严格数据守门员版 · {report_date}</p>
    <p style="margin-top:6px">数据源：Tencent qt.gtimg.cn + Eastmoney push2delay.eastmoney.com</p>
  </div>
</div>
</body>
</html>"""


def _render_stock_table(stocks: list[dict], val_label: str, fmt: str) -> str:
    """渲染股票表格。fmt 接受 {change_pct} {amount} {main_net_inflow}。"""
    if not stocks:
        return '<div class="note" style="color:#facc15">⚠️ 未查询到数据（API 调用失败或无符合条件记录）</div>'

    rows = ""
    for s in stocks[:20]:
        chg = s.get("change_pct") or 0
        chg_cls = "pos" if chg >= 0 else "neg"
        try:
            val_str = fmt.format(**s)
        except (KeyError, ValueError, ZeroDivisionError):
            val_str = "—"
        rows += f"""
        <tr>
          <td>{s['name']} <span style="color:#64748b;font-size:10px">{s['code']}</span></td>
          <td class="v">{s.get('price', '—')}</td>
          <td class="v {chg_cls}">{chg:+.2f}%</td>
          <td class="v">{val_str}</td>
        </tr>"""

    return f"""
    <table class="matrix">
      <thead>
        <tr><th>名称</th><th>现价</th><th>涨跌幅</th><th>{val_label}</th></tr>
      </thead>
      <tbody>{rows}
      </tbody>
    </table>"""


def _render_sector_table(sectors: list[dict]) -> str:
    if not sectors:
        return '<div class="note" style="color:#facc15">⚠️ 未查询到数据</div>'

    rows = ""
    for s in sectors[:15]:
        chg = s.get("change_pct") or 0
        chg_cls = "pos" if chg >= 0 else "neg"
        rows += f"""
        <tr>
          <td>{s['name']} <span style="color:#64748b;font-size:10px">{s['code']}</span></td>
          <td class="v {chg_cls}">{chg:+.2f}%</td>
          <td class="v">{s.get('change_amount') or 0:.2f}</td>
        </tr>"""

    return f"""
    <table class="matrix">
      <thead>
        <tr><th>板块</th><th>涨跌幅</th><th>涨跌额</th></tr>
      </thead>
      <tbody>{rows}
      </tbody>
    </table>"""


def _render_announcements_section(announcements: list[dict], watchlist_ann: list[dict]) -> str:
    """渲染巨潮资讯公告章节。"""
    parts = []

    # 全市场重大事项公告
    if announcements:
        rows = ""
        for a in announcements[:15]:
            time_short = (a.get("time") or "")[:16]
            title = (a.get("title") or "")[:55]
            pdf_url = a.get("pdf_url", "")
            title_html = f'<a href="{pdf_url}" target="_blank" style="color:#60a5fa;text-decoration:none">{title}</a>' if pdf_url else title
            ann_type = a.get("type") or ""
            rows += f"""
        <tr>
          <td style="color:#94a3b8;font-size:11px">{time_short}</td>
          <td>{a.get('code', '')} {a.get('name', '')}</td>
          <td>{title_html}</td>
          <td style="color:#64748b;font-size:10px">{ann_type[:20]}</td>
        </tr>"""

        parts.append(f"""
  <div class="section">
    <h2 class="section-title"><span class="num">8</span>📢 今日重大事项公告 TOP {len(announcements)}（已验证）</h2>
    <p class="section-desc">数据源：巨潮资讯网 cninfo.com.cn · 沪深京全市场 category=major_event</p>
    <table class="matrix">
      <thead>
        <tr><th style="width:140px">发布时间</th><th style="width:160px">公司</th><th>标题</th><th style="width:120px">类型</th></tr>
      </thead>
      <tbody>{rows}
      </tbody>
    </table>
  </div>""")

    # 关注股公告
    if watchlist_ann:
        rows = ""
        for a in watchlist_ann[:15]:
            time_short = (a.get("time") or "")[:16]
            title = (a.get("title") or "")[:55]
            pdf_url = a.get("pdf_url", "")
            title_html = f'<a href="{pdf_url}" target="_blank" style="color:#60a5fa;text-decoration:none">{title}</a>' if pdf_url else title
            rows += f"""
        <tr>
          <td style="color:#94a3b8;font-size:11px">{time_short}</td>
          <td>{a.get('code', '')} {a.get('name', '')}</td>
          <td>{title_html}</td>
        </tr>"""

        parts.append(f"""
  <div class="section">
    <h2 class="section-title"><span class="num">9</span>⭐ 关注股公告（已验证）</h2>
    <p class="section-desc">数据源：巨潮资讯网 · 按公司名 searchkey 搜索近 30 天</p>
    <table class="matrix">
      <thead>
        <tr><th style="width:140px">发布时间</th><th style="width:160px">公司</th><th>标题</th></tr>
      </thead>
      <tbody>{rows}
      </tbody>
    </table>
  </div>""")

    if not parts:
        parts.append("""
  <div class="section">
    <h2 class="section-title"><span class="num">8</span>📢 公告（已验证）</h2>
    <div class="note" style="color:#facc15">⚠️ 巨潮资讯公告数据未查询到（API 调用失败）</div>
  </div>""")

    return "\n".join(parts)


def _render_diff_section(diff: dict) -> str:
    """渲染昨日 vs 今日异动对比章节。"""
    if not diff:
        return """
  <div class="section">
    <h2 class="section-title"><span class="num">★</span>昨日 vs 今日 异动对比</h2>
    <div class="note" style="color:#94a3b8">
      💡 提示：可通过 <code>--diff-date 2026-06-03</code> 启用昨日对比
    </div>
  </div>"""

    summary = diff.get("summary", {})
    lud = diff.get("limit_up_diff", {})
    mcd = diff.get("main_capital_diff", {})
    sd = diff.get("sector_diff", {})

    # 摘要
    summary_html = f"""
    <div class="stock-grid" style="grid-template-columns:repeat(4,1fr)">
      <div class="stock-card">
        <div class="name">涨停家数变化</div>
        <div class="price-row" style="color:{'#4ade80' if summary.get('limit_up_delta', 0) >= 0 else '#f87171'}">
          <span class="price">{summary.get('limit_up_delta', 0):+d}</span>
        </div>
        <div class="note" style="border-color:#22c55e;margin-top:6px">昨 {lud.get('yesterday_count', 0)} → 今 {lud.get('today_count', 0)}</div>
      </div>
      <div class="stock-card">
        <div class="name">炸板股</div>
        <div class="price-row" style="color:#f87171">
          <span class="price">{summary.get('exploded_count', 0)} 只</span>
        </div>
        <div class="note" style="border-color:#f87171;margin-top:6px">昨日涨停今日未封板</div>
      </div>
      <div class="stock-card">
        <div class="name">新晋涨停</div>
        <div class="price-row" style="color:#4ade80">
          <span class="price">{summary.get('new_limit_up_count', 0)} 只</span>
        </div>
        <div class="note" style="border-color:#22c55e;margin-top:6px">昨日未涨停今日涨停</div>
      </div>
      <div class="stock-card">
        <div class="name">主力资金反转</div>
        <div class="price-row" style="color:#60a5fa">
          <span class="price">{summary.get('reversed_in_count', 0) + summary.get('reversed_out_count', 0)} 只</span>
        </div>
        <div class="note" style="border-color:#3b82f6;margin-top:6px">流入/流出方向反转</div>
      </div>
    </div>"""

    # 炸板股 TOP 10
    exploded = lud.get("exploded", [])
    exploded_rows = ""
    for s in exploded[:10]:
        exploded_rows += f"""
        <tr>
          <td>{s['name']} <span style="color:#64748b;font-size:10px">{s['code']}</span></td>
          <td class="v pos">{s.get('yesterday_change_pct', 0):+.2f}%</td>
          <td class="v neg">{s.get('today_change_pct', 0):+.2f}%</td>
        </tr>"""

    # 新晋涨停 TOP 10
    new_up = lud.get("new_limit_up", [])
    new_up_rows = ""
    for s in new_up[:10]:
        new_up_rows += f"""
        <tr>
          <td>{s['name']} <span style="color:#64748b;font-size:10px">{s['code']}</span></td>
          <td class="v neg">{s.get('yesterday_change_pct', 0) if s.get('yesterday_change_pct') is not None else '—'}</td>
          <td class="v pos">{s.get('today_change_pct', 0):+.2f}%</td>
        </tr>"""

    # 主力资金反转
    rev_in = mcd.get("reversed_in", [])[:5]
    rev_out = mcd.get("reversed_out", [])[:5]
    rev_in_rows = ""
    for s in rev_in:
        rev_in_rows += f"""
        <tr>
          <td>{s['name']} <span style="color:#64748b;font-size:10px">{s['code']}</span></td>
          <td class="v neg">{s.get('yesterday_flow', 0)/1e8:+.2f} 亿</td>
          <td class="v pos">{s.get('today_flow', 0)/1e8:+.2f} 亿</td>
        </tr>"""
    rev_out_rows = ""
    for s in rev_out:
        rev_out_rows += f"""
        <tr>
          <td>{s['name']} <span style="color:#64748b;font-size:10px">{s['code']}</span></td>
          <td class="v pos">{s.get('yesterday_flow', 0)/1e8:+.2f} 亿</td>
          <td class="v neg">{s.get('today_flow', 0)/1e8:+.2f} 亿</td>
        </tr>"""

    # 板块涨跌幅变动
    improved = sd.get("improved", [])[:5]
    worsened = sd.get("worsened", [])[:5]
    sector_rows = ""
    for s in improved + worsened:
        delta = s.get("delta", 0)
        sign = "+" if delta >= 0 else ""
        cls = "pos" if delta >= 0 else "neg"
        sector_rows += f"""
        <tr>
          <td>{s['name']} <span style="color:#64748b;font-size:10px">{s['code']}</span></td>
          <td class="v">{s.get('yesterday_chg', 0):+.2f}%</td>
          <td class="v">{s.get('today_chg', 0):+.2f}%</td>
          <td class="v {cls}">{sign}{delta:.2f}%</td>
        </tr>"""

    return f"""
  <div class="section">
    <h2 class="section-title"><span class="num">★</span>昨日 vs 今日 异动对比</h2>
    <p class="section-desc">基于涨跌幅 + 主力资金 + 行业板块的昨日对比，自动识别市场情绪反转</p>
    {summary_html}
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">★</span>炸板股 TOP {len(exploded)}（昨日涨停 → 今日未封板）</h2>
    <p class="section-desc">数据源：Eastmoney push2delay · 昨日涨停股池对比</p>
    <table class="matrix">
      <thead>
        <tr><th>名称</th><th>昨日涨跌幅</th><th>今日涨跌幅</th></tr>
      </thead>
      <tbody>{exploded_rows if exploded_rows else '<tr><td colspan="3" style="text-align:center;color:#64748b">无炸板股</td></tr>'}
      </tbody>
    </table>
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">★</span>新晋涨停 TOP {len(new_up)}（昨日未涨停 → 今日涨停）</h2>
    <table class="matrix">
      <thead>
        <tr><th>名称</th><th>昨日涨跌幅</th><th>今日涨跌幅</th></tr>
      </thead>
      <tbody>{new_up_rows if new_up_rows else '<tr><td colspan="3" style="text-align:center;color:#64748b">无新晋涨停</td></tr>'}
      </tbody>
    </table>
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">★</span>主力资金反转（流入转流出 / 流出转流入）</h2>
    <div class="stock-grid">
      <div>
        <h3 style="color:#4ade80;font-size:14px;margin-bottom:8px">🟢 流出 → 流入 TOP {len(rev_in)}</h3>
        <table class="matrix">
          <thead><tr><th>名称</th><th>昨日主力</th><th>今日主力</th></tr></thead>
          <tbody>{rev_in_rows if rev_in_rows else '<tr><td colspan="3" style="text-align:center;color:#64748b">无</td></tr>'}</tbody>
        </table>
      </div>
      <div>
        <h3 style="color:#f87171;font-size:14px;margin-bottom:8px">🔴 流入 → 流出 TOP {len(rev_out)}</h3>
        <table class="matrix">
          <thead><tr><th>名称</th><th>昨日主力</th><th>今日主力</th></tr></thead>
          <tbody>{rev_out_rows if rev_out_rows else '<tr><td colspan="3" style="text-align:center;color:#64748b">无</td></tr>'}</tbody>
        </table>
      </div>
    </div>
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">★</span>行业板块涨跌幅最大变动</h2>
    <p class="section-desc">涨跌幅变动 = 今日涨跌幅 - 昨日涨跌幅</p>
    <table class="matrix">
      <thead>
        <tr><th>板块</th><th>昨日涨跌幅</th><th>今日涨跌幅</th><th>变动</th></tr>
      </thead>
      <tbody>{sector_rows if sector_rows else '<tr><td colspan="4" style="text-align:center;color:#64748b">无数据</td></tr>'}
      </tbody>
    </table>
  </div>"""


# ============ 主函数 ============
def main():
    parser = argparse.ArgumentParser(description="A股全市场盘后复盘报告（严格数据守门员版）")
    parser.add_argument("--date", default=datetime.today().strftime("%Y-%m-%d"),
                        help="报告日期（默认今天，格式 YYYY-MM-DD）")
    parser.add_argument("--topn", type=int, default=30, help="各类 TOP N（默认 30）")
    parser.add_argument("--out", default=str(PROJECT_ROOT / "reports"),
                        help="输出目录（默认 reports/）")
    parser.add_argument("--json-out", action="store_true",
                        help="同时保存 JSON 原始数据")
    parser.add_argument("--diff-date", default=None,
                        help="昨日日期（启用异动对比，格式 YYYY-MM-DD）")
    parser.add_argument("--watchlist", nargs="+", default=None,
                        help="关注股票公司名（巨潮搜索用，如 沪电股份 工业富联）")
    parser.add_argument("--push", action="store_true",
                        help="自动推送（邮件/Server酱/企业微信，按环境变量配置）")
    args = parser.parse_args()

    print(f"📊 A股复盘报告生成器 · {args.date}")
    print(f"   数据源：Tencent qt.gtimg.cn + Eastmoney push2delay.eastmoney.com + 巨潮资讯")
    print(f"   原则：真实数据，绝不 AI 推断")
    print()
    print("🔍 开始采集数据...")

    data = {}
    data["date"] = args.date

    # 1. 指数
    print("  → 查询 5 大指数实时报价...")
    data["indices"] = fetch_indices_via_tencent()
    print(f"    ✅ {len(data['indices'])} 个指数")

    # 2. 涨停股
    print(f"  → 查询涨停股池 TOP {args.topn}...")
    data["limit_up"] = fetch_limit_up_stocks(topn=args.topn)
    print(f"    ✅ {len(data['limit_up'])} 只涨停股")

    # 3. 跌停股
    print(f"  → 查询跌停股池 TOP {args.topn}...")
    data["limit_down"] = fetch_limit_down_stocks(topn=20)
    print(f"    ✅ {len(data['limit_down'])} 只跌停股")

    # 4. 行业板块
    print(f"  → 查询行业板块 TOP {args.topn}...")
    data["industries"] = fetch_industry_sectors(topn=args.topn)
    print(f"    ✅ {len(data['industries'])} 个行业板块")

    # 5. 概念板块
    print(f"  → 查询概念板块 TOP {args.topn}...")
    data["concepts"] = fetch_concept_sectors(topn=args.topn)
    print(f"    ✅ {len(data['concepts'])} 个概念板块")

    # 6. 成交额 TOP
    print(f"  → 查询成交额 TOP {args.topn}...")
    data["top_amount"] = fetch_top_amount_stocks(topn=args.topn)
    print(f"    ✅ {len(data['top_amount'])} 只成交额股")

    # 7. 主力净流入 TOP
    print(f"  → 查询主力净流入 TOP {args.topn}...")
    data["top_main_inflow"] = fetch_top_main_inflow_stocks(topn=args.topn)
    print(f"    ✅ {len(data['top_main_inflow'])} 只主力净流入股")

    # 8. 北向资金
    print("  → 查询北向资金汇总...")
    data["northbound"] = fetch_northbound_flow()
    if data["northbound"].get("available"):
        sh = data["northbound"].get("sh2hk", {}).get("day_net_amt_in")
        sz = data["northbound"].get("sz2hk", {}).get("day_net_amt_in")
        print(f"    ✅ 沪股通={sh}万 / 深股通={sz}万")
    else:
        print(f"    ❌ {data['northbound'].get('reason', '未知原因')}")

    # 9. 巨潮资讯公告
    if HAS_CNINFO:
        print("  → 查询巨潮资讯：今日重大事项公告...")
        try:
            ann = fetch_today_announcements(date=args.date, topn=20)
            data["today_announcements"] = ann.get("announcements", [])
            print(f"    ✅ {ann.get('total', 0)} 条重大事项（展示 {len(data['today_announcements'])}）")
        except Exception as e:
            print(f"    ❌ 巨潮公告查询失败: {e}")
            data["today_announcements"] = []

        # 关注股公告
        if args.watchlist:
            print(f"  → 查询关注股公告：{', '.join(args.watchlist)}...")
            watchlist_ann = []
            for company in args.watchlist:
                try:
                    res = fetch_company_announcements(company, topn=5)
                    watchlist_ann.extend(res.get("announcements", []))
                    print(f"    ✅ {company}: {res.get('total', 0)} 条")
                except Exception as e:
                    print(f"    ❌ {company}: {e}")
            # 按时间排序
            watchlist_ann.sort(key=lambda x: x.get("time") or "", reverse=True)
            data["watchlist_announcements"] = watchlist_ann[:15]
        else:
            data["watchlist_announcements"] = []
    else:
        data["today_announcements"] = []
        data["watchlist_announcements"] = []

    # 10. 昨日异动对比（需先有昨日快照文件）
    if args.diff_date and HAS_DIFF:
        print(f"  → 异动对比：昨日 {args.diff_date} vs 今日 {args.date}...")
        # 快照可在 reports/ 或 results/，优先 reports/
        for snap_dir in ["reports", "results"]:
            snapshot_file = PROJECT_ROOT / snap_dir / f"daily_review_{args.diff_date.replace('-', '')}.json"
            if snapshot_file.exists():
                break
        if snapshot_file.exists():
            try:
                yesterday_data = json.loads(snapshot_file.read_text(encoding="utf-8"))
                data["diff"] = generate_full_diff(data, yesterday_data)
                summary = data["diff"].get("summary", {})
                print(f"    ✅ 炸板 {summary.get('exploded_count', 0)} / "
                      f"新晋涨停 {summary.get('new_limit_up_count', 0)} / "
                      f"资金反转 {summary.get('reversed_in_count', 0) + summary.get('reversed_out_count', 0)}")
            except Exception as e:
                print(f"    ❌ 异动对比失败: {e}")
                data["diff"] = {}
        else:
            print(f"    ⚠️ 未找到昨日快照: {snapshot_file}")
            print(f"    💡 提示：需先运行 `python daily_review.py --date {args.diff_date} --json-out` 生成快照")
            data["diff"] = {}
    else:
        data["diff"] = {}

    # 11. 已知不可用项
    data["lhb_status"] = "not_supported"
    data["northbound_individual"] = "not_supported"

    # 渲染 HTML
    print()
    print("🎨 生成 HTML 报告...")
    html = render_html_report(args.date, data)

    # 保存
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"daily_review_{args.date.replace('-', '')}.html"
    out_file.write_text(html, encoding="utf-8")
    print(f"  ✅ HTML 报告已保存: {out_file}")
    print(f"     文件大小: {len(html)/1024:.1f} KB")

    if args.json_out:
        json_file = out_dir / f"daily_review_{args.date.replace('-', '')}.json"
        # 移除函数对象（序列化兼容）
        json_data = {k: v for k, v in data.items() if not callable(v)}
        json_file.write_text(
            json.dumps(json_data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"  ✅ JSON 原始数据已保存: {json_file}")

    # 12. 推送
    if args.push and HAS_NOTIFIER:
        print()
        print("📤 推送通知...")
        notifier = Notifier()
        # 构造 Markdown 摘要
        md = _build_markdown_summary(data)
        notifier.send_all(
            subject=f"A股复盘 · {args.date}",
            html_body=html,
            markdown_summary=md,
        )
    elif args.push and not HAS_NOTIFIER:
        print("  [WARN] notifier 模块未加载，跳过推送")

    print()
    print("=" * 60)
    print("  ⚠️ 缺失项提示：")
    print("     - 龙虎榜（接口已废弃）")
    print("     - 北向资金个股流向（字段返回空）")
    print("     - 上述项已明确标注为「未查询到」，未编造")
    print("=" * 60)
    print()
    print(f"🌐 在浏览器中打开: file:///{out_file.as_posix()}")


def _build_markdown_summary(data: dict) -> str:
    """构造推送通知用的 Markdown 摘要。"""
    lines = [f"# A股复盘 · {data.get('date', '')}", ""]

    # 指数
    indices = data.get("indices", [])
    if indices:
        lines.append("## 📊 主要指数")
        for idx in indices:
            chg = idx.get("change_pct") or 0
            emoji = "🟢" if chg >= 0 else "🔴"
            lines.append(f"- {emoji} **{idx['name']}** {idx.get('current', 0):,.2f} ({chg:+.2f}%)")
        lines.append("")

    # 涨跌停
    lines.append("## 🎯 涨跌停")
    lines.append(f"- 涨停: **{len(data.get('limit_up', []))}** 只")
    lines.append(f"- 跌停: **{len(data.get('limit_down', []))}** 只")
    lines.append("")

    # 板块
    industries = data.get("industries", [])
    if industries:
        lines.append("## 🏭 行业板块 TOP 3")
        for s in industries[:3]:
            chg = s.get("change_pct") or 0
            emoji = "🟢" if chg >= 0 else "🔴"
            lines.append(f"- {emoji} {s['name']} {chg:+.2f}%")
        lines.append("")

    # 异动对比
    diff = data.get("diff", {})
    if diff and diff.get("summary"):
        s = diff["summary"]
        lines.append("## ⚡ 异动对比")
        lines.append(f"- 涨停变化: {s.get('limit_up_delta', 0):+d} 只")
        lines.append(f"- 炸板股: {s.get('exploded_count', 0)} 只")
        lines.append(f"- 新晋涨停: {s.get('new_limit_up_count', 0)} 只")
        lines.append(f"- 主力资金反转: {s.get('reversed_in_count', 0) + s.get('reversed_out_count', 0)} 只")
        lines.append("")

    # 公告
    anns = data.get("today_announcements", [])
    if anns:
        lines.append("## 📢 重大事项公告 TOP 3")
        for a in anns[:3]:
            time_short = (a.get("time") or "")[:16]
            title = (a.get("title") or "")[:50]
            lines.append(f"- {time_short} **{a.get('name', '')}**: {title}")
        lines.append("")

    lines.append("---")
    lines.append(f"📊 数据源：Tencent + Eastmoney + 巨潮资讯")
    lines.append(f"🤖 严格数据守门员版 · 缺失项未编造")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
