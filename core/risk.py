"""
风险控制模块 —— 优先级高于策略信号。

职责：
1. 持仓止损/止盈检查（触发即强制卖出）
2. 买入前的仓位约束（单股上限、最多持股数、总仓位、现金缓冲）
3. 结合宏观情绪系数动态调节新开仓预算
"""
from __future__ import annotations

import config


def check_stops(portfolio, prices: dict) -> list[dict]:
    """
    遍历持仓，返回需要强制卖出的清单：
    [{code, reason}]  reason ∈ {止损, 止盈}
    """
    actions = []
    for code, h in portfolio.holdings.items():
        price = prices.get(code, h.get("last_price", h["cost"]))
        if h["cost"] <= 0:
            continue
        ret = price / h["cost"] - 1
        if ret <= config.STOP_LOSS:
            actions.append({"code": code, "reason": f"止损({ret*100:.1f}%)"})
        elif ret >= config.TAKE_PROFIT:
            actions.append({"code": code, "reason": f"止盈(+{ret*100:.1f}%)"})
    return actions


def can_open_new(portfolio, prices: dict) -> tuple[bool, str]:
    """是否允许再开新仓（持股数与总仓位约束）。"""
    if len(portfolio.holdings) >= config.MAX_HOLDINGS:
        return False, f"已达最大持股数 {config.MAX_HOLDINGS}"
    total = portfolio.total_asset(prices)
    mv = portfolio.market_value(prices)
    if total > 0 and mv / total >= config.MAX_TOTAL_POSITION:
        return False, "已达最大总仓位"
    return True, ""


def position_budget(portfolio, prices: dict, macro_factor: float = 1.0) -> float:
    """
    计算单只新股票可分配的资金预算。
    = min(单股上限, 剩余可用现金)  再乘以宏观情绪系数。
    macro_factor: 1.0 正常；<1 表示宏观利空日收缩仓位。
    """
    total = portfolio.total_asset(prices)
    per_stock_cap = total * config.MAX_POSITION_PER_STOCK
    # 保留现金缓冲
    investable = total * config.MAX_TOTAL_POSITION - portfolio.market_value(prices)
    budget = min(per_stock_cap, investable, portfolio.cash)
    budget *= macro_factor
    return max(0.0, budget)
