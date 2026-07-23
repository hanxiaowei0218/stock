# A股智能模拟交易系统

一个跑在 **GitHub Actions 免费云端**、电脑关机也自动运行的 A 股模拟交易系统。
采用「**技术面自动交易 + 事件面智能提醒**」双驱动，使用真实行情 + 虚拟资金（默认 10 万），零资金风险。

> ⚠️ 本系统为**模拟盘**，所有交易均不涉及真实资金。分析仅供研究，不构成投资建议。

## 功能对照

| 能力 | 实现 |
|---|---|
| 实时行情与分析 | akshare 免费数据源，自动算 MA/MACD/RSI/布林带 |
| 预设交易策略 | 双均线 / MACD / RSI / 布林带，多策略共振（`config.py` 调参） |
| 自动买卖 | 模拟撮合，遵守 T+1、100股整手、涨跌停、手续费规则 |
| 交易监控 | 自包含 HTML 仪表盘：净值曲线、持仓、流水 |
| 风险控制 | 止损 -5% / 止盈 +10% / 单股≤20% / 最多5只 / 现金缓冲 |
| 记录查询 | 全部成交与净值存 JSON，永久可追溯 |
| 宏观事件 | 财联社电报情感打分 → 利空日自动降仓（防御性） |
| 热点联动 | 概念异动识别龙头 → 仪表盘提醒（**只提醒不自动买**，标注时效/熄火/不确定性） |

## 目录结构

```
a_trader/
├── config.py              # 全部可调参数
├── main.py                # 主调度（每轮决策入口）
├── core/
│   ├── data_feed.py       # 行情数据
│   ├── indicators.py      # 技术指标
│   ├── strategy.py        # 策略引擎
│   ├── stock_selector.py  # 自动选股
│   ├── risk.py            # 风险控制
│   ├── broker.py          # 模拟撮合
│   ├── portfolio.py       # 持仓与账本
│   ├── event_analyzer.py  # 宏观+热点事件
│   └── dashboard.py       # 仪表盘生成
├── data/                  # 运行产生的持仓/流水/净值/事件(JSON)
├── dashboard/index.html   # 生成的仪表盘（双击即看）
└── .github/workflows/trade.yml  # 定时调度
```

## 本地运行

```bash
pip install -r requirements.txt
python main.py --seed     # 快速自检（少量样本股）
python main.py --force    # 强制跑一轮完整流程（忽略交易时段）
python main.py            # 正常运行（自动跳过非交易时段）
```

运行后打开 `dashboard/index.html` 查看结果。

## 云端自动运行

推送到 GitHub 后，`trade.yml` 会在交易日 9:30–15:00 每 30 分钟自动运行，
把最新持仓、流水、仪表盘回写到仓库。你的电脑关机也不影响。

- 私有仓库若要用 GitHub Pages 公开仪表盘需 GitHub Pro；否则可下载 `dashboard/index.html` 本地查看（数据已内嵌）。
- 免费版 Actions 调度可能有几分钟延迟，对 30 分钟级策略影响很小。

## 调参

所有参数集中在 `config.py`：策略组合、共振阈值、止损止盈、仓位上限、股票池、事件开关等，改完下次运行即生效。

## 从模拟到实盘

代码已按分层设计，`core/broker.py` 是唯一的下单出口。未来接实盘时，
只需实现一个同接口的真实券商 broker（如 QMT/miniQMT），替换调用即可，其余模块无需改动。
