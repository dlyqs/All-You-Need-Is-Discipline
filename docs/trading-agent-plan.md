# 交易决策 Agent 实施计划

## 1. 目标概览

这份计划用于从当前几乎为空的仓库开始，分阶段构建一个本地辅助交易决策 Agent。当前版本按“够用、轻量、方便后续改规则”的方向实施，不把初版做成完整量化系统。

最终目标：

- 有一个仓库内的主 Agent，可以和用户交互，按命令调用不同 skill，临时调用行情脚本，读取和更新用户记忆文件，并整合输出交易决策报告。
- 有一组仓库内的 skill 文件，初版默认覆盖四个用户功能：
  - 判断标的：判断某个标的是否符合用户选股规则，是否值得进入关注。
  - 判断买入：判断某个标的当前当日是否可以买入，以及买入级别。
  - 判断卖出：判断当前持仓标的是否应该卖出、减仓或继续持有。
  - 分析下一交易日方案：结合当前持仓、现金、观察池、临时查询的市场主线和行情信息，给出第二天不同情况的行动指南。
- 有轻量 Markdown 记忆存储，只保存三类长期信息：
  - 用户基础背景信息。
  - 当前持仓组合。
  - 观察池。
- 有一个确定性行情脚本，用于帮大模型快速获取 A 股和美股单个或批量标的的近期基础行情和当日粗略走势。
- 主 Agent 输出必须明确说明：评级结果、触发了哪些硬规则、符合哪些加分项、哪些证据来自脚本、哪些判断来自模型临时查询和推理。

初版范围内：

- 从零搭建工程结构。
- 本地 CLI 优先运行。不做前端。
- 默认提供四个功能：判断标的、判断买入、判断卖出、分析下一交易日方案。
- 使用三个 Markdown 文件作为用户可直接编辑的长期记忆。
- 行情脚本只负责提效，获取近期和当日基础行情，不承担复杂 K 线分析。
- 市场主线、热点题材、风险事件、较长周期 K 线形态等信息，由大模型在每次分析时临时查询和判断。
- 每个执行阶段后同步更新文档。

初版范围外：

- 暂不做回测分析。
- 暂不接入券商账户，也不自动下单。
- 暂不做可视化前端或浏览器工作流。
- 暂不做专门的规则编辑功能，后续需要改规则时可以直接让 AI 编辑 skill 文件。
- 暂不存储市场主线、每日行情快照或独立交易日志。
- 暂不做日常定时刷新行情、盘前/盘中/晚间自动工作流。
- 不承诺交易所级实时行情。
- 不做完整量化组合优化。
- 不把系统包装成确定性投资建议。系统只做决策辅助，最终交易责任仍由用户承担。

## 2. 可行性分析

这个目标在当前仓库内可行。当前项目几乎为空，只有 `README.md` 和 `LICENSE`，没有既有技术栈约束。最稳妥的初版路径是 Python CLI：适合写确定性脚本、读写本地 Markdown 记忆，也方便测试。

主要可行性风险：

- 行情源稳定性：免费的 A 股和美股行情源可能延迟、限流，或者返回结构变化。实现时需要把数据源封装成适配器，输出时带上来源和时间戳，失败时不能伪造数据。
- AI 判断边界：模型可以辅助判断主线题材、硬逻辑、风险事件、几个月级别的 K 线形态，但不能把不完整信息说成已验证事实。报告必须展示证据、假设、触发规则和缺失数据。
- 当日买卖依赖盘中时点：系统需要明确行情时间戳、市场时区、交易时段状态，并在行情延迟或闭市时提醒用户。
- 图形分析依赖模型能力：较长周期日线走势、筹码形态、平台震荡和波段位置不强行用程序判断，默认交给支持图片理解的模型结合查询到的 K 线图分析。

目前没有硬性运行时约束阻止这个项目推进，所以按简化阶段实施。

## 3. 约束和假设

- 初版运行时已按执行环境调整为 Python 3.8+。Phase 1 执行时发现本机默认 `python` 是 3.8.18，因此代码保持标准库和轻量兼容；后续如需要可再提升到 Python 3.11+。
- 默认交互方式是命令行 + 仓库内 Markdown skills + Markdown 记忆。
- 本计划不包含前端阶段，也不会触发浏览器查看、页面拉起或 playwright。
- 初版不执行真实交易，不连接券商账户。
- 日志默认不输出完整资金和持仓隐私。用户报告中可以展示这些信息，因为报告本身就是给用户看的。
- 行情数据必须包含来源、时间戳、市场、代码，以及足够判断是否陈旧或缺失的字段。
- 长期记忆只保存三份：用户基础背景信息、当前持仓组合、观察池。
- 市场相关信息不长期存储。每次执行判断或方案分析时，由大模型临时查询最新市场信息。
- 交易记录不单独建日志文件，直接记录在当前持仓表里，例如买入时间、买入价、买入数量、持仓逻辑、后续备注。
- 评级输出需要结构化，不能只有散文。初版稳定枚举如下：
  - 判断标的：`reject`、`watch`、`qualified`
  - 判断买入：`prohibited`、`avoid`、`watch`、`small_trial`、`buyable`
  - 判断卖出：`must_sell`、`reduce`、`hold`、`watch`
