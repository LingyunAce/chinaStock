"""股票代码符号转换。

chinaStock 内部约定：带前缀大写形式（"SH600519" / "SZ000001" / "BJ830799"），
遵循 README 命名约定。westock-data CLI 用小写（"sh600519"），
AKShare 多数接口只用 6 位（"600519"）。边界处统一在此模块转换。
"""

from __future__ import annotations

import re
from typing import Final

# westock-data 小写前缀 → chinaStock 大写前缀
_PREFIX_UPPER: Final[tuple[str, ...]] = ("SH", "SZ", "BJ")
_PREFIX_LOWER: Final[tuple[str, ...]] = ("sh", "sz", "bj")
_PREFIX_PATTERN: Final[re.Pattern[str]] = re.compile(r"^(SH|SZ|BJ|sh|sz|bj)")

# A 股 6 位代码首位 → 交易所前缀
# 6xxxxx / 9xxxxx = 上交所 (SH)
# 0xxxxx / 3xxxxx = 深交所 (SZ)
# 4xxxxx / 8xxxxx = 北交所 (BJ)
_EXCHANGE_BY_FIRST: Final[dict[str, str]] = {
    "6": "SH",
    "9": "SH",
    "0": "SZ",
    "3": "SZ",
    "4": "BJ",
    "8": "BJ",
}


def to_bare(symbol: str) -> str:
    """`SH600519` / `sh600519` / `600519` → `600519`"""
    if not symbol:
        raise ValueError("symbol 不能为空")
    return _PREFIX_PATTERN.sub("", symbol)


def _infer_exchange(six_digit: str) -> str:
    """从 6 位代码推断交易所前缀。"""
    if len(six_digit) != 6 or not six_digit.isdigit():
        raise ValueError(
            f"无法推断交易所：6 位数字代码应为 6 位数字，得到 {six_digit!r}"
        )
    first = six_digit[0]
    if first not in _EXCHANGE_BY_FIRST:
        raise ValueError(f"无法识别股票代码首位 {first!r}（{six_digit}）")
    return _EXCHANGE_BY_FIRST[first]


def to_chinastock(symbol: str) -> str:
    """任意形式 → chinaStock 内部约定（`SH600519`）。

    支持输入：
    - `sh600519` / `SH600519` / `sz000001` / `bj830799` → 标准化为大写
    - `600519` / `000001` / `830799` → 推断交易所
    """
    if not symbol:
        raise ValueError("symbol 不能为空")
    s = symbol.strip()
    lower = s.lower()
    for prefix_upper, prefix_lower in zip(_PREFIX_UPPER, _PREFIX_LOWER):
        if lower.startswith(prefix_lower):
            bare = (
                s[len(prefix_lower) :]
                if lower.startswith(prefix_lower)
                else s[len(prefix_upper) :]
            )
            return f"{prefix_upper}{bare}"
    bare = to_bare(s)
    if not bare.isdigit() or len(bare) != 6:
        raise ValueError(f"无法识别股票代码: {symbol!r}")
    return f"{_infer_exchange(bare)}{bare}"


def to_westock(symbol: str) -> str:
    """`SH600519` → `sh600519`（westock-data CLI 形式）。"""
    return to_chinastock(symbol).lower()


def to_akshare(symbol: str) -> str:
    """`SH600519` → `600519`（AKShare 多数接口只认 6 位）。"""
    return to_bare(symbol)


__all__ = ["to_bare", "to_chinastock", "to_westock", "to_akshare"]
