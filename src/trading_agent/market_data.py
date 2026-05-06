"""Simplified market-data fetching and normalization.

Phase 2 intentionally keeps this module small and dependency-free. It uses
public web endpoints only to save lookup time for current/recent quote facts;
longer chart interpretation remains an AI/model task.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from trading_agent.models import Market, QuoteSnapshot, RecentQuoteBar, Symbol


DEFAULT_RECENT_DAYS = 5
USER_AGENT = "Mozilla/5.0 (compatible; trading-agent/0.1)"
CHINA_TZ = timezone(timedelta(hours=8))


class MarketDataError(RuntimeError):
    """Raised when a provider cannot return usable market data."""


@dataclass(frozen=True)
class QuoteRequest:
    symbols: list[Symbol]
    recent_days: int = DEFAULT_RECENT_DAYS


def build_quote_request(
    symbols: list[str],
    market: str | None = None,
    recent_days: int = DEFAULT_RECENT_DAYS,
) -> QuoteRequest:
    """Normalize a user quote request."""

    if not symbols:
        raise ValueError("At least one symbol is required")
    if recent_days < 2:
        raise ValueError("recent_days must be at least 2")
    return QuoteRequest(
        symbols=[Symbol.from_text(item, market) for item in symbols],
        recent_days=recent_days,
    )


def infer_market(raw_symbol: str, market: Market) -> Market:
    if market != Market.UNKNOWN:
        return market
    normalized = normalize_symbol_text(raw_symbol)
    if normalized.isdigit() and len(normalized) == 6:
        return Market.A
    return Market.US


def normalize_symbol_text(raw_symbol: str) -> str:
    normalized = raw_symbol.strip().upper()
    for prefix in ("SH", "SZ"):
        if normalized.startswith(prefix) and normalized[2:].isdigit():
            return normalized[2:]
    for suffix in (".SH", ".SZ", ".SS"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized


def fetch_quotes(request: QuoteRequest, timeout: float = 10.0) -> list[QuoteSnapshot]:
    return [fetch_quote(symbol, request.recent_days, timeout=timeout) for symbol in request.symbols]


def fetch_quote(
    symbol: Symbol,
    recent_days: int = DEFAULT_RECENT_DAYS,
    timeout: float = 10.0,
) -> QuoteSnapshot:
    market = infer_market(symbol.value, symbol.market)
    normalized = Symbol(value=normalize_symbol_text(symbol.value), market=market, name=symbol.name)
    if market == Market.A:
        return fetch_a_share_quote(normalized, recent_days=recent_days, timeout=timeout)
    if market == Market.US:
        return fetch_us_quote(normalized, recent_days=recent_days, timeout=timeout)
    raise MarketDataError(f"Cannot infer market for symbol: {symbol.value}")


def fetch_a_share_quote(
    symbol: Symbol,
    recent_days: int = DEFAULT_RECENT_DAYS,
    timeout: float = 10.0,
) -> QuoteSnapshot:
    code = normalize_symbol_text(symbol.value)
    sec_prefix = tencent_a_share_prefix(code)
    quote_text = http_text(f"https://qt.gtimg.cn/q={sec_prefix}{code}", timeout=timeout, encoding="gbk")
    quote_data = parse_tencent_quote_text(quote_text)

    kline_url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
        + urllib.parse.urlencode({"param": f"{sec_prefix}{code},day,,,{recent_days},qfq"})
    )
    kline_payload = http_json(kline_url, timeout=timeout)
    recent_bars = parse_tencent_kline_payload(kline_payload, f"{sec_prefix}{code}")

    now = parse_tencent_timestamp(quote_data.get("timestamp")) or datetime.now(timezone.utc)
    latest_price = to_float(quote_data.get("latest_price"))
    open_price = to_float(quote_data.get("open_price"))
    previous_close = to_float(quote_data.get("previous_close"))
    close_price = latest_price
    change_pct = to_float(quote_data.get("change_pct"))
    high_price = to_float(quote_data.get("high_price"))
    low_price = to_float(quote_data.get("low_price"))
    turnover_rate = to_float(quote_data.get("turnover_rate"))
    missing_fields = []

    if recent_bars:
        recent_bars = attach_recent_change_pct(recent_bars)[-recent_days:]
        recent_missing = any(bar.turnover_rate is None for bar in recent_bars)
        if recent_missing:
            missing_fields.append("recent_turnover_rate")
    else:
        missing_fields.append("recent_bars")

    fields = {
        "latest_price": latest_price,
        "open_price": open_price,
        "previous_close": previous_close,
        "change_pct": change_pct,
        "turnover_rate": turnover_rate,
    }
    missing_fields.extend([key for key, value in fields.items() if value is None])
    missing_fields.extend(["is_sealed_board", "opened_after_seal"])

    is_limit_up = estimate_a_share_limit_up(change_pct)
    intraday_shape = classify_intraday_shape(
        open_price=open_price,
        latest_price=latest_price,
        previous_close=previous_close,
        high_price=high_price,
        low_price=low_price,
        is_limit_up=is_limit_up,
    )

    return QuoteSnapshot(
        symbol=Symbol(value=code, market=Market.A, name=quote_data.get("name") or symbol.name),
        source="tencent_quote+tencent_kline",
        timestamp=now,
        latest_price=latest_price,
        open_price=open_price,
        close_price=close_price,
        high_price=high_price,
        low_price=low_price,
        previous_close=previous_close,
        change_pct=change_pct,
        turnover_rate=turnover_rate,
        intraday_shape=intraday_shape,
        is_limit_up=is_limit_up,
        is_sealed_board=None,
        opened_after_seal=None,
        recent_bars=recent_bars,
        missing_fields=sorted(set(missing_fields)),
    )


def fetch_us_quote(
    symbol: Symbol,
    recent_days: int = DEFAULT_RECENT_DAYS,
    timeout: float = 10.0,
) -> QuoteSnapshot:
    ticker = normalize_symbol_text(symbol.value)
    encoded = urllib.parse.quote(ticker)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range={recent_days}d&interval=1d"
    payload = http_json(url, timeout=timeout)
    result = first_chart_result(payload, ticker)
    meta = result.get("meta") or {}
    quote = (result.get("indicators") or {}).get("quote") or []
    quote_rows = quote[0] if quote else {}
    timestamps = result.get("timestamp") or []
    recent_bars = parse_yahoo_recent_bars(timestamps, quote_rows)

    latest_price = to_float(meta.get("regularMarketPrice"))
    if len(recent_bars) >= 2:
        previous_close = recent_bars[-2].close
    else:
        previous_close = to_float(meta.get("chartPreviousClose"))

    last_open = last_number(quote_rows.get("open"))
    last_close = last_number(quote_rows.get("close"))
    last_high = last_number(quote_rows.get("high"))
    last_low = last_number(quote_rows.get("low"))
    if latest_price is None:
        latest_price = last_close

    change_pct = pct_change(latest_price, previous_close)
    timestamp = datetime.fromtimestamp(
        int(meta.get("regularMarketTime") or time.time()),
        timezone.utc,
    )
    missing_fields = []
    if not recent_bars:
        missing_fields.append("recent_bars")
    if latest_price is None:
        missing_fields.append("latest_price")
    if previous_close is None:
        missing_fields.append("previous_close")
    missing_fields.extend(["turnover_rate", "recent_turnover_rate", "is_limit_up", "is_sealed_board", "opened_after_seal"])

    return QuoteSnapshot(
        symbol=Symbol(
            value=str(meta.get("symbol") or ticker),
            market=Market.US,
            name=meta.get("shortName") or meta.get("longName") or symbol.name,
        ),
        source="yahoo_chart",
        timestamp=timestamp,
        latest_price=latest_price,
        open_price=last_open,
        close_price=last_close,
        high_price=last_high,
        low_price=last_low,
        previous_close=previous_close,
        change_pct=change_pct,
        turnover_rate=None,
        intraday_shape=classify_intraday_shape(
            open_price=last_open,
            latest_price=latest_price,
            previous_close=previous_close,
            high_price=last_high,
            low_price=last_low,
            is_limit_up=None,
        ),
        is_limit_up=None,
        is_sealed_board=None,
        opened_after_seal=None,
        recent_bars=attach_recent_change_pct(recent_bars)[-recent_days:],
        missing_fields=sorted(set(missing_fields)),
    )


def http_json(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except Exception as exc:  # pragma: no cover - exercised by live conditions
        raise MarketDataError(f"Provider request failed: {url}: {exc}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise MarketDataError(f"Provider returned non-JSON response: {url}") from exc


def http_text(url: str, timeout: float, encoding: str = "utf-8") -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode(encoding, errors="replace")
    except Exception as exc:  # pragma: no cover - exercised by live conditions
        raise MarketDataError(f"Provider request failed: {url}: {exc}") from exc


def tencent_a_share_prefix(code: str) -> str:
    if not (code.isdigit() and len(code) == 6):
        raise MarketDataError(f"A-share symbol must be a 6-digit code: {code}")
    if code.startswith(("5", "6", "9")):
        return "sh"
    if code.startswith(("0", "1", "2", "3")):
        return "sz"
    raise MarketDataError(f"Cannot infer A-share exchange prefix for: {code}")


def parse_tencent_quote_text(text: str) -> dict[str, str]:
    if '="' not in text:
        raise MarketDataError("Tencent quote response has unexpected shape")
    payload = text.split('="', 1)[1].rsplit('"', 1)[0]
    parts = payload.split("~")
    if len(parts) < 39:
        raise MarketDataError("Tencent quote response is missing fields")
    return {
        "name": parts[1],
        "code": parts[2],
        "latest_price": parts[3],
        "previous_close": parts[4],
        "open_price": parts[5],
        "timestamp": parts[30],
        "change_amount": parts[31],
        "change_pct": parts[32],
        "high_price": parts[33],
        "low_price": parts[34],
        "turnover_rate": parts[38],
    }


def parse_tencent_kline_payload(payload: dict[str, Any], key: str) -> list[RecentQuoteBar]:
    data = payload.get("data") or {}
    symbol_data = data.get(key) or {}
    rows = symbol_data.get("qfqday") or symbol_data.get("day") or []
    bars = []
    for row in rows:
        if len(row) < 3:
            continue
        bars.append(
            RecentQuoteBar(
                trade_date=str(row[0]),
                close=to_float(row[2]),
                change_pct=None,
                turnover_rate=None,
            )
        )
    return bars


def first_chart_result(payload: dict[str, Any], ticker: str) -> dict[str, Any]:
    chart = payload.get("chart") or {}
    error = chart.get("error")
    if error:
        raise MarketDataError(f"Yahoo chart error for {ticker}: {error}")
    results = chart.get("result") or []
    if not results:
        raise MarketDataError(f"Yahoo chart returned no result for {ticker}")
    return results[0]


def parse_yahoo_recent_bars(
    timestamps: Iterable[int],
    quote_rows: dict[str, list[Any]],
) -> list[RecentQuoteBar]:
    closes = quote_rows.get("close") or []
    bars = []
    for index, raw_timestamp in enumerate(timestamps):
        close = closes[index] if index < len(closes) else None
        if close is None:
            continue
        trade_date = datetime.fromtimestamp(int(raw_timestamp), timezone.utc).date().isoformat()
        bars.append(RecentQuoteBar(trade_date=trade_date, close=to_float(close)))
    return bars


def attach_recent_change_pct(bars: list[RecentQuoteBar]) -> list[RecentQuoteBar]:
    if not bars:
        return []
    enriched = []
    previous_close = None
    for bar in bars:
        change = pct_change(bar.close, previous_close)
        enriched.append(
            RecentQuoteBar(
                trade_date=bar.trade_date,
                close=bar.close,
                change_pct=change,
                turnover_rate=bar.turnover_rate,
            )
        )
        if bar.close is not None:
            previous_close = bar.close
    return enriched


def parse_tencent_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=CHINA_TZ)
    except ValueError:
        return None


def classify_intraday_shape(
    *,
    open_price: float | None,
    latest_price: float | None,
    previous_close: float | None,
    high_price: float | None,
    low_price: float | None,
    is_limit_up: bool | None,
) -> str | None:
    if open_price is None or latest_price is None or previous_close in (None, 0):
        return None

    gap_pct = pct_change(open_price, previous_close)
    move_pct = pct_change(latest_price, open_price)
    day_pct = pct_change(latest_price, previous_close)
    amplitude = None
    if high_price is not None and low_price is not None and previous_close:
        amplitude = (high_price - low_price) / previous_close * 100

    if is_limit_up and near(open_price, latest_price) and near(high_price, low_price):
        return "一字板"
    if gap_pct is not None and move_pct is not None:
        if gap_pct >= 0.5 and move_pct >= 0.5:
            return "高开高走"
        if gap_pct <= -0.5 and move_pct >= 1.0:
            return "低开高走"
        if gap_pct >= 0.5 and move_pct <= -0.5:
            return "高开低走"
    if day_pct is not None:
        if day_pct <= -1.0 and (move_pct is None or move_pct <= 0.3):
            return "弱势下跌"
        if day_pct >= 1.0:
            return "走强"
        if abs(day_pct) < 1.0 and (amplitude is None or amplitude <= 3.0):
            return "震荡"
    return "日线粗略走势"


def estimate_a_share_limit_up(change_pct: float | None) -> bool | None:
    if change_pct is None:
        return None
    return change_pct >= 9.8


def pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return round((current - previous) / previous * 100, 4)


def near(left: float | None, right: float | None, tolerance: float = 0.01) -> bool:
    if left is None or right is None:
        return False
    return math.isclose(left, right, abs_tol=tolerance)


def last_number(values: list[Any] | None) -> float | None:
    if not values:
        return None
    for value in reversed(values):
        parsed = to_float(value)
        if parsed is not None:
            return parsed
    return None


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def snapshot_to_dict(snapshot: QuoteSnapshot) -> dict[str, Any]:
    return {
        "symbol": snapshot.symbol.value,
        "market": snapshot.symbol.market.value,
        "name": snapshot.symbol.name,
        "source": snapshot.source,
        "timestamp": snapshot.timestamp.isoformat(),
        "latest_price": snapshot.latest_price,
        "open_price": snapshot.open_price,
        "close_price": snapshot.close_price,
        "high_price": snapshot.high_price,
        "low_price": snapshot.low_price,
        "previous_close": snapshot.previous_close,
        "change_pct": snapshot.change_pct,
        "turnover_rate": snapshot.turnover_rate,
        "intraday_shape": snapshot.intraday_shape,
        "is_limit_up": snapshot.is_limit_up,
        "is_sealed_board": snapshot.is_sealed_board,
        "opened_after_seal": snapshot.opened_after_seal,
        "recent_bars": [
            {
                "trade_date": bar.trade_date,
                "close": bar.close,
                "change_pct": bar.change_pct,
                "turnover_rate": bar.turnover_rate,
            }
            for bar in snapshot.recent_bars
        ],
        "missing_fields": snapshot.missing_fields,
    }


def snapshots_to_json(snapshots: list[QuoteSnapshot]) -> str:
    return json.dumps(
        [snapshot_to_dict(snapshot) for snapshot in snapshots],
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def snapshots_to_table(snapshots: list[QuoteSnapshot]) -> str:
    headers = ["symbol", "market", "name", "latest", "chg%", "open", "close", "turnover", "shape", "missing", "source"]
    rows = []
    for snapshot in snapshots:
        rows.append(
            [
                snapshot.symbol.value,
                snapshot.symbol.market.value,
                snapshot.symbol.name or "",
                fmt(snapshot.latest_price),
                fmt(snapshot.change_pct),
                fmt(snapshot.open_price),
                fmt(snapshot.close_price),
                fmt(snapshot.turnover_rate),
                snapshot.intraday_shape or "",
                str(len(snapshot.missing_fields)),
                snapshot.source,
            ]
        )
    return format_table(headers, rows)


def format_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    lines = ["  ".join(header.ljust(widths[index]) for index, header in enumerate(headers))]
    lines.append("  ".join("-" * width for width in widths))
    for row in rows:
        lines.append("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
    return "\n".join(lines)


def fmt(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.4g}"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch simplified A-share or US quote data.")
    parser.add_argument("symbols", nargs="+", help="One or more symbols.")
    parser.add_argument("--market", choices=("A", "US"), help="Optional market hint.")
    parser.add_argument("--recent-days", type=int, default=DEFAULT_RECENT_DAYS)
    parser.add_argument("--format", choices=("table", "json"), default="table")
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        request = build_quote_request(args.symbols, args.market, args.recent_days)
        snapshots = fetch_quotes(request, timeout=args.timeout)
    except (ValueError, MarketDataError) as exc:
        print(f"fetch-quotes error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(snapshots_to_json(snapshots))
    else:
        print(snapshots_to_table(snapshots))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