- 用户在需求里给出的交易规则是默认基线。后续如果要改规则，可以直接编辑对应 skill 文件。

## 4. 目标架构

计划完成后的仓库结构大致如下：

```text
.
├── docs/
│   ├── overview.md
│   └── trading-agent-plan.md
├── memory/
│   ├── user_profile.md
│   ├── portfolio.md
│   └── watchlist.md
├── skills/
│   ├── target_screening.md
│   ├── buy_rating.md
│   ├── sell_rating.md
│   ├── next_day_plan.md
│   └── memory_update.md
├── scripts/
│   └── fetch_quotes.py
├── src/
│   └── trading_agent/
│       ├── cli.py
│       ├── market_data.py
│       ├── memory.py
│       ├── models.py
│       ├── report.py
│       └── skills.py
├── tests/
└── pyproject.toml
```

初版刻意采用扁平结构，不单独创建 `agent.py`、`config.py`、`logging.py`、`market_data/`、`memory/`、`skills/`、`reports/` 这些拆分模块。只有当后续复杂度真的上来，例如多个行情 provider、多个 LLM provider、复杂报告模板或复杂记忆更新，再按实际需要拆目录。

## 5. 总阶段状态表

| 阶段 | 主题 | 主要目标 | 状态 | 实际产出 | 备注 |
| --- | --- | --- | --- | --- | --- |
| Phase 0 | 计划契约 | 创建并根据用户反馈简化阶段计划和项目概览 | completed | `docs/trading-agent-plan.md`、`docs/overview.md` | 未改实现代码 |
| Phase 1 | 工程启动 | 创建项目骨架、包配置、CLI 壳、核心数据结构和扁平模块占位 | completed | `.gitignore`、`pyproject.toml`、`src/trading_agent/*.py`、`tests/*.py` | 仅骨架和占位边界；未实现交易判断 |
| Phase 2 | 简化行情脚本 | 实现近期基础行情和当日粗略走势查询 | completed | `scripts/fetch_quotes.py`、`src/trading_agent/market_data.py`、`tests/test_market_data.py` | 使用腾讯 A 股接口和 Yahoo chart；脚本只提效，不做复杂图形判断 |
| Phase 3 | Skill 库 | 创建判断标的、买入、卖出、次日方案和轻量记忆更新 skill | completed | `skills/*.md`、`src/trading_agent/skills.py`、`tests/test_skills.py` | 已实现 metadata 解析、加载校验、执行包生成；输出契约映射规则和加分项 |
| Phase 4 | 轻量记忆存储 | 创建三份 Markdown 记忆文件和安全读写工具 | completed | `memory/user_profile.md`、`memory/portfolio.md`、`memory/watchlist.md`、`src/trading_agent/memory.py`、`tests/test_memory.py` | 不存市场上下文，不建独立交易日志 |
| Phase 5 | 主 Agent 编排 | 实现命令路由、自然语言上下文检查、对话更新识别、脚本调用、skill 加载和报告组装 | completed | `src/trading_agent/cli.py`、`src/trading_agent/report.py`、`src/trading_agent/memory.py`、`tests/test_cli_routing.py`、`tests/test_report_packets.py`、`tests/test_agent_preflight.py` | 无 API key 时生成 prompt/evidence packet |
| Phase 6 | 验证和文档收口 | 补测试、样例、README、AI 编辑器使用说明，并同步文档 | completed | `AGENTS.md`、`CLAUDE.md`、`.cursor/rules/trading-agent.mdc`、`README.md`、`tests/test_docs.py`、文档同步 | 自然语言入口已补齐；命令作为 AI 内部工具和测试工具 |

## 6. 阶段拆解

### Phase 0. 计划契约和初始概览

目标：

- 建立这个大目标的计划优先执行契约。
- 根据用户反馈把初版范围收窄到轻量可用版本。
- 记录当前仓库状态和计划架构。

预计输出：

- `docs/trading-agent-plan.md`
- `docs/overview.md`

验收清单：

- 计划明确范围内和范围外事项。
- 计划包含阶段细节、唯一的总状态表、执行规则、可观测性要求和实际完成记录区。
- 概览文档说明当前仓库状态和后续导航方式。
- 评审通过前不创建实现代码。

助手侧验证：

- 读取当前仓库文件。
- 确认本阶段只新增或修改文档。

用户侧检查：

- 检查默认假设、阶段顺序、运行时选择、行情脚本职责和简化后的记忆结构是否符合预期。

实际完成：

- 已检查仓库，初始状态只有 `README.md` 和 `LICENSE`。
- 已创建初版阶段计划和项目概览。
- 已按用户反馈把计划改为中文并简化：memory 只保留三份文件，市场信息改为临时查询，交易记录并入持仓表，移除日常刷新/调度阶段，行情脚本职责收窄。
- 已按用户反馈继续压缩工程结构：初版使用扁平 `src/trading_agent/*.py` 模块，不单独拆 `agent.py`、`config.py`、`logging.py` 或多个子目录。
- 未改实现代码。

