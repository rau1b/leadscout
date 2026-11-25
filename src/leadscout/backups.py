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


def restore(db_path: Path, src: Path) -> dict:
    """Replace the live database with the backup `src`. The dashboard must not be running.

    Saves a "pre-restore" copy first, migrates the restored data if it's an older version, then merges the
    suppression lists of both and applies them as the live rules do, so a restore never brings back someone who
    was forgotten or opted out since: forgotten businesses are deleted, opted-out leads are marked opted_out
    (history kept), bounces are left alone (sending skips them anyway).
    """
    from leadscout import db
    from leadscout.compliance import FORGET, _hash, add_suppression_rows, contacts

    db_path, src = Path(db_path).resolve(), Path(src).resolve()
    # Read the backup first: the pre-restore copy prunes expired backups, and that could include `src`.
    mem = sqlite3.connect(":memory:")
    s = sqlite3.connect(f"{src.as_uri()}?mode=rw", uri=True)  # rw, not ro: an older copy may be in WAL mode; never creates a file
    try:
        s.backup(mem)
    finally:
        s.close()
    if not mem.execute("select 1 from sqlite_master where type = 'table' and name = 'businesses'").fetchone():
        raise ValueError("it isn't a LeadScout database")
    old_version = mem.execute("pragma user_version").fetchone()[0]

    con = db.connect(db_path)
    pre = backup_now(con, db_path, "pre-restore")
    mem.backup(con)
    mem.close()
    con.close()
    db._ready.discard(str(db_path))
    con = db.connect(db_path)  # runs any migrations the restored data is missing

    p = sqlite3.connect(pre)
    add_suppression_rows(con, p.execute("select value_hash, reason, added_at from suppression").fetchall())
    p.close()
    reasons = dict(con.execute("select value_hash, reason from suppression").fetchall())
    forgotten = {h for h, why in reasons.items() if why == FORGET}
    opted_out = {h for h, why in reasons.items() if why not in (FORGET, "bounced")}

    removed = [bid for bid, held in contacts(con) if any(_hash(v) in forgotten for v in held)]
    for bid in removed:
        con.execute("delete from businesses where id = ?", (bid,))
    # As compliance.opt_out() does: the lead's email or the business phone. A won lead is left for you to decide,
    # as with a "no" reply (mailer.sender.check_replies), since a restore is automatic.
    leads = con.execute("select l.business_id, l.email, b.phone from leads l join businesses b on b.id = l.business_id "
                        "where l.status not in ('opted_out', 'won')").fetchall()
    marked = [r[0] for r in leads if any(v and _hash(v) in opted_out for v in r[1:])]
    con.executemany("update leads set status = 'opted_out', updated_at = ? where business_id = ?", [(db.now(), bid) for bid in marked])
    con.commit()
    version = con.execute("pragma user_version").fetchone()[0]
    con.close()
    m = STAMP.search(src.name)
    taken = datetime.strptime(m.group(1), "%Y%m%d-%H%M%S") if m else datetime.fromtimestamp(src.stat().st_mtime)
    return {"file": src.name, "taken": taken, "from_version": old_version, "version": version, "removed": len(removed), "opted_out": len(marked),
            "pre_restore": pre}


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
