#!/usr/bin/env python3
"""回测主入口: 下载数据 → 计算因子 → 跑回测 → 生成报告。

用法:
    python scripts/run_backtest.py
    python scripts/run_backtest.py --symbols SH601138 SH600584 --force
    python scripts/run_backtest.py --limit 300 --min-votes 2
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

from scripts.backtest_data import DEFAULT_SYMBOLS, download_all  # noqa: E402
from strategies.ma_cross import backtest_ma_cross  # noqa: E402
from strategies.macd_cross import backtest_macd_cross  # noqa: E402
from strategies.multi_signal import backtest_multi_signal  # noqa: E402

# ==================== 策略定义 ====================
STRATEGIES = {
    "MA5/10 金叉": backtest_ma_cross,
    "MACD 金叉": backtest_macd_cross,
    "多信号投票 (≥3)": lambda df, **kw: backtest_multi_signal(df, min_votes=3, **kw),
    "多信号投票 (≥2)": lambda df, **kw: backtest_multi_signal(df, min_votes=2, **kw),
}

# ==================== HTML 模板 ====================
HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>回测结果 · chinaStock 信号验证</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  background:linear-gradient(135deg,#0a0e27 0%,#1a1f3a 50%,#0f1729 100%);
  color:#e0e6f1; min-height:100vh; padding:24px; line-height:1.6;
}
.container { max-width:1400px; margin:0 auto; }
.header {
  background:linear-gradient(135deg,rgba(99,102,241,0.18),rgba(168,85,247,0.10));
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

.chart-box {
  background:rgba(15,23,42,0.6); border-radius:14px;
  padding:20px; height:400px; border:1px solid rgba(148,163,184,0.1);
}
.chart-box canvas { max-height:360px; }

.disclaimer {
  background:rgba(239,68,68,0.05); border:1px solid rgba(239,68,68,0.2);
  border-radius:14px; padding:20px 28px; color:#fca5a5;
  font-size:13px; margin-top:30px; line-height:1.8;
}
.disclaimer b { color:#fef2f2; }

@media (max-width:1100px) {
  .header-meta { flex-direction:column; }
}
</style>
</head>
<body>
<div class="container">
"""


def run_all_backtests(
    data: dict[str, pd.DataFrame],
    strategies: dict | None = None,
    **kwargs,
) -> list[dict]:
    """对每只票 × 每个策略跑回测。

    :param data: {symbol: DataFrame}
    :param strategies: {name: backtest_func}
    :return: list of result dicts
    """
    strategies = strategies or STRATEGIES
    results = []
    total = len(data) * len(strategies)
    done = 0
    for sym, df in data.items():
        for strat_name, strat_func in strategies.items():
            done += 1
            try:
                r = strat_func(df, **kwargs)
                r["symbol"] = sym
                r["strategy"] = strat_name
                results.append(r)
                print(
                    f"  [{done}/{total}] {sym} × {strat_name}: 年化 {r['annual_return']:+.2f}%  Sharpe {r['sharpe']:.3f}  最大回撤 {r['max_drawdown']:.1f}%"
                )
            except Exception as e:
                print(f"  [{done}/{total}] {sym} × {strat_name}: 失败 - {e}")
    return results


