#!/usr/bin/env python3
"""巨潮资讯网（cninfo）数据源 - A股公告/新闻/业绩预告。

数据源说明：
    巨潮资讯网（http://www.cninfo.com.cn/）是证监会指定的上市公司
    信息披露官方平台。提供公开的 POST API：
    http://www.cninfo.com.cn/new/hisAnnouncement/query

支持的数据：
    - 全市场公告（沪深京）
    - 个股公告（按公司名 searchkey 搜索）
    - 业绩公告（年报/半年报/季报/快报/预告）
    - 重大事项（重组/中标/合同/担保）
    - 分类公告（category 维度）

使用示例：
    from scripts.cninfo_source import fetch_today_announcements, fetch_company_announcements
    announcements = fetch_today_announcements(date="2026-06-04", topn=20)
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import warnings
from datetime import datetime, timedelta
from typing import Any

warnings.filterwarnings("ignore")

# ============ 配置 ============
CNINFO_BASE = "http://www.cninfo.com.cn"
CNINFO_API = f"{CNINFO_BASE}/new/hisAnnouncement/query"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": f"{CNINFO_BASE}/",
    "Origin": CNINFO_BASE,
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

# 常用公告分类（巨潮 category 编码）
# 格式: category_xxx_szsh = 深沪通用
CATEGORY_MAPPING = {
    "annual_report": "category_ndbg_szsh",  # 年度报告
    "semi_annual": "category_bndbg_szsh",  # 半年报
    "q1_report": "category_yjdbg_szsh",  # 一季报
    "q3_report": "category_sjdbg_szsh",  # 三季报
    "earnings_preview": "category_yjygjxz_szsh;category_yjygsz_szsh;category_yjkb_szsh",  # 业绩预告
    "major_event": "category_qtgg_szsh;category_gqdljg_szsh;category_zj_szsh",  # 重大事项
    "equity_change": "category_gqdljg_szsh",  # 股权变动
    "contract": "category_htgg_szsh",  # 重大合同
    "all_categories": "",  # 不限
}


# ============ HTTP 客户端 ============
def _http_post(url: str, data: dict, timeout: int = 15) -> str | None:
    """POST 请求（带代理绕过）。"""
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=encoded, headers=DEFAULT_HEADERS, method="POST")

    import socket
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    socket.setdefaulttimeout(timeout)
    try:
        with opener.open(req, timeout=timeout) as resp:
            data_bytes = resp.read()
            for enc in ("utf-8", "gbk"):
                try:
                    return data_bytes.decode(enc)
                except UnicodeDecodeError:
                    continue
            return data_bytes.decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, Exception) as e:
        print(f"  [WARN] 巨潮 HTTP 失败: {type(e).__name__}: {str(e)[:80]}", file=sys.stderr)
        return None


def _parse_timestamp(ms: int | None) -> str | None:
    """毫秒时间戳 → YYYY-MM-DD HH:MM:SS。"""
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OSError):
        return None


# ============ 数据采集接口 ============
def fetch_announcements(
    date: str,
    column: str = "szse",  # szse/sse/bse
    plate: str = "sz;szcn",  # sz=深主板, szcn=创业板, sh=沪主板, shmb=沪主板, shkcp=科创板
    category: str = "",  # CATEGORY_MAPPING 中的 key 或直接传 category_xxx_szsh
    searchkey: str = "",  # 公司名/股票名搜索
    page_size: int = 30,
) -> dict:
    """通用公告查询。

    Args:
        date: 查询日期 YYYY-MM-DD
        column: 板块列（szse=深, sse=沪, bse=北）
        plate: 板块代码（sz;szcn;sh;shmb;shkcp 等）
        category: 公告分类（用 CATEGORY_MAPPING key 或直接传 category 字符串）
        searchkey: 搜索关键词（公司名/股票名）
        page_size: 返回数量

    Returns:
        {
            "total": int,  # 总数
            "announcements": list[dict],  # 公告列表
            "source": "cninfo:hisAnnouncement",
        }
    """
    # 解析 category
    if category in CATEGORY_MAPPING:
        category = CATEGORY_MAPPING[category]

    data = {
        "pageNum": 1,
        "pageSize": page_size,
        "column": column,
        "tabName": "fulltext",
        "plate": plate,
        "stock": "",
        "searchkey": searchkey,
        "secid": "",
        "category": category,
        "trade": "",
        "seDate": f"{date}~{date}",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }

    raw = _http_post(CNINFO_API, data)
    if not raw:
        return {"total": 0, "announcements": [], "source": "cninfo:hisAnnouncement", "error": "API调用失败"}

    try:
        j = json.loads(raw)
    except json.JSONDecodeError:
        return {"total": 0, "announcements": [], "source": "cninfo:hisAnnouncement", "error": "JSON解析失败"}

    if not j.get("announcements"):
        return {
            "total": j.get("totalAnnouncement", 0),
            "announcements": [],
            "source": "cninfo:hisAnnouncement",
        }

    # 归一化字段
    announcements = []
    for a in j["announcements"]:
        announcements.append({
            "code": a.get("secCode", ""),
            "name": a.get("secName", ""),
            "title": a.get("announcementTitle", ""),
            "time": _parse_timestamp(a.get("announcementTime")),
            "type": a.get("announcementTypeName", ""),
            "type_code": a.get("announcementType", ""),
            "pdf_url": (CNINFO_BASE + "/" + a.get("adjunctUrl", "")) if a.get("adjunctUrl") else "",
            "size_kb": a.get("adjunctSize", 0),
            "important": a.get("important", False),
            "column": a.get("pageColumn", ""),
            "source": "cninfo:hisAnnouncement",
        })

    return {
        "total": j.get("totalAnnouncement", 0),
        "announcements": announcements,
        "source": "cninfo:hisAnnouncement",
    }


def fetch_today_announcements(date: str, topn: int = 20) -> dict:
    """查询某日全市场公告 TOP N（沪深京合并，重要公告优先）。

    Args:
        date: YYYY-MM-DD
        topn: 返回数量
    """
    # 1. 深市
    sz = fetch_announcements(
        date=date, column="szse", plate="sz;szcn",
        category="major_event", page_size=topn
    )
    # 2. 沪市
    sh = fetch_announcements(
        date=date, column="sse", plate="sh;shkcp",
        category="major_event", page_size=topn
    )

    all_ann = (sz.get("announcements") or []) + (sh.get("announcements") or [])
    # 按时间倒序
    all_ann.sort(key=lambda x: x.get("time") or "", reverse=True)
    return {
        "total": sz.get("total", 0) + sh.get("total", 0),
        "announcements": all_ann[:topn],
        "source": "cninfo:hisAnnouncement",
    }


def fetch_company_announcements(
    company_name: str,
    start_date: str | None = None,
    end_date: str | None = None,
    topn: int = 10,
) -> dict:
    """查询个股公告（按公司名）。

    Args:
        company_name: 公司名称（如 "沪电股份"）
        start_date: 起始日期 YYYY-MM-DD（默认 30 天前）
        end_date: 结束日期 YYYY-MM-DD（默认今天）
        topn: 返回数量
    """
    if not end_date:
        end_date = datetime.today().strftime("%Y-%m-%d")
    if not start_date:
        start_dt = datetime.today() - timedelta(days=30)
        start_date = start_dt.strftime("%Y-%m-%d")

    data = {
        "pageNum": 1,
        "pageSize": topn,
        "column": "szse",
        "tabName": "fulltext",
        "plate": "sz;szcn",
        "stock": "",
        "searchkey": company_name,
        "seDate": f"{start_date}~{end_date}",
        "isHLtitle": "true",
    }

    raw = _http_post(CNINFO_API, data)
    if not raw:
        return {"total": 0, "announcements": [], "source": "cninfo:hisAnnouncement", "error": "API调用失败"}

    try:
        j = json.loads(raw)
    except json.JSONDecodeError:
        return {"total": 0, "announcements": [], "source": "cninfo:hisAnnouncement", "error": "JSON解析失败"}

    announcements = []
    for a in (j.get("announcements") or []):
        announcements.append({
            "code": a.get("secCode", ""),
            "name": a.get("secName", ""),
            "title": a.get("announcementTitle", ""),
            "time": _parse_timestamp(a.get("announcementTime")),
            "type": a.get("announcementTypeName", ""),
            "pdf_url": (CNINFO_BASE + "/" + a.get("adjunctUrl", "")) if a.get("adjunctUrl") else "",
            "source": "cninfo:hisAnnouncement",
        })

    return {
        "total": j.get("totalAnnouncement", 0),
        "announcements": announcements,
        "source": "cninfo:hisAnnouncement",
    }


def fetch_earnings_releases(date: str, topn: int = 15) -> dict:
    """查询某日的业绩报告（年报/半年报/季报/快报/预告）。

    Args:
        date: YYYY-MM-DD
        topn: 返回数量
    """
    return fetch_announcements(
        date=date, column="szse", plate="sz;szcn",
        category="earnings_preview", page_size=topn
    )


def fetch_major_events(date: str, topn: int = 20) -> dict:
    """查询某日的重大事项（重组/中标/合同/担保）。

    Args:
        date: YYYY-MM-DD
        topn: 返回数量
    """
    return fetch_announcements(
        date=date, column="szse", plate="sz;szcn",
        category="major_event", page_size=topn
    )


# ============ CLI 测试 ============
def _cli():
    """命令行测试接口。"""
    if len(sys.argv) < 2:
        print("用法:")
        print("  python cninfo_source.py today [YYYY-MM-DD] [topn]")
        print("  python cninfo_source.py company <公司名> [topn]")
        print("  python cninfo_source.py earnings [YYYY-MM-DD] [topn]")
        return

    cmd = sys.argv[1]
    if cmd == "today":
        date = sys.argv[2] if len(sys.argv) > 2 else datetime.today().strftime("%Y-%m-%d")
        topn = int(sys.argv[3]) if len(sys.argv) > 3 else 15
        print(f"📢 查询 {date} 重大事项公告 TOP {topn}...")
        result = fetch_today_announcements(date, topn)
        print(f"  总数: {result.get('total', 0)}, 返回: {len(result.get('announcements', []))}")
        for a in result.get("announcements", []):
            print(f"  [{a.get('time')}] {a.get('code')} {a.get('name')}: {a.get('title')[:60]}")

    elif cmd == "company":
        name = sys.argv[2] if len(sys.argv) > 2 else "沪电股份"
        topn = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        print(f"🔍 查询 {name} 近期公告...")
        result = fetch_company_announcements(name, topn=topn)
        print(f"  总数: {result.get('total', 0)}, 返回: {len(result.get('announcements', []))}")
        for a in result.get("announcements", []):
            print(f"  [{a.get('time')}] {a.get('title')[:60]}")

    elif cmd == "earnings":
        date = sys.argv[2] if len(sys.argv) > 2 else datetime.today().strftime("%Y-%m-%d")
        topn = int(sys.argv[3]) if len(sys.argv) > 3 else 15
        print(f"💰 查询 {date} 业绩报告...")
        result = fetch_earnings_releases(date, topn)
        print(f"  总数: {result.get('total', 0)}, 返回: {len(result.get('announcements', []))}")
        for a in result.get("announcements", []):
            print(f"  [{a.get('time')}] {a.get('code')} {a.get('name')}: {a.get('title')[:60]}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    _cli()
