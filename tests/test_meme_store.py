import json
import tempfile
import unittest
from pathlib import Path

from meme_store import MemeWikiStore, normalize_text


class MemeWikiStoreTests(unittest.TestCase):
    def test_normalization_and_fuzzy_search(self):
        self.assertEqual(normalize_text("  YＹＤＳ  "), "yyds")
        with tempfile.TemporaryDirectory() as directory:
            store = MemeWikiStore(Path(directory) / "wiki.json")
            store.upsert("YYDS", "永远的神", "夸赞某人或事物", aliases="yyds, 永神")
            self.assertEqual(store.search("yyds")[0].meaning, "永远的神")
            self.assertEqual(store.find_in_text("这波真的YYDS")[0].term, "YYDS")

    def test_persistence_and_atomic_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wiki.json"
            store = MemeWikiStore(path)
            store.upsert("破防", "心理防线被突破", "表示受到强烈冲击")
            reloaded = MemeWikiStore(path)
            self.assertEqual(reloaded.count(), 1)
            self.assertEqual(reloaded.search("破防")[0].usage, "表示受到强烈冲击")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 1)

    def test_entry_limit_evicts_oldest(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MemeWikiStore(Path(directory) / "wiki.json", max_entries=2)
            store.upsert("甲", "a")
            store.upsert("乙", "b")
            store.upsert("丙", "c")
            self.assertEqual(store.count(), 2)
            self.assertEqual(store.search("丙")[0].meaning, "c")


if __name__ == "__main__":
    unittest.main()