### Phase 1. 启动工程骨架

目标：

- 创建最小可运行工程基础，但暂不实现交易判断逻辑。

预计输出：

- `pyproject.toml`
- `src/trading_agent/__init__.py`
- `src/trading_agent/cli.py`
- `src/trading_agent/models.py`
- `src/trading_agent/market_data.py`
- `src/trading_agent/memory.py`
- `src/trading_agent/skills.py`
- `src/trading_agent/report.py`
- `tests/`

验收清单：

- 项目可以通过选定 Python 工具链本地运行或安装。
- CLI 命令存在，并能展示可用动作。
- 核心数据结构存在，包括 symbol、简化行情快照、持仓行、评级输出、规则匹配项、证据项。
- 评级输出结构预留“硬规则命中”“加分项命中”“缺失证据”字段。
- 简单诊断输出存在，并且默认不输出敏感持仓细节。初版不单独创建 `logging.py`。
- 单元测试骨架可以运行。

助手侧验证：

- 如果配置了格式化或 lint，则运行对应命令。
- 运行初始测试命令。
- 运行 CLI help 命令。

用户侧检查：

- 确认命令命名是否顺手。
- 确认 Python CLI 是否仍是想要的初版界面。

实际完成：

- 新增 `.gitignore` 和 `pyproject.toml`，项目可通过 `python -m pip install -e .` 可编辑安装，且测试/安装产物不会进入工作区。
- 新增扁平源码结构：`src/trading_agent/__init__.py`、`cli.py`、`models.py`、`market_data.py`、`memory.py`、`skills.py`、`report.py`。
- 新增标准库 `unittest` 测试：`tests/test_models.py`、`tests/test_cli.py`、`tests/test_boundaries.py`。
- `models.py` 定义了 market、symbol、简化行情快照、持仓、证据项、规则匹配项、评级输出等核心数据结构。
- `cli.py` 暴露 `judge-target`、`judge-buy`、`judge-sell`、`plan-next-day`、`update-memory`、`fetch-quotes` 命令壳。
- `market_data.py`、`memory.py`、`skills.py`、`report.py` 只建立 Phase 1 边界，不抓取真实行情、不执行 skill、不写记忆。
- 简单诊断输出采用 `[trading-agent] chain=... event=... status=...` 格式，默认不输出完整资金或持仓。
- 执行时发现本机默认 `python` 是 3.8.18，因此 `pyproject.toml` 设置为 `requires-python = ">=3.8"`。
- 已运行验证：
  - `python -m pip install -e .`
  - `python -m unittest discover -s tests`
  - `python -m trading_agent.cli --help`
  - `/Users/dlyqs/.pyenv/versions/3.8.18/bin/trading-agent --help`
  - `PYTHONPATH=src python -m trading_agent.cli judge-target NVDA --market US`

### Phase 2. 简化行情数据脚本

目标：

- 实现 A 股和美股单个/批量标的的确定性基础行情查询，重点帮大模型节省查询当日详细信息的时间。

预计输出：

- `scripts/fetch_quotes.py`
- `src/trading_agent/market_data.py`
- `tests/test_market_data.py`

验收清单：

- 命令支持一个或多个 symbol。
- 命令支持必要的市场选择，例如 `A` 和 `US`。
- 输出支持 JSON，也支持终端表格展示。
- 近期基础字段尽量包含：
  - 近几日收盘价。
  - 近几日涨跌幅。
  - 近几日换手率，数据源不支持时明确标记缺失。
- 当日基础字段尽量包含：
  - 开盘价。
  - 最新价或收盘价。
  - 当日涨跌幅。
  - 当日换手率，数据源不支持时明确标记缺失。
  - 是否涨停或接近涨停，数据源不支持涨跌停价时用可解释的近似判断并标记。
  - 是否封板、是否封板后打开，只有在数据源能支持时才输出；否则标记缺失，不猜。
  - 粗略走势标签，例如高开高走、一字板、低开高走、高开低走、震荡、弱势下跌等。标签必须基于可用的当日价格或分时数据，不能硬猜。
- 输出必须包含 source、timestamp、market、symbol、missing_fields。
- 不分析几个月级别日线走势，不做复杂 K 线形态判断，不判断筹码峰。
- 数据源失败时清晰报错，不能输出假数据。
- 测试覆盖数据标准化、缺失字段和失败处理，且不依赖实时网络。

助手侧验证：

- 运行单元测试。
- 运行基于 fixture 的命令。
- 如果安全可用，分别用一个 A 股 symbol 和一个美股 symbol 做 live smoke check，并记录来源和时间戳表现。

用户侧检查：

- 确认这些字段是否足够帮大模型节省当日行情查询时间。
- 如果你有偏好的行情数据源，可以在此阶段指定。

备注和依赖：

- 公共金融数据包和接口可能变化，所以 provider 的具体选择要在 Phase 2 执行时验证。
- 走势标签只是“粗略辅助信息”，不能替代模型结合 K 线图和上下文做最终判断。

