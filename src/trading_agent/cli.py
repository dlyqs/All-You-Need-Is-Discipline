"""Command-line shell for the trading decision agent."""

from __future__ import annotations

import argparse
import sys
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
from trading_agent.memory import (
    MemoryError,
    build_setup_questions,
    detect_memory_update_plan,
    find_row_by_symbol,
    memory_table_rows,
    preflight_buy,
    preflight_next_day,
    preflight_sell,
    read_memory_bundle,
)
from trading_agent.report import format_agent_packet, packet_to_json
from trading_agent.skills import SkillError, build_execution_packet


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
        help="Prepare a lightweight memory update request.",
    )
    update_memory.add_argument("note", nargs="*", help="Explicit user update note.")
    update_memory.add_argument("--apply", action="store_true", help="Apply a complete safe memory update.")
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
    parser.add_argument("--user-note", help="User text that may contain buy/sell/position updates.")
    parser.add_argument(
        "--apply-memory-updates",
        action="store_true",
        help="Apply complete detected portfolio updates before building the packet.",
    )
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
        apply_memory_updates=getattr(args, "apply_memory_updates", False),
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
    emit_diagnostic("cli", "route", "ok", command="update-memory", note_count=len(args.note))
    try:
        plan = detect_memory_update_plan(note, _project_root(args.project_root), apply=args.apply)
    except MemoryError as exc:
        print(f"update-memory error: {exc}", file=sys.stderr)
        return 1
    packet = {
        "status": plan.status,
        "command": "update-memory",
        "memory_update": memory_update_plan_to_dict(plan),
    }
    if args.format == "json":
        print(packet_to_json(packet))
    else:
        print(format_agent_packet(packet))
    return 0


def _handle_fetch_quotes_shell(args: argparse.Namespace) -> int:
    request = build_quote_request(args.symbols, args.market, args.recent_days)
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
    apply_memory_updates: bool = False,
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

    memory_update = None
    if user_note:
        try:
            memory_update = detect_memory_update_plan(user_note, project_root, apply=apply_memory_updates)
        except MemoryError as exc:
            return {
                "status": "memory_update_error",
                "command": command,
                "symbol_or_name": symbol_or_name,
                "errors": [str(exc)],
            }
        if memory_update.status == "needs_confirmation":
            return {
                "status": "needs_memory_confirmation",
                "command": command,
                "symbol_or_name": symbol_or_name,
                "setup_questions": [],
                "memory_update": memory_update_plan_to_dict(memory_update),
            }
        if memory_update.status == "applied":
            memory_bundle = read_memory_bundle(project_root)

    preflight_issues = []
    portfolio_notices = []
    if command == "judge-buy" and symbol_or_name:
        buy_issues, buy_notices = preflight_buy(project_root, symbol_or_name, user_note=user_note)
        preflight_issues = [preflight_issue_to_dict(issue) for issue in buy_issues]
        portfolio_notices = [portfolio_notice_to_dict(notice) for notice in buy_notices]
    elif command == "judge-sell" and symbol_or_name:
        preflight_issues = [preflight_issue_to_dict(issue) for issue in preflight_sell(project_root, symbol_or_name)]
    elif command == "plan-next-day":
        preflight_issues = [
            preflight_issue_to_dict(issue)
            for issue in preflight_next_day(project_root, allow_empty_portfolio=allow_empty_portfolio)
        ]

    if preflight_issues:
        return {
            "status": "needs_portfolio_info",
            "command": command,
            "symbol_or_name": symbol_or_name,
            "setup_questions": [],
            "preflight_issues": preflight_issues,
            "portfolio_notices": portfolio_notices,
            "memory_update": memory_update_plan_to_dict(memory_update) if memory_update else None,
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

    status = "ready"
    return {
        "status": status,
        "command": command,
        "symbol_or_name": symbol_or_name,
        "setup_questions": setup_questions,
        "preflight_issues": preflight_issues,
        "portfolio_notices": portfolio_notices,
        "memory_update": memory_update_plan_to_dict(memory_update) if memory_update else None,
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
    symbols = quote_symbols_for_command(project_root, command, symbol_or_name)
    if not symbols:
        return [], []
    try:
        request = build_quote_request(symbols, market, recent_days)
        snapshots = fetch_quotes(request, timeout=timeout)
        return [snapshot_to_dict(snapshot) for snapshot in snapshots], []
    except (ValueError, MarketDataError) as exc:
        return [], [str(exc)]


def quote_symbols_for_command(project_root: Path, command: str, symbol_or_name: str | None) -> list[str]:
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
                symbol = row.get("symbol", "").strip()
                if symbol and symbol not in symbols:
                    symbols.append(symbol)
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
    portfolio_rows = memory_table_rows(project_root, "portfolio.md")
    watchlist_rows = memory_table_rows(project_root, "watchlist.md")
    inputs: dict[str, object] = {
        "user_profile": memory_bundle.get("user_profile.md", ""),
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
    """Return optional context prompts relevant to the command.

    Portfolio gaps are handled by command-specific preflight checks, so these
    setup questions are never used as a hard gate.
    """

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


def memory_update_plan_to_dict(plan: object | None) -> dict[str, object]:
    if plan is None:
        return {"status": "no_update_detected"}
    return {
        "status": getattr(plan, "status"),
        "action": getattr(plan, "action"),
        "target_file": getattr(plan, "target_file"),
        "row": getattr(plan, "row"),
        "missing_fields": list(getattr(plan, "missing_fields")),
        "questions": list(getattr(plan, "questions")),
        "diff": getattr(plan, "diff"),
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
