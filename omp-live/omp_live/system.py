"""What a memory system has to implement to take part: one import, one export.

Nothing else. A system keeps the full interchange record it was given (spec
§3.2: unknown fields are preserved) and overlays whatever it changed natively
when asked to export.
"""
from __future__ import annotations

from pathlib import Path


class System:
    name: str = "system"

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def normalize(self) -> None:
        """Give native content that lacks OMP identity an identity. Optional."""

    def export(self) -> list[dict]:
        """Every memory this system holds, as OMP interchange records."""
        raise NotImplementedError

    def export_one(self, identifier: str) -> dict | None:
        for r in self.export():
            if r["identifier"] == identifier:
                return r
        return None

    def import_(self, record: dict) -> None:
        """Take an OMP record and store it natively. Idempotent."""
        raise NotImplementedError

    def forget(self, identifier: str) -> None:
        """Erase the memory with this identifier. Idempotent."""
        raise NotImplementedError

    def reset(self) -> None:
        """Wipe the native store so it can be rebuilt from the export folder."""
        raise NotImplementedError
