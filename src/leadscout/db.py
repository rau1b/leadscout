"""SQLite storage. One file: data/leadscout.db."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from leadscout.config import IST, data_dir

# Lead status flow:
# new -> drafted -> approved -> contacted -> replied | won | lost
# plus: opted_out, bounced, excluded (by scoring), hidden (by you; scoring never changes it),
# send_failed (Gmail refused the send; the sender moved on)
STATUSES = ["new", "drafted", "approved", "contacted", "replied", "won", "lost", "opted_out", "bounced", "excluded", "hidden", "send_failed"]


def now() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


MIGRATIONS = Path(__file__).parent / "migrations"

# Database files already migrated in this process. The dashboard connects on every request, so the
# migrations run once per file instead of on every page load.
_ready: set[str] = set()


def connect(path=None) -> sqlite3.Connection:
    path = Path(path or data_dir() / "leadscout.db").resolve()
    fresh = str(path) not in _ready or not path.exists()
    # The dashboard's search worker writes while pages read: wait for locks instead of failing, and use WAL.
    con = sqlite3.connect(path, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys = on")
    if fresh:
        con.execute("pragma journal_mode = wal")  # stored in the file, so once is enough
        _upgrade(con, path)
        _ready.add(str(path))
    return con


def migrations() -> list[tuple[int, Path]]:
    """The numbered .sql files, in order: 0001_baseline.sql is version 1."""
    return sorted((int(p.name.split("_")[0]), p) for p in MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def _upgrade(con, path: Path) -> None:
    """Apply pending migrations in order, each in its own transaction; `pragma user_version` is the last one applied."""
    version = con.execute("pragma user_version").fetchone()[0]
    pending = [(n, p) for n, p in migrations() if n > version]
    if not pending:
        return
    if con.execute("select 1 from sqlite_master where type = 'table'").fetchone():
        _backup(con, path, version)
        if version == 0:
            # Made before numbered migrations: _migrate() adds the columns 0001 already has, then 0001's
            # "create table if not exists" adds only the tables this file lacks, as the old schema script did.
            _migrate(con)
    for n, p in pending:
        try:
            con.executescript(f"begin;\n{p.read_text(encoding='utf-8')}\n;pragma user_version = {n};\ncommit;")
        except Exception:
            if con.in_transaction:
                con.rollback()
            raise


def _backup(con, path: Path, version: int) -> None:
    """Copy the database before migrating it. sqlite's backup API, because with WAL the file alone can be stale."""
    folder = path.parent / "backups"
    folder.mkdir(exist_ok=True)
    dest = sqlite3.connect(folder / f"{path.stem}-{datetime.now(IST):%Y%m%d-%H%M%S}-v{version}.db")
    with dest:
        con.backup(dest)
    dest.close()


def _migrate(con) -> None:
    """One-time step for databases made before numbered migrations (user_version 0): bring them up to
    the 0001 baseline. Only _upgrade() calls it; schema changes now go in a new migrations/*.sql file."""
    cols = {r[1] for r in con.execute("pragma table_info(businesses)")}
    if cols and "city" not in cols:
        con.execute("alter table businesses add column city text")
        # Older rows stored "Area, City" in `area`; the city is the last part.
        for bid, area in con.execute("select id, area from businesses").fetchall():
            city = (area or "").split(",")[-1].strip() or None
            con.execute("update businesses set city = ? where id = ?", (city, bid))
        con.commit()
    search_cols = {r[1] for r in con.execute("pragma table_info(searches)")}
    for col, kind in (("lat", "real"), ("lon", "real"), ("state", "text"), ("population", "integer"), ("resolved", "text")):
        if search_cols and col not in search_cols:
            con.execute(f"alter table searches add column {col} {kind}")
    if search_cols:
        # Older versions added a new row each time an area was searched again: keep only the latest finished one.
        con.execute(
            """delete from searches where status in ('done', 'failed') and id not in (
                   select max(id) from searches
                   group by coalesce(round(lat, 4) || ',' || round(lon, 4), lower(label)), lower(coalesce(neighbourhood, '')))"""
        )
    lead_cols = {r[1] for r in con.execute("pragma table_info(leads)")}
    for col, kind in (("quote_inr", "integer"), ("paid_inr", "integer"), ("deal_note", "text"), ("won_at", "text")):
        if lead_cols and col not in lead_cols:
            con.execute(f"alter table leads add column {col} {kind}")
    con.commit()


def log_event(con, type: str, business_id=None, actor: str = "system", **data) -> None:
    """Record an event. Doesn't commit, so the event lands in the same transaction as the change it describes."""
    con.execute(
        "insert into events (at, business_id, type, actor, data_json) values (?, ?, ?, ?, ?)",
        (now(), business_id, type, actor, json.dumps(data, ensure_ascii=False) if data else None),
    )


def jload(s) -> list:
    return json.loads(s) if s else []


def get_meta(con, key, default=None):
    row = con.execute("select value from meta where key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(con, key, value) -> None:
    con.execute("insert into meta(key, value) values(?, ?) on conflict(key) do update set value = excluded.value", (key, str(value)))
    con.commit()
