"""Durable export snapshots, including legacy records and forget boundaries."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from omp_live.export_dir import ExportDir, safe_name
from omp_live.model import checksum, version_value, with_checksum


def memory(identifier="note", version=1, body="Original", **extra):
    return {"identifier": identifier, "media_type": "text/markdown",
            "body": body, "attributes": {},
            "version": {"value": version, "comparator": "integer"}, **extra}


class RevisionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "omp-export"
        self.export = ExportDir(self.root)

    def snapshots(self):
        return sorted((self.root / "revisions").glob("*.json"))

    def test_two_real_revisions_survive_restart_and_keep_latest_reads(self):
        first = self.export.put(memory())
        second = self.export.put(memory(version=2, body="Updated"))
        restarted = ExportDir(self.root)
        self.assertEqual(restarted.get_revision("note", 1), first)
        self.assertEqual(restarted.get_revision("note", 2), second)
        self.assertIsNone(restarted.get_revision("note", 3))
        self.assertIsNone(restarted.get_revision("missing", 1))
        self.assertEqual(restarted.revisions("note"), [first, second])
        self.assertEqual(restarted.get("note"), second)
        self.assertEqual(restarted.all(), [second])
        self.assertEqual(restarted.list_ids(), ["note"])
        self.assertEqual(len(list((self.root / "memories").glob("*.json"))), 1)
        self.assertNotIn("links", second)  # ordinary edits do not invent supersession

    def test_same_canonical_record_is_deduplicated_without_rewriting(self):
        stored = self.export.put(memory())
        path, = self.snapshots()
        original = (path.read_bytes(), path.stat().st_mtime_ns)
        reordered = dict(reversed(list(stored.items())))
        reordered["checksum"] = "a stale incoming checksum"
        self.assertEqual(self.export.put(reordered), stored)
        self.assertEqual(len(self.snapshots()), 1)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), original)
        self.assertEqual(self.export.revisions(), [stored])

    def test_same_version_metadata_variants_are_immutable_and_deterministic(self):
        first = self.export.put(memory())
        original_path, = self.snapshots()
        original_bytes = original_path.read_bytes()
        second = self.export.put(memory(x_conflicts=[{"system": "wiki"}]))
        history = self.export.revisions("note")
        self.assertEqual(len(self.snapshots()), 2)
        self.assertEqual(original_path.read_bytes(), original_bytes)
        self.assertEqual(history, sorted([first, second], key=checksum))
        self.assertEqual(self.export.get_revision("note", 1), history[-1])
        self.assertEqual(ExportDir(self.root).get_revision("note", 1), history[-1])

    def test_lossy_safe_names_have_separate_history_keys(self):
        self.assertEqual(safe_name("a/b"), safe_name("a_b"))
        first = self.export.put(memory("a/b", body="Slash identifier"))
        second = self.export.put(memory("a_b", body="Underscore identifier"))
        self.assertEqual(len(self.snapshots()), 2)
        restarted = ExportDir(self.root)
        self.assertEqual(restarted.revisions("a/b"), [first])
        self.assertEqual(restarted.revisions("a_b"), [second])
        self.assertEqual(restarted.revisions(), [first, second])
        restarted.forget("a/b", by="test", reason="Erase slash identifier")
        self.assertEqual(restarted.revisions("a/b"), [])
        self.assertEqual(restarted.revisions("a_b"), [second])

    def test_legacy_lookup_includes_current_without_inventing_earlier_versions(self):
        legacy = memory(version=7, body="Only surviving legacy revision")
        path = self.root / "memories" / "note.json"
        path.write_text(json.dumps(legacy))
        self.assertEqual(self.export.revisions(), [legacy])
        self.assertEqual(self.export.revisions("note"), [legacy])
        self.assertEqual(self.export.get_revision("note", 7), legacy)
        self.assertIsNone(self.export.get_revision("note", 6))
        self.assertEqual(self.snapshots(), [])

    def test_first_write_archives_legacy_latest_before_replacing_it(self):
        legacy = memory(version=7, body="Legacy body")
        (self.root / "memories" / "note.json").write_text(json.dumps(legacy))
        latest = self.export.put(memory(version=8, body="New body"))
        restarted = ExportDir(self.root)
        self.assertEqual(restarted.get_revision("note", 7), with_checksum(legacy))
        self.assertEqual(restarted.get_revision("note", 8), latest)
        self.assertEqual(len(self.snapshots()), 2)
        self.assertIsNone(restarted.get_revision("note", 6))

    def test_history_sorts_by_identifier_numeric_version_and_checksum(self):
        for record in (memory("z", 1), memory("a", 10), memory("a", 2),
                       memory("a", 2, title="Metadata variant")):
            self.export.put(record)
        history = self.export.revisions()
        self.assertEqual([(r["identifier"], version_value(r)) for r in history],
                         [("a", 2), ("a", 2), ("a", 10), ("z", 1)])
        self.assertEqual(history, sorted(history, key=lambda r: (
            r["identifier"], version_value(r), checksum(r))))

    def test_remove_retains_history_without_creating_a_tombstone(self):
        stored = self.export.put(memory())
        self.export.remove("note")
        self.assertIsNone(self.export.get("note"))
        self.assertEqual(self.export.tombstones(), [])
        self.assertEqual(ExportDir(self.root).get_revision("note", 1), stored)

    def test_forget_purges_all_variants_and_tombstones_prevent_history_resurrection(self):
        self.export.put(memory(body="Secret original"))
        self.export.put(memory(body="Secret original", title="Secret title"))
        self.export.put(memory(version=2, body="Secret replacement"))
        other = self.export.put(memory("other", body="Unrelated"))
        saved = [(p.name, p.read_bytes()) for p in self.snapshots()
                 if json.loads(p.read_text())["identifier"] == "note"]
        self.assertEqual(len(saved), 3)
        tomb = self.export.forget("note", by="test", reason="Erase request")
        self.assertIsNone(self.export.get("note"))
        self.assertEqual([json.loads(p.read_text()) for p in self.snapshots()], [other])
        self.assertEqual(set(tomb), {"identifier", "origin", "forgotten_at", "by", "reason"})
        self.assertNotIn("Secret", json.dumps(self.export.tombstones()))
        restarted = ExportDir(self.root)
        self.assertEqual(restarted.revisions("note"), [])
        self.assertIsNone(restarted.get_revision("note", 1))
        # A stale external snapshot/latest copy must not bypass the tombstone.
        name, content = saved[0]
        (self.root / "revisions" / name).write_bytes(content)
        (self.root / "memories" / "note.json").write_bytes(content)
        self.assertEqual(restarted.revisions(), [other])
        self.assertIsNone(restarted.get_revision("note", 1))
        restarted.forget("note", by="test", reason="Repeat erasure")
        self.assertEqual([json.loads(p.read_text()) for p in self.snapshots()], [other])


if __name__ == "__main__":
    unittest.main()
