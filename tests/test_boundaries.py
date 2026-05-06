from pathlib import Path
import unittest

from trading_agent.market_data import build_quote_request
from trading_agent.memory import MEMORY_FILENAMES, expected_memory_paths
from trading_agent.skills import SKILL_FILENAMES, build_skill_request


class BoundaryTest(unittest.TestCase):
    def test_memory_contract_has_three_files(self):
        self.assertEqual(
            MEMORY_FILENAMES,
            ("user_profile.md", "portfolio.md", "watchlist.md"),
        )
        paths = expected_memory_paths(Path("/tmp/project"))
        self.assertEqual(paths.user_profile.name, "user_profile.md")
        self.assertEqual(paths.portfolio.name, "portfolio.md")
        self.assertEqual(paths.watchlist.name, "watchlist.md")

    def test_skill_contract_has_initial_commands(self):
        self.assertEqual(SKILL_FILENAMES["judge-target"], "target_screening.md")
        self.assertEqual(SKILL_FILENAMES["judge-buy"], "buy_rating.md")
        self.assertEqual(SKILL_FILENAMES["judge-sell"], "sell_rating.md")
        self.assertEqual(SKILL_FILENAMES["plan-next-day"], "next_day_plan.md")

        request = build_skill_request(Path("/tmp/project"), "judge-target", "NVDA")
        self.assertEqual(request.skill_path.name, "target_screening.md")
        self.assertEqual(request.symbol_or_name, "NVDA")

    def test_quote_request_normalizes_symbols(self):
        request = build_quote_request(["NVDA"], "US")

        self.assertEqual(len(request.symbols), 1)
        self.assertEqual(request.symbols[0].value, "NVDA")
        self.assertEqual(request.symbols[0].market.value, "US")


if __name__ == "__main__":
    unittest.main()

