import sqlite3

import pytest

from leadscout import db


def _version(con) -> int:
    return con.execute("pragma user_version").fetchone()[0]


def test_fresh_database_reaches_latest_version(tmp_path):
    con = db.connect(tmp_path / "t.db")
    assert _version(con) == db.migrations()[-1][0]
    assert con.execute("select count(*) from leads").fetchone()[0] == 0
    assert not (tmp_path / "backups").exists()  # nothing to back up


def test_old_database_migrates_keeps_rows_and_is_backed_up(tmp_path):
    path = tmp_path / "leadscout.db"
    old = sqlite3.connect(path)
    # The early schema: no businesses.city, no searches.lat/lon/state/population/resolved, no leads deal columns,
    # and no replies or meta tables.
    old.executescript("""
        create table businesses (id text primary key, source text not null, name text not null, area text, fetched_at text not null);
        create table searches (id integer primary key autoincrement, city text not null, neighbourhood text, label text not null,
            categories text not null, status text not null default 'queued', message text, places integer, stored integer,
            created_at text not null, finished_at text);
        create table leads (business_id text primary key references businesses(id) on delete cascade, score integer not null,
            reasons text not null default '[]', status text not null default 'new', email text, email_ok integer, updated_at text not null);
        insert into businesses values ('x', 'overture', 'Old Dental', 'Kukatpally, Hyderabad', '2026-11-01');
        insert into leads (business_id, score, updated_at) values ('x', 70, '2026-11-01');
        insert into searches (city, label, categories, status, created_at) values ('Hyderabad', 'Hyderabad', '[]', 'done', '2026-11-01');
    """)
    old.close()

    con = db.connect(path)
    assert _version(con) == db.migrations()[-1][0]
    assert con.execute("select city from businesses where id = 'x'").fetchone()[0] == "Hyderabad"
    assert con.execute("select score, quote_inr from leads").fetchone()[:] == (70, None)
    assert con.execute("select lat from searches").fetchone()[0] is None
    assert con.execute("select count(*) from replies").fetchone()[0] == 0  # missing tables were created

    [backup] = (tmp_path / "backups").glob("leadscout-*-v0.db")
    saved = sqlite3.connect(backup)
    assert saved.execute("select name from businesses").fetchall() == [("Old Dental",)]
    assert "city" not in {r[1] for r in saved.execute("pragma table_info(businesses)")}  # taken before migrating
    saved.close()


def test_connecting_twice_is_idempotent(tmp_path):
    path = tmp_path / "t.db"
    con = db.connect(path)
    con.execute("insert into businesses (id, source, name, fetched_at) values ('a', 't', 'A', '2026-11-20')")
    con.commit()
    con.close()
    db._ready.clear()  # as if a new process opened it
    con = db.connect(path)
    assert _version(con) == db.migrations()[-1][0]
    assert con.execute("select count(*) from businesses").fetchone()[0] == 1
    assert not (tmp_path / "backups").exists()  # nothing was pending, so no backup


def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    db.connect(path).close()
    latest = db.migrations()[-1][0]
    bad = tmp_path / f"{latest + 1:04d}_bad.sql"
    bad.write_text("create table half_done (x);\nthis is not sql;", encoding="utf-8")
    real = db.migrations()
    monkeypatch.setattr(db, "migrations", lambda: [*real, (latest + 1, bad)])
    db._ready.clear()
    with pytest.raises(sqlite3.OperationalError):
        db.connect(path)
    con = sqlite3.connect(path)
    assert _version(con) == latest
    assert not con.execute("select 1 from sqlite_master where name = 'half_done'").fetchone()


def test_log_event_and_forget_deletes_events(tmp_path, monkeypatch):
    from leadscout.compliance import forget

    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))  # forget() also cleans pitch files under data/
    con = db.connect()
    for bid, email in (("a", "a@shop.in"), ("b", "b@shop.in")):
        con.execute("insert into businesses (id, source, name, emails, fetched_at) values (?, 't', ?, ?, '2026-11-20')", (bid, bid, f'["{email}"]'))
        db.log_event(con, "lead.created", bid, actor="you", note="Café")
    db.log_event(con, "search.done")  # not about a business
    con.commit()
    assert con.execute("select data_json from events where business_id = 'a'").fetchone()[0] == '{"note": "Café"}'

    assert forget(con, "a@shop.in") == (1, [])
    assert [r[0] for r in con.execute("select business_id from events order by id")] == ["b", None]


def _old_database(path):
    """A database from before numbered migrations: tables exist, user_version is 0."""
    old = sqlite3.connect(path)
    old.executescript("""
        create table businesses (id text primary key, source text not null, name text not null, area text, fetched_at text not null);
        insert into businesses values ('x', 'overture', 'Old Dental', 'Kukatpally, Hyderabad', '2026-11-01');
    """)
    old.close()


