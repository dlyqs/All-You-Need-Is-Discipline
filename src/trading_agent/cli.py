"""Command-line shell: quotes, memory-aware packets, and skill prompt assembly.

长期记忆文件的**写入**由对话里的模型按 `skills/memory_update.md` 直接改 Markdown；
此处仅负责读取、表格解析（用于持仓预检）和组装执行包。Skill 不会也不能替代确定性的读盘与表解析。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from trading_agent.market_data import (
    MarketDataError,
    build_quote_request,
    fetch_quotes,
    snapshot_to_dict,
    snapshots_to_json,
    snapshots_to_table,
)
from trading_agent.skills import SkillError, build_execution_packet

# --- Long-term memory (read + table parse only) --------------------------------

MEMORY_FILENAMES = ("portfolio.md", "watchlist.md")
QUOTE_CACHE_TTL_SECONDS = 300

PORTFOLIO_HOLDINGS_HEADING = "## 持仓表"
PORTFOLIO_ACCOUNT_HEADING = "## 用户与账户"


class MemoryError(ValueError):
    """Raised when a memory read or table parse fails."""


@dataclass(frozen=True)
class MemoryPaths:
    root: Path
    portfolio: Path
    watchlist: Path


@dataclass(frozen=True)
class MarkdownTable:
    headers: tuple[str, ...]
    rows: list[dict[str, str]]
    start_line: int
    end_line: int


@dataclass(frozen=True)
class SetupQuestion:
    area: str
    question: str
    required_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class PortfolioPreflightIssue:
    symbol: str
    missing_fields: tuple[str, ...]
    question: str


@dataclass(frozen=True)
class PortfolioContextNotice:
    symbol: str
    level: str
    message: str


@dataclass(frozen=True)
class QuoteCacheEntry:
    request_symbol: str
    market: str
    recent_days: int
    cached_at: float
    quote_snapshots: list[dict[str, object]]
    quote_errors: list[str]


def expected_memory_paths(project_root: Path | str) -> MemoryPaths:
    root = Path(project_root).resolve() / "memory"
    return MemoryPaths(
        root=root,
        portfolio=root / "portfolio.md",
        watchlist=root / "watchlist.md",
    )


def existing_memory_files(project_root: Path | str) -> list[Path]:
    paths = expected_memory_paths(project_root)
    return [path for path in (paths.portfolio, paths.watchlist) if path.exists()]


def allowed_memory_path(project_root: Path | str, filename: str) -> Path:
    if filename not in MEMORY_FILENAMES:
        raise MemoryError(f"Unsupported memory file: {filename}")
    paths = expected_memory_paths(project_root)
    mapping = {
        "portfolio.md": paths.portfolio,
        "watchlist.md": paths.watchlist,
    }
    return mapping[filename]


def read_memory_file(project_root: Path | str, filename: str) -> str:
    path = allowed_memory_path(project_root, filename)
    if not path.exists():
        raise MemoryError(f"Memory file does not exist: {path}")
    return path.read_text(encoding="utf-8")


def read_memory_bundle(project_root: Path | str) -> dict[str, str]:
    return {filename: read_memory_file(project_root, filename) for filename in MEMORY_FILENAMES}


def iter_markdown_tables(text: str, start_line: int = 0) -> list[MarkdownTable]:
    lines = text.splitlines()
    tables: list[MarkdownTable] = []
    index = start_line
    while index < len(lines) - 1:
        if is_table_row(lines[index]) and is_separator_row(lines[index + 1]):
            headers = tuple(split_table_row(lines[index]))
            rows = []
            end = index + 2
            while end < len(lines) and is_table_row(lines[end]):
                values = split_table_row(lines[end])
                if any(value != "" for value in values):
                    rows.append(row_from_values(headers, values))
                end += 1
            tables.append(MarkdownTable(headers=headers, rows=rows, start_line=index, end_line=end))
            index = end
            continue
        index += 1
    return tables


def parse_first_markdown_table(text: str) -> MarkdownTable:
    tables = list(iter_markdown_tables(text, start_line=0))
    if not tables:
        raise MemoryError("No Markdown table found")
    return tables[0]


def _holdings_heading_line_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == PORTFOLIO_HOLDINGS_HEADING or stripped.startswith("## 持仓表"):
            return index
    return None


def parse_holdings_table(text: str) -> MarkdownTable:
    lines = text.splitlines()
    start_scan = 0
    heading_idx = _holdings_heading_line_index(lines)
    if heading_idx is not None:
        start_scan = heading_idx + 1
    for table in iter_markdown_tables(text, start_line=start_scan):
        if "symbol" in table.headers:
            return table
    for table in iter_markdown_tables(text, start_line=0):
        if "symbol" in table.headers:
            return table
    raise MemoryError("No holdings table with a symbol column found in portfolio.md")


def parse_account_table(text: str) -> MarkdownTable | None:
    lines = text.splitlines()
    start_scan = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == PORTFOLIO_ACCOUNT_HEADING or stripped.startswith("## 用户与账户"):
            start_scan = index + 1
            break
    else:
        return None
    for table in iter_markdown_tables(text, start_line=start_scan):
        if "字段" in table.headers and "值" in table.headers:
            return table
    return None


def extract_account_section_markdown(text: str) -> str:
    start = text.find(PORTFOLIO_ACCOUNT_HEADING)
    if start == -1:
        start = text.find("## 用户与账户")
    if start == -1:
        return ""
    next_heading = text.find("\n## ", start + 1)
    if next_heading == -1:
        return text[start:].strip()
    return text[start:next_heading].strip()


def parse_memory_table(project_root: Path | str, filename: str) -> MarkdownTable:
    raw = read_memory_file(project_root, filename)
    if filename == "portfolio.md":
        return parse_holdings_table(raw)
    return parse_first_markdown_table(raw)


def memory_table_rows(project_root: Path | str, filename: str) -> list[dict[str, str]]:
    return parse_memory_table(project_root, filename).rows


def find_row_by_symbol(rows: list[dict[str, str]], symbol_or_name: str) -> dict[str, str] | None:
    target = symbol_or_name.strip().lower()
    for row in rows:
        candidates = (
            row.get("symbol", ""),
            row.get("name", ""),
        )
        if any(candidate.strip().lower() == target for candidate in candidates if candidate):
            return row
    return None


def build_setup_questions(project_root: Path | str) -> list[SetupQuestion]:
    questions: list[SetupQuestion] = []
    raw_portfolio = read_memory_file(project_root, "portfolio.md")
    account = parse_account_table(raw_portfolio)
    profile_rows = account.rows if account else []
    blank_profile_fields = [
        row.get("字段", "")
        for row in profile_rows
        if is_template_value(row.get("值", ""))
    ]
    if blank_profile_fields:
        questions.append(
            SetupQuestion(
                area="user_profile",
                question=(
                    "请在 `memory/portfolio.md` 的「用户与账户」表中补充：主要交易市场、账户币种、"
                    "资金规模或记录方式、风险偏好、最低现金保留规则。"
                ),
                required_fields=tuple(blank_profile_fields),
            )
        )

    portfolio_rows = parse_holdings_table(raw_portfolio).rows
    if not portfolio_rows:
        questions.append(
            SetupQuestion(
                area="portfolio",
                question=(
                    "请确认你当前是否有持仓；如果有，请逐只补充 symbol、market、name、"
                    "quantity、buy_date、buy_price、lots（分批买入明细）；仅在有必要时填写 notes。"
                    "同时请说明当前总仓位比例、现金比例，以及是否还有其他持仓或同题材持仓。"
                ),
                required_fields=("symbol", "market", "quantity", "buy_date", "buy_price", "lots"),
            )
        )

    watchlist_rows = memory_table_rows(project_root, "watchlist.md")
    if not watchlist_rows:
        questions.append(
            SetupQuestion(
                area="watchlist",
                question=(
                    "请确认你是否已有观察池；如果有，请补充 symbol、market、theme、priority、"
                    "focus_pool、thesis、invalidation。没有观察池可以明确说暂无。"
                ),
                required_fields=("symbol", "market", "theme", "priority", "focus_pool", "thesis", "invalidation"),
            )
        )
    return questions


def is_template_value(value: str) -> bool:
    normalized = value.strip()
    return normalized == "" or normalized in {"待填写", "TBD", "todo", "TODO"}


def holding_missing_fields(row: dict[str, str]) -> tuple[str, ...]:
    missing = []
    for field in ("symbol", "quantity", "buy_date", "buy_price"):
        if is_template_value(row.get(field, "")):
            missing.append(field)
    return tuple(missing)


def portfolio_context_notices(
    project_root: Path | str,
    command: str,
    symbol_or_name: str | None = None,
) -> list[PortfolioContextNotice]:
    if command not in {"judge-buy", "judge-sell", "plan-next-day"}:
        return []

    rows = memory_table_rows(project_root, "portfolio.md")
    target = symbol_or_name or "portfolio"
    notices = [
        PortfolioContextNotice(
            symbol=target,
            level="info",
            message=(
                "请确认当前总仓位比例、现金比例、该标的仓位占比，以及是否还有其他持仓或同题材持仓；"
                "如果未补充，分析只能按已记录持仓和脚本行情给出，仓位建议需要保守处理。"
            ),
        )
    ]
    if rows and symbol_or_name and find_row_by_symbol(rows, symbol_or_name) and len(rows) == 1:
        notices.append(
            PortfolioContextNotice(
                symbol=symbol_or_name,
                level="warning",
                message=(
                    f"当前持仓表只记录了 `{symbol_or_name}`；如果实际还有其他持仓，"
                    "请补充后再判断组合仓位和同题材集中度。"
                ),
            )
        )
    return notices


def preflight_sell(project_root: Path | str, symbol_or_name: str) -> list[PortfolioPreflightIssue]:
    rows = memory_table_rows(project_root, "portfolio.md")
    row = find_row_by_symbol(rows, symbol_or_name)
    if row is None:
        return [
            PortfolioPreflightIssue(
                symbol=symbol_or_name,
                missing_fields=("portfolio_holding",),
                question=(
                    f"`{symbol_or_name}` 不在当前持仓表里。请先补充该标的持仓，"
                    "包括 quantity、buy_date、buy_price，以及分批买入 lots（如有）。"
                ),
            )
        ]
    missing = holding_missing_fields(row)
    if not missing:
        return []
    return [
        PortfolioPreflightIssue(
            symbol=row.get("symbol") or symbol_or_name,
            missing_fields=missing,
            question=f"`{row.get('symbol') or symbol_or_name}` 持仓信息不完整，请补充：{', '.join(missing)}。",
        )
    ]


def detect_add_buy_intent(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in text for keyword in ("加仓", "补仓", "追加仓位")) or any(
        keyword in lowered for keyword in ("add", "increase position")
    )


def preflight_buy(
    project_root: Path | str,
    symbol_or_name: str,
    user_note: str | None = None,
) -> tuple[list[PortfolioPreflightIssue], list[PortfolioContextNotice]]:
    rows = memory_table_rows(project_root, "portfolio.md")
    add_intent = detect_add_buy_intent(user_note or "")
    if not rows:
        if add_intent:
            return [
                PortfolioPreflightIssue(
                    symbol=symbol_or_name,
                    missing_fields=("portfolio_holding",),
                    question=(
                        f"你在判断 `{symbol_or_name}` 是否加仓，但当前持仓表为空。"
                        "请先补充该标的当前持仓数量、买入日期、买入价和分批买入明细。"
                    ),
                )
            ], []
        return [], [
            PortfolioContextNotice(
                symbol="portfolio",
                level="info",
                message=(
                    "当前持仓表为空；本次按空仓开新仓继续判断。"
                    "如果你实际已有持仓或这是加仓，请先告诉我当前持仓数量、买入日期、买入价和分批买入明细。"
                ),
            )
        ]

    row = find_row_by_symbol(rows, symbol_or_name)
    if row is None:
        if add_intent:
            return [
                PortfolioPreflightIssue(
                    symbol=symbol_or_name,
                    missing_fields=("portfolio_holding",),
                    question=(
                        f"你在判断 `{symbol_or_name}` 是否加仓，但持仓表里没有这个标的。"
                        "请先补充该标的当前持仓数量、买入日期、买入价和分批买入明细。"
                    ),
                )
            ], []
        return [], [
            PortfolioContextNotice(
                symbol=symbol_or_name,
                level="info",
                message=(
                    f"`{symbol_or_name}` 不在当前持仓表里；本次按新开仓买入判断。"
                ),
            )
        ]

    missing = holding_missing_fields(row)
    if missing:
        message = (
            f"`{row.get('symbol') or symbol_or_name}` 已在持仓表里，但信息不完整："
            f"{', '.join(missing)}。"
        )
        if add_intent:
            return [
                PortfolioPreflightIssue(
                    symbol=row.get("symbol") or symbol_or_name,
                    missing_fields=missing,
                    question=message + "加仓判断需要这些字段，请先补充。",
                )
            ], []
        return [], [
            PortfolioContextNotice(
                symbol=row.get("symbol") or symbol_or_name,
                level="warning",
                message=message + "如果这是加仓判断，需要先补充；如果只是另起一笔观察买点，可以继续。",
            )
        ]

    return [], [
        PortfolioContextNotice(
            symbol=row.get("symbol") or symbol_or_name,
            level="info",
            message=(
                f"`{row.get('symbol') or symbol_or_name}` 已在当前持仓表里；"
                "买入判断会同时参考现有仓位、买入价和 notes 中的持仓逻辑（若有）。"
            ),
        )
    ]


def preflight_next_day(project_root: Path | str, allow_empty_portfolio: bool = False) -> list[PortfolioPreflightIssue]:
    rows = memory_table_rows(project_root, "portfolio.md")
    if not rows:
        if allow_empty_portfolio:
            return []
        return [
            PortfolioPreflightIssue(
                symbol="portfolio",
                missing_fields=("portfolio_confirmation",),
                question="当前持仓表为空。请确认你现在是否空仓；如果不是空仓，请先补充持仓表。",
            )
        ]
    issues = []
    for row in rows:
        missing = holding_missing_fields(row)
        if missing:
            issues.append(
                PortfolioPreflightIssue(
                    symbol=row.get("symbol") or row.get("name") or "unknown",
                    missing_fields=missing,
                    question=(
                        f"`{row.get('symbol') or row.get('name') or 'unknown'}` 持仓信息不完整，"
                        f"请补充：{', '.join(missing)}。"
                    ),
                )
            )
    return issues


def is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def is_separator_row(line: str) -> bool:
    if not is_table_row(line):
        return False
    cells = split_table_row(line)
    if not cells:
        return False
    return all(cell and set(cell) <= {"-", ":", " "} for cell in cells)


def split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip().replace("\\|", "|") for cell in stripped.split("|")]


def row_from_values(headers: tuple[str, ...], values: list[str]) -> dict[str, str]:
    padded = values + [""] * max(0, len(headers) - len(values))
    return {header: padded[index] if index < len(padded) else "" for index, header in enumerate(headers)}


def clean_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


# --- Report / JSON ----------------------------------------------------------------

def packet_to_json(packet: dict[str, object]) -> str:
    return json.dumps(packet, ensure_ascii=False, indent=2)


def format_agent_packet(packet: dict[str, object]) -> str:
    lines = [
        "# Trading Agent Packet",
        "",
        f"status: {packet.get('status')}",
        f"command: {packet.get('command')}",
    ]
    if packet.get("symbol_or_name"):
        lines.append(f"symbol_or_name: {packet.get('symbol_or_name')}")

    setup_questions = packet.get("setup_questions") or []
    if setup_questions:
        lines.extend(["", "## 可选补充的上下文信息"])
        for item in setup_questions:
            if isinstance(item, dict):
                lines.append(f"- [{item.get('area')}] {item.get('question')}")

    portfolio_notices = packet.get("portfolio_notices") or []
    if portfolio_notices:
        lines.extend(["", "## 持仓上下文提示"])
        for item in portfolio_notices:
            if isinstance(item, dict):
                lines.append(f"- [{item.get('level')}] {item.get('message')}")

    preflight_issues = packet.get("preflight_issues") or []
    if preflight_issues:
        lines.extend(["", "## 阻塞分析的持仓信息缺口"])
        for item in preflight_issues:
            if isinstance(item, dict):
                lines.append(f"- {item.get('question')}")

    quote_errors = packet.get("quote_errors") or []
    if quote_errors:
        lines.extend(["", "## 行情脚本问题"])
        for error in quote_errors:
            lines.append(f"- {error}")

    quote_snapshots = packet.get("quote_snapshots") or []
    if quote_snapshots:
        lines.extend(["", "## 脚本行情证据"])
        for snapshot in quote_snapshots:
            if isinstance(snapshot, dict):
                latest_bar = quote_snapshot_latest_bar(snapshot)
                intraday_points = quote_snapshot_intraday_point_count(snapshot)
                lines.append(
                    "- {symbol} {market} latest={latest} change_pct={change_pct} "
                    "intraday_points={intraday_points} missing={missing}".format(
                        symbol=snapshot.get("symbol"),
                        market=snapshot.get("market"),
                        latest=latest_bar.get("close") if latest_bar else None,
                        change_pct=latest_bar.get("change_pct") if latest_bar else None,
                        intraday_points=intraday_points,
                        missing=",".join(snapshot.get("missing_fields") or []),
                    )
                )

    skill_packet = packet.get("skill_packet")
    if isinstance(skill_packet, dict):
        lines.extend(
            [
                "",
                "## Skill 执行信息",
                f"- skill_id: {skill_packet.get('skill_id')}",
                f"- output_contract: {skill_packet.get('output_contract')}",
                f"- missing_inputs: {', '.join(skill_packet.get('missing_inputs') or [])}",
                "",
                "## Prompt / Evidence Packet",
                "```markdown",
                str(skill_packet.get("prompt", "")).rstrip(),
                "```",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def quote_snapshot_latest_bar(snapshot: dict[str, object]) -> dict[str, object] | None:
    recent_bars = snapshot.get("recent_bars")
    if not isinstance(recent_bars, list):
        return None
    for bar in recent_bars:
        if isinstance(bar, dict):
            return bar
    return None


def quote_snapshot_intraday_point_count(snapshot: dict[str, object]) -> int:
    recent_bars = snapshot.get("recent_bars")
    if not isinstance(recent_bars, list):
        return 0
    for bar in recent_bars:
        if not isinstance(bar, dict):
            continue
        samples = bar.get("intraday_samples")
        if isinstance(samples, list):
            return len(samples)
    return 0


# --- CLI -------------------------------------------------------------------------

COMMANDS = (
    "judge-target",
    "judge-buy",
    "judge-sell",
    "plan-next-day",
    "update-memory",
    "fetch-quotes",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading-agent",
        description="Local CLI shell for an auxiliary trading decision agent.",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Repository root used to resolve memory and skill files.",
    )
    parser.add_argument("--debug", action="store_true", help="Print extra diagnostics.")

    subparsers = parser.add_subparsers(dest="command", metavar="command")

    for command in ("judge-target", "judge-buy", "judge-sell"):
        subparser = subparsers.add_parser(command, help=f"Prepare a {command} request.")
        subparser.add_argument("symbol_or_name", help="Target symbol, stock name, or ETF name.")
        subparser.add_argument("--market", choices=("A", "US"), help="Optional market hint.")
        add_agent_packet_options(subparser)

    plan_next_day = subparsers.add_parser(
        "plan-next-day",
        help="Prepare a next-trading-day plan request from memory files.",
    )
    plan_next_day.add_argument(
        "--allow-empty-portfolio",
        action="store_true",
        help="Allow an empty portfolio after the user has confirmed they are in cash.",
    )
    add_agent_packet_options(plan_next_day)

    update_memory = subparsers.add_parser(
        "update-memory",
        help="Assemble the memory_update skill packet (model edits Markdown per skill).",
    )
    update_memory.add_argument("note", nargs="*", help="User update text for the skill input.")
    update_memory.add_argument("--format", choices=("text", "json"), default="text")

    fetch_quotes = subparsers.add_parser(
        "fetch-quotes",
        help="Fetch simplified quote data for A-share or US symbols.",
    )
    fetch_quotes.add_argument("symbols", nargs="+", help="One or more symbols or names.")
    fetch_quotes.add_argument("--market", choices=("A", "US"), help="Optional market hint.")
    fetch_quotes.add_argument("--recent-days", type=int, default=5, help="Recent daily bars to request.")
    fetch_quotes.add_argument("--format", choices=("table", "json"), default="table")
    fetch_quotes.add_argument("--timeout", type=float, default=10.0)

    return parser


def add_agent_packet_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--user-note", help="Optional user text for context (not used to auto-write memory).")
    parser.add_argument("--skip-quotes", action="store_true", help="Skip live quote fetching.")
    parser.add_argument("--recent-days", type=int, default=5, help="Recent daily bars to request.")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--output-packet", help="Write the generated packet to this file.")


def emit_diagnostic(chain: str, event: str, status: str, **fields: object) -> None:
    safe_fields = " ".join(f"{key}={value}" for key, value in fields.items())
    suffix = f" {safe_fields}" if safe_fields else ""
    print(
        f"[trading-agent] chain={chain} event={event} status={status}{suffix}",
        file=sys.stderr,
    )


def _project_root(value: str) -> Path:
    return Path(value).resolve()


def quote_cache_path(project_root: Path) -> Path:
    digest = hashlib.sha1(str(project_root).encode("utf-8")).hexdigest()[:12]
    filename = f"trading-agent-quote-cache-{digest}.json"
    return Path(tempfile.gettempdir()) / filename


def load_quote_cache(project_root: Path) -> QuoteCacheEntry | None:
    path = quote_cache_path(project_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        entry = QuoteCacheEntry(
            request_symbol=str(payload["request_symbol"]),
            market=str(payload["market"]),
            recent_days=int(payload["recent_days"]),
            cached_at=float(payload["cached_at"]),
            quote_snapshots=list(payload.get("quote_snapshots") or []),
            quote_errors=[str(item) for item in (payload.get("quote_errors") or [])],
        )
    except (KeyError, TypeError, ValueError):
        return None
    if time.time() - entry.cached_at > QUOTE_CACHE_TTL_SECONDS:
        return None
    return entry


def store_quote_cache(
    project_root: Path,
    *,
    request_symbol: str,
    market: str | None,
    recent_days: int,
    quote_snapshots: list[dict[str, object]],
    quote_errors: list[str],
) -> None:
    entry = QuoteCacheEntry(
        request_symbol=request_symbol,
        market=market or "",
        recent_days=recent_days,
        cached_at=time.time(),
        quote_snapshots=quote_snapshots,
        quote_errors=quote_errors,
    )
    path = quote_cache_path(project_root)
    try:
        path.write_text(
            json.dumps(
                {
                    "request_symbol": entry.request_symbol,
                    "market": entry.market,
                    "recent_days": entry.recent_days,
                    "cached_at": entry.cached_at,
                    "quote_snapshots": entry.quote_snapshots,
                    "quote_errors": entry.quote_errors,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        return


def lookup_cached_quote_evidence(
    project_root: Path,
    *,
    request_symbols: list[str],
    market: str | None,
    recent_days: int,
) -> tuple[list[dict[str, object]], list[str]] | None:
    if len(request_symbols) != 1:
        return None
    entry = load_quote_cache(project_root)
    if entry is None:
        return None
    if entry.request_symbol != request_symbols[0]:
        return None
    if entry.market != (market or ""):
        return None
    if entry.recent_days != recent_days:
        return None
    return entry.quote_snapshots, entry.quote_errors


def _handle_agent_packet_command(args: argparse.Namespace) -> int:
    emit_diagnostic(
        "cli",
        "route",
        "ok",
        command=args.command,
        has_symbol=bool(getattr(args, "symbol_or_name", None)),
    )
    packet = build_agent_packet(
        project_root=_project_root(args.project_root),
        command=args.command,
        symbol_or_name=getattr(args, "symbol_or_name", None),
        market=getattr(args, "market", None),
        user_note=getattr(args, "user_note", None),
        skip_quotes=getattr(args, "skip_quotes", False),
        allow_empty_portfolio=getattr(args, "allow_empty_portfolio", False),
        recent_days=getattr(args, "recent_days", 5),
        timeout=getattr(args, "timeout", 10.0),
    )
    emit_diagnostic(
        "agent",
        "packet",
        str(packet.get("status", "unknown")),
        command=args.command,
        setup_questions=len(packet.get("setup_questions") or []),
        preflight_issues=len(packet.get("preflight_issues") or []),
    )
    output_packet(packet, args)
    return 0


def _handle_update_memory_shell(args: argparse.Namespace) -> int:
    note = " ".join(args.note).strip()
    root = _project_root(args.project_root)
    emit_diagnostic("cli", "route", "ok", command="update-memory", note_count=len(args.note))
    try:
        bundle = read_memory_bundle(root)
    except MemoryError as exc:
        print(f"update-memory error: {exc}", file=sys.stderr)
        return 1
    provided_inputs = {
        "user_update_text": note,
        "current_portfolio": bundle["portfolio.md"],
        "current_watchlist": bundle["watchlist.md"],
    }
    try:
        skill_packet = build_execution_packet(root, "update-memory", None, provided_inputs)
    except SkillError as exc:
        print(f"update-memory error: {exc}", file=sys.stderr)
        return 1
    packet = {
        "status": "ready",
        "command": "update-memory",
        "skill_packet": skill_execution_packet_to_dict(skill_packet),
    }
    if args.format == "json":
        print(packet_to_json(packet))
    else:
        print(format_agent_packet(packet))
    return 0


def _handle_fetch_quotes_shell(args: argparse.Namespace) -> int:
    try:
        request = build_quote_request(args.symbols, args.market, args.recent_days)
    except (ValueError, MarketDataError) as exc:
        print(f"fetch-quotes error: {exc}", file=sys.stderr)
        return 1
    emit_diagnostic(
        "cli",
        "route",
        "ok",
        command="fetch-quotes",
        symbol_count=len(request.symbols),
    )
    try:
        snapshots = fetch_quotes(request, timeout=args.timeout)
    except (ValueError, MarketDataError) as exc:
        emit_diagnostic("market_data", "fetch", "error", command="fetch-quotes")
        print(f"fetch-quotes error: {exc}", file=sys.stderr)
        return 1
    emit_diagnostic("market_data", "fetch", "ok", symbol_count=len(snapshots))
    if args.format == "json":
        print(snapshots_to_json(snapshots))
    else:
        print(snapshots_to_table(snapshots))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    if args.command in {"judge-target", "judge-buy", "judge-sell", "plan-next-day"}:
        return _handle_agent_packet_command(args)
    if args.command == "update-memory":
        return _handle_update_memory_shell(args)
    if args.command == "fetch-quotes":
        return _handle_fetch_quotes_shell(args)

    parser.error(f"Unsupported command: {args.command}")
    return 2


def build_agent_packet(
    *,
    project_root: Path,
    command: str,
    symbol_or_name: str | None = None,
    market: str | None = None,
    user_note: str | None = None,
    skip_quotes: bool = False,
    allow_empty_portfolio: bool = False,
    recent_days: int = 5,
    timeout: float = 10.0,
) -> dict[str, object]:
    try:
        memory_bundle = read_memory_bundle(project_root)
        setup_questions = [
            setup_question_to_dict(item)
            for item in setup_questions_for_command(
                command,
                build_setup_questions(project_root),
                allow_empty_portfolio=allow_empty_portfolio,
            )
        ]
    except MemoryError as exc:
        return {
            "status": "memory_error",
            "command": command,
            "symbol_or_name": symbol_or_name,
            "errors": [str(exc)],
        }

    preflight_issues = []
    portfolio_notices = []
    if command == "judge-buy" and symbol_or_name:
        buy_issues, buy_notices = preflight_buy(project_root, symbol_or_name, user_note=user_note)
        preflight_issues = [preflight_issue_to_dict(issue) for issue in buy_issues]
        portfolio_notices = [portfolio_notice_to_dict(notice) for notice in buy_notices]
        portfolio_notices.extend(
            portfolio_notice_to_dict(notice)
            for notice in portfolio_context_notices(project_root, command, symbol_or_name)
        )
    elif command == "judge-sell" and symbol_or_name:
        preflight_issues = [preflight_issue_to_dict(issue) for issue in preflight_sell(project_root, symbol_or_name)]
        portfolio_notices = [
            portfolio_notice_to_dict(notice)
            for notice in portfolio_context_notices(project_root, command, symbol_or_name)
        ]
    elif command == "plan-next-day":
        preflight_issues = [
            preflight_issue_to_dict(issue)
            for issue in preflight_next_day(project_root, allow_empty_portfolio=allow_empty_portfolio)
        ]
        portfolio_notices = [
            portfolio_notice_to_dict(notice)
            for notice in portfolio_context_notices(project_root, command, symbol_or_name)
        ]

    if preflight_issues:
        return {
            "status": "needs_portfolio_info",
            "command": command,
            "symbol_or_name": symbol_or_name,
            "setup_questions": [],
            "preflight_issues": preflight_issues,
            "portfolio_notices": portfolio_notices,
        }

    quote_snapshots, quote_errors = collect_quote_evidence(
        project_root=project_root,
        command=command,
        symbol_or_name=symbol_or_name,
        market=market,
        skip_quotes=skip_quotes,
        recent_days=recent_days,
        timeout=timeout,
    )
    provided_inputs = build_skill_inputs(
        project_root=project_root,
        command=command,
        symbol_or_name=symbol_or_name,
        memory_bundle=memory_bundle,
        quote_snapshots=quote_snapshots,
        quote_errors=quote_errors,
    )
    try:
        skill_packet = build_execution_packet(project_root, command, symbol_or_name, provided_inputs)
    except SkillError as exc:
        return {
            "status": "skill_error",
            "command": command,
            "symbol_or_name": symbol_or_name,
            "errors": [str(exc)],
        }

    return {
        "status": "ready",
        "command": command,
        "symbol_or_name": symbol_or_name,
        "setup_questions": setup_questions,
        "preflight_issues": preflight_issues,
        "portfolio_notices": portfolio_notices,
        "quote_snapshots": quote_snapshots,
        "quote_errors": quote_errors,
        "skill_packet": skill_execution_packet_to_dict(skill_packet),
    }


def collect_quote_evidence(
    *,
    project_root: Path,
    command: str,
    symbol_or_name: str | None,
    market: str | None,
    skip_quotes: bool,
    recent_days: int,
    timeout: float,
) -> tuple[list[dict[str, object]], list[str]]:
    if skip_quotes:
        return [], ["quote_fetch_skipped"]
    request_symbols = quote_symbols_for_command(
        project_root,
        command,
        symbol_or_name,
    )
    if not request_symbols:
        return [], []
    cached = lookup_cached_quote_evidence(
        project_root,
        request_symbols=request_symbols,
        market=market,
        recent_days=recent_days,
    )
    if cached is not None:
        emit_diagnostic("market_data", "cache", "hit", symbol=request_symbols[0], recent_days=recent_days)
        return cached
    try:
        request = build_quote_request(request_symbols, market, recent_days)
        snapshots = fetch_quotes(request, timeout=timeout)
        snapshot_dicts = [snapshot_to_dict(snapshot) for snapshot in snapshots]
        store_quote_cache(
            project_root,
            request_symbol=request_symbols[0],
            market=market,
            recent_days=recent_days,
            quote_snapshots=snapshot_dicts,
            quote_errors=[],
        )
        emit_diagnostic("market_data", "cache", "store", symbol=request_symbols[0], recent_days=recent_days)
        return snapshot_dicts, []
    except (ValueError, MarketDataError) as exc:
        return [], [str(exc)]


def quote_symbols_for_command(
    project_root: Path,
    command: str,
    symbol_or_name: str | None,
) -> list[str]:
    if command in {"judge-target", "judge-buy", "judge-sell"} and symbol_or_name:
        return [symbol_or_name]
    if command == "plan-next-day":
        symbols = []
        for filename in ("portfolio.md", "watchlist.md"):
            try:
                rows = memory_table_rows(project_root, filename)
            except MemoryError:
                continue
            for row in rows:
                sym = row.get("symbol", "").strip()
                if sym and sym not in symbols:
                    symbols.append(sym)
        return symbols
    return []


def build_skill_inputs(
    *,
    project_root: Path,
    command: str,
    symbol_or_name: str | None,
    memory_bundle: dict[str, str],
    quote_snapshots: list[dict[str, object]],
    quote_errors: list[str],
) -> dict[str, object]:
    portfolio_doc = memory_bundle.get("portfolio.md", "")
    portfolio_rows = memory_table_rows(project_root, "portfolio.md")
    watchlist_rows = memory_table_rows(project_root, "watchlist.md")
    inputs: dict[str, object] = {
        "user_profile": extract_account_section_markdown(portfolio_doc),
        "quote_snapshot": quote_snapshots[0] if quote_snapshots else {"missing": quote_errors or ["not_requested"]},
        "quote_snapshots": quote_snapshots,
        "model_market_research": "由执行该 packet 的大模型临时查询最新市场主线、风险事件、题材轮动和必要 K 线图。",
    }
    if symbol_or_name:
        inputs["symbol_or_name"] = symbol_or_name
        watchlist_row = find_row_by_symbol(watchlist_rows, symbol_or_name)
        if watchlist_row:
            inputs["watchlist_status"] = watchlist_row
        else:
            inputs["watchlist_status"] = {"status": "not_found", "symbol_or_name": symbol_or_name}

    if command == "judge-buy":
        inputs["portfolio"] = portfolio_rows
    elif command == "judge-sell":
        holding = find_row_by_symbol(portfolio_rows, symbol_or_name or "")
        if holding:
            inputs["portfolio_holding"] = holding
    elif command == "plan-next-day":
        inputs["portfolio"] = portfolio_rows
        inputs["watchlist"] = watchlist_rows
    return inputs


def output_packet(packet: dict[str, object], args: argparse.Namespace) -> None:
    text = packet_to_json(packet) if getattr(args, "format", "text") == "json" else format_agent_packet(packet)
    output_path = getattr(args, "output_packet", None)
    if output_path:
        Path(output_path).write_text(text, encoding="utf-8")
        print(f"packet_written={Path(output_path).resolve()}")
    else:
        print(text, end="")


def setup_questions_for_command(
    command: str,
    questions: list[object],
    *,
    allow_empty_portfolio: bool = False,
) -> list[object]:
    if command == "judge-target":
        return []
    filtered = [question for question in questions if getattr(question, "area") != "portfolio"]
    if command == "judge-buy":
        return filtered
    if command == "plan-next-day" and allow_empty_portfolio:
        return filtered
    return filtered


def setup_question_to_dict(question: object) -> dict[str, object]:
    return {
        "area": getattr(question, "area"),
        "question": getattr(question, "question"),
        "required_fields": list(getattr(question, "required_fields")),
    }


def preflight_issue_to_dict(issue: object) -> dict[str, object]:
    return {
        "symbol": getattr(issue, "symbol"),
        "missing_fields": list(getattr(issue, "missing_fields")),
        "question": getattr(issue, "question"),
    }


def portfolio_notice_to_dict(notice: object) -> dict[str, object]:
    return {
        "symbol": getattr(notice, "symbol"),
        "level": getattr(notice, "level"),
        "message": getattr(notice, "message"),
    }


def skill_execution_packet_to_dict(packet: object) -> dict[str, object]:
    definition = getattr(packet, "definition")
    metadata = getattr(definition, "metadata")
    return {
        "command": getattr(getattr(packet, "request"), "command"),
        "skill_id": metadata.skill_id,
        "skill_path": str(getattr(definition, "path")),
        "output_contract": metadata.output_contract,
        "rating_enum": list(metadata.rating_enum),
        "required_inputs": list(metadata.required_inputs),
        "provided_input_keys": sorted(getattr(packet, "provided_inputs").keys()),
        "missing_inputs": list(getattr(packet, "missing_inputs")),
        "prompt": getattr(packet, "prompt"),
    }


if __name__ == "__main__":
    raise SystemExit(main())