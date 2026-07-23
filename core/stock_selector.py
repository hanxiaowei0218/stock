"""
自动选股模块 —— 从指数成分股中筛选候选池。

流程：
1. 取指数成分股（默认沪深300）
2. 逐只拉K线、算指标、评估策略信号
3. 保留出现买入信号（或接近买入）的股票，按信号强度排序取前 N
返回候选列表，附带已算好指标的 DataFrame 供后续复用。
"""
from __future__ import annotations

import config
from core import data_feed, indicators, strategy


def build_candidates(max_size: int | None = None) -> list[dict]:
    """
    返回候选股列表：
    [{code, name, df, signal}]  signal 为 strategy.evaluate 的结果
    只保留 action == 'buy' 的股票，按买入票数降序。
    """
    max_size = max_size or config.MAX_POOL_SIZE
    codes = data_feed.index_constituents(config.INDEX_POOL)
    if not codes:
        print("[selector] 成分股获取失败，跳过选股")
        return []

    candidates = []
    scanned = 0
    for code in codes:
        df = data_feed.get_kline(code, days=120)
        scanned += 1
        if df is None or len(df) < 30:
            continue
        df = indicators.enrich(df, config.STRATEGY_PARAMS)
        sig = strategy.evaluate(df, config.ACTIVE_STRATEGIES,
                                config.STRATEGY_PARAMS, config.BUY_CONSENSUS)
        if sig["action"] == "buy":
            name = data_feed.get_stock_name(code)
            candidates.append({"code": code, "name": name, "df": df, "signal": sig})

    candidates.sort(key=lambda c: c["signal"]["buy_votes"], reverse=True)
    print(f"[selector] 扫描 {scanned} 只，命中买入信号 {len(candidates)} 只")
    return candidates[:max_size]


def evaluate_holdings(holding_codes: list[str]) -> dict:
    """对当前持仓逐只评估卖出信号，返回 {code: signal}。"""
    out = {}
    for code in holding_codes:
        df = data_feed.get_kline(code, days=120)
        if df is None or len(df) < 30:
            continue
        df = indicators.enrich(df, config.STRATEGY_PARAMS)
        out[code] = strategy.evaluate(df, config.ACTIVE_STRATEGIES,
                                      config.STRATEGY_PARAMS, config.BUY_CONSENSUS)
    return out
