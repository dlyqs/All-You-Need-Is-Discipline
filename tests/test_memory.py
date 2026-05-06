from pathlib import Path
import unittest

from trading_agent.cli import MEMORY_FILENAMES, MemoryError, parse_memory_table, read_memory_bundle, read_memory_file


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class MemoryTest(unittest.TestCase):
    def test_repo_has_planned_memory_files(self):
        memory_root = PROJECT_ROOT / "memory"
        filenames = tuple(sorted(path.name for path in memory_root.glob("*.md")))

        self.assertEqual(filenames, tuple(sorted(MEMORY_FILENAMES)))
        self.assertFalse((memory_root / "market_context.md").exists())
        self.assertFalse((memory_root / "decision_log.md").exists())

    def test_templates_have_required_table_columns(self):
        portfolio = parse_memory_table(PROJECT_ROOT, "portfolio.md")
        watchlist = parse_memory_table(PROJECT_ROOT, "watchlist.md")

        self.assertIn("buy_date", portfolio.headers)
        self.assertIn("buy_price", portfolio.headers)
        self.assertIn("lots", portfolio.headers)
        self.assertIn("symbol", portfolio.headers)
        self.assertNotIn("cost", portfolio.headers)
        self.assertIn("focus_pool", watchlist.headers)
        self.assertIn("invalidation", watchlist.headers)

    def test_read_memory_bundle_reads_both_files(self):
        bundle = read_memory_bundle(PROJECT_ROOT)

        self.assertEqual(set(bundle), set(MEMORY_FILENAMES))
        self.assertIn("## 持仓表", bundle["portfolio.md"])

    def test_rejects_unsupported_memory_file(self):
        with self.assertRaises(MemoryError):
            read_memory_file(PROJECT_ROOT, "market_context.md")


if __name__ == "__main__":
    unittest.main()