实际完成：

- 新增 `scripts/fetch_quotes.py`，可从仓库根目录直接运行简化行情查询。
- 将 `src/trading_agent/market_data.py` 从 Phase 1 占位改为真实基础行情边界。
- `python -m trading_agent.cli fetch-quotes ...` 已从占位输出改为真实调用。
- 支持单个或批量 symbol，支持 `--market A|US`，也可对 6 位数字 A 股代码和美股 ticker 做简单市场推断。
- 支持 `--format table|json`、`--recent-days`、`--timeout`。
- A 股当前使用腾讯行情接口：
  - `qt.gtimg.cn` 获取实时/当日基础信息。
  - `web.ifzq.gtimg.cn/appstock/app/fqkline/get` 获取近期日线基础信息。
- 美股当前使用 Yahoo chart 接口获取近期日线和 regular market 基础信息。
- 标准化输出包含：source、timestamp、market、symbol、name、latest/open/close/high/low/previous close、change pct、turnover rate、rough intraday shape、limit-up 近似标记、sealed-board 相关字段、recent bars、missing fields。
- 没有实现复杂 K 线分析、筹码峰分析、长期走势判断；这些仍按计划交给模型临时查询和看图分析。
- 已明确标记数据源缺失：
  - 美股通常缺少换手率、涨停/封板字段。
  - 当前 A 股近期日线缺少逐日换手率；封板和开板字段不可靠，因此标记缺失，不猜。
- 已运行验证：
  - `python -m unittest discover -s tests`，14 个测试通过。
  - `python -m trading_agent.market_data --help`
  - `scripts/fetch_quotes.py --help`
  - `python -m trading_agent.cli fetch-quotes --help`
  - `python -m trading_agent.cli fetch-quotes NVDA --market US --recent-days 5 --format json --timeout 10`
  - `python -m trading_agent.cli fetch-quotes 600519 --market A --recent-days 5 --format json --timeout 10`
  - `scripts/fetch_quotes.py 600519 --market A --recent-days 5 --format table --timeout 10`
  - `python -m trading_agent.cli fetch-quotes NVDA 600519 --recent-days 5 --format table --timeout 10`

### Phase 3. 仓库内 Skill 库

目标：

- 创建 skill prompt / workflow，把用户默认交易规则结构化，输出可比较的评级、规则命中原因和加分项原因。

预计输出：

- `skills/target_screening.md`
- `skills/buy_rating.md`
- `skills/sell_rating.md`
- `skills/next_day_plan.md`
- `skills/memory_update.md`
- `src/trading_agent/skills.py`
- `tests/test_skills.py`

验收清单：

- 每个判断类 skill 的输出都必须包含：
  - 评级枚举。
  - 结论摘要。
  - 逐条规则匹配表：规则名称、是否命中、证据、理由、置信度。
  - 加分项匹配表：加分项名称、是否符合、证据、理由、置信度。
  - 一票否决项列表。
  - 缺失证据列表。
  - 最终行动建议。
- 判断标的 skill 包含一票否决项：
  - 是否主线大题材，且有持续上涨预期。
  - 是否有营收和利润支撑进一步上涨。
  - 股性是否好，大盘跌时抗跌，大盘涨时更强。
  - 是否无重大风险或减持压力。
  - 行业排名、规模、涨势是否处于前排，不能明显弱于行业前排。
  - 是否能说出选择该股的硬逻辑。
- 判断标的 skill 包含加分项：
  - 基本面好、盈利逐年增加、PE 不算特别高。
  - 筹码峰集中且近期底部集中筹码峰未明显变动。
  - 热度高，容易被资金拉涨停。
  - 盈利结构健康，不会因单一题材崩盘而全面崩盘。
- 判断买入 skill 包含用户列出的全部禁止购买规则：
  - 下跌中继，未见止跌企稳或强反弹。
  - 前面有极夸张连板异动，但并非热门龙头，且已开始二波。
  - 高位平台初期，且未突破趋势。
  - 当前一波拉升已几十个点或已连板，属于中途追高。
  - 大盘大跌且下跌中继未见底未反弹，标的又不是逆市板块。
  - 上午开盘时以及下午开盘时的冲动买入风险。
  - 处于近期连续类似图线的第三波。
  - 前一日高位长上影且当日绿收盘。
  - 没经过观察，不在重点关注池。
- 判断买入 skill 包含通过后的交易纪律：
  - 禁止直接满仓，至少保留 30% 现金。
  - 不要同一题材板块买多只，只保留股性最好的一只。
- 判断卖出 skill 包含用户列出的“不卖”和“必须卖”规则。
- 次日方案 skill 使用用户基础背景、现金、当前持仓、观察池、临时查询的市场上下文、脚本行情和模型补充证据，输出类似“今晚观察、明天早盘、上午 10 点后、下午开盘、持仓去留”的行动清单。
- 次日方案也要说明每个行动建议对应的触发条件、仓位约束和风险点。
- `memory_update.md` 只做轻量辅助，用于把明确的用户更新写入三份记忆文件；不是默认交易判断功能。
- 每个 skill 都声明必需输入、优先使用的确定性数据、模型查询/看图分析边界、输出结构和缺失数据处理方式。

