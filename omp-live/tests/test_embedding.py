"""Search embeds memories, the export carries the vector, the wiki drops it."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from omp_live import embedding
from omp_live.cli import build


class FakeEmbedder:
    """Deterministic vectors: one dimension per topic word."""
    model = "test/fake-embedding"
    TOPICS = ["coffee", "cat", "telescope", "drink"]

    def __init__(self):
        self.calls = 0

    def embed(self, texts, timeout=30):
        self.calls += 1
        out = []
        for t in texts:
            t = t.lower()
            v = [float(t.count(w)) for w in self.TOPICS]
            if "espresso" in t or "coffee" in t:
                v[3] += 1  # both are drinks
            out.append(v if any(v) else [0.0, 0.0, 0.0, 0.01])
        return out


class EmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sync = build(self.root)
        self.search = self.sync.systems["search"]
        self.search.embedder = FakeEmbedder()  # no thread: drive embed_pending() by hand
        self.wiki = self.root / "wiki"
        (self.wiki / "coffee.md").write_text("# Coffee\n\nJuniper drinks black coffee.\n")
        (self.wiki / "cat.md").write_text("# Moss\n\nMoss the cat sleeps in the dome.\n")
        self.sync.reconcile()
        self.ids = {r["path"]: r["identifier"] for r in self.sync.export.all()}

    def settle(self):
        while self.search.embed_pending() or self.sync.reconcile():
            pass

    def test_vector_reaches_export_but_not_markdown(self):
        start = self.sync._seq
        self.settle()
        record = self.sync.export.get(self.ids["coffee.md"])
        emb = embedding.carried(record)
        self.assertEqual(emb["model"], "test/fake-embedding")
        self.assertEqual(emb["dimensions"], 4)
        self.assertTrue(embedding.valid(record))
        self.assertTrue(any(p.get("id") == "system:search" for p in record["provenance"]))
        self.assertTrue(embedding.carried(self.sync.systems["graph"].export_one(record["identifier"])))
        self.assertNotIn("vector", (self.wiki / "coffee.md").read_text())
        self.assertNotIn("embedding", (self.wiki / "coffee.md").read_text())
        added = [e for e in self.sync.events_since(start) if e["kind"] == "exported" and e["system"] == "search"]
        self.assertTrue(added and not any(e["animate"] for e in added))  # bookkeeping is not animated
        self.assertEqual(self.sync.reconcile(), 0)

    def test_wiki_edit_keeps_vector_unless_text_changes(self):
        self.settle()
        calls = self.search.embedder.calls
        path = self.wiki / "coffee.md"
        text = path.read_text().replace("tags:", "tags:\n- drink", 1) if "tags:" in path.read_text() \
            else path.read_text().replace("---\n", "---\ntags: [drink]\n", 1)
        path.write_text(text)
        self.settle()
        record = self.sync.export.get(self.ids["coffee.md"])
        self.assertIn("drink", record["tags"])
        self.assertTrue(embedding.valid(record), "a tag-only edit keeps the vector")
        self.assertEqual(self.search.embedder.calls, calls, "and does not re-embed")

        path.write_text(path.read_text().replace("black coffee", "black coffee with cardamom"))
        self.settle()
        record = self.sync.export.get(self.ids["coffee.md"])
        self.assertIn("cardamom", record["body"])
        self.assertTrue(embedding.valid(record), "a text edit gets a fresh vector")
        self.assertGreater(self.search.embedder.calls, calls)

    def test_search_finds_by_meaning(self):
        self.settle()
        hits = self.search.search("espresso")
        self.assertEqual(hits[0]["identifier"], self.ids["coffee.md"])
        self.assertEqual(hits[0]["match"], "meaning")
        both = self.search.search("coffee")
        self.assertEqual(both[0]["match"], "both")

    def test_without_embedder_search_is_keywords_only(self):
        self.search.embedder = None
        hits = self.search.search("coffee")
        self.assertEqual([h["match"] for h in hits], ["keyword"])
        self.assertEqual(self.search.search("espresso"), [])


if __name__ == "__main__":
    unittest.main()
