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
    emailcheck._known.clear()
    yield answers
    emailcheck._known.clear()


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


class FlakyGmail:
    """Fails to send to the addresses in `bad`; everything else 'sends' (in memory)."""

    def __init__(self, bad=()):
        self.bad, self.sent = set(bad), []

    def incoming(self, thread_id, me):
        return []

    def message_id_header(self, gid):
        return None

    def send(self, to, subject, body, sender, thread_id=None, in_reply_to=None, unsubscribe=None):
        if to in self.bad or "*" in self.bad:
            raise RuntimeError("Gmail 500")
        self.sent.append(to)
        return {"id": f"s{len(self.sent)}", "threadId": f"t{len(self.sent)}"}


def _approved(con, bid, email, score):
    _lead(con, bid, status="approved", email=email)
    con.execute("update leads set score = ? where business_id = ?", (score, bid))
    con.execute("insert into pitches (business_id, subject, body, source, approved, created_at, updated_at) values (?, 'S', 'B', 'template', 1, 'x', 'x')", (bid,))
    con.commit()


@pytest.fixture
def no_wait(monkeypatch):
    from leadscout.mailer import sender

    monkeypatch.setattr(sender, "in_window", lambda *a: True)
    monkeypatch.setattr(sender.time, "sleep", lambda s: None)


def test_send_error_marks_lead_and_moves_on(con, cfg, no_wait):
    from leadscout.mailer import sender

    _approved(con, "b1", "first@clinic.in", 90)  # best score: picked first, and fails
    _approved(con, "b2", "second@clinic.in", 80)
    gm = FlakyGmail(bad={"first@clinic.in"})
    logs = []
    sender.run(con, cfg, gm, log=logs.append)
    assert _status(con, "b1") == "send_failed" and _status(con, "b2") == "contacted"
    assert gm.sent == ["second@clinic.in"] and any("first@clinic.in" in m for m in logs)


def test_repeated_send_errors_stop_the_run(con, cfg, no_wait):
    from leadscout.mailer import sender

    for i in range(5):
        _approved(con, f"b{i}", f"o{i}@clinic.in", 90 - i)
    sender.run(con, cfg, FlakyGmail(bad={"*"}), log=lambda m: None)
    statuses = [r[0] for r in con.execute("select status from leads order by business_id")]
    assert statuses.count("send_failed") == 3 and statuses.count("approved") == 2


# ---- 5. A short internet drop never wipes lead emails --------------------------------------

def test_dns_timeouts_are_unknown_and_not_cached(fake_dns):
    import dns.exception

    from leadscout import emailcheck

    fake_dns["clinic.in"] = dns.exception.Timeout
    assert emailcheck.domain_accepts_mail("clinic.in") is None
    fake_dns["clinic.in"] = True  # back online
    assert emailcheck.domain_accepts_mail("clinic.in") is True
    assert emailcheck.domain_accepts_mail("gone.in") is False  # NXDOMAIN: definite, cached
    fake_dns["gone.in"] = True
    assert emailcheck.domain_accepts_mail("gone.in") is False


@pytest.mark.parametrize("status", ["new", "approved", "contacted", "replied", "won"])
def test_dns_outage_keeps_lead_emails(con, cfg, fake_dns, status):
    import dns.exception

    from leadscout.scoring import score_all

    _lead(con, status=status)
    con.execute("""update businesses set emails = '["owner@clinic.in"]'""")
    con.commit()
    fake_dns["clinic.in"] = dns.exception.Timeout
    score_all(con, cfg)
    assert con.execute("select email from leads").fetchone()[0] == "owner@clinic.in"


@pytest.mark.parametrize("status,kept", [("new", False), ("approved", True), ("contacted", True), ("replied", True), ("won", True)])
def test_dead_domain_only_clears_email_before_contact(con, cfg, fake_dns, status, kept):
    from leadscout.scoring import score_all

    _lead(con, status=status)  # clinic.in answers NXDOMAIN
    con.execute("""update businesses set emails = '["owner@clinic.in"]'""")
    con.commit()
    score_all(con, cfg)
    assert (con.execute("select email from leads").fetchone()[0] == "owner@clinic.in") is kept


