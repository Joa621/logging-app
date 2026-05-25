"""
JSONL-based record storage.

Each line is a JSON-serialised SensorRecord.  The file is append-only during
a run and safe for concurrent reads within a single process (thread lock).

Format (one line per record):
    {"id":"...","received_at":"...","dev_eui":"...","f_cnt":42,
     "packet_time":"...","temp":25.0,"ph":7.5,"bat":80}
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import List, Optional

from .models import SensorRecord


class RecordStore:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        # Ensure the parent directory exists; create an empty file if missing.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(self, record: SensorRecord) -> None:
        """Append one record as a single JSONL line.  Thread-safe."""
        line = record.model_dump_json() + "\n"
        with self._lock:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read_all(self) -> List[SensorRecord]:
        """Return every stored record in insertion order."""
        records: List[SensorRecord] = []
        with self._lock:
            if not self._path.exists():
                return records
            with self._path.open("r", encoding="utf-8") as fh:
                for lineno, raw in enumerate(fh, start=1):
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        records.append(SensorRecord.model_validate_json(raw))
                    except Exception as exc:
                        # Log and skip malformed lines; do not abort.
                        import logging
                        logging.getLogger(__name__).warning(
                            "Skipping malformed record at line %d: %s", lineno, exc
                        )
        return records

    def read_latest(self) -> Optional[SensorRecord]:
        """Return the most recently stored record, or None if the store is empty."""
        all_records = self.read_all()
        return all_records[-1] if all_records else None
