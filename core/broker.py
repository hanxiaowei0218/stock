"""
模拟撮合引擎 —— 按 A 股规则成交。

规则：
- 一手 = 100 股，买入数量向下取整到整手
- T+1：当日买入次日才可卖（由 portfolio.available 控制）
- 涨跌停：涨停不可买、跌停不可卖（用日涨跌幅近似判断）
- 费用：佣金(万2.5,最低5) + 印花税(卖出千0.5) + 过户费
"""
from __future__ import annotations

import config


def _buy_cost(amount: float) -> float:
    commission = max(amount * config.COMMISSION_RATE, config.MIN_COMMISSION)
    transfer = amount * config.TRANSFER_FEE_RATE
    return commission + transfer


def _sell_cost(amount: float) -> float:
    commission = max(amount * config.COMMISSION_RATE, config.MIN_COMMISSION)
    stamp = amount * config.STAMP_TAX_RATE
    transfer = amount * config.TRANSFER_FEE_RATE
    return commission + stamp + transfer


def calc_buy_shares(cash_budget: float, price: float) -> int:
    """在预算内可买的最大整手股数（预留费用）。"""
    if price <= 0:
        return 0
    raw = int(cash_budget / (price * 1.002))       # 粗略预留0.2%费用
    lots = raw // config.LOT_SIZE
    return lots * config.LOT_SIZE


def execute_buy(portfolio, ledger, code, name, price, budget, date, reason="", pct_chg=None):
    """
    尝试买入。返回 (成功?, 说明)。
    budget: 本次可用于该股的资金上限。
    """
    if pct_chg is not None and pct_chg >= config.PRICE_LIMIT * 100 - 0.1:
        return False, "涨停无法买入"

    shares = calc_buy_shares(min(budget, portfolio.cash), price)
    if shares < config.LOT_SIZE:
        return False, "资金不足一手"

    amount = shares * price
    fee = _buy_cost(amount)
    if amount + fee > portfolio.cash:
        shares -= config.LOT_SIZE
        if shares < config.LOT_SIZE:
            return False, "资金不足"
        amount = shares * price
        fee = _buy_cost(amount)

    portfolio.cash -= (amount + fee)
    portfolio.add_position(code, name, shares, price, date)
    ledger.record_trade(
        side="buy", code=code, name=name, price=round(price, 3),
        shares=shares, amount=round(amount, 2), fee=round(fee, 2),
        date=date, reason=reason,
    )
    return True, f"买入 {name}({code}) {shares}股 @ {price:.2f}"


def execute_sell(portfolio, ledger, code, price, date, reason="", pct_chg=None):
    """卖出全部可卖持仓。返回 (成功?, 说明)。"""
    if code not in portfolio.holdings:
        return False, "无持仓"
    h = portfolio.holdings[code]
    sellable = h.get("available", 0)
    if sellable <= 0:
        return False, "无可卖数量(T+1锁定)"
    if pct_chg is not None and pct_chg <= -config.PRICE_LIMIT * 100 + 0.1:
        return False, "跌停无法卖出"

    amount = sellable * price
    fee = _sell_cost(amount)
    cost_basis = h["cost"] * sellable
    pnl = amount - fee - cost_basis

    portfolio.cash += (amount - fee)
    name = h["name"]
    portfolio.reduce_position(code, sellable)
    ledger.record_trade(
        side="sell", code=code, name=name, price=round(price, 3),
        shares=sellable, amount=round(amount, 2), fee=round(fee, 2),
        pnl=round(pnl, 2), date=date, reason=reason,
    )
    return True, f"卖出 {name}({code}) {sellable}股 @ {price:.2f}，盈亏 {pnl:+.2f}"