def test_suppression_handles_missing_values(con):
    from leadscout.compliance import is_suppressed, suppress

    suppress(con, None, "bounced")  # a lead without an email
    assert not is_suppressed(con, None) and not is_suppressed(con, None, "")
    assert con.execute("select count(*) from suppression").fetchone()[0] == 0


# ---- 6. Security ---------------------------------------------------------------------------

def test_names_never_land_inside_inline_javascript(web):
    client, con = web
    evil = "Raju's Café');alert(1);//"
    _lead(con, status="drafted")
    con.execute("update businesses set name = ?, area = ?", (evil, evil))
    con.execute("insert into pitches (business_id, subject, body, source, approved, created_at, updated_at) values ('b1', 'S', 'B', 'template', 0, 'x', 'x')")
    con.commit()
    for page in (client.get("/leads/b1").text, client.get("/pitches", params={"area": evil}).text):
        assert "return confirm(" not in page and "data-confirm=" in page
        assert "');alert(1)" not in page  # only the escaped form appears


@pytest.mark.parametrize("headers,ok", [
    ({"Origin": "http://127.0.0.1:8000"}, True),
    ({"Origin": "http://localhost:8000"}, True),
    ({"Referer": "http://127.0.0.1:8000/pitches?area=x"}, True),
    ({"Origin": "https://evil.com"}, False),
    ({"Origin": "http://127.0.0.1:9999"}, False),
    ({"Origin": "null"}, False),
    ({"Referer": "http://127.0.0.1:8000.evil.com/"}, False),
    ({"Origin": "https://evil.com", "Referer": "http://127.0.0.1:8000/"}, False),
    ({}, True),  # browsers always send Origin or Referer on a form POST; a bare request isn't cross-site
])
def test_posts_need_a_local_origin(web, headers, ok):
    client, con = web
    r = client.post("/pitches/approve-all", headers=headers, follow_redirects=False)
    assert (r.status_code == 303) is ok and (r.status_code == 403) is (not ok)


def test_htmx_approve_still_works(web):
    client, con = web
    _lead(con, status="drafted")
    con.execute("insert into pitches (business_id, subject, body, source, approved, created_at, updated_at) values ('b1', 'S', 'B', 'template', 0, 'x', 'x')")
    con.commit()
    htmx = {"HX-Request": "true", "Origin": "http://127.0.0.1:8000", "Referer": "http://127.0.0.1:8000/pitches"}
    assert client.post("/leads/b1/approve", headers=htmx).status_code == 200
    assert _status(con) == "approved"
    assert client.get("/pitches").status_code == 200  # GETs need no Origin


LOCAL = {"Origin": "http://127.0.0.1:8000"}


@pytest.mark.parametrize("back,goes_to", [
    ("/leads?status=new", "/leads?status=new"),
    ("//evil.com", "/leads/b1"),
    ("/\evil.com", "/leads/b1"),
    ("https://evil.com", "/leads/b1"),
    ("", "/leads/b1"),
])
def test_hide_only_redirects_within_the_dashboard(web, back, goes_to):
    client, con = web
    _lead(con, status="new")
    r = client.post("/leads/b1/hide", data={"back": back}, headers=LOCAL, follow_redirects=False)
    assert r.headers["location"] == goes_to


# ---- 7. Expired Gmail login ----------------------------------------------------------------

class FakeCreds:
    def __init__(self, refresh_token="r", fails=False):
        self.valid, self.refresh_token, self.fails = False, refresh_token, fails

    def refresh(self, request):
        from google.auth.exceptions import RefreshError

        if self.fails:
            raise RefreshError("invalid_grant: Token has been expired or revoked.")
        self.valid = True

    def to_json(self):
        return "{}"


@pytest.mark.parametrize("creds", [FakeCreds(fails=True), FakeCreds(refresh_token=None)])
def test_expired_gmail_login_says_log_in_again(tmp_path, monkeypatch, creds):
    from leadscout.mailer import gmail

    token = tmp_path / "gmail_token.json"
    token.write_text("{}")
    monkeypatch.setattr(gmail, "_token_path", lambda: token)
    monkeypatch.setattr(gmail.Credentials, "from_authorized_user_file", lambda *a: creds)
    with pytest.raises(RuntimeError, match="gmail-login"):
        gmail.Gmail()


# ---- 8. Export respects the suppression list -----------------------------------------------

