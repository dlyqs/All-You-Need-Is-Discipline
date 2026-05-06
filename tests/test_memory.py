from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import unittest

from trading_agent.memory import (
    MEMORY_FILENAMES,
    MemoryError,
    parse_memory_table,
    read_memory_bundle,
    read_memory_file,
    upsert_memory_table_row,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class MemoryTest(unittest.TestCase):
    def test_repo_has_only_three_planned_memory_files(self):
        memory_root = PROJECT_ROOT / "memory"
        filenames = tuple(sorted(path.name for path in memory_root.glob("*.md")))

        self.assertEqual(filenames, tuple(sorted(MEMORY_FILENAMES)))
        self.assertFalse((memory_root / "market_context.md").exists())
        self.assertFalse((memory_root / "decision_log.md").exists())

    def test_templates_have_required_table_columns(self):
        portfolio = parse_memory_table(PROJECT_ROOT, "portfolio.md")
        watchlist = parse_memory_table(PROJECT_ROOT, "watchlist.md")
        profile = parse_memory_table(PROJECT_ROOT, "user_profile.md")

        self.assertIn("buy_date", portfolio.headers)
        self.assertIn("buy_price", portfolio.headers)
        self.assertIn("thesis", portfolio.headers)
        self.assertIn("focus_pool", watchlist.headers)
        self.assertIn("invalidation", watchlist.headers)
        self.assertEqual(profile.headers, ("字段", "值", "备注"))

    def test_read_memory_bundle_reads_three_files(self):
        bundle = read_memory_bundle(PROJECT_ROOT)

        self.assertEqual(set(bundle), set(MEMORY_FILENAMES))
        self.assertIn("# 当前持仓组合", bundle["portfolio.md"])

    def test_rejects_unsupported_memory_file(self):
        with self.assertRaises(MemoryError):
            read_memory_file(PROJECT_ROOT, "market_context.md")

    def test_dry_run_upsert_does_not_write_and_preserves_notes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(PROJECT_ROOT / "memory", root / "memory")
            original = (root / "memory" / "portfolio.md").read_text(encoding="utf-8")

            result = upsert_memory_table_row(
                root,
                "portfolio.md",
                "symbol",
                {
                    "symbol": "NVDA",
                    "market": "US",
                    "name": "NVIDIA",
                    "quantity": "10",
                    "buy_date": "2026-05-06",
                    "buy_price": "196.5",
                    "theme": "AI",
                    "thesis": "AI 算力核心",
                },
                dry_run=True,
            )

            after = (root / "memory" / "portfolio.md").read_text(encoding="utf-8")
            self.assertTrue(result.changed)
            self.assertTrue(result.dry_run)
            self.assertIn("+| NVDA | US | NVIDIA | 10 | 2026-05-06 | 196.5", result.diff)
            self.assertIn("## 自由备注", result.new_text)
            self.assertEqual(after, original)

    def test_apply_upsert_writes_only_table_block(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(PROJECT_ROOT / "memory", root / "memory")

            result = upsert_memory_table_row(
                root,
                "watchlist.md",
                "symbol",
                {
                    "symbol": "600519",
                    "market": "A",
                    "name": "贵州茅台",
                    "theme": "白酒",
                    "priority": "low",
                    "focus_pool": "no",
                    "thesis": "测试观察",
                },
                dry_run=False,
            )

            written = (root / "memory" / "watchlist.md").read_text(encoding="utf-8")
            self.assertTrue(result.changed)
            self.assertIn("| 600519 | A | 贵州茅台 | 白酒 | low | no", written)
            self.assertIn("## 自由备注", written)

    def test_ambiguous_update_requires_key_value(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(PROJECT_ROOT / "memory", root / "memory")

            with self.assertRaises(MemoryError):
                upsert_memory_table_row(root, "portfolio.md", "symbol", {"market": "US"})


if __name__ == "__main__":
    unittest.main()

