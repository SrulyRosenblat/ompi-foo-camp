"""Wiki locations are mutable; memory identifiers remain stable."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath


def wiki_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError('A wiki path is required')
    value = value.strip()
    path = PurePosixPath(value)
    if path.is_absolute() or '\\' in value or any(p in ('..', '.') or p.startswith('.') for p in value.split('/')):
        raise ValueError('Use a relative wiki path without hidden or parent directories')
    if any(ord(c) < 32 for c in value) or ':' in value:
        raise ValueError('Invalid wiki path')
    value = str(path)
    if not value.endswith('.md'):
        value += '.md'
    return value


def folder_path(value: str) -> str:
    if not value:
        return ''
    value = value.strip().rstrip('/')
    marker = wiki_path(value + '/__folder__.md')
    return marker.rsplit('/', 1)[0]


def default_wiki_path(record: dict) -> str:
    if record.get('path'):
        return wiki_path(record['path'])
    identifier = str(record['identifier'])
    if identifier.endswith('.md'):
        try:
            return wiki_path(identifier)
        except ValueError:
            pass
    title = record.get('title') or identifier
    name = re.sub(r'[^a-z0-9]+', '-', str(title).lower()).strip('-')[:72] or 'memory'
    suffix = hashlib.sha256(identifier.encode()).hexdigest()[:8]
    return f'uncategorized/{name}-{suffix}.md'


def inside(root: Path, rel: str) -> Path:
    path = root / rel
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Path is outside the wiki folder')
    return path
