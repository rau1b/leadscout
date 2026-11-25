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
