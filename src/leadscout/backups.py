"""Copies of the database in data/backups/: one before each migration and one a day. They expire after
[backups] keep_days, and `leadscout forget` cleans them too (see docs/INDIA_RULES.md)."""

import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from leadscout import config
from leadscout.config import IST

STAMP = re.compile(r"-(\d{8}-\d{6})-[^-]+\.db$")


def folder(db_path: Path) -> Path:
    return Path(db_path).parent / "backups"


def backup_now(con, path: Path, reason: str) -> Path:
    """Copy the live database to backups/<name>-<YYYYmmdd-HHMMSS>-<reason>.db, then drop expired copies.

    sqlite's backup API, because with WAL on the database file alone can be missing recent writes.
    """
    path = Path(path)
    d = folder(path)
    d.mkdir(exist_ok=True)
    out = d / f"{path.stem}-{datetime.now(IST):%Y%m%d-%H%M%S}-{reason}.db"
    dest = sqlite3.connect(out)
    try:
        con.backup(dest)
        dest.execute("pragma journal_mode = delete")  # the copy inherits WAL mode; one self-contained file is easier to handle
    finally:
        dest.close()
    prune(d, config.load().backups["keep_days"])
    return out


def nightly(con, path: Path) -> Path | None:
    """Make today's (IST) "nightly" backup unless one exists. Returns the new file, or None if there already was one."""
    path = Path(path)
    if any(folder(path).glob(f"{path.stem}-{datetime.now(IST):%Y%m%d}-*-nightly.db")):
        return None
    return backup_now(con, path, "nightly")


def prune(d: Path, keep_days: int = 14) -> list[str]:
    """Delete backups older than keep_days. Age comes from the name, not the file time: forget rewrites old backups."""
    cutoff = datetime.now(IST).replace(tzinfo=None) - timedelta(days=keep_days)
    gone = []
    for f in sorted(Path(d).glob("*.db")):
        m = STAMP.search(f.name)
        if m and datetime.strptime(m.group(1), "%Y%m%d-%H%M%S") < cutoff:
            for p in (f, f.with_name(f.name + "-wal"), f.with_name(f.name + "-shm"), f.with_name(f.name + "-journal")):
                p.unlink(missing_ok=True)
            gone.append(f.name)
    return gone
