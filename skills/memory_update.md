<!-- skill-metadata
skill_id: memory_update
command: update-memory
schema_version: 1
rating_enum: update_plan
required_inputs: user_update_text, current_portfolio, current_watchlist
output_contract: memory_update_plan_v1
-->

# 记忆更新 Skill

## 目标

把用户明确给出的基础背景、账户资金口径、当前持仓组合、观察池更新转换成安全、可审计的 Markdown **修改计划**，并由执行方（Cursor / Claude Code 等）**直接编辑**仓库内的记忆文件。本 skill 不做交易判断，不主动改交易规则。

## 可更新文件

长期记忆只有两份 Markdown：

1. `memory/portfolio.md`（包含「用户与账户」表与「持仓表」）
2. `memory/watchlist.md`

不能创建或更新长期 `market_context.md`，也不能创建独立 `decision_log.md`。

## 输入要求

- `user_update_text`: 用户明确说出的更新内容。
- `current_portfolio`: `memory/portfolio.md` 全文（含用户与账户 + 持仓表）。
- `current_watchlist`: `memory/watchlist.md` 全文。

## 更新规则

- 只写入用户明确表达的事实；不清楚的数量、日期、代码、市场、价格必须列入 `needs_confirmation`，禁止猜测。
- 当前市场主线、当日热点、外围消息不写入长期记忆。
- 持仓行写入或更新：`symbol`、`market`、`name`、`quantity`、`buy_date`、`buy_price`、分批 `lots`；仅在用户**额外说明**时填写 `notes`。
- 行情价格、浮盈浮亏、题材判断、临时止损/止盈判断不写入持仓表。
- 卖出、减仓、清仓：更新持仓表对应行；清仓可将 `quantity` 置 `0` 或删除该行（二选一并在计划中说明），不强制写 `notes`。
- 观察池写入 `watchlist.md`。
- 用户与账户背景、资金口径写入 `portfolio.md` 顶部的「用户与账户」表。
- 必须保留各文件中原有的自由备注段落，禁止整文件覆盖。

## 输出结构

必须输出：

```json
{
  "status": "ready_to_apply|needs_confirmation|reject",
  "target_files": ["memory/portfolio.md"],
  "proposed_changes": [
    {
      "file": "memory/portfolio.md",
      "operation": "add_row|update_row|replace_section|no_change",
      "reason": "为什么改",
      "details": "具体改什么"
    }
  ],
  "needs_confirmation": [
    {
      "field": "buy_price",
      "question": "需要用户确认的问题"
    }
  ],
  "ignored_items": [
    {
      "text": "被忽略的内容",
      "reason": "为什么不写长期记忆"
    }
  ]
}
```

## 输出要求

- 计划经用户确认后，由助手通过编辑工具写入 Markdown；**不存在**单独的 Python 自动写回协议。
- 含糊更新不能猜；不能把市场临时观点写入长期记忆。