def test_export_skips_suppressed_bounced_and_hidden(tmp_path, monkeypatch):
    import csv

    from typer.testing import CliRunner

    from leadscout.cli import app
    from leadscout.compliance import suppress

    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    con = db.connect()
    _lead(con, "keep", status="new", email="keep@a.in")
    _lead(con, "mail_out", status="new", email="gone@a.in")
    _lead(con, "phone_out", status="new", email="other@a.in")
    _lead(con, "bounced", status="bounced", email="b@a.in")
    _lead(con, "hidden", status="hidden", email="h@a.in")
    con.execute("update businesses set phone = '+919848022338' where id = 'phone_out'")
    con.commit()
    suppress(con, "GONE@a.in", "test")
    suppress(con, "098480 22338", "test")
    out = tmp_path / "leads.csv"
    result = CliRunner().invoke(app, ["export", str(out)])
    assert result.exit_code == 0, result.output
    emails = [r["email"] for r in csv.DictReader(out.open(encoding="utf-8-sig"))]
    assert emails == ["keep@a.in"]


# ---- 9. No pitches or sends signed "Your Name" ---------------------------------------------

REAL_SENDER = """[sender]
name = "Asha Rao"
business = "Rao Web Studio"
city = "Hyderabad"
phone = "+91 98480 11111"
email = "asha.outreach@gmail.com"
portfolio = "https://asharao.in"
"""


def _write_config(home, sender=REAL_SENDER):
    example = (config.Path(config.__file__).resolve().parents[2] / "config.example.toml").read_text(encoding="utf-8")
    rest = example[example.index("[pitch]"):]
    (home / "config.toml").write_text(sender + "\n" + rest, encoding="utf-8")


def test_sender_problem(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    assert "leadscout init" in config.sender_problem(config.load())  # no config.toml: example values in use
    _write_config(tmp_path, sender=(config.Path(config.__file__).resolve().parents[2] / "config.example.toml").read_text(encoding="utf-8").split("[pitch]")[0])
    problem = config.sender_problem(config.load())
    assert "name" in problem and "phone" in problem
    _write_config(tmp_path)
    assert config.sender_problem(config.load()) is None


def test_cli_refuses_to_draft_or_send_with_example_sender(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from leadscout.cli import app

    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    for args in (["pitch", "--templates", "5"], ["pitch", "--prepare", "5"], ["send"]):
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 1 and "leadscout init" in result.output, args


def test_dashboard_refuses_to_draft_with_example_sender(web):
    client, con = web
    _lead(con, status="new")
    r = client.post("/leads/b1/draft", headers=LOCAL, follow_redirects=False)
    assert "msg=" in r.headers["location"]
    assert con.execute("select count(*) from pitches").fetchone()[0] == 0


# ---- 10. Broken SSL certificates -----------------------------------------------------------

def test_broken_certificate_is_recorded_not_hidden():
    import asyncio

    import httpx
    import respx

    from leadscout.audit.site import audit_site

    html = '<html><head><meta name="viewport" content="width=device-width"></head><body>' + "Welcome " * 30 + \
           '<a href="mailto:hi@clinic.in">mail</a></body></html>'

    async def go():
        async with httpx.AsyncClient() as client:
            return await audit_site(client, "https://clinic.in")

    with respx.mock:
        respx.get("https://clinic.in").mock(side_effect=[
            httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"),
            httpx.Response(200, html=html),
        ])
        r = asyncio.run(go())
    assert r["site_class"] == "real" and r["https"] == 0 and r["fetch_error"] == "bad_certificate"
    assert r["viewport"] == 1 and r["found_emails"] == {"hi@clinic.in"}  # the page was still checked


def test_broken_certificate_reason_and_pitch(cfg):
    from leadscout.pitch import templates
    from leadscout.scoring import site_need

    a = {"site_class": "real", "fetch_error": "bad_certificate", "https": 0, "perf_score": 80, "lcp_s": 2.0,
         "viewport": 1, "copyright_year": 2026, "has_whatsapp": 1, "has_tel": 1}
    pts, why = site_need(a)
    assert pts > 0 and any("security warning" in w for w in why) and not any("No HTTPS" in w for w in why)
    body = templates.render({**a, "name": "Smile", "category": "dentist", "website": "https://clinic.in"}, cfg)["body"]
    assert "browsers show a security warning" in body and "Not secure" not in body
