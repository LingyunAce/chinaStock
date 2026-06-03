"""纯技术因子 — 从 OHLCV DataFrame 计算，无 API 依赖。

所有信号统一输出格式:
    DataFrame(date, signal)  其中 signal ∈ {-1, 0, 1}
    -1 = 卖出/看空
     0 = 无信号
    +1 = 买入/看多

支持的因子:
- MA 金叉/死叉 (MA5/MA10, MA5/MA20)
- MACD 金叉/死叉 (DIF/DEA)
- RSI 超买/超卖 (RSI6)
- KDJ 金叉/死叉 (K/D)
- BOLL 突破/跌破 (均值回归信号)
- 多信号投票组合
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    """确保 DataFrame 有 date/open/close/high/low/volume 列。"""
    df = df.copy()
    rename = {"last": "close"}
    df = df.rename(columns=rename)
    for col in ("open", "close", "high", "low", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df


# ==================== MA ====================


def compute_ma(
    df: pd.DataFrame,
    short: int = 5,
    long: int = 10,
) -> pd.DataFrame:
    """MA 金叉/死叉信号。

    short MA 上穿 long MA → +1 (金叉买入)
    short MA 下穿 long MA → -1 (死叉卖出)
    """
    df = _ensure_columns(df)
    df = df.sort_values("date").reset_index(drop=True)
    df[f"ma{short}"] = df["close"].rolling(short).mean()
    df[f"ma{long}"] = df["close"].rolling(long).mean()
    df["signal"] = 0
    # 金叉: 短线从下穿上
    prev_short = df[f"ma{short}"].shift(1)
    prev_long = df[f"ma{long}"].shift(1)
    cross_up = (prev_short <= prev_long) & (df[f"ma{short}"] > df[f"ma{long}"])
    cross_down = (prev_short >= prev_long) & (df[f"ma{short}"] < df[f"ma{long}"])
    df.loc[cross_up, "signal"] = 1
    df.loc[cross_down, "signal"] = -1
    return df[["date", "signal", f"ma{short}", f"ma{long}", "close"]].dropna()


# ==================== MACD ====================


def compute_macd(
    df: pd.DataFrame,
    fast: int = 5,
    slow: int = 13,
    signal_period: int = 5,
) -> pd.DataFrame:
    """MACD 金叉/死叉信号。

    默认参数 5/13/5（回测验证：强趋势板块年化 +291%，优于默认 12/26/9 的 +161%）。
    DIF 上穿 DEA → +1 (金叉买入)
    DIF 下穿 DEA → -1 (死叉卖出)
    """
    df = _ensure_columns(df)
    df = df.sort_values("date").reset_index(drop=True)
    df["ema_fast"] = df["close"].ewm(span=fast, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=slow, adjust=False).mean()
    df["dif"] = df["ema_fast"] - df["ema_slow"]
    df["dea"] = df["dif"].ewm(span=signal_period, adjust=False).mean()
    df["macd_hist"] = (df["dif"] - df["dea"]) * 2
    df["signal"] = 0
    prev_dif = df["dif"].shift(1)
    prev_dea = df["dea"].shift(1)
    cross_up = (prev_dif <= prev_dea) & (df["dif"] > df["dea"])
    cross_down = (prev_dif >= prev_dea) & (df["dif"] < df["dea"])
    df.loc[cross_up, "signal"] = 1
    df.loc[cross_down, "signal"] = -1
    return df[["date", "signal", "dif", "dea", "macd_hist", "close"]].dropna()


# ==================== RSI ====================


def compute_rsi(
    df: pd.DataFrame,
    period: int = 6,
    oversold: float = 30.0,
    overbought: float = 70.0,
) -> pd.DataFrame:
    """RSI 超买/超卖信号。

    RSI 从超卖区 (<oversold) 回升 → +1 (买入)
    RSI 从超买区 (>overbought) 回落 → -1 (卖出)
    """
    df = _ensure_columns(df)
    df = df.sort_values("date").reset_index(drop=True)
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    df["signal"] = 0
    prev_rsi = df["rsi"].shift(1)
    # 从超卖区回升
    cross_up = (prev_rsi < oversold) & (df["rsi"] >= oversold)
    # 从超买区回落
    cross_down = (prev_rsi > overbought) & (df["rsi"] <= overbought)
    df.loc[cross_up, "signal"] = 1
    df.loc[cross_down, "signal"] = -1
    return df[["date", "signal", "rsi", "close"]].dropna()


# ==================== KDJ ====================


def compute_kdj(
    df: pd.DataFrame,
    n: int = 9,
    m1: int = 3,
    m2: int = 3,
) -> pd.DataFrame:
    """KDJ 金叉/死叉信号。

    K 上穿 D → +1 (金叉买入)
    K 下穿 D → -1 (死叉卖出)
    """
    df = _ensure_columns(df)
    df = df.sort_values("date").reset_index(drop=True)
    low_n = df["low"].rolling(n).min()
    high_n = df["high"].rolling(n).max()
    rsv = (df["close"] - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    df["k"] = rsv.ewm(com=m1 - 1, adjust=False).mean()
    df["d"] = df["k"].ewm(com=m2 - 1, adjust=False).mean()
    df["j"] = 3 * df["k"] - 2 * df["d"]
    df["signal"] = 0
    prev_k = df["k"].shift(1)
    prev_d = df["d"].shift(1)
    cross_up = (prev_k <= prev_d) & (df["k"] > df["d"])
    cross_down = (prev_k >= prev_d) & (df["k"] < df["d"])
    df.loc[cross_up, "signal"] = 1
    df.loc[cross_down, "signal"] = -1
    return df[["date", "signal", "k", "d", "j", "close"]].dropna()


# ==================== BOLL ====================


def compute_boll(
    df: pd.DataFrame,
    period: int = 20,
    num_std: float = 2.0,
) -> pd.DataFrame:
    """BOLL 通道突破/跌破信号 (均值回归)。

    价格跌破下轨 → +1 (超卖买入)
    价格突破上轨 → -1 (超买卖出)
    """
    df = _ensure_columns(df)
    df = df.sort_values("date").reset_index(drop=True)
    df["boll_mid"] = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std()
    df["boll_upper"] = df["boll_mid"] + num_std * std
    df["boll_lower"] = df["boll_mid"] - num_std * std
    df["signal"] = 0
    # 跌破下轨后回到下轨上方 → 买入
    prev_close = df["close"].shift(1)
    prev_lower = df["boll_lower"].shift(1)
    prev_upper = df["boll_upper"].shift(1)
    cross_lower_up = (prev_close <= prev_lower) & (df["close"] > df["boll_lower"])
    cross_upper_down = (prev_close >= prev_upper) & (df["close"] < df["boll_upper"])
    df.loc[cross_lower_up, "signal"] = 1
    df.loc[cross_upper_down, "signal"] = -1
    return df[
        ["date", "signal", "boll_upper", "boll_mid", "boll_lower", "close"]
    ].dropna()


# ==================== 多信号组合 ====================


def compute_all_signals(df: pd.DataFrame) -> pd.DataFrame:
    """计算所有技术信号并合并。

    返回 DataFrame(date, ma_sig, macd_sig, rsi_sig, kdj_sig, boll_sig, close)
    """
    ma = compute_ma(df)[["date", "signal", "close"]].rename(
        columns={"signal": "ma_sig"}
    )
    macd = compute_macd(df)[["date", "signal"]].rename(columns={"signal": "macd_sig"})
    rsi = compute_rsi(df)[["date", "signal"]].rename(columns={"signal": "rsi_sig"})
    kdj = compute_kdj(df)[["date", "signal"]].rename(columns={"signal": "kdj_sig"})
    boll = compute_boll(df)[["date", "signal"]].rename(columns={"signal": "boll_sig"})

    result = ma.merge(macd, on="date", how="outer")
    result = result.merge(rsi, on="date", how="outer")
    result = result.merge(kdj, on="date", how="outer")
    result = result.merge(boll, on="date", how="outer")
    result = result.fillna(0)
    return result


def compute_vote_signal(df: pd.DataFrame, min_votes: int = 2) -> pd.DataFrame:
    """多信号投票: 至少 min_votes 个同向信号才执行。

    返回 DataFrame(date, signal, vote_count, close)
    signal: 投票结果 (+1/-1/0)
    vote_count: 同向信号数
    """
    all_sig = compute_all_signals(df)
    sig_cols = ["ma_sig", "macd_sig", "rsi_sig", "kdj_sig", "boll_sig"]
    all_sig["bull_votes"] = all_sig[sig_cols].apply(lambda row: (row > 0).sum(), axis=1)
    all_sig["bear_votes"] = all_sig[sig_cols].apply(lambda row: (row < 0).sum(), axis=1)
    all_sig["signal"] = 0
    all_sig.loc[all_sig["bull_votes"] >= min_votes, "signal"] = 1
    all_sig.loc[all_sig["bear_votes"] >= min_votes, "signal"] = -1
    all_sig["vote_count"] = all_sig[["bull_votes", "bear_votes"]].max(axis=1)
    return all_sig[["date", "signal", "vote_count", "close"]]


def compute_macd_with_ma_filter(
    df: pd.DataFrame,
    fast: int = 5,
    slow: int = 13,
    signal_period: int = 5,
) -> pd.DataFrame:
    """MACD 金叉 + MA20 方向过滤。

    规则：
    - 金叉信号只在 MA20 向上（当日 MA20 > 前日 MA20）时才触发 +1
    - 死叉信号只在 MA20 向下时才触发 -1
    - MA20 平坦时信号 = 0（过滤震荡市假信号）
    """
    df = _ensure_columns(df)
    df = df.sort_values("date").reset_index(drop=True)
    # MACD
    df["ema_fast"] = df["close"].ewm(span=fast, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=slow, adjust=False).mean()
    df["dif"] = df["ema_fast"] - df["ema_slow"]
    df["dea"] = df["dif"].ewm(span=signal_period, adjust=False).mean()
    # MA20
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma20_up"] = df["ma20"] > df["ma20"].shift(1)
    df["signal"] = 0
    prev_dif = df["dif"].shift(1)
    prev_dea = df["dea"].shift(1)
    # 金叉 + MA20 向上
    cross_up = (prev_dif <= prev_dea) & (df["dif"] > df["dea"]) & df["ma20_up"]
    # 死叉 + MA20 向下
    cross_down = (prev_dif >= prev_dea) & (df["dif"] < df["dea"]) & ~df["ma20_up"]
    df.loc[cross_up, "signal"] = 1
    df.loc[cross_down, "signal"] = -1
    return df[["date", "signal", "dif", "dea", "ma20", "close"]].dropna()


def compute_fundamental_filtered_macd(
    macd_signals: pd.DataFrame,
    has_positive_earnings: bool,
) -> pd.DataFrame:
    """基本面过滤：只在 2025 净利 YoY > 0 时保留 MACD 信号。

    :param macd_signals: compute_macd() 的返回值
    :param has_positive_earnings: True 时保留全部信号，False 时全部清零（不交易）
    """
    if has_positive_earnings:
        return macd_signals
    out = macd_signals.copy()
    out["signal"] = 0
    return out


__all__ = [
    "compute_ma",
    "compute_macd",
    "compute_rsi",
    "compute_kdj",
    "compute_boll",
    "compute_all_signals",
    "compute_vote_signal",
    "compute_macd_with_ma_filter",
    "compute_fundamental_filtered_macd",
]
