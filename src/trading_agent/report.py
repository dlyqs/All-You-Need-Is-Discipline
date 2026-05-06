"""Output formatting helpers for agent packets and later reports."""

from __future__ import annotations

import json

from trading_agent.models import RatingResult
from trading_agent.skills import SkillRequest


def format_phase1_command_placeholder(request: SkillRequest) -> str:
    target = f" target={request.symbol_or_name}" if request.symbol_or_name else ""
    return "\n".join(
        [
            "CLI shell accepted the command.",
            f"command={request.command}{target}",
            f"planned_skill={request.skill_path}",
            "Real skill loading and LLM execution will be implemented in later phases.",
        ]
    )


def format_rating_result(result: RatingResult) -> str:
    """Format the structured rating contract into a compact text report."""

    lines = [f"rating={result.rating}", f"conclusion={result.conclusion}"]
    if result.vetoes:
        lines.append("vetoes=" + ", ".join(result.vetoes))
    if result.missing_evidence:
        lines.append("missing_evidence=" + ", ".join(result.missing_evidence))
    if result.action:
        lines.append(f"action={result.action}")
    return "\n".join(lines)


def packet_to_json(packet: dict[str, object]) -> str:
    return json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True)


def format_agent_packet(packet: dict[str, object]) -> str:
    """Format an agent packet into readable text for CLI/manual LLM use."""

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

    memory_update = packet.get("memory_update")
    if isinstance(memory_update, dict) and memory_update.get("status") != "no_update_detected":
        lines.extend(["", "## 检测到的持仓/交易更新"])
        lines.append(f"- status: {memory_update.get('status')}")
        lines.append(f"- action: {memory_update.get('action')}")
        questions = memory_update.get("questions") or []
        for question in questions:
            lines.append(f"- {question}")
        diff = memory_update.get("diff")
        if diff:
            lines.extend(["", "```diff", str(diff).rstrip(), "```"])

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
                lines.append(
                    "- {symbol} {market} latest={latest} change_pct={change_pct} shape={shape} missing={missing}".format(
                        symbol=snapshot.get("symbol"),
                        market=snapshot.get("market"),
                        latest=snapshot.get("latest_price"),
                        change_pct=snapshot.get("change_pct"),
                        shape=snapshot.get("intraday_shape"),
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
