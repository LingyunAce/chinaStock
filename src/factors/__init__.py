"""因子层：把数据集成组合成可复用的纯函数。

每个因子 = 一个无副作用函数，签名形如：
    def factor_xxx(date: str, *, source: DataSource | None = None, **kw) -> pd.DataFrame

约定：
- 输入：日期（YYYY-MM-DD），可选数据源
- 输出：DataFrame，列遵循 `{category}_{name}` snake_case
- 因子值列以 `value` 命名（统一）
- 业务层可直接 `from src.factors.lhb_flow import institutional_net_buy` 调用
"""

from src.factors.lhb_flow import institutional_net_buy, lhb_signal_score
from src.factors.market_sentiment import market_sentiment_factor
from src.factors.sector_resonance import sector_resonance_factor
from src.factors.limit_up_streak import limit_up_streak_distribution

__all__ = [
    "institutional_net_buy",
    "lhb_signal_score",
    "market_sentiment_factor",
    "sector_resonance_factor",
    "limit_up_streak_distribution",
]
