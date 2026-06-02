"""文件级 parquet 缓存。

设计目标：
- 减少对 AKShare（及未来 westock/neodata）的网络请求
- 缓存粒度：`source_name + params` 决定唯一文件
- TTL 控制：龙虎榜/涨停池用短 TTL（小时级），板块/财务用长 TTL（天级）
- 强制刷新：`force=True` 跳过缓存读

约定：缓存目录为 `data/cache/`（已被 .gitignore 忽略）。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

import pandas as pd

# 项目根目录解析：cache.py 在 src/data_layer/，向上两级是项目根
_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
CACHE_DIR: Path = _PROJECT_ROOT / "data" / "cache"


def _key_path(source_name: str, params: dict[str, Any]) -> Path:
    """根据 `source_name + params` 生成缓存文件路径。"""
    payload = json.dumps(
        {"source": source_name, "params": params},
        sort_keys=True,
        default=str,
        ensure_ascii=False,
    )
    h = hashlib.md5(payload.encode("utf-8")).hexdigest()[:12]
    safe_name = source_name.replace("/", "_").replace("\\", "_")
    return CACHE_DIR / f"{safe_name}__{h}.parquet"


def cached_call(
    source_name: str,
    params: dict[str, Any],
    fetcher: Callable[[], pd.DataFrame],
    ttl_hours: float = 24.0,
    force: bool = False,
) -> pd.DataFrame:
    """带 TTL 缓存的拉取：缓存命中则读 parquet，否则调 `fetcher()` 并落盘。

    :param source_name: 数据源 + 指标名（如 "akshare.lhb" / "akshare.limit_up"）
    :param params: 拉取参数（symbol, date, start, end 等），参与生成缓存 key
    :param fetcher: 实际拉取函数（无参，返回 DataFrame）
    :param ttl_hours: 缓存有效期（小时）
    :param force: 强制刷新（忽略已有缓存）
    :return: 拉取到的 DataFrame
    """
    path = _key_path(source_name, params)
    if not force and path.exists():
        age_h = (time.time() - path.stat().st_mtime) / 3600
        if age_h < ttl_hours:
            return pd.read_parquet(path)
    df = fetcher()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    return df


def clear_cache(source_name: str | None = None) -> int:
    """清空缓存。返回删除的文件数。

    :param source_name: 若指定，只删除以 `source_name` 开头的缓存
    """
    if not CACHE_DIR.exists():
        return 0
    if source_name is None:
        files = list(CACHE_DIR.glob("*.parquet"))
    else:
        prefix = source_name.replace("/", "_").replace("\\", "_")
        files = list(CACHE_DIR.glob(f"{prefix}__*.parquet"))
    for f in files:
        f.unlink()
    return len(files)


__all__ = ["CACHE_DIR", "cached_call", "clear_cache"]
