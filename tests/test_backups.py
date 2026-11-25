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


def test_forget_overwrites_the_live_database_file(tmp_path, monkeypatch):
    from leadscout.compliance import forget

    con = _people(tmp_path, monkeypatch)
    con.execute("pragma wal_checkpoint(truncate)")
    assert b"gone@shop.in" in db.default_path().read_bytes()  # so the check below means something
    forget(con, "gone@shop.in")
    con.execute("pragma wal_checkpoint(truncate)")
    data = db.default_path().read_bytes()
    assert b"gone@shop.in" not in data and b"stays@shop.in" in data


def test_housekeeping_runs_daily_jobs_once_a_day(tmp_path, monkeypatch):
    from leadscout.web.app import housekeeping

    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    housekeeping()
    housekeeping()  # the hourly repeat: nothing new the same day
    assert len(list((tmp_path / "data" / "backups").glob("*-nightly.db"))) == 1
    assert db.get_meta(db.connect(), "last_purge") == f"{datetime.now(IST):%Y-%m-%d}"


def test_housekeeping_logs_a_failure_and_keeps_going(tmp_path, monkeypatch, caplog):
    from leadscout import compliance
    from leadscout.web.app import housekeeping

    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))

    def broken(*a):
        raise RuntimeError("disk full")

    monkeypatch.setattr(compliance, "purge_if_due", broken)
    housekeeping()  # doesn't raise
    assert "retention purge failed" in caplog.text and "disk full" in caplog.text
    assert list((tmp_path / "data" / "backups").glob("*-nightly.db"))  # the backup still ran


def test_hourly_task_stops_cleanly_on_shutdown(tmp_path, monkeypatch):
    import asyncio

    from leadscout import searches
    from leadscout.web import app as web

    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    monkeypatch.setattr(searches, "start_worker", lambda: None)

    async def run():
        async with web.lifespan(web.app):
            await asyncio.sleep(0)  # the hourly task is now waiting on its first hour
        return [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    assert asyncio.run(run()) == []


def _rows(con, sql):
    return [tuple(r) for r in con.execute(sql)]


def test_restore_brings_back_the_backup(tmp_path, monkeypatch):
    con = _people(tmp_path, monkeypatch)
    saved = backups.backup_now(con, db.default_path(), "manual")
    before = _rows(con, "select * from businesses order by id"), _rows(con, "select * from leads order by business_id")
    con.execute("insert into businesses (id, source, name, fetched_at) values ('c', 't', 'New', '2026-11-21')")
    con.execute("update leads set score = 99")
    con.commit()
    con.close()

    r = backups.restore(db.default_path(), saved)
    con = db.connect()
    assert (_rows(con, "select * from businesses order by id"), _rows(con, "select * from leads order by business_id")) == before
    assert r["removed"] == 0 and r["file"] == saved.name
    assert "c" in {x[0] for x in _rows(sqlite3.connect(r["pre_restore"]), "select id from businesses")}  # the state before is kept


def test_restore_follows_the_live_suppression_rules(tmp_path, monkeypatch):
    from leadscout.compliance import FORGET, _hash, forget, opt_out, suppress

    con = _people(tmp_path, monkeypatch)  # a: gone@shop.in, b: stays@shop.in, each with a lead
    con.execute("update leads set email = 'stays@shop.in', status = 'contacted' where business_id = 'b'")
    con.execute("insert into outreach (business_id, channel, kind, to_addr, sent_at) values ('b', 'email', 'first', 'stays@shop.in', '2026-11-20')")
    con.execute("insert into businesses (id, source, name, emails, fetched_at) values ('c', 't', 'Shop c', '[\"dead@shop.in\"]', '2026-11-20')")
    suppress(con, "gone@shop.in", "bounced")  # in the backup only as a bounce
    # A copy kept outside data/backups/, so forget can't clean it.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    saved = backups.backup_now(con, db.default_path(), "manual").replace(elsewhere / "leadscout-20261120-100000-manual.db")
    forget(con, "gone@shop.in")
    opt_out(con, "stays@shop.in", "dashboard")
    suppress(con, "dead@shop.in", "bounced")
    con.close()

    r = backups.restore(db.default_path(), saved)
    con = db.connect()
    assert (r["removed"], r["opted_out"]) == (1, 1)
    assert _rows(con, "select id from businesses order by id") == [("b",), ("c",)]  # forgotten: deleted; the bounce is kept
    assert _rows(con, "select status from leads where business_id = 'b'") == [("opted_out",)]  # opted out: kept, marked
    assert _rows(con, "select to_addr from outreach") == [("stays@shop.in",)]  # with its history
    reason = lambda v: con.execute("select reason from suppression where value_hash = ?", (_hash(v),)).fetchone()[0]  # noqa: E731
    assert (reason("gone@shop.in"), reason("stays@shop.in"), reason("dead@shop.in")) == (FORGET, "dashboard", "bounced")


def test_restore_migrates_an_older_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    db.connect().close()
    old = tmp_path / "old.db"
    o = sqlite3.connect(old)
    o.executescript(db.migrations()[0][1].read_text(encoding="utf-8"))  # the old schema: the baseline without city
    o.executescript("""
        alter table businesses drop column city;
        insert into businesses (id, source, name, area, fetched_at) values ('x', 'overture', 'Old Dental', 'Kukatpally, Hyderabad', '2026-11-01');
    """)
    o.close()

    r = backups.restore(db.default_path(), old)
    con = db.connect()
    assert (r["from_version"], r["version"]) == (0, db.migrations()[-1][0])
    assert con.execute("pragma user_version").fetchone()[0] == db.migrations()[-1][0]
    assert _rows(con, "select name, city from businesses") == [("Old Dental", "Hyderabad")]


def test_restore_refuses_while_the_dashboard_runs(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from leadscout import launch
    from leadscout.cli import app

    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    monkeypatch.setattr(launch, "dashboard_pid", lambda: 4242)
    out = CliRunner().invoke(app, ["restore", "anything.db"])
    assert out.exit_code == 1 and "leadscout stop" in out.output

    monkeypatch.setattr(launch, "dashboard_pid", lambda: None)
    monkeypatch.setattr(launch, "running", lambda: True)  # a terminal `leadscout serve`
    out = CliRunner().invoke(app, ["restore", "anything.db"])
    assert out.exit_code == 1 and "Ctrl+C" in out.output


def test_suppression_keeps_the_strongest_reason(tmp_path):
    from leadscout.compliance import FORGET, is_opted_out, is_suppressed, opt_out, suppress

    con = db.connect(tmp_path / "t.db")
    row = lambda: tuple(con.execute("select reason, added_at from suppression").fetchone())  # noqa: E731

    suppress(con, "a@x.in", "bounced")
    opt_out(con, "a@x.in", "dashboard")  # bounce, then opt-out: becomes an opt-out
    assert row()[0] == "dashboard" and is_suppressed(con, "a@x.in") and is_opted_out(con, "a@x.in")

    con.execute("update suppression set added_at = 'when it was opted out'")
    suppress(con, "a@x.in", "bounced")  # opt-out, then bounce: stays an opt-out, date untouched
    assert row() == ("dashboard", "when it was opted out")

    suppress(con, "a@x.in", FORGET)  # anything, then forget: forget
    suppress(con, "a@x.in", "opted_out")  # and nothing downgrades it again
    assert row()[0] == FORGET
