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
- `quote_snapshot`: 行情脚本输出的近期基础行情，以及 A 股当日 10 分钟级日内采样点。
- `user_profile`: 用户基础背景、市场、资金纪律和风险偏好。
- `watchlist_status`: 该标的是否已在观察池、题材、优先级、入池逻辑。
- `model_market_research`: 模型临时查询得到的主线题材、行业地位、基本面、风险事件、K 线/图形观察。

## 数据使用边界

- 行情脚本只作为事实证据：近期涨跌、当日涨跌、换手、A 股当日日内采样点、缺失字段；走势形态由模型根据这些数据自行判断。
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

## 筹码峰处理规则

- 行情脚本不获取筹码峰，当前 agent 也不能稳定从公开接口直接拿到筹码峰数据。
- 不要把“筹码峰缺失”写入 `missing_evidence`，因为这不是脚本应覆盖的字段。
- 如果模型能通过行情软件截图、K 线图或用户补充看到筹码峰，就按证据判断加分项 2。
- 如果看不到筹码峰，需要在输出里单独写 `chip_peak_check`，提示用户自己看：
  - 如果底部筹码峰集中，且近期上涨/震荡过程中底部集中筹码峰没有明显松动或上移，加分项 2 可以加分。
  - 如果筹码峰分散、上方套牢盘很重、底部筹码明显松动，或近期筹码快速上移，加分项 2 不加分。
  - 如果只能看到部分信息，标记为人工确认项，不要因为缺失而扣到一票否决。

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
  "chip_peak_check": {
    "status": "confirmed_bonus|confirmed_no_bonus|user_check_required",
    "instruction": "用户需要看什么",
    "bonus_if": "什么情况下加分",
    "no_bonus_if": "什么情况下不加分"
  },
  "vetoes": ["命中的一票否决项"],
  "missing_evidence": ["缺失证据"],
  "action": "进入观察池/维持观察/剔除/等待更多证据"
}
```

## 输出要求

- 不能只给评级，必须解释每条核心规则和每个加分项。
- 必须分清脚本行情证据、模型临时查询证据、用户记忆证据。
- 筹码峰如果无法确认，必须写成 `chip_peak_check.user_check_required`，不要写入 `missing_evidence`。
- 如果是 ETF，也要按题材代表性、成分股结构、流动性和风险来解释。
