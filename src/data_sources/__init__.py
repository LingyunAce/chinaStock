"""数据源适配器层。

每个数据源（westock-data、neodata-financial-search、AKShare）实现 DataSource ABC，
业务层只依赖 ABC 接口，不直接 import 具体实现。
"""

from src.data_sources.base import DataSource, SourceRole
from src.data_sources.akshare_source import AkShareSource

__all__ = ["DataSource", "SourceRole", "AkShareSource"]
