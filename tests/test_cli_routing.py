from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import unittest
from unittest.mock import patch

from trading_agent.cli import main


class CliRoutingTest(unittest.TestCase):
    def run_cli(self, args):
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_judge_target_outputs_json_packet(self):
        code, stdout, stderr = self.run_cli(
            ["judge-target", "NVDA", "--market", "US", "--skip-quotes", "--format", "json"]
        )

        self.assertEqual(code, 0)
        packet = json.loads(stdout)
        self.assertEqual(packet["command"], "judge-target")
        self.assertEqual(packet["skill_packet"]["skill_id"], "target_screening")
        self.assertIn("chain=agent", stderr)

    def test_update_memory_reports_missing_fields(self):
        code, stdout, stderr = self.run_cli(["update-memory", "我买了", "NVDA", "--format", "json"])

        self.assertEqual(code, 0)
        packet = json.loads(stdout)
        self.assertEqual(packet["status"], "needs_confirmation")
        self.assertEqual(packet["memory_update"]["action"], "buy")
        self.assertIn("quantity", packet["memory_update"]["missing_fields"])
        self.assertIn("chain=cli", stderr)

    def test_update_memory_ignores_analysis_question(self):
        code, stdout, _stderr = self.run_cli(["update-memory", "帮我判断", "NVDA", "能不能加仓", "--format", "json"])

        self.assertEqual(code, 0)
        packet = json.loads(stdout)
        self.assertEqual(packet["status"], "no_update_detected")

    def test_update_memory_ignores_planned_trade_intent(self):
        code, stdout, _stderr = self.run_cli(["update-memory", "我准备加仓", "NVDA", "--format", "json"])

        self.assertEqual(code, 0)
        packet = json.loads(stdout)
        self.assertEqual(packet["status"], "no_update_detected")

    def test_output_packet_writes_file(self):
        with patch("pathlib.Path.write_text") as write_text:
            code, stdout, _stderr = self.run_cli(
                [
                    "judge-buy",
                    "NVDA",
                    "--market",
                    "US",
                    "--skip-quotes",
                    "--output-packet",
                    "packet.md",
                ]
            )

        self.assertEqual(code, 0)
        self.assertIn("packet_written=", stdout)
        self.assertTrue(write_text.called)


if __name__ == "__main__":
    unittest.main()
