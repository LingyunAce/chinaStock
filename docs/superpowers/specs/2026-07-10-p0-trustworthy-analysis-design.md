# P0 真实可信股票分析设计

日期：2026-07-10  
状态：已获用户批准，待实施

## 1. 目标

P0 的目标不是增加更多指标或数据源，而是保证系统只在数据和验证均可靠时输出买卖结论。系统必须满足以下红线：

1. 回测不使用未来数据；T 日收盘产生的信号最早在 T+1 日开盘执行。
2. 网络失败、解析失败、字段漂移和合法空数据具有不同语义。
3. 只有 `trusted` 分析可以输出买卖结论。
4. `partial` 或 `blocked` 分析仍可生成报告，但建议必须为空，并展示缺失项和阻断原因。
5. 每个结论都展示数据截止时间、数据来源、复权口径、样本区间和交易成本。

## 2. 非目标

P0 不做以下工作：

- 不全面重写现有 `DataSource` 抽象；能力接口拆分留到 P1。
- 不新增数据库、任务队列、Web 服务或大型验证框架。
- 不重构全部历史个股脚本和 HTML 模板。
- 不声称买卖结论是收益保证或预测概率。
- 不使用未校准的“高置信度”“80% 胜率”等表述。

## 3. 范围与入口

P0 建立一个可信核心，由现有单股分析、回测和报告入口逐步接入。核心组件为：

- `src/data_layer/quality.py`：K 线与通用 DataFrame 的质量校验。
- `src/data_sources/base.py`：增加结构化 `DataSourceError`，保留现有 DataFrame 返回接口。
- `src/analysis/trust.py`：聚合数据证据，形成 `trusted / partial / blocked` 状态。
- `src/analysis/advice.py`：仅接受 `trusted` 输入，生成结构化建议。
- `strategies/base.py`：实现没有未来数据的 A 股回测撮合。
- `scripts/run_backtest.py`：展示可信回测参数、基准和样本警告。
- `scripts/gen_single_report.py`：接入建议门禁；实施时保留主工作区已有的空评级列表修复。

历史股票专用脚本在 P0 中不继续扩展。未接入可信核心的旧报告应视为 legacy，不能作为可信买卖结论入口。

## 4. 数据可信契约

### 4.1 数据状态

```python
class TrustStatus(str, Enum):
    TRUSTED = "trusted"
    PARTIAL = "partial"
    BLOCKED = "blocked"
```

```python
@dataclass(frozen=True)
class QualityIssue:
    code: str
    message: str
    source: str | None = None
    critical: bool = False
```

```python
@dataclass(frozen=True)
class SourceEvidence:
    source: str
    dataset: str
    as_of: str | None
    fetched_at: str
    status: str
    row_count: int
    adjustment: str | None = None
```

```python
@dataclass
class AnalysisTrust:
    status: TrustStatus
    issues: list[QualityIssue]
    source_manifest: list[SourceEvidence]
    checked_at: str
```

判定规则：

- 所有关键数据通过校验且没有可选数据缺失：`trusted`。
- 关键数据通过，但可选数据缺失或陈旧：`partial`。
- 任一关键数据失败、陈旧、字段异常或逻辑异常：`blocked`。
- 只有 `trusted` 可以生成建议；`partial` 和 `blocked` 的建议字段必须是 `None`。

### 4.2 错误语义

数据源外部调用发生超时、网络错误、解析错误或上游 schema 漂移时抛出 `DataSourceError`。合法的“查询成功但没有记录”继续返回空 DataFrame。

分析入口不得全局屏蔽 warning。入口捕获 `DataSourceError` 后，将失败写入 `AnalysisTrust`；关键数据失败为 `blocked`，可选数据失败为 `partial`。

### 4.3 K 线最低质量要求

K 线是形成技术结论和回测的关键数据，必须满足：

- 存在 `date, open, high, low, close, volume` 列。
- 日期可解析、唯一、严格递增，且不晚于分析截止时间。
- OHLCV 可转换为数值；成交量非负。
- 每行满足 `high >= max(open, close)` 和 `low <= min(open, close)`。
- 最新日期满足调用入口配置的时效窗口。
- 指标历史长度充足；默认买卖分析至少 60 个交易日。
- 复权方式必须写入来源清单；缺少复权口径时不得标记为 `trusted`。

## 5. 回测设计

### 5.1 时间一致性

策略函数继续按交易日输出信号，但回测器将信号放入待执行订单队列。T 日收盘信号只能在后续首个可交易日的开盘尝试成交，禁止同日开盘成交。

### 5.2 A 股成交约束

`BacktestConfig` 明确保存并返回到报告中：

