"""Real MCP initialization/tool calls over Streamable HTTP and stdio."""
import asyncio
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from omp_live.cli import build, index_server
from omp_live.httpkit import serve_in_thread
from omp_live.memory_service import MemoryService
from omp_live.mcp_server import start_http


def payload(result):
    if result.isError:
        raise AssertionError(str(result.content))
    return result.structuredContent or json.loads(result.content[0].text)


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_transports_share_the_live_search_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            sync = build(Path(tmp))
            service = MemoryService(sync)
            site = index_server(sync, 0, service=service)
            serve_in_thread(site)
            self.addCleanup(site.server_close)
            self.addCleanup(site.shutdown)
            site_url = f'http://127.0.0.1:{site.server_address[1]}'
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            mcp = start_http(service, port)
            try:
                async with streamable_http_client(f'http://127.0.0.1:{port}/mcp') as (read, write, _):
                    async with ClientSession(read, write) as client:
                        await client.initialize()
                        tools = await client.list_tools()
                        self.assertEqual({t.name for t in tools.tools},
                                         {'add_memory', 'update_memory', 'supersede_memory', 'get_memory', 'search_memories', 'list_folders', 'move_memory', 'about_omp'})
                        info = await client.initialize()
                        self.assertIn('Open Memory Protocol Initiative', info.instructions)
                        overview = payload(await client.call_tool('about_omp', {}))
                        self.assertIn('OMPI', overview['summary'])
                        self.assertIn('ompi', overview['topics'])
                        self.assertEqual(overview['repository'], 'https://github.com/The-AI-Disclosures-Project/Open-Memory-Protocol')
                        record_topic = payload(await client.call_tool('about_omp', {'topic': 'record'}))
                        self.assertIn('identifier, media_type, body and attributes', record_topic['text'])
                        resource = await client.read_resource('omp://about')
                        self.assertIn('Open-Memory-Protocol', resource.contents[0].text)
                        target = payload(await client.call_tool('add_memory', {'body': '# Transport target', 'path': 'team/target.md'}))
                        start = sync._seq
                        added = payload(await client.call_tool('add_memory', {
                            'body': 'A memory created over MCP HTTP.', 'title': 'MCP transport example',
                            'links': [{'target': target['identifier'], 'rel': 'derived_from'}]}))
                        self.assertTrue(added['path'].startswith('uncategorized/'))
                        self.assertEqual(added['links'][0]['target'], target['identifier'])
                        self.assertTrue(all(not event['animate'] for event in sync.events_since(start)))
                        results = payload(await client.call_tool('search_memories', {'query': 'created'}))
                        self.assertEqual(results['items'][0]['memory']['identifier'], added['identifier'])
                        changed = payload(await client.call_tool('update_memory', {'identifier': added['identifier'],
                                               'body': 'Changed over MCP HTTP.', 'if_version': added['version']['value']}))
                        moved = payload(await client.call_tool('move_memory', {'identifier': added['identifier'], 'path': 'team/mcp.md'}))
                        self.assertEqual(moved['memory']['identifier'], added['identifier'])
                        self.assertEqual(moved['memory']['path'], 'team/mcp.md')
                        self.assertEqual(service.get_memory(added['identifier'])['body'], changed['body'])
                        self.assertIn('team', payload(await client.call_tool('list_folders'))['folders'])
                        error = await client.call_tool('add_memory', {'body': 'No overwrite', 'path': 'team/target.md'})
                        self.assertTrue(error.isError)
                        previous_version = moved['memory']['version']['value']
                        replaced = payload(await client.call_tool('supersede_memory', {
                            'identifier': added['identifier'], 'body': 'Explicit replacement over MCP.',
                            'reason': 'correction', 'contributor': {'id': 'user:test', 'kind': 'human'},
                            'if_version': previous_version}))
                        self.assertEqual(replaced['links'][-1]['rel'], 'supersedes')
                        historical = payload(await client.call_tool('get_memory', {
                            'identifier': added['identifier'], 'version': previous_version}))
                        self.assertEqual(historical['body'], changed['body'])
                        historical_hits = payload(await client.call_tool('search_memories', {
                            'query': 'Changed', 'include_history': True}))
                        self.assertTrue(historical_hits['items'])
                env = dict(os.environ, PYTHONPATH=str(BASE))
                process = StdioServerParameters(command=sys.executable, args=['-m', 'omp_live.cli', 'mcp', '--site', site_url], env=env)
                async with stdio_client(process) as (read, write):
                    async with ClientSession(read, write) as client:
                        await client.initialize()
                        record = payload(await client.call_tool('get_memory', {'identifier': added['identifier']}))
                        self.assertEqual(record['path'], 'team/mcp.md')
                        created = payload(await client.call_tool('add_memory', {'body': 'An item from the stdio bridge.'}))
                        self.assertEqual(service.get_memory(created['identifier'])['body'], created['body'])
                        self.assertEqual(sync.reconcile(), 0)
            finally:
                mcp.should_exit = True
                await asyncio.sleep(.2)


if __name__ == '__main__':
    unittest.main()
