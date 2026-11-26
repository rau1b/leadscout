"""SQLite storage. One file: data/leadscout.db."""

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from leadscout.config import IST, data_dir

# Lead status flow:
# new -> drafted -> approved -> contacted -> replied | won | lost
# plus: opted_out, bounced, excluded (by scoring), hidden (by you; scoring never changes it),
# send_failed (Gmail refused the send; the sender moved on)
# meeting and proposal are set by Show & close (crm/), only from replied, meeting or proposal (contract C6).
STATUSES = ["new", "drafted", "approved", "contacted", "replied", "meeting", "proposal", "won", "lost", "opted_out", "bounced", "excluded", "hidden",
            "send_failed"]


def now() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


MIGRATIONS = Path(__file__).parent / "migrations"

# Database files already migrated in this process. The dashboard connects on every request, so the
# migrations run once per file instead of on every page load. The lock stops two dashboard threads migrating at once.
_ready: set[str] = set()
_ready_lock = threading.Lock()


def default_path() -> Path:
    return data_dir() / "leadscout.db"


def connect(path=None) -> sqlite3.Connection:
    path = Path(path or default_path()).resolve()
    missing = not path.exists()
    # The dashboard's search worker writes while pages read: wait for locks instead of failing, and use WAL.
    con = sqlite3.connect(path, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys = on")
    con.execute("pragma secure_delete = on")  # deleted rows (forget, purge...) are overwritten, not left in free pages
    if missing or str(path) not in _ready:
        with _ready_lock:
            if missing or str(path) not in _ready:  # another thread may have migrated it while we waited
                con.execute("pragma journal_mode = wal")  # stored in the file, so once is enough
                _upgrade(con, path)
                _ready.add(str(path))
    return con


def file_of(con) -> Path:
    """The file this connection has open."""
    return Path(con.execute("pragma database_list").fetchone()[2])


def migrations() -> list[tuple[int, Path]]:
    """The numbered .sql files, in order: 0001_baseline.sql is number 1."""
    return sorted((int(p.name.split("_")[0]), p) for p in MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def migration_name(p: Path) -> str:
    """The file name without its number: "0004_demos.sql" -> "demos". Applied migrations are recorded by this name,
    so renumbering a file after a clash between the two tracks never re-runs or skips it."""
    return p.stem.split("_", 1)[1]


def _has_table(con, name: str) -> bool:
    return con.execute("select 1 from sqlite_master where type = 'table' and name = ?", (name,)).fetchone() is not None


def _has_tables(con) -> bool:
    return con.execute("select 1 from sqlite_master where type = 'table'").fetchone() is not None


def _applied(con) -> set[str] | None:
    """Names of the applied migrations, or None before schema_migrations exists (then numbers up to user_version count)."""
    if not _has_table(con, "schema_migrations"):
        return None
    return {r[0] for r in con.execute("select name from schema_migrations")}


def _upgrade(con, path: Path) -> None:
    """Apply every migration whose name isn't in schema_migrations, in number order, each in its own transaction.
    `pragma user_version` still holds the highest number applied, for older code and backup names."""
    from leadscout import backups

    files = migrations()
    version = con.execute("pragma user_version").fetchone()[0]
    applied = _applied(con)
    seeded = applied is not None
    if applied is None:
        applied = {migration_name(p) for n, p in files if n <= version}
    pending = [(n, p) for n, p in files if migration_name(p) not in applied]
    if seeded and not pending:
        return
    if pending and _has_tables(con):
        backups.backup_now(con, path, f"v{version}")
    # autocommit=True: we control the transactions, and executescript() won't commit one behind our back.
    mig = sqlite3.connect(path, timeout=30, autocommit=True)
    try:
        # BEGIN IMMEDIATE takes the write lock, so another process can't migrate in between; each step re-checks inside it.
        _in_transaction(mig, lambda: _seed(mig, files))
        for _, p in pending:
            _in_transaction(mig, lambda p=p: _apply(mig, p, files))
    finally:
        mig.close()


def _in_transaction(mig, step) -> None:
    mig.execute("begin immediate")
    try:
        step()
        mig.execute("commit")
    except BaseException:
        if mig.in_transaction:
            mig.execute("rollback")
        raise


def _seed(mig, files) -> None:
    """First run with schema_migrations: the files up to user_version were applied by number, so record them by name."""
    if _has_table(mig, "schema_migrations"):
        return
    mig.execute("create table schema_migrations (name text primary key, applied_at text not null)")
    version = mig.execute("pragma user_version").fetchone()[0]
    mig.executemany("insert into schema_migrations (name, applied_at) values (?, ?)",
                    [(migration_name(p), now()) for n, p in files if n <= version])


def _apply(mig, p: Path, files) -> None:
    name = migration_name(p)
    if mig.execute("select 1 from schema_migrations where name = ?", (name,)).fetchone():
        return  # another process applied it while we waited; alter table can't run twice
    if name == "baseline" and _has_table(mig, "businesses"):
        # Made before numbered migrations: _migrate() adds the columns 0001 already has, then 0001's
        # "create table if not exists" adds only the tables this file lacks, as the old schema script did.
        # Its commit() calls do nothing on an autocommit=True connection, so it stays in this transaction.
        _migrate(mig)
    mig.executescript(p.read_text(encoding="utf-8"))
    mig.execute("insert into schema_migrations (name, applied_at) values (?, ?)", (name, now()))
    # The highest current number among applied files, so code that still counts by number never re-runs one.
    done = {r[0] for r in mig.execute("select name from schema_migrations")}
    mig.execute(f"pragma user_version = {max(m for m, f in files if migration_name(f) in done)}")


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
