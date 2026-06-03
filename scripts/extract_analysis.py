"""Extract key per-stock analysis from the long_form JSON."""

import json

d = json.load(open("reports/long_form_data_20260603.json", encoding="utf-8"))

for s in d["stocks"]:
    sym = s["symbol"]
    name = s["name"]
    print()
    print("=" * 70)
    print(f"  {sym}  {name}")
    print("=" * 70)

    # 财务关键（最新年报 = 2025）
    fs = s.get("finance_summary", {}).get("head", [])
    if fs:
        last = fs[-1]
        prev = fs[-2] if len(fs) > 1 else None
        rev = float(last["TotalOperatingRevenueTTM"])
        ni = float(last["NPParentCompanyOwnersTTM"])
        eps = float(last["BasicEPS"])
        rev_yoy = (
            float(fs[-1]["TotalOperatingRevenueTTM"])
            / float(fs[0]["TotalOperatingRevenueTTM"])
            - 1
        )
        print(f"  2025 营收 TTM:     {rev / 1e8:>10.2f} 亿")
        print(f"  2025 归母净利 TTM: {ni / 1e8:>10.2f} 亿")
        print(f"  2025 EPS:          {eps:>10.4f}")
        if prev:
            ni_prev = float(prev["NPParentCompanyOwnersTTM"])
            growth = (ni / ni_prev - 1) * 100
            print(f"  2024→2025 净利 YoY: {growth:+.1f}%")

    # 一致预期
    cons = s.get("consensus", {})
    if cons and cons.get("forecasts"):
        print("  一致预期:")
        for f in cons["forecasts"][:3]:
            yr = f.get("year", "?")
            rev = float(f.get("revenue", 0)) / 1e8
            np_ = float(f.get("netProfit", 0)) / 1e8
            np_yoy = f.get("netProfitYoy") or "-"
            print(f"    {yr}: 营收 {rev:>8.1f}亿  净利 {np_:>6.1f}亿  YoY {np_yoy}%")
        if cons.get("target_price"):
            print(f"  目标价: {cons['target_price']}")

    # 评级
    rt = s.get("rating", {}).get("head", [])
    if rt:
        r = rt[0]
        buy = r.get("rating_buy", 0)
        inc = r.get("rating_inc", 0)
        hold = r.get("rating_hold", 0)
        sell = r.get("rating_sell", 0)
        print(f"  评级: 买入 {buy}  增持 {inc}  持有 {hold}  卖出 {sell}")

    # 研报
    rep = s.get("reports", {}).get("head", [])
    print(f"  最新研报 ({len(rep)} 篇):")
    for r in rep[:3]:
        t = r.get("time", "")
        src = r.get("src", "")
        title = r.get("title", "")[:60]
        tzpj = r.get("tzpj", "-")
        print(f"    {t[:10]}  {src[:8]:<8s}  {title}  ({tzpj})")

    # 新闻 TOP 3
    news = s.get("news", {}).get("head", [])
    print(f"  最新新闻 ({len(news)} 条):")
    for r in news[:3]:
        t = r.get("time", "")
        title = r.get("title", "")[:60]
        print(f"    {t[:10]}  {title}")

    # 公告 TOP 3
    notices = s.get("notices", {}).get("head", [])
    print(f"  最新公告 ({len(notices)} 条):")
    for r in notices[:3]:
        t = r.get("time", "")
        title = r.get("title", "")[:60]
        print(f"    {t[:10]}  {title}")

# 板块行情上下文
print()
print("=" * 70)
print("  板块行情（聚源产业概念 5 日涨幅 TOP 15）")
print("=" * 70)
sec5 = d.get("sector_rank_industry_5d", [])
sorted5 = sorted(sec5, key=lambda x: x.get("chg_5d_pct") or 0, reverse=True)
for r in sorted5[:15]:
    code = r.get("sector_code", "")
    name = r.get("sector_name", "")
    chg = r.get("chg_5d_pct", 0) or 0
    chg20 = r.get("chg_20d_pct", 0) or 0
    print(f"  {code:<14s}  {name:<20s}  5日 {chg:+6.2f}%  20日 {chg20:+6.2f}%")

print()
print("  申万一级 5 日 TOP 10")
sw1 = d.get("sector_rank_sw1_5d", [])
sorted_sw = sorted(sw1, key=lambda x: x.get("chg_5d_pct") or 0, reverse=True)
for r in sorted_sw[:10]:
    code = r.get("sector_code", "")
    name = r.get("sector_name", "")
    chg = r.get("chg_5d_pct", 0) or 0
    print(f"  {code:<14s}  {name:<14s}  5日 {chg:+6.2f}%")
