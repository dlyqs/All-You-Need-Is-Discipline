# Project Overview

## Current Project Overview

`All-You-Need-Is-Discipline` is a greenfield repository for building a disciplined auxiliary trading decision agent. Phase 1 created the lightweight Python package skeleton, CLI shell, core data contracts, placeholder module boundaries, and unit-test scaffold. Phase 2 added the simplified quote-fetching script and real market-data normalization boundary. Phase 3 added repo-local trading skills plus a lightweight skill loader and execution-packet builder. Phase 4 added the three long-term Markdown memory files and safe table-oriented memory helpers. Phase 5 connected CLI, memory, quote evidence, skills, setup questions, portfolio preflight, and prompt/evidence packet assembly. Phase 6 added AI-tool entry files and final usage/testing documentation.

The planned runtime shape is a local, CLI-first Python project. The agent will use deterministic scripts only to speed up basic quote lookup, repository-local Markdown skills for trading judgment workflows, and a small set of Markdown memory files for durable user context.

There is no frontend in the current project. The implementation plan intentionally avoids browser/page inspection and frontend tooling.

## Project File Organization

Current files:

- `README.md`: user-facing guide for natural-language use through Codex, Cursor, or Claude Code plus module testing commands.
- `AGENTS.md`: primary natural-language trading agent entry for Codex/general AI tools.
- `CLAUDE.md`: Claude Code entry pointing to `AGENTS.md`.
- `.cursor/rules/trading-agent.mdc`: Cursor rule pointing to `AGENTS.md`.
- `LICENSE`: MIT license.
- `.gitignore`: ignores Python caches, editable-install metadata, virtual environments, and build outputs.
- `pyproject.toml`: package metadata, editable-install support, and the `trading-agent` console entry point.
- `docs/overview.md`: this developer entry document.
- `docs/trading-agent-plan.md`: the staged implementation contract for the trading decision agent. Later `continue`, `继续`, or `执行 Phase X` work should read this plan first.
- `src/trading_agent/__init__.py`: package marker and version.
- `src/trading_agent/cli.py`: CLI command routing and Phase 5 Agent packet assembly for judgment commands, memory updates, quote calls, setup questions, and portfolio preflight.
- `src/trading_agent/models.py`: core data contracts for markets, symbols, quote snapshots, holdings, evidence, rule matches, and rating results.
- `src/trading_agent/market_data.py`: simplified market-data fetching and normalization. It currently uses Tencent quote/kline endpoints for A-shares and Yahoo chart for US stocks.
- `src/trading_agent/memory.py`: safe helpers for the three planned memory files, including allowed-file checks, Markdown table parsing, dry-run diffs, table-row upsert, setup question generation, portfolio preflight, and simple buy/sell update detection.
- `src/trading_agent/skills.py`: repo-local skill metadata parser, loader, validator, and execution-packet builder.
- `src/trading_agent/report.py`: Agent packet and rating result formatting helpers.
- `scripts/fetch_quotes.py`: executable repository-local quote script for simplified A-share and US quote lookup.
- `skills/target_screening.md`: judging whether a target passes the user's selection rules.
- `skills/buy_rating.md`: judging whether a target is buyable today under the user's prohibition rules and cash discipline.
- `skills/sell_rating.md`: judging whether a holding should be sold, reduced, held, or watched.
- `skills/next_day_plan.md`: producing scenario-based next-trading-day action plans.
- `skills/memory_update.md`: converting explicit user updates into safe memory update plans.
- `memory/user_profile.md`: durable user background and trading discipline.
- `memory/portfolio.md`: current holdings table. Buy date, buy price, quantity, thesis, stop notes, and remarks live here instead of a separate transaction log.
- `memory/watchlist.md`: selected targets, themes, priority, focus-pool status, thesis, invalidation conditions, and notes.
- `tests/test_models.py`, `tests/test_cli.py`, `tests/test_boundaries.py`, `tests/test_market_data.py`, `tests/test_skills.py`, `tests/test_memory.py`, `tests/test_agent_preflight.py`, `tests/test_cli_routing.py`, `tests/test_report_packets.py`, `tests/test_docs.py`: standard-library `unittest` coverage for current contracts, market-data normalization, skill loading, memory helpers, Agent preflight, CLI routing, report packets, and documentation entry files.

Planned directories after phased implementation:

- `src/trading_agent/`: main Python package with a deliberately flat v1 layout: `cli.py`, `models.py`, `market_data.py`, `memory.py`, `skills.py`, and `report.py`.
- `scripts/`: deterministic executable scripts, starting with simplified A-share and US quote lookup.
- `skills/`: repository-local Markdown skill definitions for target screening, buy rating, sell rating, next-day planning, and lightweight memory update discipline.
- `memory/`: exactly three user-editable Markdown memory documents for user profile, current portfolio, and watchlist.
- `tests/`: unit and fixture tests for quote normalization, memory parsing, skill loading, routing, and report packets.
- `docs/`: execution plan, project overview, and later operational notes.

## Core Functional Modules And Key Chains

The core behavior is planned around these chains:

- AI-tool natural-language entry:
  - Primary entry is `AGENTS.md`.
  - Codex/general agents should read `AGENTS.md`, `docs/overview.md`, and `docs/trading-agent-plan.md` before acting.
  - Claude Code starts from `CLAUDE.md`, which delegates to `AGENTS.md`.
  - Cursor starts from `.cursor/rules/trading-agent.mdc`, which delegates to `AGENTS.md`.
  - The user should talk naturally; the AI tool calls CLI commands internally when useful.
