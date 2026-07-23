"""
行情数据模块 —— 基于 akshare 免费数据源。

提供：
- 沪深300成分股列表
- 单只股票历史日K线（前复权）
- 单只/批量股票实时快照价格
所有网络请求都带重试与异常兜底，失败返回 None 而非抛出，保证主流程不中断。
"""
from __future__ import annotations

import time
from functools import lru_cache

import pandas as pd
import requests

# 某些网络环境会拒绝非浏览器 UA 的请求，这里全局强制使用浏览器 UA
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_orig_request = requests.Session.request


def _patched_request(self, method, url, **kw):
    headers = kw.get("headers") or {}
    headers["User-Agent"] = _UA
    kw["headers"] = headers
    kw.setdefault("timeout", 8)
    return _orig_request(self, method, url, **kw)


requests.Session.request = _patched_request

try:
    import akshare as ak
except Exception:  # noqa: BLE001
    ak = None

# ============ 离线 mock 开关 ============
# 某些受限网络环境无法稳定访问行情接口；--mock 模式下用确定性随机数据
# 跑通全部交易逻辑，便于本地验证。GitHub Actions 云端通常可直连真实行情。
_MOCK = False


def set_mock(on: bool):
    global _MOCK
    _MOCK = on


def _mock_kline(code: str, days: int = 120) -> pd.DataFrame:
    """确定性随机游走K线（同代码同种子，可复现）。"""
    import numpy as np
    rng = np.random.default_rng(abs(hash(code)) % (2**32))
    n = max(days, 60)
    price = 10 + abs(hash(code)) % 40
    dates = pd.date_range(end=pd.Timestamp.now(), periods=n, freq="B")
    closes, highs, lows, opens, vols = [], [], [], [], []
    for i in range(n):
        chg = rng.normal(0.0008, 0.022)
        c = price * (1 + chg)
        o = price * (1 + rng.normal(0, 0.008))
        hi = max(o, c) * (1 + abs(rng.normal(0, 0.01)))
        lo = min(o, c) * (1 - abs(rng.normal(0, 0.01)))
        v = int(5e5 + abs(rng.normal(0, 2e5)))
        opens.append(round(o, 2)); closes.append(round(c, 2))
        highs.append(round(hi, 2)); lows.append(round(lo, 2)); vols.append(v)
        price = c
    return pd.DataFrame({
        "date": dates, "open": opens, "close": closes,
        "high": highs, "low": lows, "volume": vols,
        "amount": [c * v for c, v in zip(closes, vols)],
        "pct_chg": [0.0] + [round((closes[i] / closes[i - 1] - 1) * 100, 2) for i in range(1, n)],
    })


def _mock_spot(codes: list[str]) -> pd.DataFrame:
    if not codes:
        return pd.DataFrame(columns=["代码", "名称", "最新价", "涨跌幅"])
    rows = []
    for c in codes:
        rng = __import__("numpy").random.default_rng(abs(hash(c)) % (2**32))
        base = 10 + abs(hash(c)) % 40
        price = round(base * (1 + rng.normal(0, 0.02)), 2)
        rows.append({"代码": str(c).zfill(6), "名称": f"模拟股{c[-2:]}", "最新价": price,
                     "涨跌幅": round(rng.normal(0.5, 2.5), 2)})
    return pd.DataFrame(rows)


def _retry(func, *args, tries: int = 2, delay: float = 0.5, **kwargs):
    """通用重试包装，全部失败返回 None。"""
    for i in range(tries):
        try:
            return func(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                print(f"[data_feed] {getattr(func, '__name__', func)} 失败: {e}")
                return None
            time.sleep(delay)
    return None


@lru_cache(maxsize=1)
def index_constituents(index_code: str = "000300") -> tuple:
    """获取指数成分股代码列表（带6位代码）。缓存一次运行内不重复请求。"""
    if _MOCK:
        return tuple(f"6{str(i).zfill(5)}" for i in range(100, 130))
    if ak is None:
        return tuple()
    df = _retry(ak.index_stock_cons, symbol=index_code)
    if df is None or df.empty:
        return tuple()
    col = "品种代码" if "品种代码" in df.columns else df.columns[0]
    codes = [str(c).zfill(6) for c in df[col].tolist()]
    return tuple(codes)


def get_kline(code: str, days: int = 120) -> pd.DataFrame | None:
    """获取单只股票最近 days 根日K线（前复权），标准化列名。"""
    if _MOCK:
        return _mock_kline(code, days)
    if ak is None:
        return None
    end = pd.Timestamp.now().strftime("%Y%m%d")
    start = (pd.Timestamp.now() - pd.Timedelta(days=days * 2 + 40)).strftime("%Y%m%d")
    df = _retry(
        ak.stock_zh_a_hist,
        symbol=code, period="daily",
        start_date=start, end_date=end, adjust="qfq",
    )
    if df is None or df.empty:
        return None
    rename = {
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume",
        "成交额": "amount", "涨跌幅": "pct_chg",
    }
    df = df.rename(columns=rename)
    keep = [c for c in ["date", "open", "close", "high", "low", "volume", "amount", "pct_chg"] if c in df.columns]
    df = df[keep].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df.tail(days).reset_index(drop=True)


@lru_cache(maxsize=1)
def _spot_snapshot() -> pd.DataFrame | None:
    """全市场A股实时快照（一次请求拿全部，避免逐只查询）。"""
    if ak is None:
        return None
    df = _retry(ak.stock_zh_a_spot_em)
    if df is None or df.empty:
        return None
    return df


def get_spot_snapshot() -> pd.DataFrame | None:
    """公开：返回全市场 A 股实时快照（单次请求，运行内缓存）。"""
    if _MOCK:
        codes = [f"6{str(i).zfill(5)}" for i in range(100, 130)]
        return _mock_spot(codes)
    return _spot_snapshot()


def get_realtime_price(code: str) -> float | None:
    """从全市场快照里取单只股票最新价。"""
    df = _mock_spot([code]) if _MOCK else _spot_snapshot()
    if df is None:
        return None
    code6 = str(code).zfill(6)
    row = df[df["代码"] == code6]
    if row.empty:
        return None
    try:
        return float(row.iloc[0]["最新价"])
    except Exception:  # noqa: BLE001
        return None


def get_realtime_batch(codes: list[str]) -> dict[str, float]:
    """批量取最新价，返回 {code: price}。取不到的跳过。"""
    df = _mock_spot(list(codes)) if _MOCK else _spot_snapshot()
    out: dict[str, float] = {}
    if df is None:
        return out
    codes6 = {str(c).zfill(6) for c in codes}
    sub = df[df["代码"].isin(codes6)]
    for _, r in sub.iterrows():
        try:
            out[r["代码"]] = float(r["最新价"])
        except Exception:  # noqa: BLE001
            continue
    return out


def get_stock_name(code: str) -> str:
    """取股票简称，取不到返回代码本身。"""
    df = _mock_spot([code]) if _MOCK else _spot_snapshot()
    if df is None:
        return str(code)
    row = df[df["代码"] == str(code).zfill(6)]
    if row.empty:
        return str(code)
    return str(row.iloc[0].get("名称", code))


def is_trading_day() -> bool:
    """判断今天是否为交易日（用交易日历，失败则按工作日近似）。"""
    if _MOCK:
        return True
    if ak is None:
        return pd.Timestamp.now().weekday() < 5
    df = _retry(ak.tool_trade_date_hist_sina)
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    if df is None:
        return pd.Timestamp.now().weekday() < 5
    dates = {str(d) for d in df["trade_date"].astype(str)}
    return today in dates
