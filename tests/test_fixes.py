"""Regression tests for the audit bug fixes. None of these touch the network or send email."""

import json

import pytest

from leadscout import config, db
from leadscout.pitch import jobs


@pytest.fixture
def con(tmp_path):
    return db.connect(tmp_path / "t.db")


@pytest.fixture
def cfg():
    return config.load()


def _lead(con, bid="b1", status="new", email="owner@clinic.in", site_class="none", **audit):
    con.execute("insert into businesses (id, source, name, fetched_at, area, city) values (?, 'overture', 'Smile Dental', '2026-11-20', 'Baner, Pune', 'Pune')", (bid,))
    cols = ", ".join(["business_id", "site_class", "audited_at", *audit])
    marks = ", ".join("?" * (3 + len(audit)))
    con.execute(f"insert into audits ({cols}) values ({marks})", (bid, site_class, "2026-11-20", *audit.values()))
    con.execute("insert into leads (business_id, score, status, email, updated_at) values (?, 80, ?, ?, '2026-11-20')", (bid, status, email))
    con.commit()


def _status(con, bid="b1"):
    return con.execute("select status from leads where business_id = ?", (bid,)).fetchone()[0]


PITCH = {"subject": "Hi", "body": "Hello", "whatsapp": "hey"}


# ---- 1. Saving a pitch must not reset contacted leads --------------------------------------

@pytest.mark.parametrize("before,after", [("new", "drafted"), ("drafted", "drafted"), ("approved", "drafted"),
                                          ("contacted", "contacted"), ("replied", "replied"), ("won", "won")])
def test_save_pitch_only_moves_early_leads(con, before, after):
    _lead(con, status=before)
    jobs.save_pitch(con, "b1", PITCH, "edited")
    assert _status(con) == after
    assert con.execute("select body from pitches").fetchone()[0] == "Hello"


def test_import_results_skips_contacted_leads(con, cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "data_dir", lambda: tmp_path)
    _lead(con, "b1", status="new")
    _lead(con, "b2", status="contacted")
    jobs.results_path().write_text(json.dumps([{"id": "b1", **PITCH}, {"id": "b2", **PITCH}]), encoding="utf-8")
    n, rejected = jobs.import_results(con, cfg)
    assert n == 1 and rejected == []
    assert _status(con, "b2") == "contacted"
    assert con.execute("select count(*) from pitches where business_id = 'b2'").fetchone()[0] == 0


@pytest.fixture
def web(tmp_path, monkeypatch):
    """Dashboard client on an empty temp project folder (no lifespan, so no search worker)."""
    from fastapi.testclient import TestClient

    from leadscout.web.app import app

    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    return TestClient(app, base_url="http://127.0.0.1:8000"), db.connect()


def test_pitch_editor_is_read_only_after_sending(web):
    client, con = web
    _lead(con, status="contacted")
    jobs.save_pitch(con, "b1", PITCH, "template")
    con.commit()
    assert 'action="/leads/b1/pitch"' in client.get("/leads/b1").text  # not sent yet: editable
    con.execute("insert into outreach (business_id, channel, kind, to_addr, sent_at) values ('b1', 'email', 'first', 'owner@clinic.in', '2026-11-20T10:00:00+05:30')")
    con.commit()
    page = client.get("/leads/b1").text
    assert 'action="/leads/b1/pitch"' not in page and "readonly" in page