- User command to agent routing:
  - Entry will be a CLI command in `src/trading_agent/cli.py`.
  - Routing and orchestration will live in `src/trading_agent/cli.py` for v1. A separate `agent.py` is unnecessary until orchestration becomes meaningfully complex.
  - Initial commands should map directly to: `judge-target`, `judge-buy`, `judge-sell`, and `plan-next-day`.
  - The report for a command such as `judge-target <symbol-or-name>` must include the rating plus rule-by-rule reasons and matching bonus items.
  - Current Phase 5 behavior generates prompt/evidence packets rather than executing an LLM directly.
  - Blank profile/watchlist context is now optional context, not a hard initialization gate.
  - Explicit factual buy/sell/add/reduce/clear updates can be detected via `--user-note` or `update-memory`; analysis questions or planned-trade intents such as “能不能买/是否加仓/准备买入/要不要卖” should not be treated as memory updates.
  - `judge-buy` checks portfolio context without blocking normal empty-position buys. Explicit add-buy requests require an existing complete holding first.
  - `judge-sell` and `plan-next-day` preflight portfolio completeness. If a holding lacks quantity plus buy date and buy price/cost, the Agent asks the user to fill those fields before analysis.
- Simplified quote retrieval:
  - `scripts/fetch_quotes.py` will provide a deterministic user-facing script.
  - `src/trading_agent/market_data.py` holds the initial provider calls, parsing, normalization, output formatting, and CLI helper for the script.
  - Quote outputs focus on recent closing prices, recent percentage changes, turnover where available, current-day open/latest or close, current-day percentage change, rough intraday shape, limit-up/sealed-board related flags where available, source, timestamp, and missing fields.
  - The script should not analyze months of daily K-line behavior, chip distribution, or complex chart patterns. Those remain model-side analysis tasks.
  - Current provider limitations are explicit: US turnover and limit-up/board fields are missing; A-share recent daily turnover and board-open status are not reliably available through the current lightweight endpoints.
- Skill execution:
  - `skills/*.md` will contain the user-specific trading rules and output schemas.
  - `src/trading_agent/skills.py` will load skill files, validate required inputs, and prepare execution packets.
  - Skills must separate deterministic quote evidence from model search, model chart/image analysis, assumptions, and missing evidence.
  - Judging skills must output rating, conclusion, `rule_matches`, `bonus_matches`, `vetoes`, `missing_evidence`, and action. This is now encoded in the skill files and checked by tests.
- Memory storage:
  - `memory/user_profile.md` will store durable background such as market, funds/risk preferences, cash-reserve rule, and trading discipline notes.
  - `memory/portfolio.md` will store current holdings. Trade information such as buy date, buy price, quantity, thesis, stop notes, and remarks belongs in this table rather than a separate trading log.
  - `memory/watchlist.md` will store selected targets, themes, priority, focus-pool status, thesis, and invalidation conditions.
  - No long-term `market_context.md` is planned for v1. Market themes, risk events, and rotations are queried fresh during each analysis.
  - `src/trading_agent/memory.py` can parse the first Markdown table in each memory file and apply safe row upserts with a dry-run diff. It only replaces the table block and preserves surrounding notes.
  - Agent orchestration treats portfolio buy information as required for sell judgments, next-day holding plans, and explicit add-buy judgments.
- Report assembly:
  - `src/trading_agent/report.py` will format structured outputs into practical trading checklists.
  - Reports should include rating enum, conclusion, hard-rule matches, bonus-item matches, veto triggers, script evidence, model evidence, missing data, action recommendation, and risk notes.
  - Current output is an LLM-ready packet containing optional setup/context questions, portfolio notices, blocking preflight issues, quote evidence, skill metadata, and the full skill prompt.

## Maintenance Notes

- For this large goal, `docs/trading-agent-plan.md` is the phase source of truth. Before executing `continue`, `继续`, or `执行 Phase X`, read that file first.
- After each executed phase, update both `docs/trading-agent-plan.md` and this overview so future agents can continue from the actual project state.
- Keep trading rules in `skills/*.md` rather than burying them in code unless deterministic validation requires code-level constants.
- Keep quote provider details behind adapters so data sources can be replaced when public APIs change.
- Do not add brokerage order execution in the initial version.
- Do not add frontend work, page viewing, or playwright usage for this project unless the user explicitly changes that instruction.
- Do not store market context or daily quote snapshots in v1. Query current market information at analysis time.
- Do not create a separate transaction log in v1. Record buy date, buy price, quantity, thesis, and notes in the holdings table.
- Do not log full portfolio values, private notes, or raw generated prompts by default.
- If backtesting, daily refresh, scheduling, or automation is added later, treat it as a separate planned feature after the initial four functions are stable.
- If quote endpoints become unstable, replace them inside `src/trading_agent/market_data.py` without changing the higher-level CLI contract.
- Phase 6 should now focus on README, usage examples for Codex/Cursor/Claude Code, fixture smoke checks, and final documentation sync.
- Phase 6 is complete. Future work should be planned as a new phase or extension, such as direct LLM provider integration, backtesting, or automation.
