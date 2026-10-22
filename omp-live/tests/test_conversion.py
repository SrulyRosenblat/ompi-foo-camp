"""The real wiki-to-OMP path used by the automatic dashboard."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from omp_live.cli import build
from omp_live.model import validate


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sync = build(Path(self.tmp.name))
        self.wiki = self.sync.systems['wiki']

    def test_minimal_record_has_no_required_creation_time(self):
        record = {'identifier': 'MEMORY.md', 'media_type': 'text/markdown',
                  'body': 'The user prefers concise answers.', 'attributes': {}}
        self.assertEqual(validate(record), [])
        self.assertTrue(validate({**record, 'attributes': []}))

    def test_markdown_targets_reach_graph_and_search(self):
        self.wiki.write_page('agent/vegan.md', '# Vegan\n\nThe user eats vegan.')
        self.wiki.write_page('agent/kosher.md', '# Kosher\n\nThe user eats kosher.')
        body = '# Dislikes sushi\n\nThe user does not like sushi.\nRelated: [Vegan](vegan.md), [Kosher](kosher.md).\n`[Example](not-a-link.md)`\n![Image](photo.png)'
        self.wiki.write_page('agent/dislikes-sushi.md', body)
        self.sync.reconcile()
        record = self.sync.export.get('agent/dislikes-sushi.md')
        self.assertEqual(record['body'], body)
        self.assertEqual(record['attributes'], {})
        self.assertNotIn('created_at', record)
        self.assertEqual([link['target'] for link in record['links']],
                         ['agent/vegan.md', 'agent/kosher.md'])
        edges = self.sync.systems['graph'].snapshot()['edges']
        self.assertEqual({e['dst'] for e in edges if e['src'] == record['identifier'] and e['carrier'] == 'inline'},
                         {'agent/vegan.md', 'agent/kosher.md'})
        self.assertIn(record['identifier'], [hit['identifier'] for hit in self.sync.systems['search'].search('sushi')])
        self.assertEqual(self.sync.reconcile(), 0)

    def test_queued_events_keep_their_own_revision(self):
        self.wiki.write_page('agent/note.md', '# First\n\nOriginal body.')
        self.sync.reconcile()
        first = next(e for e in self.sync.events if e['kind'] == 'exported')
        self.wiki.write_page('agent/note.md', '# Second\n\nUpdated body.')
        self.sync.reconcile()
        second = [e for e in self.sync.events if e['kind'] == 'exported'][-1]
        self.assertEqual(first['record']['body'], '# First\n\nOriginal body.')
        self.assertEqual(second['record']['body'], '# Second\n\nUpdated body.')
        self.assertNotEqual(first['record']['checksum'], second['record']['checksum'])
        self.assertEqual(first['identifier'], second['identifier'])

    def test_existing_identity_and_known_date_survive(self):
        self.wiki.write_page('old.md', '---\nidentifier: existing-id\ncreated_at: 2025-01-01T00:00:00Z\n---\n\nKnown date.')
        self.sync.reconcile()
        record = self.sync.export.get('existing-id')
        self.assertEqual(record['created_at'], '2025-01-01T00:00:00Z')
        self.assertEqual(record['path'], 'old.md')


if __name__ == '__main__':
    unittest.main()
