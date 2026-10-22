"""The sync loop. One process, one algorithm, no hub.

For every system S, on each tick:

  1. outbound   S.export() -> anything whose content changed since S last
                synced goes into the export folder as a new revision. If S
                was editing a stale base, that's a conflict and OMP does not
                resolve it (§6.1): the revision is parked in conflicts/ and
                every copy gets an `x_conflicts` marker.
  2. deletions  anything S used to hold and no longer does is forgotten:
                tombstone in the export folder (§6.5).
  3. inbound    every export record S has not seen at its current checksum
                is imported into S; every tombstone S still holds is applied.

State per system, per identifier:
  held[S][id]  checksum of S's own rendition, for change detection and echo
               suppression (S re-exporting what it just imported is a no-op)
  base[S][id]  checksum of the export record S last synced with, for conflict
               detection

Tombstoned identifiers never come back (§6.5 anti-resurrection): a system
re-presenting one is rejected with a receipt.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .export_dir import ExportDir
from .model import add_contributor, bump_version, checksum, now_iso, validate
from .system import System
from .lifecycle import supersession_warnings
from . import embedding

log = logging.getLogger("omp-sync")


def _shape(record: dict) -> str:
    """For the 'transformed' receipt only: the record with list order ignored."""
    r = {k: v for k, v in record.items() if k != "checksum"}
    for key in ("links", "provenance", "evidence", "tags", "scope"):
        if isinstance(r.get(key), list):
            r[key] = sorted(json.dumps(x, sort_keys=True) for x in r[key])
    return json.dumps(r, sort_keys=True)


def _plain(record: dict) -> dict:
    """The record without bookkeeping: vector, version, timestamps, contributors."""
    r = embedding.without(record)
    return {k: v for k, v in r.items() if k not in ("version", "updated_at", "provenance")}


class Sync:
    def __init__(self, root: Path, systems: list[System]):
        self.root = Path(root)
        self.export = ExportDir(self.root / "omp-export")
        self.systems: dict[str, System] = {s.name: s for s in systems}
        self.state_path = self.export.path / ".sync-state.json"
        self.held: dict[str, dict[str, str]] = {}
        self.base: dict[str, dict[str, str]] = {}
        self._lock = threading.RLock()
        self.events: list[dict] = []   # in-memory stream for the projector's flow view
        self._seq = 0
        self._animate = True
        self._actor = "ui"
        self._operation_ids: set[str] | None = None
        self._presentation: dict[str, bool] = {}
        self._history_ready = False
        self._supersession_warnings = set()
        self._load_state()
        for name in self.systems:
            self.held.setdefault(name, {})
            self.base.setdefault(name, {})

    # ---- state ----------------------------------------------------------
    def _load_state(self) -> None:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text())
                self.held = data.get("held", {})
                self.base = data.get("base", {})
            except json.JSONDecodeError:
                pass

    def _save_state(self) -> None:
        content = json.dumps({"held": self.held, "base": self.base}, indent=1)
        if self.state_path.exists() and self.state_path.read_text() == content:
            return
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(content)
        tmp.replace(self.state_path)

    def forget_state(self, name: str) -> None:
        with self._lock:
            self._history_ready = False
            self.held[name] = {}
            self.base[name] = {}
            self._save_state()

    def event(self, kind: str, system: str, identifier: str, **detail) -> None:
        self._seq += 1
        scoped = self._operation_ids is None or identifier in self._operation_ids
        animate = self._animate if scoped else True
        if kind in ("exported", "forgotten", "conflict", "rejected"):
            self._presentation[identifier] = animate
        self.events.append({"seq": self._seq, "at": now_iso(), "ms": int(time.time() * 1000), "kind": kind, "system": system,
                            "identifier": identifier, "animate": animate,
                            "actor": self._actor if scoped else "ui", **detail})
        del self.events[:-400]

    @contextmanager
    def operation(self, *, animate: bool = True, actor: str = "ui", identifiers: set[str] | None = None):
        """Serialize a whole mutation and its sync; presentation is not memory data."""
        with self._lock:
            previous = self._animate, self._actor, self._operation_ids
            self._animate, self._actor, self._operation_ids = animate, actor, identifiers
            try:
                yield
            finally:
                self._animate, self._actor, self._operation_ids = previous

    def silent_identifiers(self) -> list[str]:
        with self._lock:
            return [identifier for identifier, animate in self._presentation.items() if not animate]

    def events_since(self, seq: int) -> list[dict]:
        return [e for e in self.events if e["seq"] > seq]

    # ---- the tick -------------------------------------------------------
    def reconcile(self) -> int:
        """One pass. Returns the number of receipts written."""
        with self._lock:
            before = len(list(self.export.receipts_dir.glob("*.json")))
            for name, system in self.systems.items():
                try:
                    self._outbound(name, system)
                except Exception:  # keep the loop alive; a broken system must not stall the others
                    log.exception("outbound from %s failed", name)
            for name, system in self.systems.items():
                try:
                    self._inbound(name, system)
                except Exception:
                    log.exception("inbound to %s failed", name)
            self._save_state()
            after = len(list(self.export.receipts_dir.glob("*.json")))
            if after != before or not self._history_ready:
                history = self.export.revisions()
                for system in self.systems.values():
                    if hasattr(system, 'remember_revisions'):
                        system.remember_revisions(history)
                warnings = set(supersession_warnings(history))
                for identifier, warning in sorted(warnings - self._supersession_warnings):
                    self.export.receipt('sync', identifier, 'accepted', 'Supersession warning: ' + warning,
                                        warnings=[warning])
                self._supersession_warnings = warnings
                self._history_ready = True
                after = len(list(self.export.receipts_dir.glob("*.json")))
            if after != before:
                self.export.touch_manifest()
            return after - before

    def _outbound(self, name: str, system: System) -> None:
        system.normalize()
        held, base = self.held[name], self.base[name]
        current = {r["identifier"]: r for r in system.export()}

        for identifier, record in current.items():
            cs = checksum(record)
            if held.get(identifier) == cs:
                continue  # unchanged, or an echo of our own import
            problems = validate(record, audit='audit' in self.export.manifest().get('profiles', []))
            if problems:
                self.export.receipt(name, identifier, "rejected", "; ".join(problems))
                self.event("rejected", name, identifier, reason="; ".join(problems))
                held[identifier] = cs
                continue
            tomb = self.export.is_tombstoned(identifier)
            if tomb:
                self.export.receipt(
                    name, identifier, "rejected",
                    f"forgotten at {tomb['forgotten_at']} by {tomb['by']}: {tomb['reason']}. "
                    "A pre-forget copy does not come back (§6.5).",
                )
                self.event("rejected", name, identifier, reason="forgotten; a pre-forget copy does not come back")
                held[identifier] = cs
                continue

            existing = self.export.get(identifier)
            if existing is not None and identifier in base and base[identifier] != existing["checksum"]:
                # S edited a base that has since moved on. OMP keeps both; a person picks.
                self.export.put_conflict(identifier, name, record)
                marker = {"system": name, "at": now_iso(), "version": record.get("version")}
                existing.setdefault("x_conflicts", []).append(marker)
                stored = self.export.put(existing)
                self.export.receipt(name, identifier, "conflict",
                                    f"{name} revised version {record.get('version')} but the export "
                                    f"is at {existing.get('version')}; both kept (§6.1)")
                self.event("conflict", name, identifier, title=record.get("title"))
                held[identifier] = cs
                base.pop(identifier, None)  # so the marked export record is imported back into this system
                continue

            new = dict(record)
            # A revision that only adds or refreshes the vector (or other bookkeeping) is not an edit:
            # it keeps the version, so one change never shows up as two (§6.6 metadata-only variants).
            quiet = existing is not None and _shape(_plain(new)) == _shape(_plain(existing))
            if existing is not None:
                new["version"] = dict(existing.get("version") or {"value": 0, "comparator": "integer"})
                if not quiet:
                    bump_version(new)
                contribution = "edited"
                # provenance is append-only: keep contributors the system's copy never saw (§4.2)
                merged = list(new.get("provenance") or [])
                for entry in existing.get("provenance") or []:
                    if entry not in merged:
                        merged.append(entry)
                if merged:
                    new["provenance"] = merged
                # keep lifecycle markers the system might not carry
                if "x_conflicts" in existing and "x_conflicts" not in new:
                    new["x_conflicts"] = existing["x_conflicts"]
                # a system that drops the vector (the wiki) keeps it if the text it describes is unchanged
                if not embedding.carried(new) and embedding.carried(existing) \
                        and embedding.carried(existing)["text_checksum"] == embedding.text_checksum(new):
                    new = embedding.attach(new, embedding.carried(existing)["model"], embedding.carried(existing)["vector"])
            else:
                if "version" not in new:
                    new["version"] = {"value": 1, "comparator": "integer"}
                contribution = "imported"
            new["updated_at"] = existing.get("updated_at", now_iso()) if quiet else now_iso()
            # A system is credited once per kind of contribution; repeating it on every edit adds noise, not information.
            if not any(p.get("id") == f"system:{name}" and p.get("contribution") == contribution
                       for p in new.get("provenance") or [] if isinstance(p, dict)):
                add_contributor(new, f"system:{name}", "system", contribution, at=new["updated_at"])
            stored = self.export.put(new)
            self.export.receipt(name, identifier, "accepted",
                                f"{'refreshed bookkeeping' if quiet else contribution}; version {stored['version']['value']}")
            # Bookkeeping is not news: don't animate it.
            previous, self._animate = self._animate, self._animate and not quiet
            self.event("exported", name, identifier, title=stored.get("title"), path=stored.get("path"),
                       version=stored["version"]["value"], new=existing is None,
                       record=json.loads(json.dumps(stored)))
            self._animate = previous
            held[identifier] = cs
            # Bring the origin onto the accepted canonical revision as well. Otherwise
            # its version can lag one behind its own supersedes edge.
            base.pop(identifier, None)

        for identifier in list(held):
            if identifier in current:
                continue
            if self.export.get(identifier) is not None:
                self.export.forget(identifier, by=name, reason=f"removed from {name}")
                self.event("forgotten", name, identifier)
            held.pop(identifier, None)
            base.pop(identifier, None)

    def _inbound(self, name: str, system: System) -> None:
        held, base = self.held[name], self.base[name]
        for tomb in self.export.tombstones():
            identifier = tomb["identifier"]
            if identifier in held or identifier in base:
                system.forget(identifier)
                self.event("erased", name, identifier)
                held.pop(identifier, None)
                base.pop(identifier, None)
        for record in self.export.all():
            identifier = record["identifier"]
            # Older runs left an origin's revision number behind its canonical
            # export. Refresh non-Markdown heads once when restoring a session.
            if base.get(identifier) == record["checksum"] and (self._history_ready or name == 'wiki'):
                continue
            system.import_(record)
            self.event("imported", name, identifier, title=record.get("title"), version=(record.get("version") or {}).get("value"))
            rendition = system.export_one(identifier)
            if rendition is None:
                self.export.receipt(name, identifier, "omitted", f"{name} cannot hold this memory")
                base[identifier] = record["checksum"]
                continue
            rcs = checksum(rendition)
            if _shape(rendition) != _shape(record):
                self.export.receipt(name, identifier, "transformed",
                                    f"{name} holds a projection; fields changed or dropped (§10.2)")
            held[identifier] = rcs
            base[identifier] = record["checksum"]

    # ---- commands -------------------------------------------------------
    def forget(self, identifier: str, by: str = "cli", reason: str = "forget requested") -> dict:
        with self._lock:
            tomb = self.export.forget(identifier, by=by, reason=reason)
            self.event("forgotten", by, identifier, reason=reason)
            self.reconcile()
            return tomb

    def resolve(self, identifier: str, keep: str, contributor=None) -> dict | None:
        """keep = 'export' or the name of the system whose parked revision wins."""
        with self._lock:
            current = self.export.get(identifier)
            if current is None:
                return None
            conflicts = self.export.conflicts(identifier)
            if keep != "export":
                if contributor is None and 'audit' in self.export.manifest().get('profiles', []):
                    raise ValueError('Audit resolution requires the contributor who chose the replacement')
                winner = next((c for c in reversed(conflicts) if c["system"] == keep), None)
                if winner is None:
                    return None
                new = dict(winner["record"])
                new["version"] = dict(current.get("version", {"value": 0, "comparator": "integer"}))
                bump_version(new)
                new["updated_at"] = now_iso()
                new.setdefault("links", []).append(
                    {"target": identifier, "version": current.get("version", {}).get("value"),
                     "rel": "supersedes", "reason": "Conflict resolved by choosing " + keep,
                     **({'contributor': contributor} if contributor is not None else {})})
                add_contributor(new, "user:resolver", "human", "approved", at=new["updated_at"])
                new.pop("x_conflicts", None)
                current = new
            else:
                current.pop("x_conflicts", None)
                add_contributor(current, "user:resolver", "human", "approved")
            stored = self.export.put(current)
            self.export.clear_conflicts(identifier)
            self.export.receipt("cli", identifier, "resolved", f"kept {keep}")
            self.reconcile()
            return stored

    def rebuild(self, name: str) -> int:
        with self._lock:
            system = self.systems[name]
            system.reset()
            self.forget_state(name)
            self.reconcile()
            return len(self.held[name])

    def seed(self, records: list[dict], by: str = "seed") -> int:
        """Load interchange records straight into the export folder, then fan out."""
        with self._lock:
            n = 0
            for record in records:
                record = {"attributes": {}, **record}
                problems = validate(record, audit='audit' in self.export.manifest().get('profiles', []))
                if problems:
                    self.export.receipt(by, record.get("identifier", "?"), "rejected", "; ".join(problems))
                    continue
                if self.export.is_tombstoned(record["identifier"]):
                    self.export.receipt(by, record["identifier"], "rejected", "tombstoned")
                    continue
                self.export.put(record)
                self.export.receipt(by, record["identifier"], "accepted", "seeded")
                n += 1
            self.reconcile()
            return n
