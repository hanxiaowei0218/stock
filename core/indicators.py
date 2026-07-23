"""
技术指标计算 —— 纯 pandas 实现，不依赖网络。

输入均为按时间升序排列、含 'close'/'high'/'low'/'volume' 列的 DataFrame。
"""
from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    """简单移动平均。"""
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """指数移动平均。"""
    return series.ewm(span=period, adjust=False).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """返回 (dif, dea, macd_hist)。"""
    dif = ema(close, fast) - ema(close, slow)
    dea = ema(dif, signal)
    hist = (dif - dea) * 2
    return dif, dea, hist


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """相对强弱指标 RSI (Wilder 平滑)。"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def bollinger(close: pd.Series, period: int = 20, std: float = 2.0):
    """返回 (中轨, 上轨, 下轨)。"""
    mid = sma(close, period)
    sd = close.rolling(window=period, min_periods=period).std()
    upper = mid + std * sd
    lower = mid - std * sd
    return mid, upper, lower


def enrich(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """给K线DataFrame附加所有需要用到的指标列，返回新DataFrame。"""
    df = df.copy()
    close = df["close"]

    ma = params.get("ma_cross", {"fast": 5, "slow": 20})
    df["ma_fast"] = sma(close, ma["fast"])
    df["ma_slow"] = sma(close, ma["slow"])

    m = params.get("macd", {"fast": 12, "slow": 26, "signal": 9})
    df["dif"], df["dea"], df["macd_hist"] = macd(close, m["fast"], m["slow"], m["signal"])

    r = params.get("rsi", {"period": 14})
    df["rsi"] = rsi(close, r["period"])

    b = params.get("boll", {"period": 20, "std": 2.0})
    df["boll_mid"], df["boll_up"], df["boll_low"] = bollinger(close, b["period"], b["std"])

    return df


def trend_summary(df: pd.DataFrame) -> dict:
    """给出一段K线最新状态的走势摘要，供分析/展示用。"""
    if df is None or len(df) < 2:
        return {"trend": "数据不足", "detail": ""}
    last = df.iloc[-1]
    prev = df.iloc[-2]
    parts = []

    if "ma_fast" in df and pd.notna(last.get("ma_fast")) and pd.notna(last.get("ma_slow")):
        if last["ma_fast"] > last["ma_slow"]:
            parts.append("短均线在长均线之上(多头)")
        else:
            parts.append("短均线在长均线之下(空头)")

    if "rsi" in df and pd.notna(last.get("rsi")):
        rv = last["rsi"]
        if rv >= 70:
            parts.append(f"RSI={rv:.0f} 超买")
        elif rv <= 30:
            parts.append(f"RSI={rv:.0f} 超卖")
        else:
            parts.append(f"RSI={rv:.0f} 中性")

    if "macd_hist" in df and pd.notna(last.get("macd_hist")):
        if last["macd_hist"] > 0 and prev.get("macd_hist", 0) <= 0:
            parts.append("MACD金叉")
        elif last["macd_hist"] < 0 and prev.get("macd_hist", 0) >= 0:
            parts.append("MACD死叉")

    pct = (last["close"] / prev["close"] - 1) * 100 if prev["close"] else 0
    trend = "上涨" if pct > 0 else ("下跌" if pct < 0 else "持平")
    return {"trend": trend, "pct": round(pct, 2), "detail": "，".join(parts)}
