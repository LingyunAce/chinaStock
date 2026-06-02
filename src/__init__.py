"""chinaStock — A 股研究框架。

按 4 层架构组织：
- src.data_sources: 数据源适配器（westock/neodata/AKShare）
- src.data_layer:    缓存、归一化、符号转换
- src.integrations:  业务集成（龙虎榜/涨停池/板块等）
- 顶层 strategies/ 与 notebooks/ 留给用户
"""
