"""
全局配置 —— A股智能模拟交易系统

所有可调参数集中在此。修改后下次运行即生效。
"""
from __future__ import annotations

# ============ 资金与账户 ============
INITIAL_CASH = 100_000.0          # 初始虚拟本金（元）
COMMISSION_RATE = 0.00025         # 佣金费率（双边，万2.5，最低5元）
MIN_COMMISSION = 5.0              # 单笔最低佣金
STAMP_TAX_RATE = 0.0005           # 印花税（仅卖出收取，千0.5）
TRANSFER_FEE_RATE = 0.00001       # 过户费（沪深双边，十万分之一）

# ============ 股票池 ============
# 从哪个指数的成分股里自动选股
INDEX_POOL = "000300"             # 沪深300
MAX_POOL_SIZE = 40                # 候选池最大数量（选股后保留信号最强的前N只）

# ============ 策略 ============
# 可选：ma_cross / macd / rsi / boll ；多个策略同时启用时取共振信号
ACTIVE_STRATEGIES = ["ma_cross", "macd", "rsi"]
STRATEGY_PARAMS = {
    "ma_cross": {"fast": 5, "slow": 20},        # 双均线：5日上穿20日买入
    "macd":     {"fast": 12, "slow": 26, "signal": 9},
    "rsi":      {"period": 14, "buy": 30, "sell": 70},
    "boll":     {"period": 20, "std": 2.0},
}
# 需要多少个策略同时给出买入信号才买入（共振阈值）
BUY_CONSENSUS = 2

# ============ 风险控制（稳健默认值） ============
STOP_LOSS = -0.05                 # 单股止损线 -5%
TAKE_PROFIT = 0.10                # 单股止盈线 +10%
MAX_POSITION_PER_STOCK = 0.20     # 单股最大仓位占总资产比例
MAX_HOLDINGS = 5                  # 最多同时持有股票数
MAX_TOTAL_POSITION = 0.90         # 最大总仓位（留10%现金缓冲）

# ============ 事件驱动 ============
ENABLE_MACRO = True               # 宏观新闻情绪调节（防御性自动降仓）
ENABLE_HOTSPOT = True             # 热点联动提醒（只提醒不自动买）
MACRO_BEARISH_CUT = 0.5           # 宏观强利空日：新开仓仓位打5折
HOTSPOT_HEAT_THRESHOLD = 3.0      # 概念板块异动涨幅阈值(%)，超过视为热点
HOTSPOT_TTL_DAYS = 3              # 热点提醒默认时效（交易日）

# ============ 交易规则（A股） ============
LOT_SIZE = 100                    # 一手 = 100股
PRICE_LIMIT = 0.10               # 主板涨跌停 ±10%（科创/创业板20%另算）

# ============ 路径 ============
DATA_DIR = "data"
PORTFOLIO_FILE = "data/portfolio.json"     # 当前持仓与现金
TRADES_FILE = "data/trades.json"           # 历史成交流水
EQUITY_FILE = "data/equity_curve.json"     # 每日净值曲线
EVENTS_FILE = "data/events.json"           # 事件提醒记录
DASHBOARD_FILE = "dashboard/index.html"    # 生成的仪表盘
