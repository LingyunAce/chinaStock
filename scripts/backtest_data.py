#!/usr/bin/env python3
"""批量下载历史 K 线数据（westock CLI）。

用法:
    python scripts/backtest_data.py                  # 下载默认股票池
    python scripts/backtest_data.py --symbols SH601138 SH600584  # 指定股票
    python scripts/backtest_data.py --limit 500      # 拉 500 个交易日

输出: data/raw/daily/{SYMBOL}.parquet
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

from src.data_sources.westock_source import (  # noqa: E402
    _call_westock,
    _parse_markdown_table,
    to_westock,
)

# 默认股票池: 5 只光模块 + 工业富联 + 长电科技
DEFAULT_SYMBOLS = [
    "SZ002281",  # 光迅科技
    "SZ000988",  # 华工科技
    "SH600522",  # 中天科技
    "SH601869",  # 长飞光纤
    "SH600487",  # 亨通光电
    "SH601138",  # 工业富联
    "SH600584",  # 长电科技
]


def download_kline(symbol: str, limit: int = 500) -> pd.DataFrame:
    """用 westock CLI 拉取历史 K 线。

    :param symbol: chinaStock 格式 (SH600519)
    :param limit: 交易日数 (westock 只支持 --limit，不支持 --start/--end)
    :return: DataFrame(date, open, close, high, low, volume, amount)
    """
    westock_code = to_westock(symbol)
    text = _call_westock(
        ["kline", westock_code, "--period", "daily", "--limit", str(limit)],
        timeout=30,
    )
    df = _parse_markdown_table(text)
    if df.empty:
        return df
    # 重命名 last → close
    df = df.rename(columns={"last": "close"})
    for col in ("open", "close", "high", "low", "volume", "amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df[["date", "open", "close", "high", "low", "volume", "amount"]].dropna(
        subset=["close"]
    )
    return df


def download_all(
    symbols: list[str] | None = None,
    limit: int = 500,
    force: bool = False,
) -> dict[str, pd.DataFrame]:
    """批量下载所有股票的历史 K 线。

    :param symbols: 股票列表，默认 DEFAULT_SYMBOLS
    :param limit: 每只票拉取的交易日数
    :param force: 强制重新下载（忽略已有文件）
    :return: {symbol: DataFrame}
    """
    symbols = symbols or DEFAULT_SYMBOLS
    out_dir = PROJECT_ROOT / "data" / "raw" / "daily"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    for sym in symbols:
        out_file = out_dir / f"{sym}.parquet"
        if out_file.exists() and not force:
            df = pd.read_parquet(out_file)
            print(f"  [缓存] {sym}: {len(df)} 行 ({out_file})")
            results[sym] = df
            continue
        try:
            df = download_kline(sym, limit=limit)
            if df.empty:
                print(f"  [空] {sym}: 无数据")
                continue
            df.to_parquet(out_file)
            print(f"  [下载] {sym}: {len(df)} 行 -> {out_file}")
            results[sym] = df
        except Exception as e:
            print(f"  [失败] {sym}: {e}")
    return results


def main():
    parser = argparse.ArgumentParser(description="批量下载历史 K 线数据")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="股票列表 (如 SH601138 SH600584)，默认 7 只",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="每只票拉取的交易日数 (默认 500，约 2 年)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新下载",
    )
    args = parser.parse_args()

    print(f"开始下载历史 K 线 ({args.limit} 个交易日) ...")
    results = download_all(
        symbols=args.symbols,
        limit=args.limit,
        force=args.force,
    )
    print(f"\n完成: {len(results)} 只票已下载")
    return 0


if __name__ == "__main__":
    sys.exit(main())
