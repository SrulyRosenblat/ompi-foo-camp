"""UI save preconditions protect drafts against concurrent changes."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from omp_live.cli import build
from omp_live.httpkit import serve_in_thread
from omp_live.memory_service import MemoryService
from omp_live.systems.wiki.serve import server


class UIWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sync = build(Path(self.tmp.name))
        self.service = MemoryService(self.sync)
        self.original = self.service.add_memory('Original body', path='note.md')
        self.server = server(self.sync.systems['wiki'], 0, sync=self.sync, service=self.service)
        serve_in_thread(self.server)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'

    def post(self, route, body):
        return urlopen(Request(self.url+route, data=json.dumps(body).encode(), headers={'Content-Type':'application/json'}))

    def test_stale_wiki_save_preserves_a_pending_external_edit(self):
        version = self.original['version']['value']
        self.sync.systems['wiki'].write_page('note.md', 'Changed in another editor')
        with self.assertRaises(HTTPError) as caught:
            self.post('/api/page', {'path':'note.md','body':'A stale draft','if_version':version})
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(self.service.get_memory('note.md')['body'], 'Changed in another editor')
        current = self.service.get_memory('note.md')['version']['value']
        with self.post('/api/page', {'path':'note.md','body':'A deliberate new edit','if_version':current}) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual(self.service.get_memory('note.md')['body'], 'A deliberate new edit')

    def test_new_page_does_not_overwrite_an_existing_path(self):
        with self.assertRaises(HTTPError) as caught:
            self.post('/api/new', {'path':'note.md','title':'Replacement','body':'Accidental overwrite'})
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(self.service.get_memory('note.md')['body'], 'Original body')


if __name__ == '__main__':
    unittest.main()
