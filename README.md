# A股分析项目 (chinaStock)

本项目用于 A 股市场的数据分析、策略研究与回测。

## 目录结构

```
chinaStock/
├── data/           # 数据文件 (默认被 git 忽略，按需提交)
│   ├── raw/        # 原始数据
│   └── processed/  # 处理后的数据
├── src/            # 源代码
├── notebooks/      # Jupyter 探索性分析
├── strategies/     # 策略实现
├── results/        # 图表与回测结果
├── docs/           # 文档与笔记
└── tests/          # 单元测试
```

## 环境

- Python 3.10+
- 主要数据源：见 `westock-data` / `neodata-financial-search` 工具

## 快速开始

```bash
git clone <repo-url>
cd chinaStock
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 命名约定

- 股票代码使用 6 位数字字符串（如 `"600519"`），带市场前缀时使用 `"SH600519"` / `"SZ000001"`
- 日期统一使用 `YYYY-MM-DD` 格式
- 因子/特征命名：`{category}_{name}`，例如 `momentum_20d`

## 免责声明

本项目仅用于学习与研究，不构成任何投资建议。

## 可信分析约束

- 单股快照标记为 `trusted`、`partial` 或 `blocked`；只有 `trusted` 报告展示规则化买卖结论。
- 缺少可信状态的旧报告按 `blocked` 处理，数据失败不会再伪装成“无事件”。
- 收盘信号最早在下一可交易日开盘执行，并考虑 100 股整数手、涨跌停、停牌、佣金、印花税和滑点。
- 默认回测成本为佣金 0.03%（最低 5 元）、卖出印花税 0.05%、双边滑点 0.05%。
- 少于 60 个交易日不展示年化收益和夏普比率。

## 数据源

chinaStock 采用**多源融合**策略，根据各数据源的特点分层使用：

| 角色 | 数据源 | 形式 | 用途 |
|---|---|---|---|
| **主源（Primary）** | [`westock-data`](https://github.com/) (Node CLI) | `.claude/skills/westock-data/` | A 股基础行情（K 线 / 实时价 / 财务 / 股东） |
| **主源（Primary）** | [`neodata-financial-search`](https://copilot.tencent.com) (Python) | `.claude/skills/neodata-financial-search/` | 自然语言金融检索（7 大类语义查询） |
| **补充源（Supplementary）** | [**AKShare**](https://github.com/akfamily/akshare) (Python) | `pip install akshare` | 深度补充 + 跨源交叉验证（600+ 接口） |

### 为什么不直接用 AKShare 作主源？

AKShare 优点是接口多（600+），但偶发接口失效、没有 SLA、对单一数据源依赖重。chinaStock 已经有稳定的 westock + neodata 双主源接入，AKShare 的角色是：

1. **深度补充** — 提供 westock 没有的接口（龙虎榜深度数据、申万行业、巨潮公告、同花顺数据、基金深度数据等）
2. **跨源交叉验证** — `AkShareSource.get_quote_for_validation()` 接口预留，可对 westock 关键数据做 diff
3. **业务层永远不直接 import akshare** — 走 `DataSource` ABC 适配，未来切换/降级不影响业务代码

### 三层架构

```
Layer 3  业务集成   src/integrations/        ← 用户主要调这里
Layer 2  数据层     src/data_layer/           ← 缓存/归一化/符号
Layer 1  数据源     src/data_sources/         ← westock/neodata/akshare 适配器
Layer 0  存储       data/{raw,processed,cache}/
```

### 快速使用

```python
from src.integrations.lhb import get_lhb, explain_anomaly
from src.integrations.limit_up import market_sentiment_score
from src.integrations.sectors import get_sector_constituents, get_sector_performance

# 龙虎榜
df = get_lhb("SH600519", "2025-12-15")

# 当日市场情绪
score = market_sentiment_score("2025-12-15")
# {'date': '2025-12-15', 'limit_up_count': 67, 'max_consecutive': 8,
#  'broken_ratio': 0.18, 'sentiment': 'overheat'}

# 板块成分股与日 K
members = get_sector_constituents("机器人")
perf = get_sector_performance("机器人", "2025-11-01", "2025-12-15")
```

完整端到端示例见 [`notebooks/01_akshare_supplementary_intake.ipynb`](notebooks/01_akshare_supplementary_intake.ipynb)。

### 命名约定

- 股票代码：`SH600519` / `SZ000001` / `BJ830799`（大写带前缀，内部统一；6 位裸代码在边界处自动推断）
- 日期：`YYYY-MM-DD`
- 因子/列名：`snake_case`（如 `net_buy_amount`, `consecutive_boards`）
- 缓存：`data/cache/*.parquet`（已 gitignore，不会污染仓库）
