# All-You-Need-Is-Discipline

A local, CLI-backed trading decision assistant designed for use through Codex, Cursor, or Claude Code.

The intended workflow is natural-language first: open this repository in an AI coding tool, talk to the trading agent, and let the agent call the local scripts and memory helpers internally.

## Agent Entry

Use [AGENTS.md](AGENTS.md) as the main agent entry.

For tool-specific entrypoints:

- Codex / general agents: [AGENTS.md](AGENTS.md)
- Claude Code: [CLAUDE.md](CLAUDE.md)
- Cursor: [.cursor/rules/trading-agent.mdc](.cursor/rules/trading-agent.mdc)

Normal use should look like this. You do not need to know the memory schema upfront; the agent asks for missing facts only when a function needs them.

```text
我现在持仓 NVDA，10 股，2026-05-06 买入，买入价 196.5，逻辑是 AI 算力核心。
帮我判断 NVDA 今天还能不能买。
帮我判断 NVDA 要不要卖。
帮我整理明天的交易计划。
```

The AI tool should read `AGENTS.md`, inspect memory, call the internal CLI, and answer according to the relevant skill. You should not need to manually run commands for ordinary use.

## What Exists Now

- `memory/portfolio.md`: 「用户与账户」+ 当前持仓表。列：`symbol`, `market`, `name`, `quantity`, `buy_date`, `buy_price`, `lots`, `notes`（仅在有说明时填写）。不长期存现价、浮盈浮亏、题材、临时的止损止盈判断。
- `memory/watchlist.md`: watchlist targets and invalidation logic.
- `skills/*.md`: judgment rules for target screening, buy rating, sell rating, next-day planning, and memory updates.
- `scripts/fetch_quotes.py`: simplified A-share and US quote lookup.
- `src/trading_agent/`: Python package with `cli.py` (memory read + preflight + packet formatting), `market_data.py`, `models.py`, and `skills.py`.

## First-Time Setup

Install the package in editable mode:

```bash
python -m pip install -e .
```

Then talk to the AI agent in natural language. You can give account and holding facts when they are relevant; the agent should not require a separate manual initialization step.

Minimum useful user profile:

```text
主要交易市场：A股/美股
账户币种：CNY/USD
资金规模或记录方式：例如总资金 54300，现金 24644
风险偏好：保守/均衡/进攻
最低现金保留规则：至少 30% 现金
```

Minimum useful holding row (持仓表):

```text
symbol, market, name, quantity, buy_date, buy_price, lots, notes(optional)
```

For multiple buys, summarize the current position and keep lot details in `lots`, for example:

```text
2026-04-24:100@88.1; 2026-04-28:100@88.76
```

Buy judgments can run with an empty portfolio because they may be new-position buys. Add-buy judgments, sell judgments, and next-day plans require complete holding information. If buy date, buy price, or quantity is missing, the agent should ask you to fill it before analysis. For buy/sell sizing, the agent should also ask for total position ratio, cash ratio, target position weight, other holdings, and same-theme holdings when those are unknown.

## Natural-Language Use

After opening the project in Codex, Cursor, or Claude Code, speak normally:

```text
我买了 NVDA，market=US，quantity=10，buy_date=2026-05-06，buy_price=196.5，notes=AI 算力核心。
```

The agent should treat this as a factual memory update: follow `skills/memory_update.md` and edit `memory/portfolio.md` / `memory/watchlist.md` when fields are clear; otherwise ask for missing fields only.

Examples:

```text
帮我判断 600519 是否符合选股规则。
帮我判断 NVDA 今天是否可以买入。
我持有 NVDA，帮我判断要不要卖。
根据我当前持仓和观察池，帮我做明天交易计划。
```

The agent should internally:

1. Check whether the message clearly reports a factual buy/sell/add/reduce/clear update, without treating questions or plans like “能不能加仓/准备买入” as completed trades.
2. Update memory or ask for missing fields only for factual updates.
3. Run the appropriate CLI command to build a prompt/evidence packet.
4. Check portfolio context for non-target functions.
5. Let normal new-position buy analysis continue even if the portfolio is empty.
6. Block add-buy, sell, and next-day plan when required holding facts are missing.
7. Fetch script quote evidence when useful.
8. Query current market context itself.
9. Produce the final structured judgment using the relevant skill.

## Internal Commands

These commands are for testing and for AI tools to call internally. They are not the main user interface.

Run all tests:

```bash
python -m unittest discover -s tests
```

Fetch quotes:

```bash
python -m trading_agent.cli fetch-quotes NVDA --market US --format table
python -m trading_agent.cli fetch-quotes 600519 --market A --format json
```

Generate packets:

```bash
python -m trading_agent.cli judge-target NVDA --market US --format text
python -m trading_agent.cli judge-buy NVDA --market US --format json
python -m trading_agent.cli judge-sell NVDA --market US --format text
python -m trading_agent.cli plan-next-day --allow-empty-portfolio --format text
```

Assemble the memory-update skill packet (you still edit Markdown yourself):

```bash
python -m trading_agent.cli update-memory '我买了 NVDA market=US quantity=10 buy_date=2026-05-06 buy_price=196.5' --format json
```

Save a packet for another AI tool:

```bash
python -m trading_agent.cli judge-target NVDA --market US --output-packet packet.md
```

## Module Test Checklist

- Quote module:
  `python -m trading_agent.cli fetch-quotes NVDA --market US --format table`
- Skill loader:
  `python - <<'PY'
from pathlib import Path
from trading_agent.skills import load_all_skills
for command, skill in load_all_skills(Path.cwd()).items():
    print(command, skill.metadata.skill_id, skill.metadata.output_contract)
PY`
- Memory update skill packet:
  `python -m trading_agent.cli update-memory '我买了 NVDA' --format json`
- Agent packet:
  `python -m trading_agent.cli judge-target NVDA --market US --skip-quotes --format json`
- Portfolio preflight:
  `python -m trading_agent.cli judge-sell NVDA --market US --skip-quotes --format text`
- Full tests:
  `python -m unittest discover -s tests`

## Current Limits

- The system does not place trades.
- The CLI generates prompt/evidence packets; the AI tool performs the final reasoning.
- A-share quotes currently use Tencent quote/K-line endpoints plus Eastmoney intraday minutes when available.
- US quotes currently use Yahoo chart.
- US turnover and limit-up/board fields are usually missing.
- A-share recent-bar turnover uses the 10jqka daily endpoint when available; if it is unavailable, historical turnover is omitted instead of estimated.
- A-share sealed-board/opened-board flags are estimated from high/latest price versus inferred limit-up percentage.
- Long-term K-line interpretation, chip distribution, and market theme analysis are model-side tasks.