助手侧验证：

- 运行 skill loader 测试。
- 用静态样例包确认每个 skill 可以加载，并能生成有效执行契约。

用户侧检查：

- 阅读 skill 文件，确认交易规则表述是否需要更严格或更宽松。
- 特别确认规则匹配表和加分项匹配表是否符合你想看的报告粒度。

备注和依赖：

- Skills 应该是仓库内 Markdown 文件，而不是安装到全局 Codex 的 skill，除非后续用户明确要求做成可复用 Codex skill 包。

实际完成：

- 新增 5 个仓库内 Markdown skill：
  - `skills/target_screening.md`
  - `skills/buy_rating.md`
  - `skills/sell_rating.md`
  - `skills/next_day_plan.md`
  - `skills/memory_update.md`
- 每个 skill 都包含 `skill-metadata` 块，声明 `skill_id`、`command`、`schema_version`、`rating_enum`、`required_inputs`、`output_contract`。
- 判断标的、判断买入、判断卖出三个判断类 skill 都要求输出：
  - 评级枚举。
  - 结论摘要。
  - `rule_matches` 逐条规则匹配表。
  - `bonus_matches` 加分项匹配表。
  - `vetoes` 一票否决或必须卖规则。
  - `missing_evidence` 缺失证据。
  - `action` 最终行动建议。
- `target_screening.md` 已包含用户给出的选股一票否决和加分项。
- `buy_rating.md` 已包含用户给出的全部禁止购买规则、买入加分项、30% 现金保留和同题材不买多只纪律。
- `sell_rating.md` 已包含用户给出的“不卖”和“必须卖”规则。
- `next_day_plan.md` 已约束输出今晚观察、明天早盘、上午 10 点后、下午开盘、持仓去留等情景剧本。
- `memory_update.md` 已约束初版只允许更新三份长期记忆，不写市场上下文或独立交易日志。
- `src/trading_agent/skills.py` 从路径占位升级为轻量 loader：
  - 解析 metadata。
  - 加载单个或全部 skill。
  - 校验 command、必需 section 和判断类输出字段。
  - 生成 `SkillExecutionPacket`，记录 provided inputs、missing inputs 和 prompt。
- 新增 `tests/test_skills.py`，覆盖五个 skill 的加载、metadata、规则文本、输出契约和执行包。
- 已运行验证：
  - `python -m unittest discover -s tests`，21 个测试通过。
  - 静态样例执行包验证：`judge-target` 能生成 `# Skill Execution Packet: target_screening`，并正确列出缺失输入。
  - `python -m trading_agent.cli judge-target NVDA --market US` 仍能正常走 CLI 占位入口。

### Phase 4. 轻量 Markdown 记忆存储

目标：

- 创建三份用户可直接编辑的 Markdown 记忆文件，并实现安全读取和更新工具。

预计输出：

- `memory/user_profile.md`
- `memory/portfolio.md`
- `memory/watchlist.md`
- `src/trading_agent/memory.py`
- `tests/test_memory.py`

验收清单：

- 用户基础背景文件记录：
  - 主要交易市场。
  - 账户币种。
  - 资金规模或可用资金记录方式。
  - 风险偏好。
  - 最低现金保留规则。
  - 交易纪律备注。
- 当前持仓组合文件用 Markdown 表格记录：
  - symbol、market、名称、数量、买入日期、买入价、成本、市值或当前价、浮盈浮亏、题材、持仓逻辑、止损/止盈备注、交易备注。
  - 买入时间和买入价作为初版交易记录来源，不再单独建立交易日志。
- 观察池文件记录：
  - symbol、market、名称、题材、优先级、是否重点关注、入池日期、观察逻辑、失效条件、备注。
- 不创建 `market_context.md`。市场主线、热点和轮动方向每次分析时临时查询。
- 不创建 `decision_log.md`。必要交易备注写入持仓表。
- 更新工具必须保留周围 Markdown 内容，不能抹掉用户自由备注。
- 含糊的更新必须要求确认，不能猜。

助手侧验证：

- 用 fixture 文件运行 parser / writer 单元测试。
- 跑一次 dry-run 记忆更新，只打印 diff，不写入。

用户侧检查：

- 填写或确认初始用户基础背景、持仓组合和观察池。

实际完成：

- 新增三份长期记忆模板：
  - `memory/user_profile.md`
  - `memory/portfolio.md`
  - `memory/watchlist.md`
