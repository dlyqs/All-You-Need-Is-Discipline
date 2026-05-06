from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DocsTest(unittest.TestCase):
    def test_ai_tool_entry_files_exist(self):
        self.assertTrue((PROJECT_ROOT / "AGENTS.md").exists())
        self.assertTrue((PROJECT_ROOT / "CLAUDE.md").exists())
        self.assertTrue((PROJECT_ROOT / ".cursor" / "rules" / "trading-agent.mdc").exists())

    def test_agents_entry_describes_natural_language_workflow(self):
        text = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")

        self.assertIn("natural language", text)
        self.assertIn("Do not make the user manually run CLI commands", text)
        self.assertIn("update-memory", text)
        self.assertIn("judge-target", text)
        self.assertIn("judge-sell", text)
        self.assertIn("plan-next-day", text)

    def test_readme_explains_ai_tool_usage_and_testing(self):
        text = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("Codex", text)
        self.assertIn("Cursor", text)
        self.assertIn("Claude Code", text)
        self.assertIn("Agent Entry", text)
        self.assertIn("Module Test Checklist", text)


if __name__ == "__main__":
    unittest.main()

