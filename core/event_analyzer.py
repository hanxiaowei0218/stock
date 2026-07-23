"""
事件驱动分析模块 —— 两条链路。

链路一 · 宏观新闻事件（防御性自动动作）：
  采集财联社电报 → 关键词情感打分 → 得出「宏观情绪系数」(0.5~1.0)
  强利空日返回 <1 的系数，用于收缩当日新开仓仓位。

链路二 · 热点联动事件（只提醒不自动买）：
  采集概念板块实时涨幅+资金流 → 找异动板块龙头 → 生成提醒卡片
  卡片强制包含：关联逻辑、时效窗口、熄火信号、不确定性等级。

所有网络请求失败都安全兜底，不影响主交易流程。
"""
from __future__ import annotations

from datetime import datetime

import config

try:
    import akshare as ak
except Exception:  # noqa: BLE001
    ak = None


# 情感词典（精简版，可扩充）
BULLISH_WORDS = [
    "利好", "增长", "超预期", "宽松", "降准", "降息", "刺激", "复苏", "回暖",
    "支持", "扶持", "减税", "创新高", "大涨", "提振", "突破", "订单", "中标",
]
BEARISH_WORDS = [
    "利空", "下滑", "低于预期", "收紧", "加息", "违约", "风险", "暴跌", "衰退",
    "制裁", "调查", "处罚", "退市", "减持", "亏损", "下调", "警告", "冲突", "战争",
]


def macro_sentiment() -> dict:
    """
    链路一：返回宏观情绪。
    {
      'factor': 0.5~1.0,          # 新开仓预算乘数
      'label': '偏多/中性/偏空/强利空',
      'score': int,               # 多空词净值
      'headlines': [前若干条影响较大的新闻标题],
    }
    """
    result = {"factor": 1.0, "label": "中性", "score": 0, "headlines": []}
    if not config.ENABLE_MACRO or ak is None:
        return result

    df = None
    for fn in ("stock_info_global_cls", "stock_info_cjzc_em", "stock_info_global_em"):
        try:
            func = getattr(ak, fn, None)
            if func is None:
                continue
            df = func()
            if df is not None and not df.empty:
                break
        except Exception:  # noqa: BLE001
            continue
    if df is None or df.empty:
        return result

    # 找到标题/内容列
    text_col = None
    for c in ["标题", "内容", "title", "content", "摘要"]:
        if c in df.columns:
            text_col = c
            break
    if text_col is None:
        text_col = df.columns[0]

    texts = df[text_col].astype(str).head(50).tolist()
    score = 0
    hot = []
    for t in texts:
        b = sum(w in t for w in BULLISH_WORDS)
        s = sum(w in t for w in BEARISH_WORDS)
        score += b - s
        if b - s != 0:
            hot.append({"text": t[:60], "tone": "利好" if b > s else "利空"})

    result["score"] = score
    result["headlines"] = hot[:6]
    if score >= 4:
        result.update(factor=1.0, label="偏多")
    elif score <= -6:
        result.update(factor=config.MACRO_BEARISH_CUT, label="强利空")
    elif score <= -3:
        result.update(factor=0.75, label="偏空")
    else:
        result.update(factor=1.0, label="中性")
    return result


def hotspot_alerts() -> list[dict]:
    """
    链路二：热点联动提醒（只提醒不自动买）。
    返回提醒卡片列表，每张卡片：
    {
      'concept': 板块名, 'change': 涨幅%, 'leader': 龙头股名,
      'leader_code': 代码, 'logic': 联动逻辑说明,
      'ttl': 时效(交易日), 'fade_signal': 熄火信号, 'uncertainty': 不确定性等级,
      'timestamp'
    }
    """
    alerts: list[dict] = []
    if not config.ENABLE_HOTSPOT or ak is None:
        return alerts

    try:
        board = ak.stock_board_concept_name_em()
    except Exception:  # noqa: BLE001
        return alerts
    if board is None or board.empty:
        return alerts

    chg_col = "涨跌幅" if "涨跌幅" in board.columns else None
    name_col = "板块名称" if "板块名称" in board.columns else board.columns[0]
    if chg_col is None:
        return alerts

    board = board.sort_values(chg_col, ascending=False)
    hot = board[board[chg_col] >= config.HOTSPOT_HEAT_THRESHOLD].head(5)

    for _, row in hot.iterrows():
        concept = str(row[name_col])
        change = float(row[chg_col])
        leader_name, leader_code = _find_leader(concept)
        uncertainty = "极高" if change >= 6 else ("高" if change >= 4 else "中")
        alerts.append({
            "concept": concept,
            "change": round(change, 2),
            "leader": leader_name,
            "leader_code": leader_code,
            "logic": f"「{concept}」概念今日整体大涨 {change:.1f}%，属热度驱动的资金抱团；"
                     f"龙头 {leader_name} 领涨，若为消息/人物走红催化，需辨别是启动初期还是高位接力。",
            "ttl": config.HOTSPOT_TTL_DAYS,
            "fade_signal": "放量滞涨、龙头炸板、板块涨幅收窄或资金净流出即为熄火信号",
            "uncertainty": uncertainty,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
    return alerts


def _find_leader(concept: str):
    """取概念板块内涨幅第一的成分股作为龙头。失败返回占位。"""
    try:
        cons = ak.stock_board_concept_cons_em(symbol=concept)
        if cons is not None and not cons.empty and "涨跌幅" in cons.columns:
            top = cons.sort_values("涨跌幅", ascending=False).iloc[0]
            code = str(top.get("代码", "")).zfill(6)
            name = str(top.get("名称", ""))
            return name, code
    except Exception:  # noqa: BLE001
        pass
    return "（龙头识别失败）", ""