def generate_report(
    results: list[dict], symbols: list[str], num_strategies: int = 4
) -> str:
    """生成 HTML 回测报告。

    :param results: run_all_backtests 的返回值
    :param symbols: 股票列表
    :return: HTML 字符串
    """
    if not results:
        return "<p>无回测结果</p>"

    # 最佳策略汇总
    best_by_symbol = {}
    for r in results:
        sym = r["symbol"]
        if (
            sym not in best_by_symbol
            or r["annual_return"] > best_by_symbol[sym]["annual_return"]
        ):
            best_by_symbol[sym] = r

    # 汇总表
    rows = []
    for r in results:
        ret_cls = "pos" if r["annual_return"] > 0 else "neg"
        dd_cls = (
            "neg"
            if r["max_drawdown"] > 20
            else ("neu" if r["max_drawdown"] > 10 else "pos")
        )
        sharpe_cls = (
            "pos" if r["sharpe"] > 0.5 else ("neu" if r["sharpe"] > 0 else "neg")
        )
        win_cls = "pos" if r["win_rate"] > 50 else "neg"
        rows.append(f"""
        <tr>
          <td>{html.escape(r["symbol"])}</td>
          <td>{html.escape(r["strategy"])}</td>
          <td class="v {ret_cls}">{r["annual_return"]:+.2f}%</td>
          <td class="v {ret_cls}">{r["total_return"]:+.2f}%</td>
          <td class="v {sharpe_cls}">{r["sharpe"]:.3f}</td>
          <td class="v {dd_cls}">{r["max_drawdown"]:.1f}%</td>
          <td class="v {win_cls}">{r["win_rate"]:.0f}%</td>
          <td class="v">{r["profit_loss_ratio"]:.2f}</td>
          <td class="v">{r["total_trades"]}</td>
          <td class="v">{r["final_value"]:,.0f}</td>
        </tr>
        """)

    # 最佳策略卡片
    best_cards = []
    for sym in symbols:
        if sym in best_by_symbol:
            r = best_by_symbol[sym]
            ret_cls = "pos" if r["annual_return"] > 0 else "neg"
            best_cards.append(f"""
            <div style="background:rgba(15,23,42,0.6); padding:16px; border-radius:12px; border:1px solid rgba(148,163,184,0.15);">
              <div style="font-size:16px; font-weight:700; color:#f1f5f9">{html.escape(sym)}</div>
              <div style="font-size:12px; color:#94a3b8; margin-top:4px">最佳: {html.escape(r["strategy"])}</div>
              <div style="font-size:24px; font-weight:800; color:{"#4ade80" if r["annual_return"] > 0 else "#f87171"}; margin-top:8px">
                {r["annual_return"]:+.2f}%
              </div>
              <div style="font-size:11px; color:#64748b; margin-top:4px">
                Sharpe {r["sharpe"]:.2f} · 回撤 {r["max_drawdown"]:.1f}% · 胜率 {r["win_rate"]:.0f}%
              </div>
            </div>
            """)

    # 年化收益柱图数据
    strat_names = list(STRATEGIES.keys())
    chart_datasets = []
    colors = [
        "#60a5fa",
        "#f87171",
        "#4ade80",
        "#fbbf24",
        "#c084fc",
        "#06b6d4",
        "#f97316",
    ]
    for i, sym in enumerate(symbols):
        data_points = []
        for sn in strat_names:
            matching = [
                r for r in results if r["symbol"] == sym and r["strategy"] == sn
            ]
            data_points.append(matching[0]["annual_return"] if matching else 0)
        chart_datasets.append(
            {
                "label": sym,
                "data": data_points,
                "backgroundColor": colors[i % len(colors)],
                "borderRadius": 4,
            }
        )

    return f"""{HTML_HEAD}
  <div class="header">
    <div class="header-content">
      <span class="stock-tag">📊 chinaStock 回测引擎 v1.0 · 技术信号历史验证</span>
      <h1>回测结果报告</h1>
      <p class="subtitle">{len(symbols)} 只票 × {num_strategies} 个策略 = {len(results)} 个回测 · 数据窗口: ~2 年日 K</p>
      <div class="header-meta">
        <div class="item"><div class="label">股票数</div><div class="value">{len(symbols)}</div></div>
        <div class="item"><div class="label">策略数</div><div class="value">{num_strategies}</div></div>
        <div class="item"><div class="label">回测数</div><div class="value">{len(results)}</div></div>
        <div class="item"><div class="label">最佳年化</div><div class="value" style="color:#4ade80">{max(r["annual_return"] for r in results):+.1f}%</div></div>
      </div>
    </div>
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">1</span>最佳策略汇总</h2>
    <p class="section-desc">每只票年化收益最高的策略</p>
    <div style="display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:14px; margin-top:12px">
      {"".join(best_cards)}
    </div>
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">2</span>年化收益对比 (按策略分组)</h2>
    <p class="section-desc">每只票在不同策略下的年化收益，越高越好</p>
    <div class="chart-box"><canvas id="returnChart"></canvas></div>
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">3</span>详细回测结果</h2>
    <p class="section-desc">所有 {len(results)} 个回测的完整指标</p>
    <table class="matrix">
      <thead>
        <tr>
          <th>标的</th><th>策略</th><th class="v">年化收益</th><th class="v">总收益</th>
          <th class="v">Sharpe</th><th class="v">最大回撤</th><th class="v">胜率</th>
          <th class="v">盈亏比</th><th class="v">交易次数</th><th class="v">期末资金</th>
        </tr>
      </thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
  </div>

  <div class="section">
    <h2 class="section-title"><span class="num">4</span>结论</h2>
    <div style="font-size:14px; color:#cbd5e1; line-height:1.85; margin-top:12px">
      <p><b style="color:#f1f5f9">回测说明</b>：以上回测基于 westock 拉取的 ~2 年日 K 数据，
      使用纯技术信号（MA/MACD/RSI/KDJ/BOLL），不包含基本面、资金流、板块动量等因子。
      初始资金 100 万，手续费 0.1%，滑点 0.05%。</p>
      <p style="margin-top:10px"><b style="color:#f1f5f9">重要提示</b>：
      历史回测不等于未来收益。技术信号在震荡市中表现较差，在趋势市中表现较好。
      实际交易还需结合基本面、资金面、市场情绪等多维度判断。</p>
      <p style="margin-top:10px"><b style="color:#f1f5f9">下一步</b>：
      1. 加入板块动量因子（近 30 日验证）
      2. 加入资金流因子（龙虎榜/涨停池）
      3. 多票组合再平衡
      4. 参数敏感性分析</p>
    </div>
  </div>

  <div class="disclaimer">
    <b>⚠️ 重要免责声明</b><br>
    本回测基于历史数据，不构成投资建议。技术信号在不同市场环境下表现差异大。
    实际交易需结合最新行情与自身风险承受能力做决策。<b>市场有风险，决策需谨慎。</b>
  </div>

</div>
<script>
Chart.defaults.color='#94a3b8';
Chart.defaults.borderColor='rgba(148,163,184,0.1)';
Chart.defaults.font.family='-apple-system,"PingFang SC","Microsoft YaHei",sans-serif';

new Chart(document.getElementById('returnChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(strat_names)},
    datasets: {json.dumps(chart_datasets)}
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{
      legend: {{ position: 'top', labels: {{ color: '#e2e8f0', font: {{ size: 12 }} }} }},
      title: {{ display: true, text: '年化收益对比 (%)', color: '#f1f5f9', font: {{ size: 15, weight: 600 }} }}
    }},
    scales: {{
      x: {{ grid: {{ color: 'rgba(148,163,184,0.05)' }} }},
      y: {{ grid: {{ color: 'rgba(148,163,184,0.05)' }}, ticks: {{ callback: v => v + '%' }} }}
    }}
  }}
}});
</script>
</body></html>"""


