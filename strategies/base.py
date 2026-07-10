"""Pure-pandas A-share backtest with next-session signal execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 1_000_000.0
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    stamp_duty_rate: float = 0.0005
    slippage: float = 0.0005
    lot_size: int = 100
    allocation: float = 0.95
    symbol: str | None = None
    is_st: bool = False
    min_annualization_days: int = 60


@dataclass
class _PortfolioState:
    cash: float
    shares: int = 0
    entry_total_cost: float = 0.0
    buy_date: str | None = None


def _price_limit_pct(symbol: str | None, is_st: bool) -> float:
    if is_st:
        return 0.05
    normalized = (symbol or "").upper()
    code = normalized.removeprefix("SH").removeprefix("SZ").removeprefix("BJ")
    if normalized.startswith("BJ") or code.startswith(("4", "8", "92")):
        return 0.30
    if code.startswith(("300", "301", "688", "689")):
        return 0.20
    return 0.10


def _limit_price(previous_close: float, change: float) -> float:
    value = Decimal(str(previous_close)) * (Decimal("1") + Decimal(str(change)))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _commission(notional: float, config: BacktestConfig) -> float:
    if notional <= 0:
        return 0.0
    return max(notional * config.commission_rate, config.minimum_commission)


def _round_lot(shares: float, lot_size: int) -> int:
    return max(0, int(shares) // lot_size * lot_size)


def _record_rejection(
    rejected_orders: list[dict], pending: dict, date: str, reason: str
) -> None:
    rejected_orders.append(
        {
            "signal_date": pending["signal_date"],
            "date": date,
            "side": pending["side"],
            "reason": reason,
        }
    )


def _attempt_pending_order(
    *,
    pending: dict,
    row: pd.Series,
    previous_close: float | None,
    state: _PortfolioState,
    config: BacktestConfig,
    trades: list[dict],
    rejected_orders: list[dict],
) -> dict | None:
    date = str(row["date"])
    open_price = float(row["open"])
    volume = float(row["volume"])
    side = pending["side"]

    if not np.isfinite(open_price) or open_price <= 0 or volume <= 0:
        _record_rejection(
            rejected_orders, pending, date, "suspended_or_no_volume"
        )
        return pending

    symbol = config.symbol or row.get("symbol")
    if previous_close is not None and np.isfinite(previous_close):
        limit_pct = _price_limit_pct(str(symbol) if symbol else None, config.is_st)
        upper = _limit_price(float(previous_close), limit_pct)
        lower = _limit_price(float(previous_close), -limit_pct)
        if side == "buy" and open_price >= upper:
            _record_rejection(rejected_orders, pending, date, "limit_up")
            return pending
        if side == "sell" and open_price <= lower:
            _record_rejection(rejected_orders, pending, date, "limit_down")
            return pending

    if side == "buy":
        if state.shares > 0:
            _record_rejection(rejected_orders, pending, date, "already_in_position")
            return None
        execution_price = open_price * (1 + config.slippage)
        shares = _round_lot(
            state.cash * config.allocation / execution_price, config.lot_size
        )
        while shares > 0:
            notional = shares * execution_price
            commission = _commission(notional, config)
            if notional + commission <= state.cash:
                break
            shares -= config.lot_size
        if shares <= 0:
            _record_rejection(rejected_orders, pending, date, "insufficient_cash")
            return None
        notional = shares * execution_price
        commission = _commission(notional, config)
        total_cost = notional + commission
        state.cash -= total_cost
        state.shares = shares
        state.entry_total_cost = total_cost
        state.buy_date = date
        trades.append(
            {
                "signal_date": pending["signal_date"],
                "date": date,
                "type": "buy",
                "price": execution_price,
                "shares": shares,
                "commission": commission,
                "stamp_duty": 0.0,
            }
        )
        return None

    if state.shares <= 0:
        _record_rejection(rejected_orders, pending, date, "no_position")
        return None
    if state.buy_date == date:
        _record_rejection(rejected_orders, pending, date, "t_plus_one")
        return pending

    execution_price = open_price * (1 - config.slippage)
    notional = state.shares * execution_price
    commission = _commission(notional, config)
    stamp_duty = notional * config.stamp_duty_rate
    net_revenue = notional - commission - stamp_duty
    pnl_pct = (
        (net_revenue - state.entry_total_cost) / state.entry_total_cost * 100
        if state.entry_total_cost > 0
        else 0.0
    )
    shares = state.shares
    state.cash += net_revenue
    trades.append(
        {
            "signal_date": pending["signal_date"],
            "date": date,
            "type": "sell",
            "price": execution_price,
            "shares": shares,
            "commission": commission,
            "stamp_duty": stamp_duty,
            "pnl_pct": pnl_pct,
        }
    )
    state.shares = 0
    state.entry_total_cost = 0.0
    state.buy_date = None
    return None


def _buy_hold_return(df: pd.DataFrame, config: BacktestConfig) -> float:
    tradable = df[(df["volume"] > 0) & (df["open"] > 0)]
    if tradable.empty:
        return 0.0
    first = tradable.iloc[0]
    execution_price = float(first["open"]) * (1 + config.slippage)
    shares = _round_lot(
        config.initial_cash * config.allocation / execution_price,
        config.lot_size,
    )
    while shares > 0:
        notional = shares * execution_price
        commission = _commission(notional, config)
        if notional + commission <= config.initial_cash:
            break
        shares -= config.lot_size
    if shares <= 0:
        return 0.0
    cost = shares * execution_price + _commission(shares * execution_price, config)
    final_value = config.initial_cash - cost + shares * float(df.iloc[-1]["close"])
    return (final_value / config.initial_cash - 1) * 100


def run_backtest(
    signal_map: dict[str, int],
    data_df: pd.DataFrame,
    initial_cash: float = 1_000_000.0,
    commission: float = 0.0003,
    slippage: float = 0.0005,
    *,
    config: BacktestConfig | None = None,
) -> dict:
    """Run close-signal orders at the next tradable session open."""

    cfg = config or BacktestConfig(
        initial_cash=initial_cash,
        commission_rate=commission,
        slippage=slippage,
    )
    df = data_df.copy()
    if "date" not in df.columns or "close" not in df.columns:
        return _empty_result(cfg, 0)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )
    if "open" not in df.columns:
        df["open"] = df["close"]
    if "volume" not in df.columns:
        df["volume"] = 0
    for column in ("open", "close", "high", "low", "volume"):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["date", "open", "close"]).sort_values("date")
    df = df.reset_index(drop=True)
    if df.empty:
        return _empty_result(cfg, 0)

    state = _PortfolioState(cash=cfg.initial_cash)
    trades: list[dict] = []
    rejected_orders: list[dict] = []
    equity_curve: list[dict] = []
    pending: dict | None = None

    for index, row in df.iterrows():
        if pending is not None:
            previous_close = float(df.iloc[index - 1]["close"]) if index else None
            pending = _attempt_pending_order(
                pending=pending,
                row=row,
                previous_close=previous_close,
                state=state,
                config=cfg,
                trades=trades,
                rejected_orders=rejected_orders,
            )

        equity_curve.append(
            {
                "date": row["date"],
                "equity": state.cash + state.shares * float(row["close"]),
            }
        )

        signal = int(signal_map.get(row["date"], 0))
        if signal:
            if pending is not None:
                _record_rejection(
                    rejected_orders, pending, row["date"], "replaced_by_new_signal"
                )
            pending = {
                "signal_date": row["date"],
                "side": "buy" if signal > 0 else "sell",
            }

    equity = pd.DataFrame(equity_curve)
    total_return = (equity["equity"].iloc[-1] / cfg.initial_cash - 1) * 100
    trading_days = len(equity)
    equity["returns"] = equity["equity"].pct_change()

    annual_return: float | None = None
    sharpe: float | None = None
    if trading_days >= cfg.min_annualization_days:
        years = trading_days / 252
        if total_return > -100:
            annual_return = ((1 + total_return / 100) ** (1 / years) - 1) * 100
        daily_returns = equity["returns"].dropna()
        if len(daily_returns) > 1 and daily_returns.std() > 0:
            sharpe = (
                (daily_returns.mean() - 0.02 / 252)
                / daily_returns.std()
                * np.sqrt(252)
            )

    equity["cummax"] = equity["equity"].cummax()
    equity["drawdown"] = (
        (equity["equity"] - equity["cummax"]) / equity["cummax"] * 100
    )
    max_drawdown = abs(float(equity["drawdown"].min()))

    closed = [trade for trade in trades if trade["type"] == "sell"]
    win_rate: float | None = None
    profit_loss_ratio: float | None = None
    if closed:
        wins = [trade["pnl_pct"] for trade in closed if trade["pnl_pct"] > 0]
        losses = [abs(trade["pnl_pct"]) for trade in closed if trade["pnl_pct"] <= 0]
        win_rate = len(wins) / len(closed) * 100
        if wins and losses and np.mean(losses) > 0:
            profit_loss_ratio = float(np.mean(wins) / np.mean(losses))

    buy_hold_return = _buy_hold_return(df, cfg)
    open_position = None
    if state.shares > 0:
        current_value = state.shares * float(df.iloc[-1]["close"])
        open_position = {
            "shares": state.shares,
            "buy_date": state.buy_date,
            "cost": state.entry_total_cost,
            "market_value": current_value,
            "unrealized_pnl": current_value - state.entry_total_cost,
        }

    return {
        "total_return": round(float(total_return), 2),
        "annual_return": round(float(annual_return), 2)
        if annual_return is not None
        else None,
        "sharpe": round(float(sharpe), 3) if sharpe is not None else None,
        "max_drawdown": round(max_drawdown, 2),
        "total_trades": len(closed),
        "win_rate": round(win_rate, 1) if win_rate is not None else None,
        "profit_loss_ratio": round(profit_loss_ratio, 2)
        if profit_loss_ratio is not None
        else None,
        "final_value": round(float(equity["equity"].iloc[-1]), 2),
        "initial_cash": cfg.initial_cash,
        "trading_days": trading_days,
        "buy_hold_return": round(float(buy_hold_return), 2),
        "excess_return": round(float(total_return - buy_hold_return), 2),
        "trades": trades,
        "rejected_orders": rejected_orders,
        "open_position": open_position,
        "config": asdict(cfg),
    }


def _empty_result(config: BacktestConfig, trading_days: int) -> dict:
    return {
        "total_return": 0.0,
        "annual_return": None,
        "sharpe": None,
        "max_drawdown": 0.0,
        "total_trades": 0,
        "win_rate": None,
        "profit_loss_ratio": None,
        "final_value": config.initial_cash,
        "initial_cash": config.initial_cash,
        "trading_days": trading_days,
        "buy_hold_return": 0.0,
        "excess_return": 0.0,
        "trades": [],
        "rejected_orders": [],
        "open_position": None,
        "config": asdict(config),
    }


__all__ = ["BacktestConfig", "run_backtest"]
