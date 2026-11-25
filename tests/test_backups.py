import sqlite3
from datetime import datetime, timedelta

from leadscout import backups, db
from leadscout.config import IST


def _stamp(days_ago: float) -> str:
    return f"{datetime.now(IST) - timedelta(days=days_ago):%Y%m%d-%H%M%S}"


def test_nightly_makes_at_most_one_backup_a_day(tmp_path):
    path = tmp_path / "leadscout.db"
    con = db.connect(path)
    con.execute("insert into businesses (id, source, name, fetched_at) values ('a', 't', 'A', '2026-11-20')")
    con.commit()
    first = backups.nightly(con, path)
    assert first and first.name.endswith("-nightly.db")
    assert backups.nightly(con, path) is None
    assert backups.backup_now(con, path, "manual")  # a manual copy doesn't count as the nightly one, and isn't blocked by it
    assert len(list((tmp_path / "backups").glob("*-nightly.db"))) == 1
    copy = sqlite3.connect(first)
    assert copy.execute("select name from businesses").fetchall() == [("A",)]
    assert copy.execute("pragma journal_mode").fetchone()[0] == "delete"  # one self-contained file
    copy.close()


def test_nightly_ignores_yesterdays_backup(tmp_path):
    path = tmp_path / "leadscout.db"
    con = db.connect(path)
    (tmp_path / "backups").mkdir()
    (tmp_path / "backups" / f"leadscout-{_stamp(1)}-nightly.db").write_bytes(b"")
    assert backups.nightly(con, path)


def test_prune_removes_only_backups_older_than_keep_days(tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    old, young, other = f"leadscout-{_stamp(15)}-nightly.db", f"leadscout-{_stamp(13)}-v1.db", "notes.db"
    for name in (old, old + "-wal", young, other):
        (d / name).write_bytes(b"x")
    assert backups.prune(d, keep_days=14) == [old]
    assert sorted(p.name for p in d.iterdir()) == sorted([young, other])  # a file without a timestamp is left alone


def test_daily_purge_prunes_backups(tmp_path, monkeypatch):
    from leadscout.compliance import purge_if_due

    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    con = db.connect()
    d = tmp_path / "data" / "backups"
    d.mkdir()
    (d / f"leadscout-{_stamp(30)}-nightly.db").write_bytes(b"x")

    class Cfg:
        retention = {"purge_uncontacted_after_days": 90}
        backups = {"keep_days": 14}

    purge_if_due(con, Cfg())
    assert list(d.iterdir()) == []
