from pathlib import Path
import unittest

from trading_agent.skills import (
    SKILL_FILENAMES,
    SkillError,
    build_execution_packet,
    load_all_skills,
    load_skill,
    parse_skill_metadata,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SkillLoaderTest(unittest.TestCase):
    def test_loads_all_planned_skills(self):
        definitions = load_all_skills(PROJECT_ROOT)

        self.assertEqual(set(definitions), set(SKILL_FILENAMES))
        self.assertEqual(definitions["judge-target"].metadata.skill_id, "target_screening")
        self.assertEqual(definitions["judge-buy"].metadata.skill_id, "buy_rating")
        self.assertEqual(definitions["judge-sell"].metadata.skill_id, "sell_rating")
        self.assertEqual(definitions["plan-next-day"].metadata.output_contract, "next_day_plan_v1")
        self.assertEqual(definitions["update-memory"].metadata.output_contract, "memory_update_plan_v1")

    def test_rating_skills_have_required_output_contract_fields(self):
        for command in ("judge-target", "judge-buy", "judge-sell"):
            definition = load_skill(PROJECT_ROOT, command)

            self.assertEqual(definition.metadata.output_contract, "rating_result_v1")
            self.assertIn("rule_matches", definition.body)
            self.assertIn("bonus_matches", definition.body)
            self.assertIn("vetoes", definition.body)
            self.assertIn("missing_evidence", definition.body)

    def test_target_skill_contains_user_rules_and_bonus_items(self):
        body = load_skill(PROJECT_ROOT, "judge-target").body

        self.assertIn("主线大题材", body)
        self.assertIn("营收和利润", body)
        self.assertIn("股性不好", body)
        self.assertIn("行业排名", body)
        self.assertIn("硬逻辑", body)
        self.assertIn("筹码峰", body)
        self.assertIn("盈利结构健康", body)

    def test_buy_skill_contains_all_prohibition_rules(self):
        body = load_skill(PROJECT_ROOT, "judge-buy").body

        for phrase in (
            "下跌中继",
            "连板异动",
            "高位平台初期",
            "中途追高",
            "大盘处于大跌",
            "上午开盘时或下午开盘时",
            "第三波",
            "高位长上影",
            "重点关注池",
            "至少保留 30% 现金",
            "同一题材板块买多只",
        ):
            self.assertIn(phrase, body)

    def test_sell_skill_contains_hold_and_must_sell_rules(self):
        body = load_skill(PROJECT_ROOT, "judge-sell").body

        for phrase in (
            "还在走趋势",
            "开盘一字",
            "主线轮动题材",
            "黑天鹅事件",
            "买点极差",
            "资金抛弃",
            "清仓止盈",
        ):
            self.assertIn(phrase, body)

    def test_execution_packet_reports_missing_inputs(self):
        packet = build_execution_packet(
            PROJECT_ROOT,
            "judge-target",
            symbol_or_name="NVDA",
            provided_inputs={"quote_snapshot": {"symbol": "NVDA"}},
        )

        self.assertEqual(packet.request.command, "judge-target")
        self.assertIn("user_profile", packet.missing_inputs)
        self.assertIn("watchlist_status", packet.missing_inputs)
        self.assertIn("# Skill Execution Packet: target_screening", packet.prompt)
        self.assertIn("symbol_or_name", packet.provided_inputs)

    def test_metadata_parser_rejects_missing_required_keys(self):
        with self.assertRaises(SkillError):
            parse_skill_metadata(
                "<!-- skill-metadata\nskill_id: broken\ncommand: judge-target\n-->\n# Broken"
            )


if __name__ == "__main__":
    unittest.main()

