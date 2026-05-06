from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import unittest
from unittest.mock import patch

from trading_agent.cli import build_agent_packet, quote_cache_path
from trading_agent.models import Market, QuoteSnapshot, Symbol


PROJECT_ROOT = Path(__file__).resolve().parents[1]

_MIN_ACCOUNT = """# x
## 用户与账户
| 字段 | 值 | 备注 |
| --- | --- | --- |
| 主要交易市场 | A股 | x |

## 持仓表
| symbol | market | name | quantity | buy_date | buy_price | lots | notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
"""


def _empty_holdings_portfolio() -> str:
    return _MIN_ACCOUNT + "\n## 自由备注\n"


def _copy_skills_watchlist(root: Path) -> None:
    (root / "memory").mkdir(parents=True, exist_ok=True)
    shutil.copytree(PROJECT_ROOT / "skills", root / "skills", dirs_exist_ok=True)
    (root / "memory" / "watchlist.md").write_text(
        (PROJECT_ROOT / "memory" / "watchlist.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )


class AgentPreflightTest(unittest.TestCase):
    def tearDown(self):
        cache_path = quote_cache_path(PROJECT_ROOT)
        if cache_path.exists():
            cache_path.unlink()

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
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _copy_skills_watchlist(root)
            (root / "memory" / "portfolio.md").write_text(_empty_holdings_portfolio(), encoding="utf-8")

            packet = build_agent_packet(
                project_root=root,
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
            _copy_skills_watchlist(root)
            body = (
                _MIN_ACCOUNT
                + "| NVDA | US | NVIDIA | 10 |  |  |  |\n\n## 自由备注\n"
            )
            (root / "memory" / "portfolio.md").write_text(body, encoding="utf-8")

            packet = build_agent_packet(
                project_root=root,
                command="judge-sell",
                symbol_or_name="NVDA",
                market="US",
                skip_quotes=True,
            )

            self.assertEqual(packet["status"], "needs_portfolio_info")
            self.assertIn("buy_date", packet["preflight_issues"][0]["missing_fields"])
            self.assertIn("buy_price", packet["preflight_issues"][0]["missing_fields"])

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

    def test_user_note_does_not_trigger_memory_confirmation(self):
        packet = build_agent_packet(
            project_root=PROJECT_ROOT,
            command="judge-target",
            symbol_or_name="NVDA",
            user_note="我买了 NVDA",
            skip_quotes=True,
        )

        self.assertEqual(packet["status"], "ready")

    def test_quote_evidence_uses_single_symbol_cache(self):
        snapshot = QuoteSnapshot(
            symbol=Symbol(value="NVDA", market=Market.US, name="NVIDIA"),
            source="fixture",
            timestamp=datetime(2026, 5, 6, tzinfo=timezone.utc),
            latest_price=100.0,
        )

        with patch("trading_agent.cli.fetch_quotes", return_value=[snapshot]) as fetch_quotes_mock:
            first = build_agent_packet(
                project_root=PROJECT_ROOT,
                command="judge-target",
                symbol_or_name="NVDA",
                market="US",
            )
            second = build_agent_packet(
                project_root=PROJECT_ROOT,
                command="judge-target",
                symbol_or_name="NVDA",
                market="US",
            )

        self.assertEqual(first["status"], "ready")
        self.assertEqual(second["status"], "ready")
        self.assertEqual(fetch_quotes_mock.call_count, 1)
        self.assertEqual(first["quote_snapshots"], second["quote_snapshots"])


if __name__ == "__main__":
    unittest.main()
