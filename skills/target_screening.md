<!-- skill-metadata
skill_id: target_screening
command: judge-target
schema_version: 1
rating_enum: reject, watch, qualified
required_inputs: symbol_or_name, quote_snapshot, user_profile, watchlist_status, model_market_research
output_contract: rating_result_v1
-->

# 判断标的 Skill

## 目标

判断某个标的是否值得进入关注或继续重点观察。这个 skill 只回答“标的质量和逻辑是否过关”，不回答“今天此刻是否可以买入”。

## 输入要求

- `symbol_or_name`: 标的 或 ETF 代码、名称。
- `quote_snapshot`: 行情脚本输出的近期基础行情和当日粗略走势。
- `user_profile`: 用户基础背景、市场、资金纪律和风险偏好。
- `watchlist_status`: 该标的是否已在观察池、题材、优先级、入池逻辑。
- `model_market_research`: 模型临时查询得到的主线题材、行业地位、基本面、风险事件、K 线/图形观察。

## 数据使用边界

- 行情脚本只作为事实证据：近期涨跌、当日涨跌、换手、粗略走势、缺失字段。
- 主线题材、行业排名、龙头地位、基本面、风险事件、筹码峰和较长周期 K 线，由模型临时查询和看图分析。
- 证据不足时必须写入 `missing_evidence`，不能把推测说成事实。

## 一票否决规则

逐条判断并在输出中写明是否命中、证据和理由：

1. 不是主线大题材，或题材没有可持续上涨预期。
2. 缺少营收和利润支撑，无法支撑进一步上涨。
3. 股性不好，大盘跌时不抗跌，大盘涨时也不够强。
4. 存在重大风险、减持压力、监管风险、财务风险或其他会破坏上涨逻辑的风险。
5. 行业排名、规模或涨势不在前排，明显弱于行业龙头或行业前排。
6. 无法说出选择该股的硬逻辑。

只要一票否决成立，评级不能是 `qualified`。

## 加分项

逐条判断并在输出中写明是否符合、证据和理由：

1. 基本面很好，盈利逐年增加，PE 不算特别高。
2. 筹码峰比较集中，且近期底部集中筹码峰未明显变动。
3. 热度高，资金活跃，股性容易被拉涨停或强势冲高。
4. 盈利结构健康，不会因为单一题材崩盘而全面崩盘。

## 评级规则

- `reject`: 命中任意明确一票否决，或核心证据严重不足且风险不可控。
- `watch`: 未明确命中硬否决，但证据不足、逻辑不够硬、题材地位不够确定，或只适合观察。
- `qualified`: 没有硬否决，主线/基本面/股性/行业地位/硬逻辑都能讲清楚，并至少有部分加分项支持。

## 输出结构

必须输出一个结构化结果，至少包含：

```json
{
  "rating": "reject|watch|qualified",
  "conclusion": "一句话结论",
  "rule_matches": [
    {
      "name": "一票否决规则名称",
      "matched": true,
      "evidence": "使用的证据",
      "reason": "为什么命中或不命中",
      "confidence": 0.0
    }
  ],
  "bonus_matches": [
    {
      "name": "加分项名称",
      "matched": true,
      "evidence": "使用的证据",
      "reason": "为什么符合或不符合",
      "confidence": 0.0
    }
  ],
  "vetoes": ["命中的一票否决项"],
  "missing_evidence": ["缺失证据"],
  "action": "进入观察池/维持观察/剔除/等待更多证据"
}
```

## 输出要求

- 不能只给评级，必须解释每条核心规则和每个加分项。
- 必须分清脚本行情证据、模型临时查询证据、用户记忆证据。
- 如果是 ETF，也要按题材代表性、成分股结构、流动性和风险来解释。

