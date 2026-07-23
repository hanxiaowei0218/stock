"""
持仓与账本管理 —— 负责状态的读写与净值计算。

数据文件（JSON，存于 data/）：
- portfolio.json : {cash, holdings:{code:{...}}, created_at}
- trades.json    : [成交记录, ...]
- equity_curve.json : [{date, total, cash, market_value}, ...]
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import config


def _load(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def _save(path: str, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


class Portfolio:
    """账户状态：现金 + 持仓。持仓结构见 buy()。"""

    def __init__(self):
        data = _load(config.PORTFOLIO_FILE, None)
        if data is None:
            self.cash = config.INITIAL_CASH
            self.holdings: dict = {}
            self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            self.cash = data.get("cash", config.INITIAL_CASH)
            self.holdings = data.get("holdings", {})
            self.created_at = data.get("created_at", datetime.now().strftime("%Y-%m-%d"))

    # ---------- 持久化 ----------
    def save(self):
        _save(config.PORTFOLIO_FILE, {
            "cash": round(self.cash, 2),
            "holdings": self.holdings,
            "created_at": self.created_at,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    # ---------- 持仓操作 ----------
    def add_position(self, code, name, shares, price, date):
        """加仓/建仓，自动计算摊薄成本。"""
        if code in self.holdings:
            h = self.holdings[code]
            total_cost = h["cost"] * h["shares"] + price * shares
            h["shares"] += shares
            h["cost"] = round(total_cost / h["shares"], 4)
            h["available"] = h.get("available", 0)   # T+1：当日买入不可卖
        else:
            self.holdings[code] = {
                "name": name, "shares": shares, "cost": round(price, 4),
                "available": 0, "buy_date": date, "last_price": price,
            }

    def reduce_position(self, code, shares):
        """减仓/清仓。"""
        if code not in self.holdings:
            return
        h = self.holdings[code]
        h["shares"] -= shares
        h["available"] = max(0, h.get("available", 0) - shares)
        if h["shares"] <= 0:
            del self.holdings[code]

    def unlock_available(self):
        """新交易日开盘：把昨日及之前买入的持仓全部解锁为可卖（T+1）。"""
        for h in self.holdings.values():
            h["available"] = h["shares"]

    # ---------- 估值 ----------
    def market_value(self, prices: dict) -> float:
        mv = 0.0
        for code, h in self.holdings.items():
            p = prices.get(code, h.get("last_price", h["cost"]))
            h["last_price"] = p
            mv += p * h["shares"]
        return mv

    def total_asset(self, prices: dict) -> float:
        return self.cash + self.market_value(prices)


class Ledger:
    """成交流水 + 净值曲线。"""

    def __init__(self):
        self.trades = _load(config.TRADES_FILE, [])
        self.equity = _load(config.EQUITY_FILE, [])

    def record_trade(self, **kw):
        kw["time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.trades.append(kw)
        _save(config.TRADES_FILE, self.trades)

    def record_equity(self, date, total, cash, market_value):
        # 同一天只保留最后一条
        self.equity = [e for e in self.equity if e.get("date") != date]
        self.equity.append({
            "date": date, "total": round(total, 2),
            "cash": round(cash, 2), "market_value": round(market_value, 2),
        })
        self.equity.sort(key=lambda e: e["date"])
        _save(config.EQUITY_FILE, self.equity)

    def stats(self) -> dict:
        """基础绩效统计。"""
        if not self.equity:
            return {}
        first = self.equity[0]["total"]
        last = self.equity[-1]["total"]
        peak = first
        max_dd = 0.0
        for e in self.equity:
            peak = max(peak, e["total"])
            dd = (e["total"] - peak) / peak if peak else 0
            max_dd = min(max_dd, dd)
        sells = [t for t in self.trades if t.get("side") == "sell" and "pnl" in t]
        wins = [t for t in sells if t["pnl"] > 0]
        return {
            "total_return": round((last / first - 1) * 100, 2) if first else 0,
            "max_drawdown": round(max_dd * 100, 2),
            "trade_count": len(self.trades),
            "win_rate": round(len(wins) / len(sells) * 100, 1) if sells else 0,
            "current_equity": round(last, 2),
        }
