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

from trading_agent.models import IntradayQuotePoint, Market, QuoteSnapshot, RecentQuoteBar, Symbol


DEFAULT_RECENT_DAYS = 5
DEFAULT_INTRADAY_SAMPLE_INTERVAL_MINUTES = 10
USER_AGENT = "Mozilla/5.0 (compatible; trading-agent/0.1)"
CHINA_TZ = timezone(timedelta(hours=8))


class MarketDataError(RuntimeError):
    """Raised when a provider cannot return usable market data."""


@dataclass(frozen=True)
class QuoteRequest:
    symbols: list[Symbol]
    recent_days: int = DEFAULT_RECENT_DAYS


@dataclass(frozen=True)
class IntradayBar:
    timestamp: str
    open: float | None = None
    close: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None
    amount: float | None = None
    average_price: float | None = None


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

    recent_source = "10jqka_kline"
    try:
        recent_bars = fetch_10jqka_recent_bars(code, recent_days=recent_days, timeout=timeout)
    except MarketDataError:
        recent_source = "tencent_kline"
        kline_url = (
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
            + urllib.parse.urlencode({"param": f"{sec_prefix}{code},day,,,{recent_days},qfq"})
        )
        kline_payload = http_json(kline_url, timeout=timeout)
        recent_bars = parse_tencent_kline_payload(kline_payload, f"{sec_prefix}{code}")
    intraday_bars: list[IntradayBar] = []
    intraday_error = False
    try:
        intraday_bars = fetch_eastmoney_intraday_bars(code, timeout=timeout)
    except MarketDataError:
        intraday_error = True
    intraday_samples = build_intraday_samples(
        intraday_bars,
        previous_close=to_float(quote_data.get("previous_close")),
        interval_minutes=DEFAULT_INTRADAY_SAMPLE_INTERVAL_MINUTES,
    )

    now = parse_tencent_timestamp(quote_data.get("timestamp")) or datetime.now(timezone.utc)
    latest_price = to_float(quote_data.get("latest_price"))
    open_price = to_float(quote_data.get("open_price"))
    previous_close = to_float(quote_data.get("previous_close"))
    close_price = latest_price
    change_pct = to_float(quote_data.get("change_pct"))
    high_price = to_float(quote_data.get("high_price"))
    low_price = to_float(quote_data.get("low_price"))
    turnover_rate = to_float(quote_data.get("turnover_rate"))
    volume = to_float(quote_data.get("volume"))
    amount = to_float(quote_data.get("amount"))
    volume_ratio = to_float(quote_data.get("volume_ratio"))
    missing_fields = []

    if recent_bars:
        recent_bars = attach_recent_metrics(recent_bars)[-recent_days:]
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
        "volume": volume,
    }
    missing_fields.extend([key for key, value in fields.items() if value is None])
    if amount is None:
        missing_fields.append("amount")
    if volume_ratio is None:
        missing_fields.append("volume_ratio")
    if intraday_error or not intraday_samples:
        missing_fields.append("intraday_samples")

    limit_pct = a_share_limit_pct(code, quote_data.get("name") or symbol.name)
    is_limit_up = estimate_a_share_limit_up(
        high_price=high_price,
        previous_close=previous_close,
        limit_pct=limit_pct,
    )
    is_sealed_board = estimate_a_share_sealed_board(
        latest_price=latest_price,
        previous_close=previous_close,
        limit_pct=limit_pct,
        is_limit_up=is_limit_up,
    )
    opened_after_seal = is_limit_up and is_sealed_board is False

    recent_bars = attach_current_day_details(
        recent_bars,
        trade_date=now.astimezone(CHINA_TZ).date().isoformat(),
        open_price=open_price,
        latest_price=latest_price,
        high_price=high_price,
        low_price=low_price,
        previous_close=previous_close,
        change_pct=change_pct,
        turnover_rate=turnover_rate,
        volume=volume,
        amount=amount,
        volume_ratio=volume_ratio,
        is_limit_up=is_limit_up,
        is_sealed_board=is_sealed_board,
        opened_after_seal=opened_after_seal,
        intraday_samples=intraday_samples,
        recent_days=recent_days,
    )

    return QuoteSnapshot(
        symbol=Symbol(value=code, market=Market.A, name=quote_data.get("name") or symbol.name),
        source=f"tencent_quote+{recent_source}+eastmoney_intraday" if intraday_bars else f"tencent_quote+{recent_source}",
        timestamp=now,
        latest_price=latest_price,
        open_price=open_price,
        close_price=close_price,
        high_price=high_price,
        low_price=low_price,
        previous_close=previous_close,
        change_pct=change_pct,
        turnover_rate=turnover_rate,
        volume=volume,
        amount=amount,
        volume_ratio=volume_ratio,
        is_limit_up=is_limit_up,
        is_sealed_board=is_sealed_board,
        opened_after_seal=opened_after_seal,
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
    last_volume = last_number(quote_rows.get("volume"))
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
    if last_volume is None:
        missing_fields.append("volume")
    missing_fields.extend(["turnover_rate", "recent_turnover_rate", "amount", "is_limit_up", "is_sealed_board", "opened_after_seal"])
    recent_bars = attach_recent_metrics(recent_bars)[-recent_days:]
    latest_volume_ratio = recent_bars[-1].volume_ratio if recent_bars else None
    if latest_volume_ratio is None:
        missing_fields.append("volume_ratio")

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
        volume=last_volume,
        amount=None,
        volume_ratio=latest_volume_ratio,
        is_limit_up=None,
        is_sealed_board=None,
        opened_after_seal=None,
        recent_bars=recent_bars,
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


def http_text(
    url: str,
    timeout: float,
    encoding: str = "utf-8",
    headers: dict[str, str] | None = None,
) -> str:
    request_headers = {"User-Agent": USER_AGENT}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
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


def eastmoney_a_share_secid(code: str) -> str:
    if not (code.isdigit() and len(code) == 6):
        raise MarketDataError(f"A-share symbol must be a 6-digit code: {code}")
    market_id = "1" if code.startswith(("5", "6", "9")) else "0"
    return f"{market_id}.{code}"


def fetch_eastmoney_intraday_bars(code: str, timeout: float) -> list[IntradayBar]:
    url = (
        "https://push2.eastmoney.com/api/qt/stock/trends2/get?"
        + urllib.parse.urlencode(
            {
                "secid": eastmoney_a_share_secid(code),
                "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
                "ndays": "1",
                "iscr": "0",
                "iscca": "0",
            }
        )
    )
    payload = http_json(url, timeout=timeout)
    data = payload.get("data") or {}
    rows = data.get("trends") or []
    if not rows:
        raise MarketDataError(f"Eastmoney intraday returned no rows for {code}")
    return parse_eastmoney_intraday_rows(rows)


def fetch_10jqka_recent_bars(code: str, recent_days: int, timeout: float) -> list[RecentQuoteBar]:
    url = f"https://d.10jqka.com.cn/v6/line/hs_{code}/01/last.js"
    text = http_text(
        url,
        timeout=timeout,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": f"https://stockpage.10jqka.com.cn/{code}/",
        },
    )
    return parse_10jqka_kline_text(text)[-recent_days:]


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
        "volume": parts[36],
        "amount": parse_tencent_amount(parts[35], parts[37] if len(parts) > 37 else ""),
        "turnover_rate": parts[38],
        "volume_ratio": parts[49] if len(parts) > 49 else "",
    }


