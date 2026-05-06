from datetime import datetime, timezone
import json
import unittest

from trading_agent.market_data import (
    attach_recent_change_pct,
    attach_recent_metrics,
    attach_current_day_details,
    build_intraday_samples,
    estimate_a_share_limit_up,
    estimate_a_share_sealed_board,
    parse_10jqka_kline_text,
    parse_eastmoney_intraday_rows,
    parse_tencent_kline_payload,
    parse_tencent_quote_text,
    parse_tencent_timestamp,
    parse_yahoo_recent_bars,
    sample_intraday_bars,
    snapshot_to_dict,
    snapshots_to_json,
    snapshots_to_table,
)
from trading_agent.models import IntradayQuotePoint, Market, QuoteSnapshot, RecentQuoteBar, Symbol


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
        self.assertEqual(parsed["volume"], "47806")
        self.assertEqual(parsed["amount"], "6550750940")

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
        self.assertEqual(bars[1].volume, 100.0)

    def test_attach_recent_metrics_adds_volume_ratio_without_estimating_turnover(self):
        bars = attach_recent_metrics(
            [
                RecentQuoteBar(trade_date="2026-04-29", close=10.0, volume=100.0, turnover_rate=3.0),
                RecentQuoteBar(trade_date="2026-04-30", close=11.0, volume=200.0, turnover_rate=8.0),
            ]
        )

        self.assertEqual(bars[1].change_pct, 10.0)
        self.assertEqual(bars[1].volume_ratio, 2.0)
        self.assertEqual(bars[0].turnover_rate, 3.0)
        self.assertEqual(bars[1].turnover_rate, 8.0)

    def test_parse_10jqka_kline_text_reads_turnover_rate(self):
        text = (
            'quotebridge_v6_line_hs_000988_01_last({"data":"'
            '20260429,114.39,120.50,114.39,119.04,83280637,1000000000.00,8.283,,,0;'
            '20260430,119.11,120.97,115.00,119.53,92020793,1100000000.00,9.153,,,0'
            '"})'
        )

        bars = parse_10jqka_kline_text(text)

        self.assertEqual(bars[0].trade_date, "2026-04-29")
        self.assertEqual(bars[0].open, 114.39)
        self.assertEqual(bars[0].high, 120.5)
        self.assertEqual(bars[0].low, 114.39)
        self.assertEqual(bars[0].close, 119.04)
        self.assertEqual(bars[0].volume, 832806.37)
        self.assertEqual(bars[0].amount, 1000000000.0)
        self.assertEqual(bars[0].turnover_rate, 8.283)

    def test_parse_yahoo_recent_bars(self):
        bars = attach_recent_change_pct(
            parse_yahoo_recent_bars(
                [1777815000, 1777901400],
                {"close": [10.0, 11.0]},
            )
        )

        self.assertEqual([bar.close for bar in bars], [10.0, 11.0])
        self.assertEqual(bars[1].change_pct, 10.0)

    def test_intraday_samples_keep_ten_minute_points_for_model(self):
        rows = [
            "2026-05-06 09:30,123.00,123.00,123.00,123.00,100,1000.00,123.00",
            "2026-05-06 09:31,123.00,123.20,123.20,123.00,100,1000.00,123.10",
            "2026-05-06 09:40,123.00,124.00,124.20,123.00,100,1000.00,123.50",
            "2026-05-06 09:50,124.00,125.00,125.20,124.00,100,1000.00,124.50",
            "2026-05-06 09:55,125.00,124.50,125.20,124.00,100,1000.00,124.80",
        ]

        bars = parse_eastmoney_intraday_rows(rows)
        sampled = sample_intraday_bars(bars, interval_minutes=10)
        points = build_intraday_samples(bars, previous_close=123.0, interval_minutes=10)

        self.assertEqual([bar.timestamp for bar in sampled], ["2026-05-06 09:30", "2026-05-06 09:40", "2026-05-06 09:50", "2026-05-06 09:55"])
        self.assertEqual(points[1].timestamp, "2026-05-06 09:40")
        self.assertAlmostEqual(points[1].change_pct, 0.813)

    def test_attach_current_day_details_adds_intraday_to_today_only(self):
        samples = build_intraday_samples(
            parse_eastmoney_intraday_rows(
                [
                    "2026-05-06 09:30,123.00,123.00,123.00,123.00,100,1000.00,123.00",
                    "2026-05-06 09:40,123.00,124.00,124.20,123.00,100,1000.00,123.50",
                ]
            ),
            previous_close=123.0,
            interval_minutes=10,
        )

        bars = attach_current_day_details(
            [RecentQuoteBar(trade_date="2026-05-05", close=123.0, volume=100.0)],
            trade_date="2026-05-06",
            open_price=123.0,
            latest_price=124.0,
            high_price=124.2,
            low_price=123.0,
            previous_close=123.0,
            change_pct=0.813,
            turnover_rate=2.0,
            volume=200.0,
            amount=2000.0,
            volume_ratio=2.0,
            is_limit_up=False,
            is_sealed_board=False,
            opened_after_seal=False,
            intraday_samples=samples,
            recent_days=5,
        )

        self.assertIsNone(bars[0].intraday_samples)
        self.assertEqual(bars[1].intraday_sample_interval_minutes, 10)
        self.assertEqual(len(bars[1].intraday_samples or []), 2)

    def test_a_share_limit_flags_use_high_and_close(self):
        touched = estimate_a_share_limit_up(high_price=110.0, previous_close=100.0, limit_pct=10.0)
        sealed = estimate_a_share_sealed_board(
            latest_price=104.0,
            previous_close=100.0,
            limit_pct=10.0,
            is_limit_up=touched,
        )

        self.assertTrue(touched)
        self.assertFalse(sealed)

    def test_snapshot_serialization_formats_missing_fields(self):
        snapshot = QuoteSnapshot(
            symbol=Symbol(value="NVDA", market=Market.US, name="NVIDIA"),
            source="fixture",
            timestamp=datetime(2026, 5, 6, tzinfo=timezone.utc),
            latest_price=100.0,
            change_pct=1.2,
            recent_bars=[
                RecentQuoteBar(trade_date="2026-05-05", close=99.0, volume_ratio=0.8),
                RecentQuoteBar(
                    trade_date="2026-05-06",
                    open=98.0,
                    close=100.0,
                    high=101.0,
                    low=97.5,
                    previous_close=99.0,
                    change_pct=1.0101,
                    volume_ratio=1.2,
                    intraday_samples=[IntradayQuotePoint(timestamp="2026-05-06 09:30", price=98.0)],
                ),
            ],
            missing_fields=["turnover_rate"],
        )

        data = snapshot_to_dict(snapshot)
        self.assertEqual(data["symbol"], "NVDA")
        self.assertEqual(data["missing_fields"], ["turnover_rate"])
        self.assertNotIn("intraday_shape", data)
        self.assertNotIn("latest_price", data)
        self.assertNotIn("change_pct", data)
        self.assertEqual(data["recent_bars"][0]["trade_date"], "2026-05-06")
        self.assertEqual(data["recent_bars"][0]["volume_ratio"], 1.2)
        self.assertEqual(list(data["recent_bars"][0])[-1], "intraday_samples")
        self.assertIn("NVDA", snapshots_to_table([snapshot]))
        decoded = json.loads(snapshots_to_json([snapshot]))
        self.assertEqual(decoded[0]["name"], "NVIDIA")
        self.assertEqual(decoded[0]["recent_bars"][0]["trade_date"], "2026-05-06")
        self.assertEqual(list(decoded[0]["recent_bars"][0])[-1], "intraday_samples")
        self.assertNotIn("intraday_samples", decoded[0]["recent_bars"][1])


if __name__ == "__main__":
    unittest.main()
