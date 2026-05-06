from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import unittest
from unittest.mock import patch

from trading_agent.cli import main
from trading_agent.models import Market, QuoteSnapshot, Symbol


class CliTest(unittest.TestCase):
    def run_cli(self, args):
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_help_lists_initial_commands(self):
        code, stdout, stderr = self.run_cli([])

        self.assertEqual(code, 0)
        self.assertIn("judge-target", stdout)
        self.assertIn("fetch-quotes", stdout)
        self.assertEqual(stderr, "")

    def test_judge_target_shell_accepts_symbol(self):
        code, stdout, stderr = self.run_cli(["judge-target", "NVDA", "--market", "US", "--skip-quotes"])

        self.assertEqual(code, 0)
        self.assertIn("# Trading Agent Packet", stdout)
        self.assertIn("status: ready", stdout)
        self.assertIn("skill_id: target_screening", stdout)
        self.assertIn("chain=cli", stderr)
        self.assertNotIn("portfolio", stderr.lower())

    def test_fetch_quotes_shell_formats_snapshot(self):
        snapshot = QuoteSnapshot(
            symbol=Symbol(value="NVDA", market=Market.US, name="NVIDIA"),
            source="test",
            timestamp=datetime(2026, 5, 6, tzinfo=timezone.utc),
            latest_price=100.0,
            change_pct=1.2,
            missing_fields=["turnover_rate"],
        )
        with patch("trading_agent.cli.fetch_quotes", return_value=[snapshot]):
            code, stdout, stderr = self.run_cli(["fetch-quotes", "NVDA", "--market", "US"])

        self.assertEqual(code, 0)
        self.assertIn("NVDA", stdout)
        self.assertIn("NVIDIA", stdout)
        self.assertIn("symbol_count=1", stderr)
        self.assertIn("chain=market_data", stderr)


if __name__ == "__main__":
    unittest.main()
