"""neodata-financial-search 数据源适配器（主源）。

通过 HTTP 调用 `https://copilot.tencent.com/agenttool/v1/neodata` 代理，
自然语言查询 → 结构化 JSON 响应。Token 来自 `~/.workbuddy/.neodata_token`，
12 小时 TTL。

设计：
- 大部分 ABC 方法（lhb / limit_up / sector 等）走自然语言查询，返回结构不固定
  → 多数方法 `raise NotImplementedError`，提示调用方用 westock/AKShare
- 仅 `get_quote_for_validation` 实现（自然语言："{symbol} 在 {date} 的行情"）
  → 用于跨源交叉验证
- 用户可直接调 `natural_query()`（非 ABC 方法）做临时性 NLP 查询
"""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from src.data_layer.symbols import to_chinastock
from src.data_sources.base import DataSource, SourceRole

try:
    import requests
except ImportError as e:  # pragma: no cover
    raise ImportError("neodata 适配器依赖 requests，请先安装") from e


# ----------------------------- Token 管理 -----------------------------
DEFAULT_ENDPOINT: str = "https://copilot.tencent.com/agenttool/v1/neodata"
TOKEN_FILE: Path = Path.home() / ".workbuddy" / ".neodata_token"
TOKEN_TTL_SECONDS: int = 12 * 3600


def _read_token() -> Optional[str]:
    """从 `~/.workbuddy/.neodata_token` 读取 token，过期返回 None。

    文件格式：`{"token": "...", "saved_at": <unix-ts>}`，权限 600。
    """
    try:
        raw = TOKEN_FILE.read_text().strip()
        if not raw:
            return None
        try:
            data = json.loads(raw)
            token = data.get("token", "")
            saved_at = data.get("saved_at", 0)
            if not token:
                return None
            if time.time() - saved_at > TOKEN_TTL_SECONDS:
                return None
            return token
        except (json.JSONDecodeError, TypeError):
            return None
    except (FileNotFoundError, PermissionError):
        return None


def save_token(token: str) -> None:
    """保存 token 到缓存文件（权限 600）。"""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(
        json.dumps({"token": token.strip(), "saved_at": int(time.time())})
    )
    try:
        TOKEN_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except (OSError, NotImplementedError):  # Windows 上 chmod 部分支持
        pass


def has_valid_token() -> bool:
    return _read_token() is not None


# ----------------------------- 主适配器 -----------------------------
class NeodataSource(DataSource):
    """neodata-financial-search 适配器（主源）。"""

    role: SourceRole = SourceRole.PRIMARY
    name: str = "neodata"

    def __init__(self, token: Optional[str] = None, endpoint: Optional[str] = None):
        self._token = token  # 留作显式覆盖
        self._endpoint = endpoint or os.getenv("NEODATA_ENDPOINT", DEFAULT_ENDPOINT)

    def _http_post(self, query: str, data_type: str = "all") -> dict:
        """发自然语言查询到 neodata 代理，返回 JSON 响应 dict。"""
        jwt_token = self._token or _read_token()
        if not jwt_token:
            raise RuntimeError(
                "neodata token 不可用：请先调用 save_token('your-token') 或"
                "构造时显式传入 token=..."
            )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {jwt_token}",
        }
        payload: dict = {
            "query": query,
            "channel": "neodata",
            "sub_channel": "workbuddy",
        }
        if data_type != "all":
            payload["data_type"] = data_type

        resp = requests.post(self._endpoint, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ---------------------- 非 ABC：自然语言查询 ----------------------
    def natural_query(self, query: str, data_type: str = "all") -> dict:
        """自然语言查询（非 ABC 方法）。

        示例：
            natural_query("贵州茅台 2025-12-15 收盘价")
            natural_query("今日涨停股", data_type="api")
        """
        return self._http_post(query, data_type=data_type)

    # ---------------------- ABC 方法 ----------------------
    def get_lhb(self, symbol: str | None, date: str, **kw: Any) -> pd.DataFrame:
        """龙虎榜：neodata 没有结构化接口，提示用自然语言查询。"""
        raise NotImplementedError(
            "neodata 不提供结构化龙虎榜接口。"
            "请用 natural_query(f'查询 {date} 的龙虎榜数据') 做 NLP 查询，"
            "或用 WestockSource / AkShareSource 替代。"
        )

    def get_limit_up_pool(self, date: str, **kw: Any) -> pd.DataFrame:
        """涨停池：neodata 不提供结构化接口。"""
        raise NotImplementedError(
            "neodata 不提供结构化涨停池接口。"
            "请用 natural_query(f'查询 {date} 的涨停股列表') 做 NLP 查询，"
            "或用 AkShareSource 替代。"
        )

    def get_sector_constituents(self, sector: str, **kw: Any) -> pd.DataFrame:
        """板块成分股：neodata 不提供结构化接口。"""
        raise NotImplementedError(
            f"neodata 不提供结构化板块成分股接口。"
            f"请用 natural_query('查询 {sector} 板块的成分股') 做 NLP 查询，"
            f"或用 WestockSource 替代。"
        )

    def get_sector_perf(
        self, sector: str, start: str, end: str, **kw: Any
    ) -> pd.DataFrame:
        """板块日 K：neodata 不提供结构化接口。"""
        raise NotImplementedError(
            f"neodata 不提供结构化板块 K 线接口。"
            f"请用 natural_query('查询 {sector} 板块 {start} 到 {end} 的走势')"
            f"做 NLP 查询，或用 AkShareSource 替代。"
        )

    def get_quote_for_validation(
        self, symbol: str, date: str, **kw: Any
    ) -> pd.DataFrame:
        """交叉验证：neodata 自然语言查询个股行情。

        返回 DataFrame（列：date, symbol, price, source_note），结构化程度有限，
        主要用于"是否存在 / 数量级对不对"的交叉验证。
        """
        chinastock = to_chinastock(symbol)
        result = self._http_post(
            f"查询 {chinastock} 在 {date} 的收盘价、成交量、成交额"
        )
        # neodata 响应结构不固定；尝试提取常见字段，否则把整个 result 平铺到一行
        data = result.get("data", result)
        return pd.DataFrame(
            [
                {
                    "date": date,
                    "symbol": chinastock,
                    "raw_response": json.dumps(data, ensure_ascii=False),
                }
            ]
        )


__all__ = ["NeodataSource", "save_token", "has_valid_token"]
