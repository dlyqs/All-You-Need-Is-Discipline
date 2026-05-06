"""Core data contracts for the lightweight trading agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Market(str, Enum):
    """Supported market identifiers for v1."""

    A = "A"
    US = "US"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_value(cls, value: str | None) -> "Market":
        if value is None or value == "":
            return cls.UNKNOWN
        normalized = value.strip().upper()
        for market in cls:
            if normalized == market.value:
                return market
        raise ValueError(f"Unsupported market: {value}")


class TargetRating(str, Enum):
    REJECT = "reject"
    WATCH = "watch"
    QUALIFIED = "qualified"


class BuyRating(str, Enum):
    PROHIBITED = "prohibited"
    AVOID = "avoid"
    WATCH = "watch"
    SMALL_TRIAL = "small_trial"
    BUYABLE = "buyable"


class SellRating(str, Enum):
    MUST_SELL = "must_sell"
    REDUCE = "reduce"
    HOLD = "hold"
    WATCH = "watch"


class EvidenceSource(str, Enum):
    SCRIPT = "script"
    MODEL_SEARCH = "model_search"
    MODEL_CHART_ANALYSIS = "model_chart_analysis"
    USER_MEMORY = "user_memory"
    USER_INPUT = "user_input"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Symbol:
    """A tradable target name/code with an optional market."""

    value: str
    market: Market = Market.UNKNOWN
    name: str | None = None

    @classmethod
    def from_text(cls, value: str, market: str | Market | None = None) -> "Symbol":
        normalized = value.strip()
        if not normalized:
            raise ValueError("Symbol cannot be empty")
        parsed_market = market if isinstance(market, Market) else Market.from_value(market)
        return cls(value=normalized, market=parsed_market)


@dataclass(frozen=True)
class IntradayQuotePoint:
    """One sampled intraday point for model-side chart reading."""

    timestamp: str
    price: float | None = None
    change_pct: float | None = None
    average_price: float | None = None
    volume: float | None = None
    amount: float | None = None


@dataclass(frozen=True)
class RecentQuoteBar:
    """One recent daily quote row used by the simplified market data script."""

    trade_date: str
    open: float | None = None
    close: float | None = None
    high: float | None = None
    low: float | None = None
    previous_close: float | None = None
    change_pct: float | None = None
    turnover_rate: float | None = None
    volume: float | None = None
    amount: float | None = None
    volume_ratio: float | None = None
    is_limit_up: bool | None = None
    is_sealed_board: bool | None = None
    opened_after_seal: bool | None = None
    intraday_sample_interval_minutes: int | None = None
    intraday_source: str | None = None
    intraday_samples: list[IntradayQuotePoint] | None = None


@dataclass(frozen=True)
class QuoteSnapshot:
    """Normalized quote data used as script evidence."""

    symbol: Symbol
    source: str
    timestamp: datetime
    latest_price: float | None = None
    open_price: float | None = None
    close_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    previous_close: float | None = None
    change_pct: float | None = None
    turnover_rate: float | None = None
    volume: float | None = None
    amount: float | None = None
    volume_ratio: float | None = None
    is_limit_up: bool | None = None
    is_sealed_board: bool | None = None
    opened_after_seal: bool | None = None
    recent_bars: list[RecentQuoteBar] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Holding:
    """A row from the current portfolio memory file."""

    symbol: Symbol
    quantity: float
    buy_date: str | None = None
    buy_price: float | None = None
    cost: float | None = None
    lots: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class EvidenceItem:
    """A single piece of evidence used in a rating report."""

    source: EvidenceSource
    title: str
    detail: str
    timestamp: datetime | None = None


@dataclass(frozen=True)
class RuleMatch:
    """Rule or bonus-item evaluation result."""

    name: str
    matched: bool | None
    evidence: str
    reason: str
    confidence: float | None = None


@dataclass(frozen=True)
class RatingResult:
    """Structured output contract shared by target/buy/sell judgments."""

    rating: str
    conclusion: str
    rule_matches: list[RuleMatch] = field(default_factory=list)
    bonus_matches: list[RuleMatch] = field(default_factory=list)
    vetoes: list[str] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    action: str | None = None
