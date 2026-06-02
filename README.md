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
