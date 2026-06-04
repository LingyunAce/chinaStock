#!/usr/bin/env python3
"""异动股对比引擎 - 昨日 vs 今日 关键指标对比。

输入：两个日期的复盘数据 dict
输出：异动股清单 + 趋势反转信号 + 主力资金反转

对比维度：
    1. 涨停股变化（昨日涨停 → 今日未涨停 = 炸板）
    2. 跌停股变化（昨日跌停 → 今日未跌停 = 反弹）
    3. 主力净流入反转（昨日流出 TOP → 今日流入 TOP）
    4. 板块涨跌反转（行业/概念涨跌幅最大变动）
    5. 连续涨停股（连板高度）
    6. 新晋涨停股（昨日未涨停 → 今日涨停）
"""
from __future__ import annotations

from typing import Any


def diff_limit_up_stocks(today: list[dict], yesterday: list[dict]) -> dict:
    """对比涨停股池：找出炸板、新晋涨停、连续涨停。

    Returns:
        {
            "exploded": [炸板股: 昨日涨停, 今日未涨停],
            "new_limit_up": [新晋涨停: 昨日未涨停, 今日涨停],
            "consecutive": [连续涨停: 昨日+今日均涨停],
            "today_count": int,
            "yesterday_count": int,
            "delta": int,  # 变化量
        }
    """
    today_codes = {s["code"] for s in today if s.get("code")}
    yesterday_codes = {s["code"] for s in yesterday if s.get("code")}

    yesterday_dict = {s["code"]: s for s in yesterday}
    today_dict = {s["code"]: s for s in today}

    # 炸板：昨日涨停，今日未涨停
    exploded = [
        {
            "code": code,
            "name": yesterday_dict[code].get("name", ""),
            "yesterday_change_pct": yesterday_dict[code].get("change_pct"),
            "today_change_pct": today_dict.get(code, {}).get("change_pct"),
            "yesterday_amount": yesterday_dict[code].get("amount"),
        }
        for code in (yesterday_codes - today_codes)
        if code in yesterday_dict
    ]
    exploded.sort(key=lambda x: x.get("yesterday_change_pct") or 0, reverse=True)

    # 新晋涨停：今日涨停，昨日未涨停
    new_limit_up = [
        {
            "code": code,
            "name": today_dict[code].get("name", ""),
            "today_change_pct": today_dict[code].get("change_pct"),
            "today_amount": today_dict[code].get("amount"),
            "yesterday_change_pct": yesterday_dict.get(code, {}).get("change_pct"),
        }
        for code in (today_codes - yesterday_codes)
        if code in today_dict
    ]
    new_limit_up.sort(key=lambda x: x.get("today_change_pct") or 0, reverse=True)

    # 连续涨停：今日+昨日都涨停
    consecutive = [
        {
            "code": code,
            "name": today_dict[code].get("name", ""),
            "today_change_pct": today_dict[code].get("change_pct"),
            "yesterday_change_pct": yesterday_dict[code].get("change_pct"),
            "consecutive_days": 2,
        }
        for code in (today_codes & yesterday_codes)
        if code in today_dict and code in yesterday_dict
    ]
    consecutive.sort(key=lambda x: x.get("today_change_pct") or 0, reverse=True)

    return {
        "exploded": exploded[:15],
        "new_limit_up": new_limit_up[:15],
        "consecutive": consecutive[:15],
        "today_count": len(today),
        "yesterday_count": len(yesterday),
        "delta": len(today) - len(yesterday),
    }


def diff_main_capital(today: list[dict], yesterday: list[dict]) -> dict:
    """对比主力净流入 TOP：找出反转股（昨日流出 → 今日流入）。"""
    today_dict = {s["code"]: s for s in today if s.get("code")}
    yesterday_dict = {s["code"]: s for s in yesterday if s.get("code")}

    # 昨日主力净流出 TOP → 今日主力净流入
    reversed_in = []
    for code, y in yesterday_dict.items():
        y_flow = y.get("main_net_inflow") or 0
        if y_flow < 0 and code in today_dict:
            t_flow = today_dict[code].get("main_net_inflow") or 0
            if t_flow > 0:
                reversed_in.append({
                    "code": code,
                    "name": today_dict[code].get("name", ""),
                    "yesterday_flow": y_flow,
                    "today_flow": t_flow,
                    "reversal": t_flow - y_flow,
                })
    reversed_in.sort(key=lambda x: x["reversal"], reverse=True)

    # 昨日主力净流入 → 今日主力净流出
    reversed_out = []
    for code, y in yesterday_dict.items():
        y_flow = y.get("main_net_inflow") or 0
        if y_flow > 0 and code in today_dict:
            t_flow = today_dict[code].get("main_net_inflow") or 0
            if t_flow < 0:
                reversed_out.append({
                    "code": code,
                    "name": today_dict[code].get("name", ""),
                    "yesterday_flow": y_flow,
                    "today_flow": t_flow,
                    "reversal": t_flow - y_flow,
                })
    reversed_out.sort(key=lambda x: x["reversal"])

    return {
        "reversed_in": reversed_in[:10],
        "reversed_out": reversed_out[:10],
        "today_top_inflow": today[:10],
        "yesterday_top_inflow": yesterday[:10],
    }


