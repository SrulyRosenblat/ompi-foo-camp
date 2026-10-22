"""Search-origin MCP operations, stable identity, and global moves."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from omp_live.cli import build
from omp_live.memory_service import MemoryService
from omp_live.systems.wiki.adapter import split_front_matter


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sync = build(Path(self.tmp.name))
        self.service = MemoryService(self.sync)

    def test_search_add_is_silent_and_reaches_every_store(self):
        target = self.service.add_memory('# Related\n\nA related note.', path='team/related.md')
        start = self.sync._seq
        record = self.service.add_memory('The user dislikes sushi.', title='Sushi preference',
                                         links=[{'target': target['identifier'], 'rel': 'derived_from'}])
        self.assertTrue(record['path'].startswith('uncategorized/'))
        self.assertNotIn('created_at', record)
        self.assertEqual(record['attributes'], {})
        self.assertEqual(record['links'][0]['rel'], 'derived_from')
        self.assertEqual(self.service.search_memories('sushi')['items'][0]['memory']['identifier'], record['identifier'])
        for system in self.sync.systems.values():
            self.assertEqual(system.export_one(record['identifier'])['path'], record['path'])
        self.assertTrue((self.sync.root/'wiki'/record['path']).exists())
        self.assertTrue(all(not e['animate'] for e in self.sync.events_since(start)))
        self.assertTrue(any(e['kind']=='exported' and e['system']=='search' for e in self.sync.events_since(start)))
        self.assertTrue(any(e['dst']==target['identifier'] and e['rel']=='derived_from'
                            for e in self.sync.systems['graph'].snapshot()['edges']))
        self.assertEqual(self.sync.reconcile(), 0)

    def test_explicit_and_markdown_links_round_trip_on_update(self):
        a = self.service.add_memory('# A', path='team/a.md')
        b = self.service.add_memory('# B', path='team/b.md')
        record = self.service.add_memory('See [A](../team/a.md).', links=[{'target': b['identifier'], 'rel': 'contradicts'}])
        self.assertEqual({l['target'] for l in record['links']}, {a['identifier'], b['identifier']})
        record = self.service.update_memory(record['identifier'], body='No inline links now.')
        self.assertEqual(record['links'], [{'target': b['identifier'], 'rel': 'contradicts'}])
        record = self.service.update_memory(record['identifier'], links=[])
        self.assertNotIn('links', record)
        self.assertEqual(self.sync.reconcile(), 0)

    def test_move_rebases_both_directions_and_preserves_ids(self):
        sibling = self.service.add_memory('# Sibling', path='uncategorized/sibling.md')
        moved = self.service.add_memory('# Moved\n\nSee [Sibling](sibling.md).', path='uncategorized/moved.md')
        incoming = self.service.add_memory('Read [Moved](../uncategorized/moved.md#details).', path='team/incoming.md',
                                          links=[{'target': moved['identifier'], 'rel': 'derived_from'}])
        result = self.service.move_memory(moved['identifier'], 'projects/moved.md', actor='ui')
        self.assertEqual(result['memory']['identifier'], moved['identifier'])
        self.assertEqual(result['memory']['path'], 'projects/moved.md')
        self.assertIn('[Sibling](../uncategorized/sibling.md)', result['memory']['body'])
        self.assertIn('[Moved](../projects/moved.md#details)', self.service.get_memory(incoming['identifier'])['body'])
        self.assertFalse((self.sync.root/'wiki/uncategorized/moved.md').exists())
        self.assertTrue((self.sync.root/'wiki/projects/moved.md').exists())
        for system in self.sync.systems.values():
            record = system.export_one(moved['identifier'])
            self.assertEqual(record['path'], 'projects/moved.md')
            self.assertEqual(record['links'][0]['target'], sibling['identifier'])
        self.assertTrue(any(l.get('rel')=='derived_from' and l['target']==moved['identifier']
                            for l in self.service.get_memory(incoming['identifier'])['links']))
        self.assertEqual(self.sync.reconcile(), 0)
        self.assertEqual(self.sync.export.tombstones(), [])

    def test_collision_and_unsafe_paths_do_not_change_content(self):
        first = self.service.add_memory('First', path='one.md')
        second = self.service.add_memory('Second', path='two.md')
        for destination in ('two.md', '../outside.md', '/tmp/outside.md'):
            with self.assertRaises(ValueError):
                self.service.move_memory(first['identifier'], destination)
        self.assertEqual(self.service.get_memory(first['identifier'])['path'], 'one.md')
        self.assertEqual(self.service.get_memory(second['identifier'])['body'], 'Second')
        self.assertEqual(self.sync.export.tombstones(), [])
        with self.assertRaises(ValueError):
            self.service.add_memory('Invalid', path='../outside.md')

    def test_optimistic_updates_and_normal_ui_animation(self):
        record = self.service.add_memory('Original', path='item.md')
        self.service.update_memory(record['identifier'], body='MCP edit', if_version=record['version']['value'])
        with self.assertRaises(ValueError):
            self.service.update_memory(record['identifier'], body='Stale edit', if_version=record['version']['value'])
        start = self.sync._seq
        self.service.update_memory(record['identifier'], body='Human edit', actor='ui', animate=True)
        events = self.sync.events_since(start)
        self.assertTrue(events and all(e['animate'] for e in events))
        self.assertNotIn(record['identifier'], self.sync.silent_identifiers())

    def test_mcp_does_not_silence_unrelated_pending_ui_edits(self):
        self.sync.systems['wiki'].write_page('human.md', 'A human wiki edit.')
        start = self.sync._seq
        mcp = self.service.add_memory('An MCP write.')
        events = self.sync.events_since(start)
        self.assertTrue(all(e['animate'] for e in events if e['identifier']=='human.md'))
        self.assertTrue(all(not e['animate'] for e in events if e['identifier']==mcp['identifier']))


if __name__ == '__main__':
    unittest.main()