- 未创建 `market_context.md` 或 `decision_log.md`；市场信息仍按计划每次临时查询，交易记录并入持仓表。
- `user_profile.md` 记录主要交易市场、账户币种、资金规模或记录方式、风险偏好、最低现金保留规则和交易纪律备注。
- `portfolio.md` 使用 Markdown 表格记录当前持仓，字段包括 `symbol`、`market`、`name`、`quantity`、`buy_date`、`buy_price`、`cost`、`current_price`、`unrealized_pnl`、`theme`、`thesis`、`stop_notes`、`notes`。
- `watchlist.md` 使用 Markdown 表格记录观察池，字段包括 `symbol`、`market`、`name`、`theme`、`priority`、`focus_pool`、`added_date`、`thesis`、`invalidation`、`notes`。
- `src/trading_agent/memory.py` 从路径占位升级为轻量 Markdown 记忆工具：
  - 限制只允许三份计划内文件。
  - 读取单个 memory 文件和三文件 bundle。
  - 解析第一张 Markdown 表格。
  - 按 key column 对表格行进行 upsert。
  - 支持 `dry_run=True` 返回 unified diff，不写文件。
  - `dry_run=False` 只替换表格块，保留周围 Markdown 和自由备注。
  - 缺少 key value 的含糊更新会抛出 `MemoryError`，不猜。
- 新增 `tests/test_memory.py`，覆盖模板文件、表头、三文件读取、不允许非计划文件、dry-run diff、不覆盖自由备注、实际写入和含糊更新拒绝。
- 已运行验证：
  - `python -m unittest discover -s tests`，28 个测试通过。
  - 静态 dry-run：向 `portfolio.md` 试插入 `NVDA` 行，只输出 diff，不写入文件。

### Phase 5. 主 Agent 编排

目标：

- 实现主 Agent，负责用户命令、自然语言上下文检查、对话中的买卖更新识别、临时查询、skill 选择、行情脚本调用、记忆读取和报告组装。

预计输出：

- `src/trading_agent/cli.py`
- `src/trading_agent/report.py`
- `tests/test_cli_routing.py`
- `tests/test_report_packets.py`
- `tests/test_agent_preflight.py`

验收清单：

- CLI 至少暴露：
  - `judge-target`
  - `judge-buy`
  - `judge-sell`
  - `plan-next-day`
  - `update-memory`
  - `fetch-quotes`
- `judge-target`、`judge-buy`、`judge-sell` 支持用户传入标的名称或代码。
- Agent 优先按显式命令路由到正确 skill。自然语言意图路由可以后续再加，不能影响初版稳定性。
- Agent 必须通过自然语言上下文检查关键记忆，不要求用户先懂“初始化流程”：
  - 如果 `memory/user_profile.md` 或 `memory/watchlist.md` 仍是模板值或空白，只作为可选上下文提示，不阻塞判断标的或普通买入判断。
  - `judge-buy` 必须检查 `memory/portfolio.md` 是否为空或是否已有该标的；空仓新开仓买入允许继续。
  - 如果用户是在问加仓/补仓，必须先确认该标的当前持仓，并补充 symbol、market、name、quantity、buy_date、buy_price、cost 或当前价、theme、thesis。
  - `judge-sell` 和 `plan-next-day` 必须强制检查持仓完整性；缺持仓或缺买入信息时不能继续完整分析。
  - 补充问题要短而明确，适合用户在 Codex、Cursor 或 Claude Code 里直接回答。
- Agent 必须在任何命令或多轮对话中识别明确的买入/卖出/加仓/减仓/清仓信息：
  - 如果用户说“我买了/卖了/加仓/减仓/清仓/成本变了/持仓变了”等，应先生成或执行 memory update 计划，再继续原本命令。
  - 明确字段齐全时，更新 `memory/portfolio.md`。
  - 字段不完整时，必须询问缺失项，不能猜买入价、卖出价、数量或日期。
  - 卖出后若仍有剩余持仓，更新数量和备注；若清仓，初版可以从持仓表移除或将数量改为 0 并在 notes 标记，具体策略需要在 Phase 5 实现时固定。
- Agent 在调用 skill 前加载相关记忆文件，并调用行情脚本获取近期和当日基础行情。
- `judge-sell` 预检：
  - 必须在 `portfolio.md` 找到该标的持仓。
  - 必须有 quantity，以及 buy_date + buy_price 或足够等价的成本信息。
  - 如果缺少买入时间、买入价格、数量或持仓逻辑，应先要求用户补充，不进入卖出判断。
- `plan-next-day` 预检：
  - 必须检查当前持仓表是否存在不完整行。
  - 如果持仓有 symbol 但缺少 quantity、buy_date、buy_price/cost、thesis 等关键字段，应先列出缺失项并要求用户补充。
  - 用户确认没有持仓时，允许基于现金和观察池生成空仓次日方案。
- Agent 每次分析需要市场主线、风险事件、热点轮动或较长周期 K 线形态时，临时交给大模型查询和看图分析，不从长期记忆读取。
- Agent 可以组装完整的 prompt / evidence packet 供 LLM 执行。
- 如果配置了 LLM API key 或客户端，Agent 可以通过 provider-agnostic adapter 调用。
- 如果没有配置 LLM，Agent 也能打印或保存 prompt / evidence packet，让用户手动使用。
- 输出必须包含评级枚举、结论摘要、逐条规则命中原因、加分项命中原因、一票否决项、脚本行情证据、模型查询证据、缺失数据、建议动作和风险提示。
- 对于 `judge-target 标的` 这类命令，不能只给评级，必须明确“为什么符合/不符合每条核心规则”和“哪些加分项成立/不成立”。

