from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import unittest

from trading_agent.cli import build_agent_packet
from trading_agent.memory import upsert_memory_table_row


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def copy_project_memory(tmp_root):
    shutil.copytree(PROJECT_ROOT / "memory", tmp_root / "memory")
    shutil.copytree(PROJECT_ROOT / "skills", tmp_root / "skills")


class AgentPreflightTest(unittest.TestCase):
    def test_judge_target_does_not_block_on_blank_memory(self):
        packet = build_agent_packet(
            project_root=PROJECT_ROOT,
            command="judge-target",
            symbol_or_name="NVDA",
            market="US",
            skip_quotes=True,
        )

        self.assertEqual(packet["status"], "ready")
        self.assertEqual(packet["setup_questions"], [])

    def test_judge_buy_empty_portfolio_is_non_blocking(self):
        packet = build_agent_packet(
            project_root=PROJECT_ROOT,
            command="judge-buy",
            symbol_or_name="NVDA",
            market="US",
            skip_quotes=True,
        )

        self.assertEqual(packet["status"], "ready")
        self.assertEqual(packet["preflight_issues"], [])
        self.assertEqual(packet["portfolio_notices"][0]["symbol"], "portfolio")

    def test_judge_buy_add_intent_requires_existing_holding(self):
        packet = build_agent_packet(
            project_root=PROJECT_ROOT,
            command="judge-buy",
            symbol_or_name="NVDA",
            market="US",
            user_note="帮我判断 NVDA 能不能加仓",
            skip_quotes=True,
        )

        self.assertEqual(packet["status"], "needs_portfolio_info")
        self.assertEqual(packet["preflight_issues"][0]["missing_fields"], ["portfolio_holding"])
        self.assertEqual(packet["memory_update"]["status"], "no_update_detected")
        self.assertEqual(packet["setup_questions"], [])

    def test_judge_sell_blocks_when_holding_missing(self):
        packet = build_agent_packet(
            project_root=PROJECT_ROOT,
            command="judge-sell",
            symbol_or_name="NVDA",
            market="US",
            skip_quotes=True,
        )

        self.assertEqual(packet["status"], "needs_portfolio_info")
        self.assertEqual(packet["preflight_issues"][0]["missing_fields"], ["portfolio_holding"])
        self.assertEqual(packet["setup_questions"], [])

    def test_judge_sell_blocks_when_buy_info_incomplete(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_project_memory(root)
            upsert_memory_table_row(
                root,
                "portfolio.md",
                "symbol",
                {"symbol": "NVDA", "market": "US", "name": "NVIDIA", "quantity": "10"},
                dry_run=False,
            )

            packet = build_agent_packet(
                project_root=root,
                command="judge-sell",
                symbol_or_name="NVDA",
                market="US",
                skip_quotes=True,
            )

            self.assertEqual(packet["status"], "needs_portfolio_info")
            self.assertIn("buy_date", packet["preflight_issues"][0]["missing_fields"])
            self.assertIn("buy_price_or_cost", packet["preflight_issues"][0]["missing_fields"])

    def test_plan_next_day_allows_confirmed_empty_portfolio(self):
        packet = build_agent_packet(
            project_root=PROJECT_ROOT,
            command="plan-next-day",
            skip_quotes=True,
            allow_empty_portfolio=True,
        )

        self.assertNotEqual(packet["status"], "needs_portfolio_info")
        areas = [item["area"] for item in packet["setup_questions"]]
        self.assertNotIn("portfolio", areas)

    def test_detected_buy_update_needs_confirmation_when_incomplete(self):
        packet = build_agent_packet(
            project_root=PROJECT_ROOT,
            command="judge-target",
            symbol_or_name="NVDA",
            user_note="我买了 NVDA",
            skip_quotes=True,
        )

        self.assertEqual(packet["status"], "needs_memory_confirmation")
        self.assertEqual(packet["memory_update"]["action"], "buy")
        self.assertIn("quantity", packet["memory_update"]["missing_fields"])
        self.assertEqual(packet["setup_questions"], [])

    def test_complete_buy_update_can_apply_before_packet(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_project_memory(root)

            packet = build_agent_packet(
                project_root=root,
                command="judge-target",
                symbol_or_name="NVDA",
                market="US",
                user_note=(
                    "action=buy symbol=NVDA market=US name=NVIDIA quantity=10 "
                    "buy_date=2026-05-06 buy_price=196.5 thesis=AI"
                ),
                apply_memory_updates=True,
                skip_quotes=True,
            )

            self.assertIn(packet["memory_update"]["status"], ("applied",))
            text = (root / "memory" / "portfolio.md").read_text(encoding="utf-8")
            self.assertIn("| NVDA | US | NVIDIA | 10 | 2026-05-06 | 196.5", text)


if __name__ == "__main__":
    unittest.main()