def test_threads_connecting_at_once_migrate_once(tmp_path):
    import threading

    path = tmp_path / "leadscout.db"
    _old_database(path)
    start, errors = threading.Barrier(8), []

    def worker():
        start.wait()
        try:
            db.connect(path).execute("select count(*) from businesses").fetchone()
        except Exception as e:  # noqa: BLE001 - reported below
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert _version(sqlite3.connect(path)) == db.migrations()[-1][0]
    assert len(list((tmp_path / "backups").glob("*-v0.db"))) == 1


def test_migration_another_process_applied_is_skipped(tmp_path, monkeypatch):
    """Between reading user_version and taking the write lock, another process may migrate the same file."""
    from leadscout import backups

    path = tmp_path / "t.db"
    one, two = tmp_path / "0001_one.sql", tmp_path / "0002_two.sql"
    one.write_text("create table t (a);", encoding="utf-8")
    two.write_text("alter table t add column b;", encoding="utf-8")  # fails if run twice
    monkeypatch.setattr(db, "migrations", lambda: [(1, one)])
    db.connect(path).close()

    monkeypatch.setattr(db, "migrations", lambda: [(1, one), (2, two)])
    real_backup = backups.backup_now

    def other_process_migrates_first(con, p, reason):
        out = real_backup(con, p, reason)
        monkeypatch.setattr(backups, "backup_now", real_backup)  # only once
        db._upgrade(sqlite3.connect(p), p)
        return out

    monkeypatch.setattr(backups, "backup_now", other_process_migrates_first)
    db._ready.clear()
    con = db.connect(path)
    assert _version(con) == 2
    assert [r[1] for r in con.execute("pragma table_info(t)")] == ["a", "b"]


def test_migration_numbers_are_unique_and_run_1_to_n():
    """Two tracks add migrations in parallel: the one merged second must be renumbered, never share a number or leave a gap."""
    files = sorted(p.name for p in db.MIGRATIONS.glob("*.sql"))
    numbers = [int(name.split("_")[0]) for name in files]
    assert all(name[:4].isdigit() and name[4] == "_" for name in files), files  # NNNN_name.sql, or connect() would skip it
    assert numbers == list(range(1, len(files) + 1)), files


def _files(tmp_path, monkeypatch, *names_and_sql):
    """Point migrations() at these files, in number order, as a fresh checkout of the repo would have them."""
    paths = []
    for name, sql in names_and_sql:
        p = tmp_path / "mig" / name
        p.parent.mkdir(exist_ok=True)
        p.write_text(sql, encoding="utf-8")
        paths.append(p)
    monkeypatch.setattr(db, "migrations", lambda: sorted((int(p.name.split("_")[0]), p) for p in paths))
    db._ready.clear()


def _names(con):
    return sorted(r[0] for r in con.execute("select name from schema_migrations"))


def test_a_renumbered_migration_is_not_run_again(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    _files(tmp_path, monkeypatch, ("0001_base.sql", "create table t (a);"), ("0002_demos.sql", "alter table t add column demo;"))
    db.connect(path).close()
    # The other track's migration took number 2 first, so this one became 0003 after merging main.
    for f in (tmp_path / "mig").iterdir():
        f.unlink()
    _files(tmp_path, monkeypatch, ("0001_base.sql", "create table t (a);"), ("0002_tags.sql", "create table tags (x);"),
           ("0003_demos.sql", "alter table t add column demo;"))  # running it again would fail: duplicate column
    con = db.connect(path)
    assert _names(con) == ["base", "demos", "tags"] and _version(con) == 3
    assert [r[1] for r in con.execute("pragma table_info(t)")] == ["a", "demo"]


def test_a_lower_numbered_migration_added_later_is_still_applied(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    _files(tmp_path, monkeypatch, ("0001_base.sql", "create table t (a);"), ("0003_late.sql", "create table late (x);"))
    db.connect(path).close()
    _files(tmp_path, monkeypatch, ("0001_base.sql", "create table t (a);"), ("0002_early.sql", "create table early (x);"),
           ("0003_late.sql", "create table late (x);"))
    con = db.connect(path)
    assert _names(con) == ["base", "early", "late"]
    assert con.execute("select count(*) from early").fetchone()[0] == 0
    assert _version(con) == 3  # the highest number applied; never lowered


def test_existing_databases_are_marked_by_name_up_to_their_user_version(tmp_path):
    import sqlite3

    path = tmp_path / "t.db"
    old = sqlite3.connect(path)  # migrated by number before schema_migrations existed: version 2
    for _, f in db.migrations()[:2]:
        old.executescript(f.read_text(encoding="utf-8"))
    old.execute("pragma user_version = 2")
    old.close()
    con = db.connect(path)
    assert _names(con) == sorted(db.migration_name(p) for _, p in db.migrations())
    assert _version(con) == db.migrations()[-1][0]


def test_migration_names_are_unique():
    """Names are what schema_migrations records, so two files must never share one, whatever their numbers."""
    names = [db.migration_name(p) for _, p in db.migrations()]
    assert len(names) == len(set(names)), names
