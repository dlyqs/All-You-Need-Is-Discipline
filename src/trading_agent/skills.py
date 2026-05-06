"""Repo-local skill loading and execution-packet helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


SKILL_FILENAMES = {
    "judge-target": "target_screening.md",
    "judge-buy": "buy_rating.md",
    "judge-sell": "sell_rating.md",
    "plan-next-day": "next_day_plan.md",
    "update-memory": "memory_update.md",
}

METADATA_START = "<!-- skill-metadata"
METADATA_END = "-->"


class SkillError(ValueError):
    """Raised when a repo-local skill is missing or malformed."""


@dataclass(frozen=True)
class SkillMetadata:
    skill_id: str
    command: str
    schema_version: str
    rating_enum: tuple[str, ...]
    required_inputs: tuple[str, ...]
    output_contract: str


@dataclass(frozen=True)
class SkillDefinition:
    path: Path
    metadata: SkillMetadata
    body: str


@dataclass(frozen=True)
class SkillRequest:
    command: str
    skill_path: Path
    symbol_or_name: str | None = None


@dataclass(frozen=True)
class SkillExecutionPacket:
    request: SkillRequest
    definition: SkillDefinition
    provided_inputs: dict[str, object] = field(default_factory=dict)
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    prompt: str = ""


def expected_skill_path(project_root: Path | str, command: str) -> Path:
    try:
        filename = SKILL_FILENAMES[command]
    except KeyError as exc:
        raise ValueError(f"Unsupported skill command: {command}") from exc
    return Path(project_root).resolve() / "skills" / filename


def build_skill_request(
    project_root: Path | str,
    command: str,
    symbol_or_name: str | None = None,
) -> SkillRequest:
    return SkillRequest(
        command=command,
        skill_path=expected_skill_path(project_root, command),
        symbol_or_name=symbol_or_name,
    )


def load_skill(project_root: Path | str, command: str) -> SkillDefinition:
    path = expected_skill_path(project_root, command)
    if not path.exists():
        raise SkillError(f"Skill file does not exist: {path}")
    text = path.read_text(encoding="utf-8")
    metadata = parse_skill_metadata(text, path)
    if metadata.command != command:
        raise SkillError(
            f"Skill command mismatch for {path}: expected {command}, got {metadata.command}"
        )
    body = strip_metadata(text)
    validate_skill_definition(SkillDefinition(path=path, metadata=metadata, body=body))
    return SkillDefinition(path=path, metadata=metadata, body=body)


def load_all_skills(project_root: Path | str) -> dict[str, SkillDefinition]:
    return {command: load_skill(project_root, command) for command in SKILL_FILENAMES}


def build_execution_packet(
    project_root: Path | str,
    command: str,
    symbol_or_name: str | None = None,
    provided_inputs: Mapping[str, object] | None = None,
) -> SkillExecutionPacket:
    definition = load_skill(project_root, command)
    request = build_skill_request(project_root, command, symbol_or_name)
    inputs = dict(provided_inputs or {})
    if symbol_or_name is not None and "symbol_or_name" not in inputs:
        inputs["symbol_or_name"] = symbol_or_name
    missing = tuple(input_name for input_name in definition.metadata.required_inputs if input_name not in inputs)
    prompt = build_skill_prompt(definition, request, inputs, missing)
    return SkillExecutionPacket(
        request=request,
        definition=definition,
        provided_inputs=inputs,
        missing_inputs=missing,
        prompt=prompt,
    )


def parse_skill_metadata(text: str, path: Path | None = None) -> SkillMetadata:
    block = extract_metadata_block(text, path)
    data = parse_metadata_lines(block)
    required_keys = (
        "skill_id",
        "command",
        "schema_version",
        "rating_enum",
        "required_inputs",
        "output_contract",
    )
    missing_keys = [key for key in required_keys if key not in data]
    if missing_keys:
        location = f" in {path}" if path else ""
        raise SkillError(f"Skill metadata missing keys{location}: {', '.join(missing_keys)}")
    return SkillMetadata(
        skill_id=data["skill_id"],
        command=data["command"],
        schema_version=data["schema_version"],
        rating_enum=split_csv(data["rating_enum"]),
        required_inputs=split_csv(data["required_inputs"]),
        output_contract=data["output_contract"],
    )


def extract_metadata_block(text: str, path: Path | None = None) -> str:
    start = text.find(METADATA_START)
    end = text.find(METADATA_END, start)
    if start == -1 or end == -1:
        location = f": {path}" if path else ""
        raise SkillError(f"Skill metadata block not found{location}")
    return text[start + len(METADATA_START) : end].strip()


def parse_metadata_lines(block: str) -> dict[str, str]:
    data = {}
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            raise SkillError(f"Invalid metadata line: {raw_line}")
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def strip_metadata(text: str) -> str:
    start = text.find(METADATA_START)
    end = text.find(METADATA_END, start)
    if start == -1 or end == -1:
        return text
    return (text[:start] + text[end + len(METADATA_END) :]).strip()


def split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def validate_skill_definition(definition: SkillDefinition) -> None:
    if not definition.metadata.rating_enum:
        raise SkillError(f"Skill has empty rating enum: {definition.path}")
    if not definition.metadata.required_inputs:
        raise SkillError(f"Skill has no required inputs: {definition.path}")
    lower_body = definition.body.lower()
    required_body_markers = ("## 输入要求", "## 输出")
    missing_markers = [marker for marker in required_body_markers if marker.lower() not in lower_body]
    if missing_markers:
        raise SkillError(
            f"Skill body missing required section(s) in {definition.path}: {', '.join(missing_markers)}"
        )

    if definition.metadata.output_contract == "rating_result_v1":
        required_terms = ("rule_matches", "bonus_matches", "vetoes", "missing_evidence")
        missing_terms = [term for term in required_terms if term not in definition.body]
        if missing_terms:
            raise SkillError(
                f"Rating skill missing output field(s) in {definition.path}: {', '.join(missing_terms)}"
            )


def build_skill_prompt(
    definition: SkillDefinition,
    request: SkillRequest,
    provided_inputs: Mapping[str, object],
    missing_inputs: tuple[str, ...],
) -> str:
    input_lines = [f"- {key}: {value}" for key, value in sorted(provided_inputs.items())]
    if missing_inputs:
        input_lines.append("- missing_inputs: " + ", ".join(missing_inputs))
    return "\n".join(
        [
            f"# Skill Execution Packet: {definition.metadata.skill_id}",
            "",
            f"command: {request.command}",
            f"skill_path: {definition.path}",
            f"output_contract: {definition.metadata.output_contract}",
            "",
            "## Provided Inputs",
            "\n".join(input_lines) if input_lines else "- none",
            "",
            "## Skill Definition",
            definition.body,
        ]
    )

