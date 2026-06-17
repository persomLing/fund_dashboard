# 基金策略面板

一个本地运行的基金分析可视化面板，用来把 `fund-rebalance-decision` 的脚本结果做成更直观的页面。

你只需要输入基金代码、基金名称、持仓金额、持仓成本价、最新净值、当前持有收益率、平台日涨跌等信息，页面会调用本地 Python 脚本完成估算，并展示观察、买入、卖出相关的决策信息。

## 主要功能

- 基金信息录入：支持基金代码、名称、持仓金额、成本净值、最新净值、持有收益率、平台日涨跌。
- 本地策略分析：通过 `scripts/fund_trade_decision.py` 执行规则化分析。
- 可视化结果：展示决策结论、建议金额、建议比例、预估日涨跌幅、预估持有收益、涨跌信号、收益位置和持仓贡献。
- 购入分析页：输入基金代码、基金名称和基金净值，基于披露持仓、A 股大盘、美股代理行情、相关主题和新闻源判断是否适合购入，并给出长期持有提示。
- 买卖提示：未触发时保持“建议金额 / 建议比例”；触发买入或卖出时自动切换为“买入金额 / 买入比例”或“卖出金额 / 卖出比例”。
- 基金信息保存：点击“保存信息”后写入 `data/funds.json`，同一基金代码会覆盖为最新数据。
- 快速填入：下次打开页面时，会从 `data/funds.json` 读取已保存基金。
- 服务关闭：提供 `stop.bat`，可以一键关闭当前 dashboard 服务。
- 响应式布局：支持 PC 和 H5 宽度。

## 启动

双击：

```text
start.bat
```

启动后会自动打开：

```text
http://127.0.0.1:8787/
```

`start.bat` 会先尝试关闭旧的 dashboard 服务，再启动新的服务，避免重复开多个 Python 进程。

## 关闭

双击：

```text
stop.bat
```

它只会关闭命令行中包含 `fund_dashboard\server.py` 的 Python 进程，不会主动关闭其他 Python 程序。

## 数据保存

页面里的“保存信息”按钮会把当前表单保存到：

```text
data/funds.json
```

保存规则：

- 使用 `fundCode` 作为唯一键。
- 同一只基金再次保存时，会替换成最新数据。
- 删除基金会从 `data/funds.json` 移除对应基金。
- 页面加载时会读取该 JSON，并生成“快速填入”列表。

数据格式示例：

```json
{
  "004241": {
    "fundCode": "004241",
    "fundName": "中欧时代先锋股票C",
    "holdingValue": "2019.49",
    "costNav": "2.0832",
    "lastNav": "2.0452",
    "returnRatePct": "-1.82",
    "navSignalPct": "-1.01"
  }
}
```

## 分析逻辑

页面不会自己重新实现基金策略，而是把表单参数传给本地脚本：

```text
scripts/fund_trade_decision.py
```

服务端入口是：

```text
server.py
```

主要接口：

```text
GET  /api/funds          读取已保存基金
POST /api/funds/save     保存或覆盖基金信息
POST /api/funds/delete   删除基金信息
POST /api/analyze        执行基金分析
```

## 文件结构

```text
fund_dashboard/
  README.md                       项目说明
  server.py                       本地 Web 服务和 API
  start.bat                       启动服务并打开页面
  stop.bat                        关闭 dashboard 服务
  data/funds.json                 已保存的基金信息
  scripts/fund_trade_decision.py  fund-rebalance-decision 脚本副本
  static/index.html               页面结构
  static/app.js                   页面交互、保存逻辑和图表渲染
  static/styles.css               页面样式和响应式布局
```

## 使用建议

1. 先填写或选择基金信息。
2. 如果当天只是盘中估算，时间门槛选择“估算模式”。
3. 点击“执行分析”查看结果。
4. 点击“保存信息”保存当前基金，下次可以快速填入。
5. 如果不再跟踪某只基金，点击“删除基金”。

## 注意事项

- 这是本地辅助工具，不是投资建议。
- 主动基金可能已经调仓，持仓贡献只能基于公开披露持仓估算。
- 当日净值以基金公司最终公布为准。
- 页面展示的“预估持有收益”是基于输入数据和脚本估算结果生成的，不等同于最终收益。
- 公开仓库如果包含真实持仓金额，请确认你接受这些信息被提交到 Git。
