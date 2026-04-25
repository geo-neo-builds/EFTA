"""Central path configuration for the local-storage pipeline.

All on-disk locations (external SSD, Time Capsule mirror) are resolved here
so the rest of the code never hardcodes a path.

Override any of these by setting the matching env var in `.env`:
  EFTA_LOCAL_ROOT           default: /Volumes/externalSSD256/EFTA
  EFTA_DB_DIR               default: <EFTA_LOCAL_ROOT>/db (override to put DB on internal drive)
  EFTA_TIME_CAPSULE_ROOT    default: unset (skip mirror when unset)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_LOCAL_ROOT = Path("/Volumes/externalSSD256/EFTA")


@dataclass(frozen=True)
class LocalPaths:
    root: Path
    staging: Path          # active batch of downloaded PDFs
    text: Path             # extracted per-doc text JSON
    db: Path               # directory holding efta.sqlite
    db_file: Path          # the SQLite file itself
    time_capsule_root: Path | None  # None → no Time Capsule mirror yet

    def ensure(self) -> None:
        for p in (self.staging, self.text, self.db):
            p.mkdir(parents=True, exist_ok=True)


def load_paths() -> LocalPaths:
    root = Path(os.getenv("EFTA_LOCAL_ROOT", str(DEFAULT_LOCAL_ROOT)))
    tc = os.getenv("EFTA_TIME_CAPSULE_ROOT")
    db_override = os.getenv("EFTA_DB_DIR")
    db_dir = Path(db_override) if db_override else root / "db"
    return LocalPaths(
        root=root,
        staging=root / "staging",
        text=root / "text",
        db=db_dir,
        db_file=db_dir / "efta.sqlite",
        time_capsule_root=Path(tc) if tc else None,
    )
