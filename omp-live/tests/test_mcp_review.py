"""Fixes from the MCP review: lean results, stable if_version, contributors, validation, merges, errors."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mcp.server.fastmcp.exceptions import ToolError

from omp_live import embedding
from omp_live.cli import build
from omp_live.mcp_server import create_mcp
from omp_live.memory_service import MemoryService
from test_embedding import FakeEmbedder


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sync = build(self.root)
        self.search = self.sync.systems["search"]
        self.search.embedder = FakeEmbedder()
        self.service = MemoryService(self.sync)

    def embed(self):
        while self.search.embed_pending() or self.sync.reconcile():
            pass

    def test_results_describe_but_do_not_carry_the_vector(self):
        m = self.service.add_memory("# Coffee\n\nBlack coffee.")
        self.embed()
        got = self.service.get_memory(m["identifier"])
        self.assertEqual(got["attributes"]["embedding"]["model"], "test/fake-embedding")
        self.assertNotIn("vector", got["attributes"]["embedding"])
        hit = self.service.search_memories("coffee")["items"][0]["memory"]
        self.assertNotIn("vector", hit["attributes"]["embedding"])
        self.assertTrue(embedding.carried(self.sync.export.get(m["identifier"])), "the export still has it")

    def test_if_version_survives_an_embedding_only_revision(self):
        m = self.service.add_memory("# Coffee\n\nBlack coffee.")
        self.embed()
        # Adding the vector is bookkeeping: it keeps the version, so one change never reads as two.
        self.assertEqual(self.service.get_memory(m["identifier"])["version"]["value"], m["version"]["value"])
        updated = self.service.update_memory(m["identifier"], body="# Coffee\n\nBlack coffee, no sugar.",
                                             if_version=m["version"]["value"])
        self.assertIn("no sugar", updated["body"])
        with self.assertRaisesRegex(ValueError, "changed since version"):
            self.service.update_memory(m["identifier"], body="# Coffee\n\nTea.", if_version=m["version"]["value"])

    def test_contributor_is_credited_and_system_entries_do_not_repeat(self):
        m = self.service.add_memory("A note.", contributor="agent:claude-code")
        for i in range(3):
            m = self.service.update_memory(m["identifier"], body=f"A note, edit {i}.", contributor={"id": "user:ana", "name": "Ana"})
        prov = m["provenance"]
        self.assertIn({"id": "agent:claude-code", "kind": "agent", "contribution": "authored"},
                      [{k: p[k] for k in ("id", "kind", "contribution")} for p in prov])
        self.assertTrue(any(p["id"] == "user:ana" and p["kind"] == "human" and p.get("name") == "Ana" for p in prov))
        system = [(p["id"], p["contribution"]) for p in prov if p["kind"] == "system"]
        self.assertEqual(len(system), len(set(system)), system)
        with self.assertRaisesRegex(ValueError, "contributor"):
            self.service.add_memory("x", contributor={"kind": "human"})

    def test_bad_values_are_rejected(self):
        for kwargs, message in [({"body": ""}, "body"), ({"body": "   "}, "body"), ({"body": "x", "title": ""}, "title"),
                                ({"body": "x", "valid_until": "soon"}, "valid_until"),
                                ({"body": "x", "media_type": "banana"}, "media_type"),
                                ({"body": "x", "tags": ["ok", ""]}, "tags")]:
            with self.assertRaisesRegex(ValueError, message):
                self.service.add_memory(**kwargs)
        m = self.service.add_memory("x", valid_until="2099-01-01")
        self.assertEqual(m["valid_until"], "2099-01-01")
        with self.assertRaisesRegex(ValueError, "body"):
            self.service.update_memory(m["identifier"], body="")

    def test_attributes_merge_and_title_follows_heading(self):
        m = self.service.add_memory("# Alpha\n\nText.", attributes={"fictional": True, "source": "test"})
        m = self.service.update_memory(m["identifier"], attributes={"note": "x", "source": None})
        self.assertEqual(m["attributes"], {"fictional": True, "note": "x"})
        m = self.service.update_memory(m["identifier"], body="# Beta\n\nText.")
        self.assertEqual(m["title"], "Beta")
        m = self.service.update_memory(m["identifier"], title="Custom")
        m = self.service.update_memory(m["identifier"], body="# Gamma\n\nText.")
        self.assertEqual(m["title"], "Custom", "an explicit title is not overwritten")

    def test_history_items_match_current_shape(self):
        m = self.service.add_memory("# Telescope\n\nThe telescope.")
        self.service.update_memory(m["identifier"], body="# Telescope\n\nThe telescope, cleaned.")
        items = self.service.search_memories("telescope", include_history=True)["items"]
        self.assertEqual(sorted(i["version"] for i in items), [1, 2])
        for i in items:
            self.assertEqual(i["match"], "keyword")
            self.assertGreaterEqual(i["score"], 0)  # higher is better, like current search
            self.assertIn("telescope", i["snippet"].lower())

    def test_move_prunes_empty_folder_and_errors_are_specific(self):
        m = self.service.add_memory("# Pavo", path="crew/pavo.md")
        self.service.move_memory(m["identifier"], "robots/pavo.md")
        self.assertNotIn("crew", self.service.list_folders()["folders"])
        with self.assertRaisesRegex(ValueError, "now at 'robots/pavo.md'"):
            self.service.add_memory("# Another", path="crew/pavo.md")
        with self.assertRaisesRegex(ValueError, "No memory with identifier"):
            self.service.get_memory("nope", version=1)

    def test_mcp_rejects_unknown_and_mistyped_arguments(self):
        mcp = create_mcp(self.service, 0)

        async def call(name, args):
            return await mcp.call_tool(name, args)

        with self.assertRaisesRegex(ToolError, "no argument 'folder', 'tag'"):
            asyncio.run(call("add_memory", {"body": "typo", "tag": ["x"], "folder": "f"}))
        with self.assertRaisesRegex(ToolError, "Invalid arguments for add_memory: tags"):
            asyncio.run(call("add_memory", {"body": "x", "tags": "not-a-list"}))
        result = asyncio.run(call("add_memory", {"body": "fine", "contributor": "agent:test"}))
        payload = json.loads(result[0].text) if isinstance(result, list) else result
        self.assertTrue(any(p["id"] == "agent:test" for p in payload["provenance"]))


if __name__ == "__main__":
    unittest.main()
