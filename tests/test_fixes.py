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


# ---- 2. Opt-out detection ------------------------------------------------------------------

@pytest.mark.parametrize("reply", [
    "No", "no.", "No thanks", "No, thank you.", "Nope.", "Not interested, thanks", "Not interested",
    "Nahi", "Nahin ji, thank you", "nahi chahiye", "No thanks, we already have a website.",
    "Please unsubscribe me", "Remove me from your list", "Stop emailing me.", "Don't email me again",
    "Do not contact us", "Hi, please stop sending these. Thanks",
])
def test_opt_out_replies(reply):
    from leadscout.mailer.gmail import is_opt_out

    assert is_opt_out(reply)


# main deliberately errs towards opting out (losing a lead is cheaper than emailing someone who said no),
# so borderline replies like "No, all good. Thanks!" or "Not interested in SEO. But a new site, yes."
# count as opt-outs there. Only replies both rules agree on are pinned here.
@pytest.mark.parametrize("reply", [
    "No problem, please send the mockup", "Yes send it", "How much would it cost?", "No worries, call me tomorrow",
    "Nothing to add, send the mockup", "",
])
def test_not_opt_out_replies(reply):
    from leadscout.mailer.gmail import is_opt_out

    assert not is_opt_out(reply)


def _contacted(con, status):
    _lead(con, status=status)
    con.execute("insert into outreach (business_id, channel, kind, to_addr, gmail_id, thread_id, sent_at) values ('b1', 'email', 'first', 'owner@clinic.in', 'g1', 't1', '2026-11-20T10:00:00+05:30')")
    con.commit()


class InboxOnly:
    def __init__(self, kind, body="Not interested"):
        self.msgs = [{"id": "m1", "from": "owner@clinic.in", "subject": "Re", "body": body, "received_ms": 1795000000000, "kind": kind}]

    def incoming(self, thread_id, me):
        return self.msgs


def test_won_lead_is_never_auto_opted_out(con, cfg):
    from leadscout.compliance import is_suppressed
    from leadscout.mailer import sender

    _contacted(con, "won")
    sender.check_replies(con, cfg, InboxOnly("opted_out"))
    assert _status(con) == "won" and not is_suppressed(con, "owner@clinic.in")
    assert con.execute("select count(*) from replies").fetchone()[0] == 1  # still saved for you to read


# ---- 3. Delay notices are not bounces ------------------------------------------------------

class FakeResp:
    def __init__(self, data):
        self.status_code, self._data = 200, data

    def json(self):
        return self._data


def _gmail_with(messages):
    from leadscout.mailer.gmail import Gmail

    g = Gmail.__new__(Gmail)  # skip the OAuth login
    thread = {"messages": [{"id": f"m{i}", "internalDate": "1795000000000", "snippet": body,
                            "payload": {"headers": [{"name": "From", "value": frm}, {"name": "Subject", "value": subj}]}}
                           for i, (frm, subj, body) in enumerate(messages)]}
    g.s = type("S", (), {"get": lambda self, *a, **k: FakeResp(thread)})()
    return g


DAEMON = "Mail Delivery Subsystem <mailer-daemon@googlemail.com>"


@pytest.mark.parametrize("frm,subject,expected", [
    (DAEMON, "Delivery Status Notification (Failure)", "bounced"),
    (DAEMON, "Undeliverable: Smile Dental", "bounced"),
    ("postmaster@clinic.in", "Mail delivery failed: returning message to sender", "bounced"),
    (DAEMON, "Delivery Status Notification (Delay)", None),
    (DAEMON, "Warning: message delayed", None),
    ("owner@clinic.in", "Re: Smile Dental", "replied"),
])
def test_only_real_failures_are_bounces(frm, subject, expected):
    g = _gmail_with([(frm, subject, "Hello, how much?")])
    kinds = [m["kind"] for m in g.incoming("t1", "me@gmail.com")]
    assert kinds == ([expected] if expected else [])


# ---- 4. One bad record never breaks a whole step -------------------------------------------

def _business(con, bid, website=None, emails="[]"):
    con.execute("insert into businesses (id, source, name, website, emails, fetched_at) values (?, 'overture', ?, ?, ?, '2026-11-20')",
                (bid, f"Biz {bid}", website, emails))
    con.commit()


@pytest.mark.parametrize("url", ["http://site.com:80a"])
def test_invalid_url_is_recorded_as_broken(url):
    import asyncio

    import httpx
    import respx

    from leadscout.audit.site import audit_site

    async def go():
        async with httpx.AsyncClient() as client:
            return await audit_site(client, url)

    with respx.mock:  # nothing may reach the network
        r = asyncio.run(go())
    assert r["site_class"] == "broken" and r["fetch_error"] == "invalid_url"


def test_one_failing_business_does_not_stop_the_audit(con, monkeypatch):
    from leadscout import audit

    _business(con, "ok", "https://good.in")
    _business(con, "bad", "https://bad.in")

    async def fake(client, url):
        if "bad" in url:
            raise RuntimeError("boom")
        return {"site_class": "real", "final_url": url, "https": 1}

    monkeypatch.setattr(audit, "audit_site", fake)
    assert audit.audit_pending(con, run_psi=False) == 2
    got = dict(con.execute("select business_id, site_class from audits").fetchall())
    assert got == {"ok": "real", "bad": "broken"}
    assert audit.audit_pending(con, run_psi=False) == 0  # nothing left pending to block later searches


@pytest.fixture
def fake_dns(monkeypatch):
    """DNS without the network: parse the name like dnspython does, then answer from `answers`."""
    import dns.name
    import dns.resolver

    from leadscout import emailcheck

    answers = {}

    def resolve(domain, rtype, lifetime=None):
        dns.name.from_text(domain)  # raises EmptyLabel for "abc..com", as the real resolver does
        outcome = answers.get(domain, dns.resolver.NXDOMAIN)
        if outcome is True:
            return ["mx"]
        raise outcome()

    monkeypatch.setattr(dns.resolver, "resolve", resolve)
    emailcheck.domain_accepts_mail.cache_clear()
    yield answers
    emailcheck.domain_accepts_mail.cache_clear()


def test_email_with_empty_label_is_rejected_without_crashing(con, cfg, fake_dns):
    from leadscout import emailcheck
    from leadscout.scoring import score_all

    assert not emailcheck.EMAIL_RE.match("info@abc..com")
    assert not emailcheck.EMAIL_RE.match("info@.abc.com")
    assert emailcheck.EMAIL_RE.match("info@abc.co.in")
    assert emailcheck.domain_accepts_mail("abc..com") is False
    _business(con, "b1", emails='["info@abc..com"]')
    con.execute("insert into audits (business_id, site_class, audited_at) values ('b1', 'none', '2026-11-20')")
    score_all(con, cfg)  # used to raise EmptyLabel on every run
    assert con.execute("select email from leads").fetchone()[0] is None