助手侧验证：

- 运行单元测试。
- 用 fixture 数据运行每个命令。
- 验证命令默认不会把完整持仓和资金写入日志。
- 验证普通判断标的不会被空白初始化信息阻塞。
- 验证普通买入在持仓为空时可继续，并给出“按空仓新开仓处理”的提示。
- 验证加仓买入、卖出和次日计划在必要持仓信息缺失时会输出补充问题。
- 验证用户输入买入/卖出更新时会走 memory update 计划。
- 验证 `judge-sell` 和 `plan-next-day` 在持仓买入信息缺失时会阻止继续分析并要求补充。

用户侧检查：

- 用真实或样例 symbol 跑一次判断标的、判断买入、判断卖出、次日方案。
- 确认报告粒度足够实用，特别是规则命中和加分项解释。

实际完成：

- `src/trading_agent/cli.py` 已从占位命令升级为 Phase 5 Agent packet 编排入口。
- 判断类命令现在会生成完整 packet，而不是直接调用 LLM：
  - `judge-target`
  - `judge-buy`
  - `judge-sell`
  - `plan-next-day`
- 每个 packet 包含：
  - `status`
  - `setup_questions`
  - `preflight_issues`
  - `portfolio_notices`
  - `memory_update`
  - `quote_snapshots`
  - `quote_errors`
  - `skill_packet`
  - 完整 prompt/evidence packet
- 新增或升级 CLI 参数：
  - `--user-note`：携带可能包含买入/卖出/加仓/减仓/清仓的用户对话内容。
  - `--apply-memory-updates`：字段完整时应用检测到的持仓更新。
  - `--skip-quotes`：跳过 live 行情，便于测试或离线生成 packet。
  - `--output-packet`：把 packet 写到文件。
  - `--allow-empty-portfolio`：用户确认空仓后允许生成次日方案。
  - `--format text|json`：判断类命令输出文本或 JSON packet。
- `update-memory` 命令现在会调用确定性更新识别逻辑：
  - 字段不完整时返回 `needs_confirmation` 和补充问题。
  - 字段完整并加 `--apply` 时可以更新 `memory/portfolio.md`。
- `src/trading_agent/memory.py` 新增 Agent 预检和更新识别能力：
  - 可选上下文问题生成。
  - `judge-buy` 空仓、已有持仓、明确加仓上下文检查。
  - 持仓表 symbol/name 查找。
  - `judge-sell` 持仓完整性预检。
  - `plan-next-day` 持仓完整性预检。
  - 明确事实型买入/卖出/加仓/减仓/清仓文本识别，避免把“能不能买/要不要卖/是否加仓/准备买入”误当成已发生交易。
  - 完整更新生成 diff 或写入；含糊更新要求用户补充。
- `src/trading_agent/report.py` 新增 Agent packet 文本和 JSON 格式化。
- 新增测试：
  - `tests/test_agent_preflight.py`
  - `tests/test_cli_routing.py`
  - `tests/test_report_packets.py`
- 已运行验证：
  - `python -m unittest discover -s tests`，46 个测试通过。
  - `python -m trading_agent.cli judge-target NVDA --market US --skip-quotes --format json`
  - `python -m trading_agent.cli judge-sell NVDA --market US --skip-quotes --format text`
  - `python -m trading_agent.cli update-memory '我买了 NVDA' --format json`
  - `python -m trading_agent.cli plan-next-day --allow-empty-portfolio --skip-quotes --format text`

### Phase 6. 验证、文档和收口

目标：

- 让初版变得可用、可维护、可验证，再考虑回测、调度或自动流程。

预计输出：

- `README.md`
- `docs/overview.md`
- `docs/trading-agent-plan.md`
- 测试 fixture 和缺失测试

验收清单：

- README 说明安装、记忆文件编辑方式、命令和示例。
- README 说明在 Codex、Cursor、Claude Code 中如何打开工程后通过自然语言交互使用：
  - 首次使用如何补充用户基础背景、当前持仓和观察池。
  - 后续对话中如何表达买入、卖出、加仓、减仓、清仓，Agent 应如何更新 memory。
  - 如何运行 `judge-target`、`judge-buy`、`judge-sell`、`plan-next-day`、`fetch-quotes`。
  - 卖出判断和次日方案为什么需要完整买入日期、买入价、数量和持仓逻辑。
- overview 反映真实实现结构。
- 计划状态表和阶段完成记录准确。
- 测试覆盖行情标准化、记忆解析、skill 加载、agent 路由、报告包组装。
- 测试覆盖自然语言上下文检查、买卖更新识别、持仓信息完整性预检。
- 已记录已知限制和人工检查项。
- 回测、日常定时刷新、自动工作流作为未来扩展记录下来，不混入初版实现。

助手侧验证：

- 运行完整测试。
- 用 fixture 跑命令 smoke check。
- 给出用户如何在 Codex、Cursor、Claude Code 中测试各模块的清单。

