"""The demo’s thin-core OMP memory object, as plain dicts.

A memory is metadata plus a body. Required fields are
`identifier`, `media_type`, `body` and `attributes`. Everything
else is optional and preserved as-is (§3.2: unknown fields MUST be preserved).

The checksum uses this demo's canonicalization, the same one as
`sample/build_sample.py`: SHA-256 over the record without `checksum`,
serialized as JSON with sorted keys and no whitespace. v0.2 does not fix a
canonicalization.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

REQUIRED = ("identifier", "media_type", "body", "attributes")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_identifier() -> str:
    return str(uuid.uuid4())


def canonical(record: dict) -> str:
    covered = {k: v for k, v in record.items() if k != "checksum"}
    return json.dumps(covered, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def checksum(record: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical(record).encode()).hexdigest()


def with_checksum(record: dict) -> dict:
    out = dict(record)
    out["checksum"] = checksum(record)
    return out


def validate(record: dict, *, audit: bool = False) -> list[str]:
    problems = []
    for key in REQUIRED:
        if key not in record:
            problems.append(f"missing required field {key!r}")
    if "body" in record and not isinstance(record["body"], str):
        problems.append("body must be a string (issue I-17)")
    if "attributes" in record and not isinstance(record["attributes"], dict):
        problems.append("attributes must be an object")
    for key in ("tags", "scope", "provenance", "evidence", "links"):
        if key in record and not isinstance(record[key], list):
            problems.append(f"{key} must be a list")
    if audit and isinstance(record.get('links'), list):
        from .lifecycle import contributor_id
        for link in record['links']:
            if isinstance(link, dict) and link.get('rel') == 'supersedes' and not contributor_id(link.get('contributor')):
                problems.append('audit supersedes edges must name a contributor')
    return problems


def version_value(record: dict) -> int:
    v = record.get("version")
    if isinstance(v, dict):
        return int(v.get("value", 0) or 0)
    if v in (None, ""):
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def bump_version(record: dict) -> None:
    record["version"] = {"value": version_value(record) + 1, "comparator": "integer"}


def add_contributor(record: dict, id: str, kind: str, contribution: str,
                    name: str | None = None, at: str | None = None) -> None:
    entry = {"id": id, "kind": kind, "contribution": contribution}
    if name:
        entry["name"] = name
    entry["at"] = at or now_iso()
    record.setdefault("provenance", []).append(entry)


def parse_time(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_expired(record: dict, now: datetime | None = None) -> bool:
    until = parse_time(record.get("valid_until"))
    if until is None:
        return False
    now = now or datetime.now(timezone.utc)
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until <= now


def new_manifest(origin: str, profiles=("minimal",), intent="copy") -> dict:
    return {
        "protocol_version": "0.2",
        "profiles": list(profiles),
        "origin": origin,
        "exported_at": now_iso(),
        "selection": "snapshot",
        "intent": intent,
        "media_types": [],
    }


def title_of(record: dict) -> str:
    return record.get("title") or record.get("path") or record["identifier"]
