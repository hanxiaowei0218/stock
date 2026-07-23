"""
策略引擎 —— 四个经典技术策略。

每个策略输入带指标的 DataFrame，输出对最新一根K线的信号：
  1  = 买入
 -1  = 卖出
  0  = 观望
主函数 evaluate() 汇总多策略共振结果。
"""
from __future__ import annotations

import pandas as pd


def _cross_up(a: pd.Series, b: pd.Series) -> bool:
    """a 上穿 b（前一根 a<=b，最新 a>b）。"""
    if len(a) < 2:
        return False
    return a.iloc[-2] <= b.iloc[-2] and a.iloc[-1] > b.iloc[-1]


def _cross_down(a: pd.Series, b: pd.Series) -> bool:
    if len(a) < 2:
        return False
    return a.iloc[-2] >= b.iloc[-2] and a.iloc[-1] < b.iloc[-1]


def sig_ma_cross(df: pd.DataFrame) -> int:
    """双均线交叉：金叉买入，死叉卖出。"""
    if "ma_fast" not in df or df["ma_slow"].isna().iloc[-1]:
        return 0
    if _cross_up(df["ma_fast"], df["ma_slow"]):
        return 1
    if _cross_down(df["ma_fast"], df["ma_slow"]):
        return -1
    return 0


def sig_macd(df: pd.DataFrame) -> int:
    """MACD：DIF上穿DEA(金叉)买入，下穿卖出。"""
    if "dif" not in df or df["dea"].isna().iloc[-1]:
        return 0
    if _cross_up(df["dif"], df["dea"]):
        return 1
    if _cross_down(df["dif"], df["dea"]):
        return -1
    return 0


def sig_rsi(df: pd.DataFrame, buy: float = 30, sell: float = 70) -> int:
    """RSI：从超卖区回升买入，进入超买区卖出。"""
    if "rsi" not in df or df["rsi"].isna().iloc[-1]:
        return 0
    prev, cur = df["rsi"].iloc[-2], df["rsi"].iloc[-1]
    if prev <= buy < cur:      # 从超卖回升
        return 1
    if cur >= sell:            # 进入超买
        return -1
    return 0


def sig_boll(df: pd.DataFrame) -> int:
    """布林带：触/破下轨买入，触/破上轨卖出。"""
    if "boll_low" not in df or df["boll_low"].isna().iloc[-1]:
        return 0
    close = df["close"].iloc[-1]
    if close <= df["boll_low"].iloc[-1]:
        return 1
    if close >= df["boll_up"].iloc[-1]:
        return -1
    return 0


_DISPATCH = {
    "ma_cross": lambda df, p: sig_ma_cross(df),
    "macd": lambda df, p: sig_macd(df),
    "rsi": lambda df, p: sig_rsi(df, p.get("buy", 30), p.get("sell", 70)),
    "boll": lambda df, p: sig_boll(df),
}


def evaluate(df: pd.DataFrame, active: list[str], params: dict, buy_consensus: int = 2) -> dict:
    """
    汇总多策略信号。
    返回 {'action': 'buy'/'sell'/'hold', 'buy_votes', 'sell_votes', 'reasons': [...]}。
    """
    buy_votes, sell_votes, reasons = 0, 0, []
    for name in active:
        fn = _DISPATCH.get(name)
        if fn is None:
            continue
        s = fn(df, params.get(name, {}))
        if s == 1:
            buy_votes += 1
            reasons.append(f"{name}买入")
        elif s == -1:
            sell_votes += 1
            reasons.append(f"{name}卖出")

    if sell_votes >= 1:                       # 任一卖出信号即考虑卖出（保守）
        action = "sell"
    elif buy_votes >= buy_consensus:          # 需达到共振阈值才买入
        action = "buy"
    else:
        action = "hold"
    return {
        "action": action,
        "buy_votes": buy_votes,
        "sell_votes": sell_votes,
        "reasons": reasons,
    }