def parse_tencent_amount(combined: str, fallback: str) -> str:
    parts = combined.split("/")
    if len(parts) >= 3 and parts[2]:
        return parts[2]
    return fallback


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
                open=to_float(row[1]) if len(row) > 1 else None,
                close=to_float(row[2]),
                high=to_float(row[3]) if len(row) > 3 else None,
                low=to_float(row[4]) if len(row) > 4 else None,
                change_pct=None,
                turnover_rate=None,
                volume=to_float(row[5]) if len(row) > 5 else None,
            )
        )
    return bars


def parse_10jqka_kline_text(text: str) -> list[RecentQuoteBar]:
    start = text.find("({")
    end = text.rfind("})")
    if start == -1 or end == -1:
        raise MarketDataError("10jqka kline response has unexpected shape")
    try:
        payload = json.loads(text[start + 1 : end + 1])
    except json.JSONDecodeError as exc:
        raise MarketDataError("10jqka kline response is not valid JSONP") from exc
    rows = str(payload.get("data") or "").split(";")
    bars = []
    for row in rows:
        if not row:
            continue
        parts = row.split(",")
        if len(parts) < 8:
            continue
        trade_date = parse_compact_trade_date(parts[0])
        if trade_date is None:
            continue
        volume_shares = to_float(parts[5])
        bars.append(
            RecentQuoteBar(
                trade_date=trade_date,
                open=to_float(parts[1]),
                high=to_float(parts[2]),
                low=to_float(parts[3]),
                close=to_float(parts[4]),
                volume=round(volume_shares / 100, 4) if volume_shares is not None else None,
                amount=to_float(parts[6]),
                turnover_rate=to_float(parts[7]),
            )
        )
    if not bars:
        raise MarketDataError("10jqka kline returned no usable rows")
    return bars


