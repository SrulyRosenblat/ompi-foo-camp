"""Explicit replacement semantics; write order alone never retires a memory."""
from __future__ import annotations

from .model import is_expired, version_value


def edge_version(link):
    value = link.get('version')
    return value.get('value') if isinstance(value, dict) else value


def matches(record: dict, link: dict) -> bool:
    version = edge_version(link)
    return record['identifier'] == link.get('target') and (version is None or str(version_value(record)) == str(version))


def replacement_edges(records: list[dict]):
    for source in records:
        for link in source.get('links') or []:
            if isinstance(link, dict) and link.get('rel') == 'supersedes' and link.get('target'):
                yield source, link


def current_records(records: list[dict]) -> list[dict]:
    replacements = [(source, link) for source, link in replacement_edges(records)
                    if not reverse_disagrees(source, link, records)]
    return [r for r in records if not is_expired(r) and not any(matches(r, link) for _, link in replacements)]


def contributor_id(value) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict) and isinstance(value.get('id'), str):
        return value['id'].strip() or None
    return None


def reverse_disagrees(source, link, records):
    for target in records:
        if not matches(target, link) or 'invalidated_by' not in target:
            continue
        reverse = target['invalidated_by']
        pointers = reverse if isinstance(reverse, list) else [reverse]
        pointers = [{'target': p} if isinstance(p, str) else p for p in pointers]
        if not any(isinstance(p, dict) and matches(source, p) for p in pointers):
            return True
    return False


def supersession_warnings(records: list[dict]) -> list[tuple[str, str]]:
    """Report missing audit context and contradictory carried reverse pointers."""
    warnings = set()
    for source, link in replacement_edges(records):
        ident = source['identifier']
        if not isinstance(link.get('reason'), str) or not link['reason'].strip():
            warnings.add((ident, 'supersedes edge is missing a reason'))
        if not contributor_id(link.get('contributor')):
            warnings.add((ident, 'supersedes edge is missing a contributor'))
        if reverse_disagrees(source, link, records):
            warnings.add((ident, 'supersedes and invalidated_by disagree; neither pointer was rewritten'))
    return sorted(warnings)
