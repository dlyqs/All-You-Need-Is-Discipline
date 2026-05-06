import json
import unittest

from trading_agent.report import format_agent_packet, packet_to_json


class ReportPacketTest(unittest.TestCase):
    def test_formats_setup_and_skill_prompt(self):
        packet = {
            "status": "needs_setup",
            "command": "judge-target",
            "symbol_or_name": "NVDA",
            "setup_questions": [{"area": "user_profile", "question": "补充背景"}],
            "quote_snapshots": [
                {
                    "symbol": "NVDA",
                    "market": "US",
                    "latest_price": 100.0,
                    "change_pct": 1.2,
                    "intraday_shape": "走强",
                    "missing_fields": ["turnover_rate"],
                }
            ],
            "skill_packet": {
                "skill_id": "target_screening",
                "output_contract": "rating_result_v1",
                "missing_inputs": [],
                "prompt": "# Skill Execution Packet: target_screening",
            },
        }

        text = format_agent_packet(packet)

        self.assertIn("# Trading Agent Packet", text)
        self.assertIn("补充背景", text)
        self.assertIn("NVDA US latest=100.0", text)
        self.assertIn("```markdown", text)

    def test_packet_to_json_keeps_chinese(self):
        encoded = packet_to_json({"status": "ready", "message": "补充背景"})

        self.assertEqual(json.loads(encoded)["message"], "补充背景")
        self.assertIn("补充背景", encoded)


if __name__ == "__main__":
    unittest.main()

