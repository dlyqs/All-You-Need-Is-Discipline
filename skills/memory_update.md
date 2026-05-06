<!-- skill-metadata
skill_id: memory_update
command: update-memory
schema_version: 1
rating_enum: update_plan
required_inputs: user_update_text, current_user_profile, current_portfolio, current_watchlist
output_contract: memory_update_plan_v1
-->

# 记忆更新 Skill

## 目标

把用户明确给出的基础背景、当前持仓组合、观察池更新转换成安全、可审计的 Markdown 修改计划。这个 skill 不做交易判断，不主动改规则。

## 可更新文件

初版只允许更新三份长期记忆：

1. `memory/user_profile.md`
2. `memory/portfolio.md`
3. `memory/watchlist.md`

不能创建或更新长期 `market_context.md`，也不能创建独立 `decision_log.md`。

## 输入要求

- `user_update_text`: 用户明确说出的更新内容。
- `current_user_profile`: 当前用户基础背景文件内容。
- `current_portfolio`: 当前持仓组合文件内容。
- `current_watchlist`: 当前观察池文件内容。

## 更新规则

- 只更新用户明确表达的事实。
- 这个规则适用于任意命令和多轮对话：只要用户明确表达买入、卖出、加仓、减仓、清仓、成本变化或持仓变化，就应该先生成 memory update 计划，再继续原本分析意图。
- 用户没有说清楚的金额、数量、买入价、日期、市场、代码，必须列入 `needs_confirmation`。
- 当前市场主线、当日热点、外围消息不写入长期记忆。
- 买入时间、买入价、数量、持仓逻辑、止损/止盈备注，写入 `portfolio.md` 对应行。
- 卖出、减仓、清仓信息也写入或更新 `portfolio.md`：如果仍持有则更新数量和备注；如果清仓，初版可以建议移除该行或将数量改为 0 并在 notes 标记，具体执行策略由确定性代码控制。
- 观察逻辑、题材、优先级、是否重点关注、失效条件，写入 `watchlist.md`。
- 风险偏好、现金保留规则、主要交易市场、账户币种，写入 `user_profile.md`。
- 必须保留用户原有自由备注，不能重写整份文件。

## 输出结构

必须输出：

```json
{
  "status": "ready_to_apply|needs_confirmation|reject",
  "target_files": ["memory/portfolio.md"],
  "proposed_changes": [
    {
      "file": "memory/portfolio.md",
      "operation": "add_row|update_row|append_note|no_change",
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

- 不直接输出“已修改”，只能输出修改计划；真实写文件由后续确定性代码执行。
- 含糊更新不能猜。
- 不能把市场临时观点写入长期记忆。