- 买入数量按 100 股整数手向下取整。
- T+1：买入当日不可卖出。
- `volume <= 0`、停牌或成交价无效时不成交。
- 涨停开盘不买入，跌停开盘不卖出。
- 默认按代码区分主板、创业板、科创板和北交所涨跌幅；ST 必须由显式参数或证券元数据标识。
- 佣金、最低佣金、卖出印花税和滑点均可配置，并计入现金及实际盈亏。
- 未成交订单保留 `date, side, reason`，不得静默丢弃。

默认成本参数用于研究基线，并在报告中显式展示，不代表用户真实券商费率：

- 佣金率：0.03%。
- 单笔最低佣金：5 元。
- 卖出印花税：0.05%。
- 双边滑点：0.05%。

### 5.3 指标语义

- `total_return` 包含已实现和未实现盈亏及全部交易费用。
- 交易列表区分订单、成交、拒绝订单和当前持仓。
- 胜率与盈亏比只基于已平仓交易；没有已平仓交易时返回 `None`。
- 少于 60 个交易日时，年化收益和夏普比率返回 `None`，报告显示“样本不足”。
- 返回同期买入并持有收益和策略超额收益。
- 最终未平仓持仓单独展示，不伪装为已完成交易。

## 6. 建议生成设计

`AdviceEngine` 接受经过验证的结构化信号和 `AnalysisTrust`。若状态不是 `trusted`，直接返回 `None`，报告层无法绕过门禁。

可信建议包含：

- `action`：`buy / hold / reduce / sell / watch`。
- `as_of`：使用的数据截止时间。
- `supporting_evidence`：触发的确定性规则。
- `risk_evidence`：相反信号和已知限制。
- `invalidation_conditions`：使当前建议失效的价格或指标条件。
- 可选 `target_price` 和 `stop_price`：仅在输入完整且公式明确时产生，并附计算依据。

报告将英文枚举渲染为“买入、持有、减仓、卖出、观望”。报告必须同时显示免责声明：结论是规则化研究信号，不是收益保证。

## 7. 报告行为

### 7.1 Trusted

- 正常生成完整报告。
- 展示买卖结论、支持证据、风险证据和失效条件。
- 展示来源清单、数据截止时间、复权方式、样本区间和回测成本。

### 7.2 Partial 或 Blocked

- 继续生成报告，确保用户能看到失败原因。
- 建议字段为 `None`。
- 建议区域固定显示“数据不足，禁止形成买卖结论”。
- 列出来源、状态、缺失字段、陈旧日期或异常信息。
- 不使用默认零值替代缺失数据来计算评分。

## 8. 测试策略

所有生产代码遵循测试驱动开发：先写失败测试并确认失败原因，再写最小实现。

新增测试覆盖：

1. 收盘信号不能在同日开盘成交。
2. 信号在下一可交易日开盘撮合。
3. 100 股整数手、资金不足、T+1、停牌、无量、涨跌停拒单。
4. 佣金、最低佣金、印花税和滑点正确进入现金与盈亏。
5. 无已平仓交易时胜率和盈亏比为 `None`。
6. 短于 60 日时年化收益和夏普为 `None`。
7. 买入并持有基准和超额收益正确。
8. 数据源失败与合法空数据严格区分。
9. K 线缺列、重复日期、未来日期、异常 OHLCV、陈旧和历史不足会产生预期状态。
10. `trusted` 可以生成结构化建议。
11. `partial / blocked` 无法生成建议。
12. 报告展示来源清单或阻断原因。

单元测试不依赖实时网络；数据源只使用固定 fixture 和可控异常。现有 88 个测试必须保持通过。

## 9. 验收标准

P0 完成必须同时满足：

- 最小复现证明 T 日收盘信号只会在 T+1 或更晚成交。
- 任一关键数据源失败时，生成的报告不包含买入、卖出、加仓或减仓结论。
- 同一查询成功返回空数据时，不被错误标记为网络失败。
- `trusted` fixture 能生成包含证据和失效条件的结构化建议。
- 新旧测试全部通过。
- P0 涉及的源码和测试通过 Ruff。
- 报告明确展示数据与回测假设，短样本不再产生夸张年化指标。

## 10. 兼容与迁移

P0 尽量保留现有函数入口。`run_backtest()` 的结果字典增加字段，并将样本不足指标从数值改为 `None`；现有报告必须同步处理该变化。

主工作区已有两处相关未提交修复，实施时必须保留：

- `scripts/gen_single_report.py` 对空机构评级列表的安全访问。
- `scripts/analyze_sh600198.py` 对 westock/AKShare 对比列显式数值转换。

这些修改不得被隔离分支的实现覆盖。

