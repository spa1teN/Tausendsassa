# core/state.py
"""
Kümmert sich nur darum, welche GUIDs schon gepostet wurden.
Einfach, aber ausreichend für kleine Bots.
"""

import json
from pathlib import Path
from typing import Set

class State:
    def __init__(self, path: Path):
        self.path = path
        self._guids: Set[str] = set()
        if path.exists():
            try:
                self._guids |= set(json.loads(path.read_text()))
            except Exception:
                path.unlink(missing_ok=True)  # kaputte Datei neu anlegen

    def already_sent(self, guid: str) -> bool:
        return guid in self._guids

    def mark_sent(self, guid: str) -> None:
        self._guids.add(guid)

    def save(self) -> None:
        self.path.write_text(json.dumps(list(self._guids), indent=2))
