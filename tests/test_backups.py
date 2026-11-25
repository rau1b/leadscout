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


def _people(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    con = db.connect()
    for bid, email in (("a", "gone@shop.in"), ("b", "stays@shop.in")):
        con.execute("insert into businesses (id, source, name, emails, fetched_at) values (?, 't', ?, ?, '2026-11-20')", (bid, f"Shop {bid}", f'["{email}"]'))
        con.execute("insert into leads (business_id, score, updated_at) values (?, 50, '2026-11-20')", (bid,))
        db.log_event(con, "lead.created", bid)
    con.commit()
    return con


def test_forget_cleans_live_database_and_every_backup(tmp_path, monkeypatch):
    from leadscout.compliance import _hash, forget

    con = _people(tmp_path, monkeypatch)
    copies = [backups.backup_now(con, db.default_path(), "nightly"), backups.backup_now(con, db.default_path(), "v1")]

    assert forget(con, "GONE@shop.in") == (1, [])
    for c in [con, *(sqlite3.connect(p) for p in copies)]:
        assert [r[0] for r in c.execute("select id from businesses")] == ["b"]
        assert [r[0] for r in c.execute("select business_id from leads")] == ["b"]  # cascaded
        assert [r[0] for r in c.execute("select business_id from events")] == ["b"]
        assert c.execute("select 1 from suppression where value_hash = ?", (_hash("gone@shop.in"),)).fetchone()
    for p in copies:
        assert b"gone@shop.in" not in p.read_bytes()  # not left behind in free pages


def test_unreadable_backup_is_reported_and_the_rest_are_cleaned(tmp_path, monkeypatch):
    from leadscout.compliance import forget

    con = _people(tmp_path, monkeypatch)
    good = backups.backup_now(con, db.default_path(), "nightly")
    (good.parent / "leadscout-20261101-000000-nightly.db").write_bytes(b"this is not a database" * 100)

    assert forget(con, "gone@shop.in") == (1, ["leadscout-20261101-000000-nightly.db"])
    assert [r[0] for r in sqlite3.connect(good).execute("select id from businesses")] == ["b"]


def test_forget_cli_reports_unreadable_backups(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from leadscout.cli import app

    _people(tmp_path, monkeypatch).close()
    d = tmp_path / "data" / "backups"
    d.mkdir()
    (d / "broken.db").write_bytes(b"x" * 1000)
    out = CliRunner().invoke(app, ["forget", "gone@shop.in"])
    assert out.exit_code == 1 and "broken.db" in out.output
