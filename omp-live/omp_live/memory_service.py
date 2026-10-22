"""Search-origin writes and wiki organization, through one live sync instance."""
from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import html

from .model import add_contributor, checksum, new_identifier, parse_time, validate, version_value
from . import embedding
from .sync import _plain, _shape
from .paths import default_wiki_path, folder_path, inside, wiki_path
from .systems.wiki.adapter import MARKDOWN_LINK, H1, join_front_matter
from .lifecycle import contributor_id, current_records

CODE = re.compile(r'```[^\n]*\n[\s\S]*?```|~~~[^\n]*\n[\s\S]*?~~~|`[^`\n]*`')


def rewrite_links(body: str, old_source: str, new_source: str, moved_from: str, moved_to: str) -> str:
    """Rebase outgoing and incoming Markdown URLs while preserving labels/code."""
    def rewrite(match):
        href = match.group(2).strip('<>')
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc or not parsed.path:
            return match.group(0)
        absolute = parsed.path.startswith('/')
        target = posixpath.normpath(unquote(parsed.path).lstrip('/') if absolute else
                                   posixpath.join(posixpath.dirname(old_source), unquote(parsed.path)))
        destination = moved_to if target == moved_from else target
        if target != moved_from and old_source == new_source:
            return match.group(0)
        updated = '/' + destination if absolute else posixpath.relpath(destination, posixpath.dirname(new_source) or '.')
        url = urlunsplit(('', '', quote(updated, safe='/-._~'), parsed.query, parsed.fragment))
        raw = match.group(2)
        replacement = '<' + url + '>' if raw.startswith('<') else url
        start, end = match.span(2)
        return match.group(0)[:start-match.start()] + replacement + match.group(0)[end-match.start():]

    parts = []
    position = 0
    for code in CODE.finditer(body):
        parts.append(MARKDOWN_LINK.sub(rewrite, body[position:code.start()]))
        parts.append(code.group(0))
        position = code.end()
    parts.append(MARKDOWN_LINK.sub(rewrite, body[position:]))
    return ''.join(parts)


MEDIA_TYPES = ('text/markdown', 'text/plain', 'application/json', 'text/csv')


def public(record: dict) -> dict:
    """A record as agents see it: the embedding is described, not dumped (768+ numbers per record)."""
    emb = embedding.carried(record)
    if not emb:
        return record
    attrs = dict(record['attributes'])
    attrs[embedding.KEY] = {k: v for k, v in emb.items() if k != 'vector'}
    return {**record, 'attributes': attrs}


def _contributor(value, contribution: str) -> dict | None:
    """Normalize a caller-supplied contributor: an id string or {id, kind, name}."""
    if value is None:
        return None
    if isinstance(value, str):
        value = {'id': value}
    if not isinstance(value, dict) or not isinstance(value.get('id'), str) or not value['id'].strip():
        raise ValueError('contributor must be an id string such as "agent:claude-code" or an object with a nonempty id')
    ident = value['id'].strip()
    kind = value.get('kind') or ('human' if ident.startswith('user:') else 'agent')
    if kind not in ('human', 'agent', 'system'):
        raise ValueError('contributor kind must be human, agent or system')
    return {'id': ident, 'kind': kind, 'name': value.get('name'), 'contribution': contribution}


def _check_text(name: str, value) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValueError(f'{name} must be a nonempty string')


def _check_valid_until(value) -> None:
    if value is not None and parse_time(value) is None:
        raise ValueError('valid_until must be an ISO 8601 date or time, for example 2027-01-31 or 2027-01-31T00:00:00Z')


def _check_tags(tags) -> None:
    if tags is not None and (not isinstance(tags, list) or not all(isinstance(t, str) and t.strip() for t in tags)):
        raise ValueError('tags must be a list of nonempty strings')