def diff_sectors(today: list[dict], yesterday: list[dict]) -> dict:
    """对比行业板块：找出涨跌幅变动最大的板块。"""
    today_dict = {s["code"]: s for s in today if s.get("code")}
    yesterday_dict = {s["code"]: s for s in yesterday if s.get("code")}

    # 涨跌幅变动 = 今日涨跌幅 - 昨日涨跌幅
    changes = []
    for code in (set(today_dict.keys()) & set(yesterday_dict.keys())):
        t = today_dict[code]
        y = yesterday_dict[code]
        t_chg = t.get("change_pct") or 0
        y_chg = y.get("change_pct") or 0
        changes.append({
            "code": code,
            "name": t.get("name", ""),
            "today_chg": t_chg,
            "yesterday_chg": y_chg,
            "delta": t_chg - y_chg,
        })

    # 最大涨幅改善
    improved = sorted(changes, key=lambda x: x["delta"], reverse=True)[:10]
    # 最大涨幅恶化
    worsened = sorted(changes, key=lambda x: x["delta"])[:10]

    return {
        "improved": improved,
        "worsened": worsened,
        "today_count": len(today),
        "yesterday_count": len(yesterday),
    }


def generate_full_diff(today_data: dict, yesterday_data: dict) -> dict:
    """生成完整异动对比报告。

    Args:
        today_data: 今日复盘数据（含 limit_up, top_main_inflow, industries 等）
        yesterday_data: 昨日复盘数据（结构同 today_data）
    """
    diff = {
        "limit_up_diff": diff_limit_up_stocks(
            today_data.get("limit_up", []),
            yesterday_data.get("limit_up", []),
        ),
        "main_capital_diff": diff_main_capital(
            today_data.get("top_main_inflow", []),
            yesterday_data.get("top_main_inflow", []),
        ),
        "sector_diff": diff_sectors(
            today_data.get("industries", []),
            yesterday_data.get("industries", []),
        ),
    }

    # 汇总统计
    diff["summary"] = {
        "limit_up_delta": diff["limit_up_diff"]["delta"],
        "exploded_count": len(diff["limit_up_diff"]["exploded"]),
        "new_limit_up_count": len(diff["limit_up_diff"]["new_limit_up"]),
        "consecutive_count": len(diff["limit_up_diff"]["consecutive"]),
        "reversed_in_count": len(diff["main_capital_diff"]["reversed_in"]),
        "reversed_out_count": len(diff["main_capital_diff"]["reversed_out"]),
    }

    return diff


# ============ CLI 测试 ============
def _cli():
    import sys
    import json
    from pathlib import Path

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if len(sys.argv) < 3:
        print("用法: python diff_engine.py <today.json> <yesterday.json>")
        return

    today_path = Path(sys.argv[1])
    yesterday_path = Path(sys.argv[2])

    if not today_path.exists() or not yesterday_path.exists():
        print(f"FAIL: 文件不存在")
        return

    today_data = json.loads(today_path.read_text(encoding="utf-8"))
    yesterday_data = json.loads(yesterday_path.read_text(encoding="utf-8"))

    diff = generate_full_diff(today_data, yesterday_data)

    print("=" * 60)
    print("📊 异动对比报告")
    print("=" * 60)
    print(f"\n[1] 涨停变化：{diff['summary']['limit_up_delta']:+d} 只")
    print(f"    炸板: {diff['summary']['exploded_count']} 只 / 新晋涨停: {diff['summary']['new_limit_up_count']} 只 / 连续涨停: {diff['summary']['consecutive_count']} 只")

    print(f"\n[2] 主力资金反转：")
    print(f"    流出转流入: {diff['summary']['reversed_in_count']} 只 / 流入转流出: {diff['summary']['reversed_out_count']} 只")

    print(f"\n[3] 板块涨跌幅最大变动：")
    print(f"    改善 TOP 3: {[(s['name'], s['delta']) for s in diff['sector_diff']['improved'][:3]]}")
    print(f"    恶化 TOP 3: {[(s['name'], s['delta']) for s in diff['sector_diff']['worsened'][:3]]}")

    print("\n[4] 炸板股 TOP 5：")
    for s in diff["limit_up_diff"]["exploded"][:5]:
        print(f"    {s['name']} ({s['code']}): 昨 {s['yesterday_change_pct']:+.2f}% → 今 {s['today_change_pct']:+.2f}%")


if __name__ == "__main__":
    _cli()
