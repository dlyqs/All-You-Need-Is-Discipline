"""Lightweight Markdown memory helpers for the v1 plan."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path


MEMORY_FILENAMES = ("user_profile.md", "portfolio.md", "watchlist.md")

PORTFOLIO_COLUMNS = (
    "symbol",
    "market",
    "name",
    "quantity",
    "buy_date",
    "buy_price",
    "cost",
    "current_price",
    "unrealized_pnl",
    "theme",
    "thesis",
    "stop_notes",
    "notes",
)

WATCHLIST_COLUMNS = (
    "symbol",
    "market",
    "name",
    "theme",
    "priority",
    "focus_pool",
    "added_date",
    "thesis",
    "invalidation",
    "notes",
)


class MemoryError(ValueError):
    """Raised when a memory operation is unsafe or malformed."""


@dataclass(frozen=True)
class MemoryPaths:
    root: Path
    user_profile: Path
    portfolio: Path
    watchlist: Path


@dataclass(frozen=True)
class MarkdownTable:
    headers: tuple[str, ...]
    rows: list[dict[str, str]]
    start_line: int
    end_line: int


@dataclass(frozen=True)
class MemoryUpdateResult:
    path: Path
    changed: bool
    dry_run: bool
    diff: str
    new_text: str


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
class MemoryUpdatePlan:
    status: str
    action: str | None
    target_file: str | None
    row: dict[str, str]
    missing_fields: tuple[str, ...]
    questions: tuple[str, ...]
    diff: str = ""


def expected_memory_paths(project_root: Path | str) -> MemoryPaths:
    root = Path(project_root).resolve() / "memory"
    return MemoryPaths(
        root=root,
        user_profile=root / "user_profile.md",
        portfolio=root / "portfolio.md",
        watchlist=root / "watchlist.md",
    )


def existing_memory_files(project_root: Path | str) -> list[Path]:
    paths = expected_memory_paths(project_root)
    return [path for path in (paths.user_profile, paths.portfolio, paths.watchlist) if path.exists()]


def allowed_memory_path(project_root: Path | str, filename: str) -> Path:
    if filename not in MEMORY_FILENAMES:
        raise MemoryError(f"Unsupported memory file: {filename}")
    paths = expected_memory_paths(project_root)
    mapping = {
        "user_profile.md": paths.user_profile,
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


def parse_first_markdown_table(text: str) -> MarkdownTable:
    lines = text.splitlines()
    for index in range(len(lines) - 1):
        if is_table_row(lines[index]) and is_separator_row(lines[index + 1]):
            headers = tuple(split_table_row(lines[index]))
            rows = []
            end = index + 2
            while end < len(lines) and is_table_row(lines[end]):
                values = split_table_row(lines[end])
                if any(value != "" for value in values):
                    rows.append(row_from_values(headers, values))
                end += 1
            return MarkdownTable(headers=headers, rows=rows, start_line=index, end_line=end)
    raise MemoryError("No Markdown table found")


def parse_memory_table(project_root: Path | str, filename: str) -> MarkdownTable:
    return parse_first_markdown_table(read_memory_file(project_root, filename))


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
    """Return concise first-use setup questions for blank/template memory."""

    questions: list[SetupQuestion] = []
    profile_rows = memory_table_rows(project_root, "user_profile.md")
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
                    "请补充你的基础背景：主要交易市场、账户币种、资金规模或记录方式、"
                    "风险偏好、最低现金保留规则。"
                ),
                required_fields=tuple(blank_profile_fields),
            )
        )

    portfolio_rows = memory_table_rows(project_root, "portfolio.md")
    if not portfolio_rows:
        questions.append(
            SetupQuestion(
                area="portfolio",
                question=(
                    "请确认你当前是否有持仓；如果有，请补充 symbol、market、name、quantity、"
                    "buy_date、buy_price、cost/current_price、theme、thesis。"
                ),
                required_fields=("symbol", "market", "quantity", "buy_date", "buy_price", "thesis"),
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
    for field in ("symbol", "quantity", "buy_date", "thesis"):
        if is_template_value(row.get(field, "")):
            missing.append(field)
    if is_template_value(row.get("buy_price", "")) and is_template_value(row.get("cost", "")):
        missing.append("buy_price_or_cost")
    return tuple(missing)


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
                    "包括 quantity、buy_date、buy_price/cost、thesis。"
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


def preflight_buy(
    project_root: Path | str,
    symbol_or_name: str,
    user_note: str | None = None,
) -> tuple[list[PortfolioPreflightIssue], list[PortfolioContextNotice]]:
    """Check portfolio context for buy judgments.

    A new-position buy can proceed without existing holdings. Explicit add-buy
    requests need the current holding first, otherwise cost and position sizing
    cannot be judged.
    """

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
                        "请先补充该标的当前持仓数量、买入日期、买入价/成本和持仓逻辑。"
                    ),
                )
            ], []
        return [], [
            PortfolioContextNotice(
                symbol="portfolio",
                level="info",
                message=(
                    "当前持仓表为空；本次按空仓开新仓继续判断。"
                    "如果你实际已有持仓或这是加仓，请先告诉我当前持仓数量、买入日期、买入价/成本和持仓逻辑。"
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
                        "请先补充该标的当前持仓数量、买入日期、买入价/成本和持仓逻辑。"
                    ),
                )
            ], []
        return [], [
            PortfolioContextNotice(
                symbol=symbol_or_name,
                level="info",
                message=f"`{symbol_or_name}` 不在当前持仓表里；本次按新开仓买入判断。",
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
                "买入判断会同时参考现有仓位、成本和持仓逻辑。"
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


def detect_memory_update_plan(
    text: str,
    project_root: Path | str,
    apply: bool = False,
) -> MemoryUpdatePlan:
    """Detect explicit buy/sell style updates and optionally apply a safe row update.

    This is intentionally conservative. It supports key=value fields and a few
    clear keywords, then asks for confirmation when critical fields are absent.
    """

    fields = parse_key_value_fields(text)
    action = detect_update_action(text, fields)
    if action is None:
        return MemoryUpdatePlan(
            status="no_update_detected",
            action=None,
            target_file=None,
            row={},
            missing_fields=(),
            questions=(),
        )

    symbol = fields.get("symbol") or infer_symbol_from_text(text)
    if symbol:
        fields["symbol"] = symbol

    required = required_fields_for_action(action)
    missing = tuple(field for field in required if is_template_value(fields.get(field, "")))
    questions = tuple(question_for_missing_field(action, field) for field in missing)
    if missing:
        return MemoryUpdatePlan(
            status="needs_confirmation",
            action=action,
            target_file="memory/portfolio.md",
            row={key: clean_cell(value) for key, value in fields.items()},
            missing_fields=missing,
            questions=questions,
        )

    row = portfolio_row_from_update(action, fields)
    result = upsert_memory_table_row(
        project_root,
        "portfolio.md",
        "symbol",
        row,
        dry_run=not apply,
    )
    return MemoryUpdatePlan(
        status="applied" if apply else "ready_to_apply",
        action=action,
        target_file="memory/portfolio.md",
        row=row,
        missing_fields=(),
        questions=(),
        diff=result.diff,
    )


def parse_key_value_fields(text: str) -> dict[str, str]:
    aliases = {
        "code": "symbol",
        "ticker": "symbol",
        "qty": "quantity",
        "shares": "quantity",
        "price": "buy_price",
        "cost_price": "buy_price",
        "date": "buy_date",
        "buydate": "buy_date",
        "buy_price": "buy_price",
        "buy_date": "buy_date",
        "remaining": "quantity",
        "remaining_quantity": "quantity",
    }
    fields = {}
    for match in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)", text):
        key = aliases.get(match.group(1).lower(), match.group(1).lower())
        fields[key] = match.group(2).strip()
    return fields


def detect_update_action(text: str, fields: dict[str, str]) -> str | None:
    if "action" in fields:
        value = fields["action"].lower()
        if value in {"buy", "add", "sell", "reduce", "clear"}:
            return value
    lowered = text.lower()
    if is_analysis_request(text):
        if has_factual_clear_update(text, lowered):
            return "clear"
        if has_factual_sell_update(text, lowered):
            return "sell"
        if has_factual_add_update(text, lowered):
            return "add"
        if has_factual_buy_update(text, lowered):
            return "buy"
        return None
    if any(keyword in text for keyword in ("清仓", "已清", "清掉")) or "clear" in lowered:
        return "clear"
    if any(keyword in text for keyword in ("减仓", "卖出", "卖了", "卖掉")) or any(
        keyword in lowered for keyword in ("sell", "sold", "reduce")
    ):
        return "sell"
    if any(keyword in text for keyword in ("加仓", "补仓")) or "add" in lowered:
        return "add"
    if any(keyword in text for keyword in ("买入", "买了", "建仓")) or any(
        keyword in lowered for keyword in ("buy", "bought")
    ):
        return "buy"
    return None


def detect_add_buy_intent(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in text for keyword in ("加仓", "补仓", "追加仓位")) or any(
        keyword in lowered for keyword in ("add", "increase position")
    )


def is_analysis_request(text: str) -> bool:
    lowered = text.lower()
    return any(
        keyword in text
        for keyword in (
            "帮我判断",
            "判断",
            "能不能",
            "能否",
            "可不可以",
            "是否",
            "该不该",
            "要不要",
            "准备",
            "计划",
            "打算",
            "考虑",
            "想",
            "吗",
            "？",
            "?",
        )
    ) or any(keyword in lowered for keyword in ("should i", "can i", "whether"))


def has_factual_buy_update(text: str, lowered: str) -> bool:
    return any(keyword in text for keyword in ("买了", "买入了", "已买", "已买入", "建仓了", "已建仓")) or "bought" in lowered


def has_factual_add_update(text: str, lowered: str) -> bool:
    return any(keyword in text for keyword in ("加仓了", "已加仓", "补仓了", "已补仓")) or "added" in lowered


def has_factual_sell_update(text: str, lowered: str) -> bool:
    return any(keyword in text for keyword in ("卖了", "卖出了", "已卖", "已卖出", "减仓了", "已减仓")) or "sold" in lowered


def has_factual_clear_update(text: str, lowered: str) -> bool:
    return any(keyword in text for keyword in ("清仓了", "已清仓", "清掉了")) or "cleared" in lowered


def infer_symbol_from_text(text: str) -> str | None:
    key_value_symbol = re.search(r"(?:symbol|ticker|code)=([^\s]+)", text, re.IGNORECASE)
    if key_value_symbol:
        return key_value_symbol.group(1)
    code_match = re.search(r"\b(?:SH|SZ)?(\d{6})(?:\.SH|\.SZ)?\b", text, re.IGNORECASE)
    if code_match:
        return code_match.group(1)
    ticker_match = re.search(r"\b[A-Z]{1,6}\b", text)
    if ticker_match:
        return ticker_match.group(0)
    return None


def required_fields_for_action(action: str) -> tuple[str, ...]:
    if action in {"buy", "add"}:
        return ("symbol", "market", "quantity", "buy_date", "buy_price")
    if action in {"sell", "reduce"}:
        return ("symbol", "quantity")
    if action == "clear":
        return ("symbol",)
    return ("symbol",)


def question_for_missing_field(action: str, field: str) -> str:
    labels = {
        "symbol": "标的代码或名称",
        "market": "市场（A 或 US）",
        "quantity": "数量",
        "buy_date": "买入日期",
        "buy_price": "买入价",
    }
    return f"检测到 {action} 更新，但缺少{labels.get(field, field)}，请补充。"


def portfolio_row_from_update(action: str, fields: dict[str, str]) -> dict[str, str]:
    row = {key: clean_cell(value) for key, value in fields.items() if key in PORTFOLIO_COLUMNS}
    if action == "clear":
        row["quantity"] = "0"
        row["notes"] = append_note(row.get("notes", ""), "清仓")
    elif action in {"sell", "reduce"}:
        row["notes"] = append_note(row.get("notes", ""), f"{action} 更新；数量为更新后的剩余持仓或用户指定数量")
    elif action in {"buy", "add"}:
        row["notes"] = append_note(row.get("notes", ""), f"{action} 更新")
    return row


def append_note(existing: str, note: str) -> str:
    if not existing:
        return note
    return f"{existing}; {note}"


def upsert_memory_table_row(
    project_root: Path | str,
    filename: str,
    key_column: str,
    row: dict[str, object],
    dry_run: bool = True,
) -> MemoryUpdateResult:
    """Insert or update a row in the first Markdown table of an allowed memory file.

    The helper replaces only the table block and preserves all surrounding
    Markdown text. Ambiguous updates are rejected by requiring a non-empty key.
    """

    path = allowed_memory_path(project_root, filename)
    if not path.exists():
        raise MemoryError(f"Memory file does not exist: {path}")
    original = path.read_text(encoding="utf-8")
    table = parse_first_markdown_table(original)
    if key_column not in table.headers:
        raise MemoryError(f"Table does not contain key column: {key_column}")
    key_value = clean_cell(row.get(key_column))
    if not key_value:
        raise MemoryError(f"Ambiguous update: missing key value for {key_column}")

    normalized_row = {header: clean_cell(row.get(header)) for header in table.headers}
    updated_rows = []
    replaced = False
    for existing in table.rows:
        if existing.get(key_column, "") == key_value:
            merged = dict(existing)
            for header, value in normalized_row.items():
                if value != "":
                    merged[header] = value
            updated_rows.append(merged)
            replaced = True
        else:
            updated_rows.append(existing)
    if not replaced:
        updated_rows.append(normalized_row)

    new_text = replace_table(original, table, updated_rows)
    diff = unified_diff(original, new_text, fromfile=str(path), tofile=str(path))
    changed = original != new_text
    if changed and not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return MemoryUpdateResult(path=path, changed=changed, dry_run=dry_run, diff=diff, new_text=new_text)


def replace_table(text: str, table: MarkdownTable, rows: list[dict[str, str]]) -> str:
    lines = text.splitlines()
    table_lines = render_markdown_table(table.headers, rows)
    new_lines = lines[: table.start_line] + table_lines + lines[table.end_line :]
    trailing_newline = "\n" if text.endswith("\n") else ""
    return "\n".join(new_lines) + trailing_newline


def render_markdown_table(headers: tuple[str, ...], rows: list[dict[str, str]]) -> list[str]:
    rendered = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        rendered.append("| " + " | ".join(escape_cell(row.get(header, "")) for header in headers) + " |")
    return rendered


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


def clean_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def escape_cell(value: str) -> str:
    return clean_cell(value).replace("|", "\\|").replace("\n", " ")


def unified_diff(original: str, new: str, fromfile: str, tofile: str) -> str:
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
        )
    )