class MemoryService:
    def __init__(self, sync):
        self.sync = sync
        self.search_store = sync.systems['search']
        self.wiki = sync.systems['wiki']

    def _settle(self):
        for _ in range(5):
            if self.sync.reconcile() == 0:
                return
        raise RuntimeError('The memory stores did not settle after synchronization')

    def _version_ok(self, identifier: str, current: dict, if_version: int | None) -> bool:
        """if_version still matches if later revisions only added bookkeeping (the search embedding)."""
        if if_version is None or version_value(current) == if_version:
            return True
        earlier = self.sync.export.get_revision(identifier, if_version)
        return earlier is not None and _shape(_plain(earlier)) == _shape(_plain(current))

    def _credit(self, record: dict, contributor: dict | None) -> None:
        if contributor:
            add_contributor(record, contributor['id'], contributor['kind'], contributor['contribution'], name=contributor.get('name'))

    def _prune_empty_folders(self, folder: Path) -> None:
        root = self.wiki.root.resolve()
        folder = folder.resolve()
        while folder != root and folder.is_relative_to(root) and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent

    def _get_stored(self, identifier: str) -> dict:
        with self.sync._lock:
            record = self.search_store.export_one(identifier)
            if record is None:
                raise ValueError(f'No memory with identifier {identifier!r}')
            return self.sync.export.get(identifier) or record

    def get_memory(self, identifier: str, version: int | None = None, include_history: bool = False) -> dict:
        with self.sync._lock:
            if self.sync.export.is_tombstoned(identifier):
                raise ValueError('This memory was forgotten')
            record = self._get_stored(identifier)
            if version is not None:
                revision = self.sync.export.get_revision(identifier, version)
                if revision is None:
                    raise ValueError(f'No retained revision {version} of {identifier!r}; the current version is {version_value(record)}')
                return public(revision)
            visible = {r['identifier'] for r in current_records(self.sync.export.all())}
            if not include_history and identifier not in visible:
                raise ValueError('Memory is superseded or expired; request include_history or a specific version')
            return public(record)

    def search_memories(self, query: str = '', limit: int = 20, path_prefix: str | None = None,
                        include_history: bool = False) -> dict:
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError('limit must be between 1 and 100')
        prefix = folder_path(path_prefix) + '/' if path_prefix else None
        with self.sync._lock:
            if include_history:
                # Same item shape as current search; one item per retained revision, keyword ranking only.
                items = []
                for hit in self.search_store.search_history(query):
                    memory = hit['memory']
                    if prefix and not memory.get('path', '').startswith(prefix):
                        continue
                    item = {'memory': public(memory), 'version': version_value(memory),
                            'snippet': html.escape(' '.join(memory.get('body', '').split())[:160])}
                    if 'score' in hit:
                        item.update(score=round(-hit['score'], 4), match='keyword')
                    items.append(item)
                    if len(items) == limit:
                        break
                return {'items': items, 'include_history': True}
            records = {record['identifier']: record for record in self.search_store.export()}
            canonical = {record['identifier']: record for record in self.sync.export.all()}
            visible = {r['identifier'] for r in current_records(list(canonical.values()))}
            if query.strip():
                hits = self.search_store.search(query, limit=100000)
            else:
                hits = [{'identifier': identifier} for identifier in sorted(records)]
            items = []
            for hit in hits:
                record = canonical.get(hit['identifier']) or records.get(hit['identifier'])
                if not record or record['identifier'] not in visible or (prefix and not record.get('path', '').startswith(prefix)):
                    continue
                items.append({'memory': public(record), **{k: v for k, v in hit.items() if k != 'identifier'}})
                if len(items) == limit:
                    break
            return {'items': items}

    def _explicit_links(self, links: list[dict] | None, existing: list[dict] | None = None) -> list[dict]:
        if links is None:
            return []
        if not isinstance(links, list):
            raise ValueError('links must be a list of objects with a target')
        records = self.sync.export.all()
        by_path = {r.get('path'): r['identifier'] for r in records}
        identifiers = {r['identifier'] for r in records}
        out = []
        for link in links:
            if not isinstance(link, dict) or not isinstance(link.get('target'), str) or not link['target'].strip():
                raise ValueError('Every explicit link requires a nonempty string target')
            if 'rel' in link and (not isinstance(link['rel'], str) or not link['rel'].strip()):
                raise ValueError('Link relations must be nonempty strings')
            item = {k: v for k, v in link.items() if k != 'x_carrier'}
            if item['target'] not in identifiers:
                item['target'] = by_path.get(item['target'], item['target'])
            if item.get('rel') == 'supersedes' and item not in (existing or []):
                if not isinstance(item.get('reason'), str) or not item['reason'].strip():
                    raise ValueError('A supersedes link requires the reason for replacement')
                if not contributor_id(item.get('contributor')):
                    raise ValueError('A supersedes link requires the contributor who made the replacement')
                target = self.sync.export.get(item['target'])
                if target is not None and 'version' not in item:
                    item['version'] = version_value(target)
            if item not in out:
                out.append(item)
        return out

    def _commit_search(self, record, *, actor="mcp", animate=False):
        problems = validate(record, audit='audit' in self.sync.export.manifest().get('profiles', []))
        if problems:
            raise ValueError('; '.join(problems))
        current = self.sync.export.get(record['identifier'])
        if current is not None and checksum(current) == checksum(record):
            return public(current)
        # Search is the origin. OMP export and the wiki/graph imports are unchanged.
        with self.sync.operation(animate=animate, actor=actor, identifiers={record["identifier"]}):
            self.search_store.import_(record)
            self._settle()
        stored = self.sync.export.get(record['identifier'])
        if stored is None:
            raise RuntimeError('The memory was not accepted by the sync')
        return public(stored)

    def add_memory(self, body: str, title: str | None = None, identifier: str | None = None,
                   path: str | None = None, media_type: str = 'text/markdown',
                   attributes: dict | None = None, tags: list[str] | None = None,
                   links: list[dict] | None = None, valid_until: str | None = None,
                   contributor: dict | str | None = None) -> dict:
        _check_text('body', body)
        _check_text('title', title)
        _check_tags(tags)
        _check_valid_until(valid_until)
        if media_type not in MEDIA_TYPES:
            raise ValueError(f'media_type must be one of {", ".join(MEDIA_TYPES)}')
        if attributes is not None and not isinstance(attributes, dict):
            raise ValueError('attributes must be an object')
        who = _contributor(contributor, 'authored')
        with self.sync._lock:
            self._settle()
            if identifier is not None and (not isinstance(identifier, str) or not identifier.strip()):
                raise ValueError('identifier must be a nonempty string')
            rel = wiki_path(path) if path else None
            ident = identifier or rel or new_identifier()
            existing = self.sync.export.get(ident) or self.search_store.export_one(ident)
            if existing:
                if identifier is None and rel:
                    raise ValueError(f'A memory already uses the identifier {ident!r} (its page is now at '
                                     f'{existing.get("path")!r}). Choose another path, or pass a different identifier.')
                raise ValueError(f'A memory with identifier {ident!r} already exists; use update_memory to change it')
            if self.sync.export.is_tombstoned(ident):
                raise ValueError('This identifier was forgotten and cannot be reused')
            heading = H1.search(body)
            record = {'identifier': ident, 'media_type': media_type, 'body': body,
                      'attributes': {} if attributes is None else attributes}
            if title is not None or heading:
                record['title'] = title if title is not None else heading.group(1)
            if rel:
                record['path'] = rel
            record['path'] = default_wiki_path(record)
            destination = inside(self.wiki.root, record['path'])
            if destination.exists():
                raise ValueError('A wiki page already occupies that path')
            if tags is not None:
                record['tags'] = tags
            if valid_until is not None:
                record['valid_until'] = valid_until
            resolved = self.wiki.links_for(body, record['path'], self._explicit_links(links)) if media_type == 'text/markdown' else self._explicit_links(links)
            if resolved:
                record['links'] = resolved
            self._credit(record, who)
            return self._commit_search(record)

    def update_memory(self, identifier: str, body: str | None = None, title: str | None = None,
                      attributes: dict | None = None, tags: list[str] | None = None,
                      links: list[dict] | None = None, if_version: int | None = None,
                      valid_until: str | None = None, contributor: dict | str | None = None,
                      *, actor: str = "mcp", animate: bool = False) -> dict:
        _check_text('body', body)
        _check_text('title', title)
        _check_tags(tags)
        _check_valid_until(valid_until)
        if attributes is not None and not isinstance(attributes, dict):
            raise ValueError('attributes must be an object')
        who = _contributor(contributor, 'edited')
        with self.sync._lock:
            self._settle()
            record = self._get_stored(identifier)
            if not self._version_ok(identifier, record, if_version):
                raise ValueError(f'The memory changed since version {if_version} (now version {version_value(record)}); '
                                 'get its latest version before updating')
            if body is not None:
                old_heading, new_heading = H1.search(record['body']), H1.search(body)
                # A title that was just the old heading follows the new heading.
                if title is None and new_heading and (record.get('title') is None or
                                                      (old_heading and record.get('title') == old_heading.group(1))):
                    record['title'] = new_heading.group(1)
                record['body'] = body
            if title is not None:
                record['title'] = title
            if attributes is not None:
                # Merge: given keys replace, a null value removes the key, everything else is kept.
                merged = dict(record.get('attributes') or {})
                for key, value in attributes.items():
                    if value is None:
                        merged.pop(key, None)
                    else:
                        merged[key] = value
                record['attributes'] = merged
            if tags is not None:
                record['tags'] = tags
            if valid_until is not None:
                record['valid_until'] = valid_until
            previous_links = [l for l in record.get('links', []) if l.get('x_carrier') != 'inline']
            typed = self._explicit_links(links, existing=previous_links) if links is not None else previous_links
            resolved = self.wiki.links_for(record['body'], record['path'], typed) if record.get('media_type') == 'text/markdown' else typed
            if resolved:
                record['links'] = resolved
            else:
                record.pop('links', None)
            self._credit(record, who)
            return self._commit_search(record, actor=actor, animate=animate)

    def supersede_memory(self, identifier: str, body: str, reason: str, contributor: dict | str,
                         title: str | None = None, if_version: int | None = None,
                         *, tags: list[str] | None = None, actor: str = 'mcp', animate: bool = False) -> dict:
        """Explicitly replace this memory's current revision; ordinary updates do not do this."""
        with self.sync._lock:
            self._settle()
            current = self._get_stored(identifier)
            if not self._version_ok(identifier, current, if_version):
                raise ValueError(f'The memory changed since version {if_version} (now version {version_value(current)}); '
                                 'get its latest version before superseding')
            if not isinstance(body, str) or body == current['body'] and (title is None or title == current.get('title')):
                raise ValueError('A replacement must change the description')
            link = {'target': identifier, 'version': version_value(current), 'rel': 'supersedes',
                    'reason': reason, 'contributor': contributor}
            typed = [l for l in current.get('links', []) if l.get('x_carrier') != 'inline']
            return self.update_memory(identifier, body=body, title=title, tags=tags, links=[*typed, link],
                                      if_version=version_value(current), contributor=contributor, actor=actor, animate=animate)

    def list_folders(self) -> dict:
        with self.sync._lock:
            folders = {''}
            for path in self.wiki.root.rglob('*'):
                if path.is_dir() and not any(part.startswith('.') for part in path.relative_to(self.wiki.root).parts) and path.resolve().is_relative_to(self.wiki.root.resolve()):
                    folders.add(path.relative_to(self.wiki.root).as_posix())
            return {'folders': sorted(folders)}

    def create_folder(self, folder: str) -> dict:
        rel = folder_path(folder)
        with self.sync._lock:
            inside(self.wiki.root, rel).mkdir(parents=True, exist_ok=True)
        return {'folder': rel}

    def move_memory(self, identifier: str, path: str, contributor: dict | str | None = None, *, actor: str = 'mcp') -> dict:
        destination = wiki_path(path)
        with self.sync._lock:
            self._settle()
            record = self._get_stored(identifier)
            current = record['path']
            if current == destination:
                return {'memory': public(record), 'updated_identifiers': []}
            target = inside(self.wiki.root, destination)
            if target.exists():
                raise ValueError('A page already exists at the destination; nothing was moved')
            source = self.wiki._find(identifier)
            if source is None:
                raise ValueError('The memory has no wiki page to move')
            # Prepare every rewrite before touching files. A move never changes identity.
            edits = []
            for original in self.wiki.files():
                meta, body, old_path = self.wiki._read(original)
                new_path = destination if old_path == current else old_path
                updated = rewrite_links(body, old_path, new_path, current, destination)
                if new_path != old_path or updated != body:
                    edits.append((original, inside(self.wiki.root, new_path), original.read_text(encoding='utf-8'),
                                  join_front_matter(meta, updated), meta['identifier']))
            applied = []
            try:
                for old, new, before, after, ident in edits:
                    new.parent.mkdir(parents=True, exist_ok=True)
                    if new != old:
                        old.replace(new)
                    applied.append((old, new, before))
                    temp = new.with_name('.' + new.name + '.move.tmp')
                    temp.write_text(after, encoding='utf-8')
                    temp.replace(new)
            except Exception:
                for old, new, before in reversed(applied):
                    old.parent.mkdir(parents=True, exist_ok=True)
                    old.write_text(before, encoding='utf-8')
                    if new != old:
                        new.unlink(missing_ok=True)
                raise
            self._prune_empty_folders(source.parent)
            with self.sync.operation(animate=False, actor=actor, identifiers={entry[4] for entry in edits}):
                self._settle()
            moved = self._get_stored(identifier)
            who = _contributor(contributor, 'edited')
            if who:  # credit the mover on the moved memory
                self._credit(moved, who)
                moved = self._commit_search(moved, actor=actor)
            return {'memory': public(moved), 'updated_identifiers': [entry[4] for entry in edits]}
