from datetime import datetime, timezone
import json
import unittest

from trading_agent.market_data import (
    attach_recent_change_pct,
    classify_intraday_shape,
    parse_tencent_kline_payload,
    parse_tencent_quote_text,
    parse_tencent_timestamp,
    parse_yahoo_recent_bars,
    snapshot_to_dict,
    snapshots_to_json,
    snapshots_to_table,
)
from trading_agent.models import Market, QuoteSnapshot, RecentQuoteBar, Symbol


TENCENT_QUOTE = (
    'v_sh600519="1~贵州茅台~600519~1375.00~1384.79~1365.10~47806~23748~24058~'
    '1375.00~38~1374.99~22~1374.98~3~1374.96~1~1374.95~1~1375.03~14~1375.09~'
    '1~1375.10~3~1375.13~1~1375.15~2~~20260506161405~-9.79~-0.71~1379.00~'
    '1360.05~1375.00/47806/6550750940~47806~655075~0.38~20.82";'
)


class MarketDataTest(unittest.TestCase):
    def test_parse_tencent_quote_text(self):
        parsed = parse_tencent_quote_text(TENCENT_QUOTE)

        self.assertEqual(parsed["name"], "贵州茅台")
        self.assertEqual(parsed["code"], "600519")
        self.assertEqual(parsed["latest_price"], "1375.00")
        self.assertEqual(parsed["change_pct"], "-0.71")
        self.assertEqual(parsed["turnover_rate"], "0.38")

    def test_parse_tencent_timestamp_uses_china_timezone(self):
        parsed = parse_tencent_timestamp("20260506161405")

        self.assertEqual(parsed.isoformat(), "2026-05-06T16:14:05+08:00")

    def test_parse_tencent_kline_payload_and_compute_change(self):
        payload = {
            "data": {
                "sh600519": {
                    "qfqday": [
                        ["2026-04-29", "1380.00", "1400.00", "1410.00", "1370.00", "100"],
                        ["2026-04-30", "1400.00", "1384.79", "1401.17", "1380.00", "100"],
                    ]
                }
            }
        }

        bars = attach_recent_change_pct(parse_tencent_kline_payload(payload, "sh600519"))

        self.assertEqual(len(bars), 2)
        self.assertIsNone(bars[0].change_pct)
        self.assertAlmostEqual(bars[1].change_pct, -1.0864)
        self.assertIsNone(bars[1].turnover_rate)

    def test_parse_yahoo_recent_bars(self):
        bars = attach_recent_change_pct(
            parse_yahoo_recent_bars(
                [1777815000, 1777901400],
                {"close": [10.0, 11.0]},
            )
        )

        self.assertEqual([bar.close for bar in bars], [10.0, 11.0])
        self.assertEqual(bars[1].change_pct, 10.0)

    def test_classify_intraday_shape(self):
        shape = classify_intraday_shape(
            open_price=101.0,
            latest_price=103.0,
            previous_close=100.0,
            high_price=103.5,
            low_price=100.8,
            is_limit_up=False,
        )

        self.assertEqual(shape, "高开高走")

    def test_snapshot_serialization_formats_missing_fields(self):
        snapshot = QuoteSnapshot(
            symbol=Symbol(value="NVDA", market=Market.US, name="NVIDIA"),
            source="fixture",
            timestamp=datetime(2026, 5, 6, tzinfo=timezone.utc),
            latest_price=100.0,
            change_pct=1.2,
            recent_bars=[RecentQuoteBar(trade_date="2026-05-06", close=100.0)],
            missing_fields=["turnover_rate"],
        )

        data = snapshot_to_dict(snapshot)
        self.assertEqual(data["symbol"], "NVDA")
        self.assertEqual(data["missing_fields"], ["turnover_rate"])
        self.assertIn("NVDA", snapshots_to_table([snapshot]))
        decoded = json.loads(snapshots_to_json([snapshot]))
        self.assertEqual(decoded[0]["name"], "NVIDIA")


if __name__ == "__main__":
    unittest.main()
