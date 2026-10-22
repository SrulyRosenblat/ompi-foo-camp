"""The OMP export folder. This is the interchange, and there is no hub.

    omp-export/
      manifest.json           spec §8.1
      memories/<id>.json      one interchange record per memory, with checksum
      revisions/<id-hash>.<checksum>.json   immutable accepted record snapshots
      tombstones/<id>.json    spec §6.5: when, who, why; never the content
      conflicts/<id>.<system>.<ts>.json   a revision OMP did not resolve (§6.1)
      receipts/<ts>-<n>.json  spec §8.4: accepted / rejected / conflict / forgotten

Any system can be deleted and rebuilt from this folder.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from pathlib import Path

from .model import checksum, new_manifest, now_iso, version_value, with_checksum

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(identifier: str) -> str:
    return _SAFE.sub("_", identifier) or "_"


class ExportDir:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.memories = self.path / "memories"
        self.revisions_dir = self.path / "revisions"
        self.tombstones_dir = self.path / "tombstones"
        self.receipts_dir = self.path / "receipts"
        self.conflicts_dir = self.path / "conflicts"
        for d in (self.memories, self.revisions_dir, self.tombstones_dir,
                  self.receipts_dir, self.conflicts_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._receipt_seq = 0
        self.manifest()  # create on first use
        # Preserve the baseline as soon as history is enabled, before an external
        # writer can overwrite a latest JSON file in place.
        for record in self.all():
            if isinstance(record, dict) and isinstance(record.get('identifier'), str) and not self.is_tombstoned(record['identifier']):
                self._snapshot(record)

    # ---- manifest -------------------------------------------------------
    @property
    def manifest_path(self) -> Path:
        return self.path / "manifest.json"

    def manifest(self) -> dict:
        if self.manifest_path.exists():
            return json.loads(self.manifest_path.read_text())
        m = new_manifest("store:" + str(uuid.uuid4()))
        self._write_json(self.manifest_path, m)
        return m

    @property
    def origin(self) -> str:
        return self.manifest()["origin"]

    def touch_manifest(self) -> None:
        m = self.manifest()
        m["exported_at"] = now_iso()
        types = sorted({r.get("media_type", "text/plain") for r in self.all()})
        m["media_types"] = types
        self._write_json(self.manifest_path, m)

    # ---- memories -------------------------------------------------------
    def _mem_path(self, identifier: str) -> Path:
        return self.memories / (safe_name(identifier) + ".json")

    def list_ids(self) -> list[str]:
        ids = []
        for p in sorted(self.memories.glob("*.json")):
            try:
                ids.append(json.loads(p.read_text())["identifier"])
            except (json.JSONDecodeError, KeyError, OSError):
                continue
        return ids

    def all(self) -> list[dict]:
        out = []
        for p in sorted(self.memories.glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except (json.JSONDecodeError, OSError):
                continue
        return out

    def get(self, identifier: str) -> dict | None:
        p = self._mem_path(identifier)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return None

    def put(self, record: dict) -> dict:
        """Write a record with its checksum. Returns the stored record."""
        with self._lock:
            stored = with_checksum(record)
            previous = self.get(record["identifier"])
            if previous is not None and previous.get("identifier") == record["identifier"]:
                self._snapshot(previous)
            self._snapshot(stored)
            self._write_json(self._mem_path(record["identifier"]), stored)
            return stored

    def remove(self, identifier: str) -> None:
        p = self._mem_path(identifier)
        if p.exists():
            p.unlink()

    # ---- revision history -----------------------------------------------
    @staticmethod
    def _revision_key(identifier: str) -> str:
        # safe_name is lossy (e.g. "a/b" and "a_b"). History must not collide.
        return hashlib.sha256(identifier.encode("utf-8")).hexdigest()

    def _snapshot(self, record: dict) -> None:
        stored = with_checksum(record)
        digest = stored["checksum"].removeprefix("sha256:")
        path = self.revisions_dir / f"{self._revision_key(stored['identifier'])}.{digest}.json"
        if not path.exists():
            self._write_json(path, stored)

    def revisions(self, identifier: str | None = None) -> list[dict]:
        """Raw accepted records, ordered by identifier, version and checksum.

        Checksums cover metadata too: multiple immutable variants can share a
        version number. Include legacy latest files without inventing history
        from before snapshots existed. Tombstones always suppress history.
        """
        with self._lock:
            forgotten = {t["identifier"] for t in self.tombstones()}
            records = {}
            pattern = "*.json" if identifier is None else f"{self._revision_key(identifier)}.*.json"
            for path in sorted(self.revisions_dir.glob(pattern)):
                try:
                    record = json.loads(path.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                if not isinstance(record, dict) or not isinstance(record.get("identifier"), str):
                    continue
                ident = record["identifier"]
                if ident not in forgotten and (identifier is None or ident == identifier):
                    records[(ident, checksum(record))] = record
            for record in self.all():
                ident = record.get("identifier")
                if isinstance(ident, str) and ident not in forgotten and (identifier is None or ident == identifier):
                    records[(ident, checksum(record))] = record
            return sorted(records.values(), key=lambda r: (r["identifier"], version_value(r), checksum(r)))

    def get_revision(self, identifier: str, version: int) -> dict | None:
        """Pick a version deterministically; checksum order breaks variant ties."""
        matches = [r for r in self.revisions(identifier) if version_value(r) == version]
        return matches[-1] if matches else None

    # ---- tombstones -----------------------------------------------------
    def _tomb_path(self, identifier: str) -> Path:
        return self.tombstones_dir / (safe_name(identifier) + ".json")

    def is_tombstoned(self, identifier: str) -> dict | None:
        p = self._tomb_path(identifier)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return None

    def tombstones(self) -> list[dict]:
        out = []
        for p in sorted(self.tombstones_dir.glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except (json.JSONDecodeError, OSError):
                continue
        return out

    def forget(self, identifier: str, by: str, reason: str) -> dict:
        """§6.5: erase the content, leave a tombstone with when, who and why."""
        with self._lock:
            tomb = {
                "identifier": identifier,
                "origin": self.origin,
                "forgotten_at": now_iso(),
                "by": by,
                "reason": reason,
            }
            self._write_json(self._tomb_path(identifier), tomb)
            self.remove(identifier)
            for path in self.revisions_dir.glob(f"{self._revision_key(identifier)}.*.json"):
                path.unlink(missing_ok=True)
            self.clear_conflicts(identifier)
            self.receipt(by, identifier, "forgotten", reason)
            return tomb

    # ---- conflicts ------------------------------------------------------
    def put_conflict(self, identifier: str, system: str, record: dict) -> Path:
        name = f"{safe_name(identifier)}.{system}.{int(time.time() * 1000)}.json"
        p = self.conflicts_dir / name
        self._write_json(p, {"system": system, "at": now_iso(), "record": record})
        return p

    def conflicts(self, identifier: str | None = None) -> list[dict]:
        out = []
        for p in sorted(self.conflicts_dir.glob("*.json")):
            try:
                c = json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            c["file"] = p.name
            if identifier is None or c["record"].get("identifier") == identifier:
                out.append(c)
        return out

    def clear_conflicts(self, identifier: str) -> None:
        for c in self.conflicts(identifier):
            (self.conflicts_dir / c["file"]).unlink(missing_ok=True)

    # ---- receipts -------------------------------------------------------
    def receipt(self, system: str, identifier: str, outcome: str,
                reason: str | None = None, **extra) -> dict:
        with self._lock:
            self._receipt_seq += 1
            r = {"at": now_iso(), "system": system, "identifier": identifier, "outcome": outcome}
            if reason:
                r["reason"] = reason
            r.update(extra)
            name = f"{int(time.time() * 1000)}-{self._receipt_seq:04d}.json"
            self._write_json(self.receipts_dir / name, r)
            return r

    def receipts(self, limit: int = 50) -> list[dict]:
        files = sorted(self.receipts_dir.glob("*.json"))[-limit:]
        out = []
        for p in files:
            try:
                out.append(json.loads(p.read_text()))
            except (json.JSONDecodeError, OSError):
                continue
        return out

    # ---- io -------------------------------------------------------------
    @staticmethod
    def _write_json(path: Path, data) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        tmp.replace(path)
