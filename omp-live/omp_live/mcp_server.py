"""MCP tools for the live search store. HTTP is shared; stdio proxies the site."""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import ValidationError
from mcp.types import ToolAnnotations

from .about import REPO, SUMMARY, about


class RemoteMemoryService:
    """Keep all writers in the running site's process, including stdio clients."""
    def __init__(self, site='http://127.0.0.1:8700'):
        self.site = site.rstrip('/')

    def _request(self, route, values=None, *, read=False):
        url = self.site + '/api/memory/' + route
        if read:
            url += '?' + urlencode({k: v for k, v in (values or {}).items() if v is not None})
        data = None if read else json.dumps(values or {}).encode()
        request = Request(url, data=data, headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            try:
                message = json.load(error).get('error', str(error))
            except (ValueError, OSError):
                message = str(error)
            raise ValueError(message) from error

    def search_memories(self, **values):
        return self._request('search', values, read=True)

    def get_memory(self, identifier, version=None, include_history=False):
        return self._request('get', {'identifier': identifier, 'version': version, 'include_history': include_history}, read=True)

    def add_memory(self, **values):
        return self._request('add', values)

    def update_memory(self, **values):
        return self._request('update', values)

    def supersede_memory(self, **values):
        return self._request('supersede', values)

    def move_memory(self, **values):
        return self._request('move', values)

    def list_folders(self):
        return self._request('folders', read=True)


class StrictMCP(FastMCP):
    """Reject misspelled arguments instead of ignoring them, and explain bad ones in plain words."""

    async def call_tool(self, name, arguments):
        tool = self._tool_manager.get_tool(name)
        if tool is not None:
            known = set(tool.parameters.get('properties', {}))
            unknown = sorted(set(arguments or {}) - known)
            if unknown:
                raise ToolError(f'{name} has no argument {", ".join(map(repr, unknown))}; '
                                f'its arguments are {", ".join(sorted(known))}')
            try:
                tool.fn_metadata.arg_model.model_validate(arguments or {})
            except ValidationError as e:
                problems = '; '.join(f'{".".join(map(str, err["loc"])) or "arguments"}: {err["msg"]}' for err in e.errors())
                raise ToolError(f'Invalid arguments for {name}: {problems}') from None
        return await super().call_tool(name, arguments)


def create_mcp(service, port=8705, host=None):
    host = host or os.environ.get('OMP_HOST', '127.0.0.1')
    mcp = StrictMCP(
        'OMP Memory',
        instructions=(SUMMARY + ' Call about_omp for details on OMP, OMPI, the record format, lifecycle and open issues. '
                      'Read and write the live search index. Writes synchronize through OMP into the wiki and graph '
                      'without playing site animations. Identifiers are stable; paths are mutable wiki locations. '
                      'Items without a path go in uncategorized/. Explicit links use target identifiers, with an '
                      'optional rel such as relates_to, derived_from or contradicts. Markdown links are also inferred. '
                      'Use supersede_memory only for an explicit replacement of the description of the world, never '
                      'for write order. Current reads exclude superseded or expired memories; historical reads are explicit. '
                      'Pass contributor on writes so provenance says who made the change. Records describe their search '
                      'embedding (model, dimensions) but omit the vector itself.'),
        host=host, port=port, stateless_http=True, json_response=True,
        # Loopback keeps the SDK's DNS-rebinding protection; a public host must accept its own hostname.
        transport_security=None if host in ('127.0.0.1', 'localhost', '::1') else TransportSecuritySettings(enable_dns_rebinding_protection=False),
        log_level='WARNING',
    )
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

    @mcp.tool(annotations=read)
    def about_omp(topic: str | None = None) -> dict:
        """Explain the Open Memory Protocol (OMP) and the Open Memory Protocol Initiative (OMPI).

        No topic returns a summary, the topic list and links. Topics: overview, ompi, why, record, export,
        provenance, lifecycle, conflicts, open-issues, drafts, this-demo.
        """
        return about(topic)

    @mcp.resource('omp://about', name='About OMP and OMPI', mime_type='text/markdown')
    def about_resource() -> str:
        from .about import TOPICS
        return '\n\n'.join(f'## {k}\n\n{v}' for k, v in TOPICS.items()) + f'\n\nRepository: {REPO}\n'

    @mcp.tool(annotations=read)
    def search_memories(query: str = '', limit: int = 20, path_prefix: str | None = None,
                        include_history: bool = False) -> dict:
        """Search current memories by keywords and by meaning.

        Each item has the memory, a snippet, a score (higher is better) and match: "keyword", "meaning" or "both";
        meaning matches also carry similarity (cosine). An empty query lists memories. path_prefix is a folder
        (e.g. "crew" or "personal/notes"), not a partial name. include_history searches retained revisions and
        expired or replaced memories by keyword only, one item per revision with its version.
        """
        return service.search_memories(query=query, limit=limit, path_prefix=path_prefix, include_history=include_history)

    @mcp.tool(annotations=read)
    def get_memory(identifier: str, version: int | None = None, include_history: bool = False) -> dict:
        """Read a current memory; pass version for a retained revision, or include_history for a retired head."""
        return service.get_memory(identifier, version=version, include_history=include_history)

    @mcp.tool(annotations=write)
    def add_memory(body: str, title: str | None = None, identifier: str | None = None,
                   path: str | None = None, media_type: str = 'text/markdown',
                   attributes: dict | None = None, tags: list[str] | None = None,
                   links: list[dict] | None = None, valid_until: str | None = None,
                   contributor: dict | str | None = None) -> dict:
        """Create a memory and sync it everywhere, silently. No path means uncategorized/.

        body must be nonempty. A leading "# Heading" becomes the title unless title is given.
        media_type: text/markdown (default), text/plain, application/json or text/csv.
        Explicit links: [{"target": "existing-memory-id", "rel": "derived_from"}]; unknown targets remain references.
        valid_until: an ISO 8601 date or time after which the memory is treated as expired. Never invent creation dates.
        Provide identifier to control identity; an existing identifier requires update_memory instead.
        contributor: who asked for this change, e.g. "agent:claude-code" or {"id": "user:ana", "kind": "human", "name": "Ana"};
        it is added to the memory's provenance.
        """
        return service.add_memory(body=body, title=title, identifier=identifier, path=path,
                                  media_type=media_type, attributes=attributes, tags=tags, links=links,
                                  valid_until=valid_until, contributor=contributor)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False))
    def update_memory(identifier: str, body: str | None = None, title: str | None = None,
                      attributes: dict | None = None, tags: list[str] | None = None,
                      links: list[dict] | None = None, if_version: int | None = None,
                      valid_until: str | None = None, contributor: dict | str | None = None) -> dict:
        """Update an existing memory and sync silently. Omitted arguments are preserved.

        attributes are merged: given keys replace, a key set to null is removed, other keys are kept.
        If the body's "# Heading" changes and the title was that heading, the title follows it.
        links replaces the explicit links; [] removes them. Markdown links in body are inferred independently.
        Pass if_version (the version you read) to reject the update if someone else changed the memory meanwhile;
        revisions that only refresh the search embedding do not count as changes.
        contributor: who asked for this change, e.g. "agent:claude-code" or {"id": "user:ana", "kind": "human", "name": "Ana"};
        it is added to the memory's provenance.
        """
        return service.update_memory(identifier=identifier, body=body, title=title, attributes=attributes, tags=tags,
                                     links=links, if_version=if_version, valid_until=valid_until, contributor=contributor)

    @mcp.tool(annotations=write)
    def supersede_memory(identifier: str, body: str, reason: str, contributor: dict | str,
                         title: str | None = None, if_version: int | None = None) -> dict:
        """Replace the current revision as a description of the world, retaining the old revision.

        Requires the reason (correction, update, merge, expiry, etc.) and the real contributor identity.
        Adds links[{target: identifier, version: old_version, rel: supersedes, reason, contributor}].
        This is a relation, never evidence. Ordinary update_memory writes do not add supersedes edges.
        To supersede another memory, pass an explicit supersedes link with reason/contributor to add/update.
        """
        return service.supersede_memory(identifier=identifier, body=body, reason=reason,
                                       contributor=contributor, title=title, if_version=if_version)

    @mcp.tool(annotations=write)
    def move_memory(identifier: str, path: str, contributor: dict | str | None = None) -> dict:
        """Move the wiki location globally; keep identity and repair incoming/outgoing Markdown links.

        Folders left empty by the move are removed.
        contributor: who asked for this change, e.g. "agent:claude-code" or {"id": "user:ana", "kind": "human", "name": "Ana"};
        it is added to the memory's provenance.
        """
        return service.move_memory(identifier=identifier, path=path, contributor=contributor)

    @mcp.tool(annotations=read)
    def list_folders() -> dict:
        """List existing wiki folder paths. An empty string denotes the wiki root."""
        return service.list_folders()

    return mcp


def start_http(service, port=8705):
    import threading
    import time
    import uvicorn
    mcp = create_mcp(service, port)
    server = uvicorn.Server(uvicorn.Config(mcp.streamable_http_app(), host=mcp.settings.host, port=port,
                                         log_level='warning', access_log=False))
    thread = threading.Thread(target=server.run, name='omp-mcp', daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started:
        if not thread.is_alive() or time.monotonic() >= deadline:
            raise RuntimeError(f'Could not start the MCP server on port {port}')
        time.sleep(.01)
    return server
