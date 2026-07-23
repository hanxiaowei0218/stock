"""
自动选股模块 —— 从指数成分股中筛选候选池。

流程：
1. 取指数成分股（默认沪深300）
2. 逐只拉K线、算指标、评估策略信号
3. 保留出现买入信号（或接近买入）的股票，按信号强度排序取前 N
返回候选列表，附带已算好指标的 DataFrame 供后续复用。
"""
from __future__ import annotations

import time

import config
from core import data_feed, indicators, strategy


def build_candidates(max_size: int | None = None) -> list[dict]:
    """
    返回候选股列表：
    [{code, name, df, signal}]  signal 为 strategy.evaluate 的结果
    只保留 action == 'buy' 的股票，按买入票数降序。

    性能优化：先用「一次全市场快照」做流动性/涨跌幅预筛，
    只对初选出的约 40 只拉 K 线算技术信号，避免对 300 只成分股
    逐只联网拉 K 线导致单次运行超时。
    """
    max_size = max_size or config.MAX_POOL_SIZE
    codes = data_feed.index_constituents(config.INDEX_POOL)
    if not codes:
        print("[selector] 成分股获取失败，跳过选股")
        return []

    # 1) 一次快照预筛（仅 1 次网络请求）
    code_set = {str(c).zfill(6) for c in codes}
    shortlist = _prefilter(code_set)
    if not shortlist:
        shortlist = list(codes)[: config.MAX_POOL_SIZE + 12]   # 快照失败退化为限量扫描

    # 2) 仅对 shortlist 拉 K 线 + 算策略信号
    candidates = []
    scanned = 0
    t0 = time.time()
    TIME_BUDGET = 540  # 秒；单次运行总时间预算（工作流 25 分钟），留足后续提交
    for code in shortlist:
        if time.time() - t0 > TIME_BUDGET:
            print(f"[selector] 已达时间预算，停止扫描（已扫 {scanned} 只）")
            break
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


def _prefilter(code_set: set) -> list:
    """用一次全市场快照，按流动性/涨跌幅初筛候选。"""
    snap = data_feed.get_spot_snapshot()
    if snap is None or snap.empty:
        print("[selector] 快照获取失败，退化为限量扫描")
        return []
    snap = snap.copy()
    snap["_code"] = snap["代码"].astype(str).str.zfill(6)
    sub = snap[snap["_code"].isin(code_set)]
    if sub.empty:
        return []
    chg_col = "涨跌幅" if "涨跌幅" in sub.columns else None
    vol_col = "成交量" if "成交量" in sub.columns else None
    if chg_col:
        # 排除接近跌停（卖不出）与已涨停（买不进）的标的
        sub = sub[sub[chg_col].between(-9.0, 9.0)]
    if vol_col:
        sub = sub.sort_values(vol_col, ascending=False)
    n = min(config.MAX_POOL_SIZE, 40)
    return sub["_code"].tolist()[:n]


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