用户侧检查：

- 用真实用户画像和持仓运行四个默认功能。
- 确认系统对不追高、保留现金、卖出纪律的约束足够严格。

实际完成：

- 新增自然语言 Agent 入口：
  - `AGENTS.md`：Codex / 通用 AI agent 主入口。
  - `CLAUDE.md`：Claude Code 入口，指向 `AGENTS.md`。
  - `.cursor/rules/trading-agent.mdc`：Cursor 自动规则，指向 `AGENTS.md`。
- `AGENTS.md` 明确了最终使用方式：
  - 用户只需要自然语言交流。
  - AI 工具内部调用 `python -m trading_agent.cli ...`。
  - 不要求用户手动运行命令，除非用户明确要测试模块。
  - 每轮对话先识别事实型买入/卖出/加仓/减仓/清仓等 memory update，分析问题和计划交易意图不误当作交易更新。
  - `judge-buy` 对空仓新买入不阻塞；明确加仓时必须检查当前持仓。
  - `judge-sell` 和 `plan-next-day` 必须先检查持仓买入信息完整性。
  - market context 每次临时查询，不写长期记忆。
- 重写 `README.md`：
  - 说明 Codex / Cursor / Claude Code 打开工程后的自然语言用法。
  - 说明首次补充用户基础背景、当前持仓、观察池。
  - 说明买卖更新如何进入 `memory/portfolio.md`。
  - 保留内部命令作为模块测试和 AI 工具内部调用说明。
  - 给出模块测试清单。
- 新增 `tests/test_docs.py`，验证 AI 工具入口文件存在、README 包含 AI 工具使用和测试说明。
- 已运行完整测试：
  - `python -m unittest discover -s tests`，46 个测试通过。
- 已运行 smoke checks：
  - `python -m trading_agent.cli fetch-quotes NVDA --market US --format table`
  - `python -m trading_agent.cli judge-target NVDA --market US --skip-quotes --format json`
  - `python -m trading_agent.cli judge-sell NVDA --market US --skip-quotes --format text`
  - `python -m trading_agent.cli plan-next-day --allow-empty-portfolio --skip-quotes --format text`

## 7. 执行规则

- 如果用户说 `execute Phase X`，只执行指定阶段。
- 如果用户说 `执行 Phase X`，只执行指定阶段。
- 如果用户说 `continue` 或 `继续`，优先继续第一个 `in_progress` 阶段；如果没有，则执行第一个 `pending` 阶段。
- 如果用户请求的阶段依赖尚未完成的前置阶段，且不能安全隔离执行，需要停止并说明依赖。
- 如果执行时发现某个阶段过大、过风险、或无法在一次上下文中安全验证，需要先把该阶段拆成子阶段，例如 `Phase 5A` 和 `Phase 5B`，再继续。
- 不为了整齐、对称或预防性好看而拆阶段。只有执行时出现证据表明原阶段不再安全可控，才拆。
- 拆分阶段时，必须先更新总阶段表、受影响阶段详情、验收清单和后续执行顺序，再开始实现新的子阶段。
- 优先采用最小有用拆分，通常拆成两个子阶段。除非技术上不可避免，不要把每个阶段都拆成很多小段。
- 尽量保留后续阶段编号。不能因为细化某个未来阶段就重写无关的已完成阶段。
- 每执行完一个阶段，都要更新这份计划文档，记录实际情况。
- 每执行完一个阶段，都要默认同步 `docs/overview.md`。
- 用户明确批准计划或要求执行某个阶段之前，不能开始 Phase 1。

## 8. 关键链路可观测性要求

这个项目会涉及多个验收关键链路：用户命令入口、记忆读取/更新、行情获取、skill 执行、报告组装。相关阶段必须在关键边界加入简洁诊断日志。

推荐日志格式：

```text
[trading-agent] chain=<chain> event=<event> status=<status> key=value
```

需要覆盖的链路和事件：

- 命令入口和路由：
  - 记录命令名、路由选择、请求 symbol、dry-run/write 模式。
  - 不记录可能包含账户细节的原始大段用户笔记。
- 记忆读取和更新：
  - 记录文件名、schema 版本、更新模式、校验成功/失败、是否生成 diff。
  - 默认不记录完整现金金额、完整持仓表或私人备注。
- 行情获取：
  - 记录 provider、market、symbol 数量、开始/结束、数据缺失字段、provider 错误。
  - 不记录巨大的 provider 原始 payload。
- Skill 加载和评估：
  - 记录 skill 文件、schema 版本、必需输入检查、缺失数据类别、输出校验结果。
  - 除非显式开启 debug，不记录完整 prompt。
- 报告组装：
  - 记录报告类型、评级枚举、规则命中数量、加分项命中数量、缺失证据数量、输出位置。
  - 常规日志不记录完整生成建议。

持久性：

- Phase 1 增加的日志工具应作为长期基础设施保留。
- provider 迁移或 LLM prompt 调试需要的额外详细日志可以是临时的，并由 `--debug` 控制。
- 日志必须便于 grep，且保持低噪声。
