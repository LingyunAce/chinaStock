"""回测运行器 — 不用 backtrader，纯 pandas 实现信号回测。

避免 backtrader 的 date index 匹配问题，用最简单的方式回测：
对每个信号日，按收盘价买卖，计算收益。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def run_backtest(
    signal_map: dict[str, int],
    data_df: pd.DataFrame,
    initial_cash: float = 1_000_000.0,
    commission: float = 0.001,
    slippage: float = 0.0005,
) -> dict:
    """运行纯信号回测（无 backtrader 依赖）。

    :param signal_map: {date_str: signal} 其中 signal ∈ {-1, 0, 1}
    :param data_df: OHLCV DataFrame (含 date/open/close)
    :param initial_cash: 初始资金
    :param commission: 手续费率
    :param slippage: 滑点
    :return: 回测指标字典
    """
    df = data_df.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values("date").reset_index(drop=True)
    for col in ("open", "close", "high", "low", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"])

    # 逐日模拟
    cash = initial_cash
    position = 0
    buy_price = 0.0
    trades = []
    equity_curve = []

    for _, row in df.iterrows():
        date = row["date"]
        close = row["close"]
        open_price = row.get("open", close)
        sig = signal_map.get(date, 0)

        # 执行信号（用开盘价模拟，更真实）
        if sig > 0 and position == 0:
            # 买入
            exec_price = open_price * (1 + slippage)
            shares = int(cash * 0.95 / exec_price)  # 留 5% 现金
            if shares > 0:
                cost = shares * exec_price * (1 + commission)
                cash -= cost
                position = shares
                buy_price = exec_price
                trades.append(
                    {"date": date, "type": "buy", "price": exec_price, "shares": shares}
                )

        elif sig < 0 and position > 0:
            # 卖出
            exec_price = open_price * (1 - slippage)
            revenue = position * exec_price * (1 - commission)
            pnl = (exec_price - buy_price) / buy_price * 100
            cash += revenue
            trades.append(
                {
                    "date": date,
                    "type": "sell",
                    "price": exec_price,
                    "shares": position,
                    "pnl_pct": pnl,
                }
            )
            position = 0
            buy_price = 0.0

        # 记录净值
        equity = cash + position * close
        equity_curve.append({"date": date, "equity": equity})

    # 计算指标
    eq = pd.DataFrame(equity_curve)
    if eq.empty:
        return _empty_result(initial_cash, 0)

    eq["returns"] = eq["equity"].pct_change()
    total_return = (eq["equity"].iloc[-1] / initial_cash - 1) * 100
    trading_days = len(eq)
    years = trading_days / 252
    annual_return = (
        ((1 + total_return / 100) ** (1 / years) - 1) * 100
        if years > 0 and total_return > -100
        else 0
    )

    # Sharpe
    daily_returns = eq["returns"].dropna()
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        sharpe = (
            (daily_returns.mean() - 0.02 / 252) / daily_returns.std() * np.sqrt(252)
        )
    else:
        sharpe = 0.0

    # 最大回撤
    eq["cummax"] = eq["equity"].cummax()
    eq["drawdown"] = (eq["equity"] - eq["cummax"]) / eq["cummax"] * 100
    max_dd = abs(eq["drawdown"].min())

    # 胜率
    sell_trades = [t for t in trades if t["type"] == "sell"]
    total_trades = len(sell_trades)
    won = len([t for t in sell_trades if t.get("pnl_pct", 0) > 0])
    win_rate = (won / total_trades * 100) if total_trades > 0 else 0

    # 盈亏比
    avg_win = (
        np.mean([t["pnl_pct"] for t in sell_trades if t.get("pnl_pct", 0) > 0])
        if won > 0
        else 0
    )
    losses = [abs(t["pnl_pct"]) for t in sell_trades if t.get("pnl_pct", 0) <= 0]
    avg_loss = np.mean(losses) if losses else 1
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0

    return {
        "total_return": round(total_return, 2),
        "annual_return": round(annual_return, 2),
        "sharpe": round(sharpe, 3),
        "max_drawdown": round(max_dd, 2),
        "total_trades": total_trades,
        "win_rate": round(win_rate, 1),
        "profit_loss_ratio": round(profit_loss_ratio, 2),
        "final_value": round(eq["equity"].iloc[-1], 2),
        "initial_cash": initial_cash,
        "trading_days": trading_days,
    }


def _empty_result(initial_cash: float, trading_days: int) -> dict:
    return {
        "total_return": 0.0,
        "annual_return": 0.0,
        "sharpe": 0.0,
        "max_drawdown": 0.0,
        "total_trades": 0,
        "win_rate": 0.0,
        "profit_loss_ratio": 0.0,
        "final_value": initial_cash,
        "initial_cash": initial_cash,
        "trading_days": trading_days,
    }


__all__ = ["run_backtest"]
