"""Online SQLite backup (safe while the app runs). Usage: python -m pricewatch.backup [dest]"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from .config import get_settings


def backup(dest: Path | None = None, keep: int = 14) -> Path:
    s = get_settings()
    src = s.data_dir / "pricewatch.db"
    backups = s.data_dir / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    dest = dest or backups / f"pricewatch-{datetime.now():%Y%m%d-%H%M%S}.db"
    with sqlite3.connect(src) as source, sqlite3.connect(dest) as target:
        source.backup(target)
    for pattern in ("pricewatch-*.db", "pre-update-*.db"):
        for path in sorted(backups.glob(pattern))[:-keep]:
            path.unlink()
    return dest


if __name__ == "__main__":
    print(backup(Path(sys.argv[1]) if len(sys.argv) > 1 else None))
