"""
主调度 —— 每次运行执行一轮完整决策流程。

流程：
1. 交易日/时段检查
2. 事件面：宏观情绪系数 + 热点提醒
3. 解锁 T+1 可卖持仓
4. 风控优先：止损/止盈强制卖出
5. 策略卖出：持仓出现卖出信号
6. 策略买入：自动选股候选池 → 风控约束 → 模拟买入（受宏观系数调节）
7. 更新净值、保存事件、生成仪表盘

用法：
  python main.py            # 正常运行（自动跳过非交易时段）
  python main.py --force    # 忽略时段限制，强制跑一轮（测试用）
  python main.py --seed     # 用少量样本股票快速自检（不依赖选股全量扫描）
  python main.py --mock     # 离线模拟数据自检（无需网络，验证全部交易逻辑）
"""
from __future__ import annotations

import sys
from datetime import datetime

import config
from core import (broker, dashboard, data_feed, event_analyzer, indicators,
                  portfolio as pf, risk, stock_selector, strategy)


def in_trading_window() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    morning = 9 * 60 + 25 <= t <= 11 * 60 + 35
    afternoon = 13 * 60 <= t <= 15 * 60 + 5
    return morning or afternoon


def run(force: bool = False, seed: bool = False, mock: bool = False):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"===== 运行开始 {now} =====")

    if mock:
        data_feed.set_mock(True)
        print("[mode] 离线mock模式：使用模拟行情验证交易逻辑")

    if not force and not seed and not mock:
        if not data_feed.is_trading_day():
            print("今日非交易日，跳过。")
            return
        if not in_trading_window():
            print("当前非交易时段，跳过。")
            return

    portfolio = pf.Portfolio()
    ledger = pf.Ledger()

    # ---- 1. 事件面 ----
    if mock:
        macro = {"factor": 1.0, "label": "中性", "score": 0, "headlines": [
            {"text": "（mock示例）央行开展逆回购操作，维护流动性合理充裕", "tone": "利好"}]}
        alerts = [{
            "concept": "（mock示例）某人物走红概念", "change": 5.6,
            "leader": "模拟龙头股", "leader_code": "600000",
            "logic": "「某人物走红概念」今日整体大涨 5.6%，属热度驱动的资金抱团；龙头领涨，需辨别是启动初期还是高位接力。",
            "ttl": 3, "fade_signal": "放量滞涨、龙头炸板、板块涨幅收窄或资金净流出即为熄火信号",
            "uncertainty": "高", "timestamp": now[:16],
        }]
    else:
        macro = event_analyzer.macro_sentiment()
        alerts = event_analyzer.hotspot_alerts()
    print(f"[event] 宏观情绪={macro['label']} 系数={macro['factor']}；热点提醒 {len(alerts)} 条")

    # ---- 2. T+1 解锁 ----
    portfolio.unlock_available()

    # ---- 3. 汇总持仓与候选股所需的实时价 ----
    hold_codes = list(portfolio.holdings.keys())
    if seed:
        candidates = _seed_candidates()
    else:
        candidates = stock_selector.build_candidates()
    if mock and not candidates:
        # mock自检：随机行情可能无共振信号，强制取2只走通买入链路
        codes = list(data_feed.index_constituents(config.INDEX_POOL))[:2]
        for code in codes:
            df = data_feed.get_kline(code, 120)
            candidates.append({"code": code, "name": data_feed.get_stock_name(code),
                               "df": df, "signal": {"action": "buy", "buy_votes": 2,
                                                    "sell_votes": 0, "reasons": ["mock验证"]}})
    cand_codes = [c["code"] for c in candidates]
    prices = data_feed.get_realtime_batch(list(set(hold_codes + cand_codes)))
    # 补齐持仓价（用K线收盘兜底）
    for code in hold_codes:
        if code not in prices:
            df = data_feed.get_kline(code, 5)
            if df is not None and len(df):
                prices[code] = float(df["close"].iloc[-1])

    # ---- 4. 风控：止损/止盈 ----
    for act in risk.check_stops(portfolio, prices):
        code = act["code"]
        price = prices.get(code)
        if price:
            ok, msg = broker.execute_sell(portfolio, ledger, code, price, today,
                                          reason=f"风控-{act['reason']}")
            print(f"[risk] {msg}" if ok else f"[risk] 卖出失败:{msg}")

    # ---- 5. 策略卖出 ----
    hold_signals = stock_selector.evaluate_holdings(list(portfolio.holdings.keys()))
    for code, sig in hold_signals.items():
        if sig["action"] == "sell" and code in prices:
            ok, msg = broker.execute_sell(portfolio, ledger, code, prices[code], today,
                                          reason="策略-" + "/".join(sig["reasons"][:2]))
            print(f"[sell] {msg}" if ok else f"[sell] {msg}")

    # ---- 6. 策略买入（受宏观系数调节） ----
    for c in candidates:
        code = c["code"]
        if code in portfolio.holdings:
            continue
        ok_open, why = risk.can_open_new(portfolio, prices)
        if not ok_open:
            print(f"[buy] 停止开新仓：{why}")
            break
        price = prices.get(code)
        if not price:
            continue
        budget = risk.position_budget(portfolio, prices, macro["factor"])
        if budget < price * config.LOT_SIZE:
            continue
        reason = "策略-" + "/".join(c["signal"]["reasons"][:2])
        if macro["factor"] < 1:
            reason += f"(宏观{macro['label']}降仓)"
        ok, msg = broker.execute_buy(portfolio, ledger, code, c["name"], price,
                                     budget, today, reason=reason)
        print(f"[buy] {msg}" if ok else f"[buy] {msg}")

    # ---- 7. 收尾：净值 / 事件 / 仪表盘 ----
    portfolio.save()
    total = portfolio.total_asset(prices)
    ledger.record_equity(today, total, portfolio.cash, portfolio.market_value(prices))

    import json, os
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(config.EVENTS_FILE, "w", encoding="utf-8") as f:
        json.dump({"macro": macro, "alerts": alerts,
                   "updated_at": now}, f, ensure_ascii=False, indent=2)

    dashboard.generate(prices=prices, macro=macro, alerts=alerts)
    stats = ledger.stats()
    print(f"[done] 总资产 ¥{total:,.2f} 收益率 {stats.get('total_return',0)}% "
          f"持仓 {len(portfolio.holdings)} 只 现金 ¥{portfolio.cash:,.2f}")
    print("===== 运行结束 =====")


def _seed_candidates():
    """自检用：直接用几只权重股，跳过全量扫描。"""
    seed_codes = ["600519", "000858", "601318", "600036", "000333"]
    out = []
    for code in seed_codes:
        df = data_feed.get_kline(code, 120)
        if df is None or len(df) < 30:
            continue
        df = indicators.enrich(df, config.STRATEGY_PARAMS)
        sig = strategy.evaluate(df, config.ACTIVE_STRATEGIES,
                                config.STRATEGY_PARAMS, config.BUY_CONSENSUS)
        name = data_feed.get_stock_name(code)
        # 自检时放宽：无论信号都放入，方便验证买入链路
        sig["_seed"] = True
        out.append({"code": code, "name": name, "df": df, "signal": sig})
    return out


if __name__ == "__main__":
    args = set(sys.argv[1:])
    run(force="--force" in args, seed="--seed" in args, mock="--mock" in args)
