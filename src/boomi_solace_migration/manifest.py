from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class ManifestStore:
    def __init__(self, path: str | Path, *, plan_id: str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self.data: dict[str, Any] = {
            "plan_id": plan_id,
            "started_at": now_iso(),
            "completed_at": "",
            "entries": [],
        }
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            if self.data.get("plan_id") != plan_id:
                raise ValueError("Manifest plan_id does not match the current plan")

    def entry_for_process(self, process_id: str) -> dict[str, Any] | None:
        with self._lock:
            for entry in self.data.get("entries", []):
                if entry.get("process_id") == process_id:
                    return cast(dict[str, Any], entry)
        return None

    def upsert_entry(self, entry: dict[str, Any]) -> None:
        with self._lock:
            entries = self.data.setdefault("entries", [])
            for index, existing in enumerate(entries):
                if existing.get("process_id") == entry.get("process_id"):
                    entries[index] = entry
                    self._save_unlocked()
                    return
            entries.append(entry)
            self._save_unlocked()

    def complete(self) -> None:
        with self._lock:
            self.data["completed_at"] = now_iso()
            self._save_unlocked()

    def save(self) -> None:
        with self._lock:
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)


def load_manifest(path: str | Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(Path(path).read_text(encoding="utf-8")))
