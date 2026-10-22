"""Explicit replacement edges, current reads, and retained non-Markdown revisions."""
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from omp_live.cli import build
from omp_live.memory_service import MemoryService
from omp_live.model import checksum, validate, version_value


class SupersessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sync = build(Path(self.tmp.name))
        self.service = MemoryService(self.sync)

    def add(self, identifier, body, **kwargs):
        return self.service.add_memory(body, identifier=identifier, **kwargs)

    def test_ordinary_edits_keep_history_without_claiming_replacement(self):
        first = self.add('note', 'Original wording')
        second = self.service.update_memory('note', body='Later wording')
        self.assertFalse(any(l.get('rel') == 'supersedes' for l in second.get('links', [])))
        self.assertEqual(self.service.get_memory('note', version=version_value(first))['body'], first['body'])
        self.assertEqual(self.service.get_memory('note')['body'], second['body'])
        for name in ('search', 'graph'):
            self.assertEqual({r['body'] for r in self.sync.systems[name].history('note')}, {'Original wording', 'Later wording'})

    def test_explicit_revision_replacement_keeps_old_body_and_context(self):
        first = self.add('preference', 'The user eats fish.')
        start = self.sync._seq
        second = self.service.supersede_memory('preference', 'The user is vegan.', 'correction', {'id': 'user:actual', 'kind': 'human'})
        link = next(l for l in second['links'] if l['rel'] == 'supersedes')
        self.assertEqual(link, {'target': 'preference', 'version': version_value(first), 'rel': 'supersedes',
                                'reason': 'correction', 'contributor': {'id': 'user:actual', 'kind': 'human'}})
        self.assertNotIn('evidence', second)
        self.assertEqual(self.service.search_memories('fish')['items'], [])
        self.assertEqual(self.service.search_memories('fish', include_history=True)['items'][0]['memory']['body'], first['body'])
        self.assertEqual(self.service.get_memory('preference')['body'], second['body'])
        self.assertTrue(all(not e['animate'] for e in self.sync.events_since(start)))
        graph = self.sync.systems['graph'].snapshot(include_history=True)
        self.assertTrue(any(e['target'] == 'preference' and e['version'] == 1 and e['source']['version'] == 2 for e in graph['revision_edges']))
        self.assertFalse(any(e['rel'] == 'supersedes' for e in self.sync.systems['graph'].snapshot()['edges']))
        self.assertEqual(next(n for n in self.sync.systems['graph'].snapshot()['nodes'] if n['id'] == 'preference')['revision_links'], second['links'])
        path = self.sync.root / 'wiki' / second['path']
        self.assertIn('The user is vegan.', path.read_text())
        self.assertNotIn('The user eats fish.', path.read_text())

    def test_cross_memory_edges_hide_only_the_targeted_revision(self):
        old = self.add('old', 'Old assertion about Tuesday.')
        new = self.add('new', 'The corrected assertion is Friday.', links=[{'target': 'old', 'rel': 'supersedes',
                        'reason': 'update', 'contributor': 'user:editor'}])
        self.assertEqual(new['links'][0]['version'], version_value(old))
        with self.assertRaisesRegex(ValueError, 'superseded'):
            self.service.get_memory('old')
        self.assertEqual(self.service.get_memory('old', include_history=True)['body'], old['body'])
        self.assertEqual(self.service.search_memories('Tuesday')['items'], [])
        self.assertNotIn('old', {r['identifier'] for r in self.sync.systems['search'].docs()})
        self.assertNotIn('old', {r['id'] for r in self.sync.systems['graph'].snapshot()['nodes']})
        self.assertTrue((self.sync.root/'wiki'/old['path']).exists())
        # A specifically targeted old revision never silently retires a later revision.
        self.service.update_memory('old', body='An independently revised assertion.')
        self.assertEqual(self.service.get_memory('old')['body'], 'An independently revised assertion.')

    def test_expired_records_require_explicit_history(self):
        old = self.add('expired', 'Expired fact', valid_until='2000-01-01T00:00:00Z')
        self.assertEqual(self.service.search_memories()['items'], [])
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.service.get_memory('expired')
        self.assertEqual(self.service.get_memory('expired', version=version_value(old))['body'], old['body'])
        self.assertEqual(len(self.sync.systems['search'].docs(include_history=True)), 1)

    def test_missing_context_rejected_for_new_authored_replacements(self):
        self.add('old', 'Old fact')
        for reason, contributor in [('', 'user:editor'), ('correction', {})]:
            with self.assertRaises(ValueError):
                self.service.supersede_memory('old', 'Corrected fact', reason, contributor)
        self.assertEqual(self.service.get_memory('old')['body'], 'Old fact')
        record = {'identifier': 'r', 'media_type': 'text/plain', 'body': 'Fact', 'attributes': {},
                  'links': [{'target': 'old', 'rel': 'supersedes', 'reason': 'correction'}]}
        self.assertEqual(validate(record), [])
        self.assertIn('audit supersedes edges must name a contributor', validate(record, audit=True))
        manifest = self.sync.export.manifest()
        manifest['profiles'] = ['audit']
        self.sync.export._write_json(self.sync.export.manifest_path, manifest)
        self.assertEqual(self.sync.seed([record]), 0)

    def test_conflicting_reverse_pointer_is_reported_without_picking(self):
        base = {'media_type': 'text/plain', 'attributes': {}}
        a = dict(base, identifier='a', body='A', version={'value': 1}, invalidated_by='c')
        b = dict(base, identifier='b', body='B', version={'value': 1}, links=[{
            'target': 'a', 'version': 1, 'rel': 'supersedes', 'reason': 'correction', 'contributor': 'user:editor'}])
        self.sync.seed([a, b])
        self.assertTrue(any('invalidated_by disagree' in r.get('reason', '') for r in self.sync.export.receipts()))
        self.assertEqual(self.service.get_memory('a')['invalidated_by'], 'c')
        self.assertEqual(self.service.get_memory('b')['links'][0]['target'], 'a')

    def test_forget_purges_history_and_rebuild_restores_retained_revisions(self):
        self.add('note', 'Before')
        self.service.supersede_memory('note', 'After', 'correction', 'user:editor')
        self.sync.rebuild('search')
        self.assertEqual(len(self.sync.systems['search'].history('note')), 2)
        self.sync.forget('note')
        self.assertEqual(self.sync.export.revisions('note'), [])
        for name in ('search', 'graph'):
            self.assertEqual(self.sync.systems[name].history('note'), [])
        with self.assertRaises(ValueError):
            self.service.get_memory('note', version=1)

    def test_restart_refreshes_legacy_source_revision_metadata(self):
        self.add('note', 'Before')
        canonical = self.service.supersede_memory('note', 'After', 'correction', 'user:editor')
        stale = dict(canonical, version={'value': 1, 'comparator': 'integer'})
        graph = self.sync.systems['graph']
        graph.import_(stale)
        self.sync.held['graph']['note'] = checksum(graph.export_one('note'))
        self.sync._save_state()
        restarted = build(self.sync.root)
        restarted.reconcile()
        self.assertEqual(version_value(restarted.export.get('note')), 2)
        node = next(n for n in restarted.systems['graph'].snapshot()['nodes'] if n['id'] == 'note')
        self.assertEqual(node['version'], 2)


if __name__ == '__main__':
    unittest.main()
