from datetime import datetime
import unittest

from trading_agent.models import Market, RatingResult, RuleMatch, Symbol


class ModelsTest(unittest.TestCase):
    def test_symbol_from_text_normalizes_market(self):
        symbol = Symbol.from_text(" NVDA ", "us")

        self.assertEqual(symbol.value, "NVDA")
        self.assertEqual(symbol.market, Market.US)

    def test_rating_result_preserves_rule_and_bonus_slots(self):
        result = RatingResult(
            rating="watch",
            conclusion="Needs more evidence.",
            rule_matches=[
                RuleMatch(
                    name="main theme",
                    matched=None,
                    evidence="not checked",
                    reason="Phase 1 contract only",
                )
            ],
            bonus_matches=[],
            missing_evidence=["market context"],
        )

        self.assertEqual(result.rating, "watch")
        self.assertEqual(result.rule_matches[0].name, "main theme")
        self.assertEqual(result.missing_evidence, ["market context"])
        self.assertIsInstance(datetime.utcnow(), datetime)


if __name__ == "__main__":
    unittest.main()