def parse_compact_trade_date(value: str) -> str | None:
    try:
        return datetime.strptime(value, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def parse_eastmoney_intraday_rows(rows: Iterable[str]) -> list[IntradayBar]:
    bars = []
    for row in rows:
        parts = str(row).split(",")
        if len(parts) < 7:
            continue
        bars.append(
            IntradayBar(
                timestamp=parts[0],
                open=to_float(parts[1]),
                close=to_float(parts[2]),
                high=to_float(parts[3]),
                low=to_float(parts[4]),
                volume=to_float(parts[5]),
                amount=to_float(parts[6]),
                average_price=to_float(parts[7]) if len(parts) > 7 else None,
            )
        )
    return bars


def build_intraday_samples(
    bars: list[IntradayBar],
    *,
    previous_close: float | None,
    interval_minutes: int = DEFAULT_INTRADAY_SAMPLE_INTERVAL_MINUTES,
) -> list[IntradayQuotePoint]:
    sampled = sample_intraday_bars(bars, interval_minutes=interval_minutes)
    points = []
    for bar in sampled:
        price = bar.close
        points.append(
            IntradayQuotePoint(
                timestamp=bar.timestamp,
                price=price,
                change_pct=pct_change(price, previous_close),
                average_price=bar.average_price,
                volume=bar.volume,
                amount=bar.amount,
            )
        )
    return points


def sample_intraday_bars(
    bars: list[IntradayBar],
    *,
    interval_minutes: int = DEFAULT_INTRADAY_SAMPLE_INTERVAL_MINUTES,
) -> list[IntradayBar]:
    if interval_minutes <= 0:
        raise ValueError("interval_minutes must be positive")
    ordered = sorted(bars, key=lambda bar: parse_intraday_timestamp(bar.timestamp) or datetime.max.replace(tzinfo=CHINA_TZ))
    sampled: list[IntradayBar] = []
    last_sample_time: datetime | None = None
    for bar in ordered:
        bar_time = parse_intraday_timestamp(bar.timestamp)
        if bar_time is None:
            continue
        if last_sample_time is None or bar_time - last_sample_time >= timedelta(minutes=interval_minutes):
            sampled.append(bar)
            last_sample_time = bar_time
    if ordered and (not sampled or sampled[-1].timestamp != ordered[-1].timestamp):
        sampled.append(ordered[-1])
    return sampled


def parse_intraday_timestamp(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=CHINA_TZ)
    except ValueError:
        return None


def attach_current_day_details(
    bars: list[RecentQuoteBar],
    *,
    trade_date: str,
    open_price: float | None,
    latest_price: float | None,
    high_price: float | None,
    low_price: float | None,
    previous_close: float | None,
    change_pct: float | None,
    turnover_rate: float | None,
    volume: float | None,
    amount: float | None,
    volume_ratio: float | None,
    is_limit_up: bool | None,
    is_sealed_board: bool | None,
    opened_after_seal: bool | None,
    intraday_samples: list[IntradayQuotePoint],
    recent_days: int,
) -> list[RecentQuoteBar]:
    existing_current = next((bar for bar in bars if bar.trade_date == trade_date), None)
    current_close = latest_price if latest_price is not None else (existing_current.close if existing_current else None)
    current_change_pct = change_pct if change_pct is not None else pct_change(current_close, previous_close)
    current_bar = RecentQuoteBar(
        trade_date=trade_date,
        open=open_price,
        close=current_close,
        high=high_price,
        low=low_price,
        previous_close=previous_close,
        change_pct=current_change_pct,
        turnover_rate=turnover_rate,
        volume=volume,
        amount=amount,
        volume_ratio=volume_ratio,
        is_limit_up=is_limit_up,
        is_sealed_board=is_sealed_board,
        opened_after_seal=opened_after_seal,
        intraday_sample_interval_minutes=DEFAULT_INTRADAY_SAMPLE_INTERVAL_MINUTES if intraday_samples else None,
        intraday_source="eastmoney_trends2" if intraday_samples else None,
        intraday_samples=intraday_samples or None,
    )
    merged = [bar for bar in bars if bar.trade_date != trade_date]
    merged.append(current_bar)
    return merged[-recent_days:]


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
        bars.append(
            RecentQuoteBar(
                trade_date=trade_date,
                close=to_float(close),
                volume=to_float((quote_rows.get("volume") or [None] * (index + 1))[index])
                if index < len(quote_rows.get("volume") or [])
                else None,
            )
        )
    return bars


def attach_recent_change_pct(bars: list[RecentQuoteBar]) -> list[RecentQuoteBar]:
    return attach_recent_metrics(bars)


def attach_recent_metrics(
    bars: list[RecentQuoteBar],
    *,
    volume_average_window: int = 5,
) -> list[RecentQuoteBar]:
    if not bars:
        return []
    enriched = []
    previous_close = None
    for index, bar in enumerate(bars):
        change = pct_change(bar.close, previous_close)
        prior_volumes = [
            item.volume
            for item in bars[max(0, index - volume_average_window) : index]
            if item.volume not in (None, 0)
        ]
        if prior_volumes and bar.volume is not None:
            volume_ratio = round(bar.volume / (sum(prior_volumes) / len(prior_volumes)), 4)
        else:
            volume_ratio = None
        enriched.append(
            RecentQuoteBar(
                trade_date=bar.trade_date,
                open=bar.open,
                close=bar.close,
                high=bar.high,
                low=bar.low,
                previous_close=previous_close,
                change_pct=change,
                turnover_rate=bar.turnover_rate,
                volume=bar.volume,
                amount=bar.amount,
                volume_ratio=volume_ratio,
                is_limit_up=bar.is_limit_up,
                is_sealed_board=bar.is_sealed_board,
                opened_after_seal=bar.opened_after_seal,
                intraday_sample_interval_minutes=bar.intraday_sample_interval_minutes,
                intraday_source=bar.intraday_source,
                intraday_samples=bar.intraday_samples,
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


def a_share_limit_pct(code: str, name: str | None = None) -> float:
    normalized_name = name or ""
    if "ST" in normalized_name.upper() or "退" in normalized_name:
        return 5.0
    if code.startswith(("300", "301", "688", "689")):
        return 20.0
    if code.startswith(("8", "4", "920")):
        return 30.0
    return 10.0


def estimate_a_share_limit_up(
    *,
    high_price: float | None,
    previous_close: float | None,
    limit_pct: float,
) -> bool | None:
    high_pct = pct_change(high_price, previous_close)
    if high_pct is None:
        return None
    return high_pct >= limit_pct - 0.2


def estimate_a_share_sealed_board(
    *,
    latest_price: float | None,
    previous_close: float | None,
    limit_pct: float,
    is_limit_up: bool | None,
) -> bool | None:
    if not is_limit_up:
        return False if is_limit_up is False else None
    latest_pct = pct_change(latest_price, previous_close)
    if latest_pct is None:
        return None
    return latest_pct >= limit_pct - 0.2


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
        "recent_bars": [recent_bar_to_dict(bar) for bar in reversed(snapshot.recent_bars)],
        "missing_fields": snapshot.missing_fields,
    }


def recent_bar_to_dict(bar: RecentQuoteBar) -> dict[str, Any]:
    data: dict[str, Any] = {
        "trade_date": bar.trade_date,
        "open": bar.open,
        "close": bar.close,
        "high": bar.high,
        "low": bar.low,
        "previous_close": bar.previous_close,
        "change_pct": bar.change_pct,
        "turnover_rate": bar.turnover_rate,
        "volume": bar.volume,
        "amount": bar.amount,
        "volume_ratio": bar.volume_ratio,
        "is_limit_up": bar.is_limit_up,
        "is_sealed_board": bar.is_sealed_board,
        "opened_after_seal": bar.opened_after_seal,
        "intraday_sample_interval_minutes": bar.intraday_sample_interval_minutes,
        "intraday_source": bar.intraday_source,
    }
    data = {key: value for key, value in data.items() if value is not None}
    if bar.intraday_samples is not None:
        data["intraday_samples"] = [
            {
                "timestamp": point.timestamp,
                "price": point.price,
                "change_pct": point.change_pct,
                "average_price": point.average_price,
                "volume": point.volume,
                "amount": point.amount,
            }
            for point in bar.intraday_samples
        ]
    return data


def snapshots_to_json(snapshots: list[QuoteSnapshot]) -> str:
    return json.dumps(
        [snapshot_to_dict(snapshot) for snapshot in snapshots],
        ensure_ascii=False,
        indent=2,
    )


def snapshots_to_table(snapshots: list[QuoteSnapshot]) -> str:
    headers = [
        "symbol",
        "market",
        "name",
        "latest",
        "chg%",
        "open",
        "close",
        "turnover",
        "vol_ratio",
        "intraday_pts",
        "missing",
        "source",
    ]
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
                fmt(snapshot.volume_ratio),
                str(intraday_point_count(snapshot)),
                str(len(snapshot.missing_fields)),
                snapshot.source,
            ]
        )
    return format_table(headers, rows)


def intraday_point_count(snapshot: QuoteSnapshot) -> int:
    for bar in reversed(snapshot.recent_bars):
        if bar.intraday_samples is not None:
            return len(bar.intraday_samples)
    return 0


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