def main():
    parser = argparse.ArgumentParser(description="回测主入口")
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--min-votes", type=int, default=3)
    args = parser.parse_args()

    symbols = args.symbols or DEFAULT_SYMBOLS

    # 1. 下载数据
    print("=" * 60)
    print("  Phase 1: 下载历史 K 线")
    print("=" * 60)
    data = download_all(symbols=symbols, limit=args.limit, force=args.force)
    if not data:
        print("无数据，退出")
        return 1

    # 2. 跑回测
    print()
    print("=" * 60)
    print("  Phase 2: 运行回测")
    print("=" * 60)
    strategies = dict(STRATEGIES)
    # 调整多信号投票的 min_votes
    strategies["多信号投票 (≥2)"] = lambda df, **kw: backtest_multi_signal(
        df, min_votes=args.min_votes, **kw
    )
    results = run_all_backtests(data, strategies)

    # 3. 生成报告
    print()
    print("=" * 60)
    print("  Phase 3: 生成报告")
    print("=" * 60)
    out_dir = PROJECT_ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    html_out = generate_report(results, list(data.keys()))
    out_file = out_dir / f"backtest_results_{datetime.now().strftime('%Y%m%d')}.html"
    out_file.write_text(html_out, encoding="utf-8")
    print(f"[OK] {out_file}  ({out_file.stat().st_size / 1024:.1f} KB)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
