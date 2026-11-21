from datetime import date, datetime, timedelta

import pytest

from leadscout import config, db
from leadscout.audit.classify import classify_static
from leadscout.audit.site import check_html
from leadscout.compliance import in_window, is_suppressed, normalize, suppress
from leadscout.config import IST
from leadscout.mailer import sender
from leadscout.mailer.gmail import NO_WORDS
from leadscout.pitch import templates
from leadscout.sources.common import phone_info, pick_website


@pytest.fixture
def con(tmp_path):
    return db.connect(tmp_path / "t.db")


@pytest.fixture
def cfg():
    # Always the example config, so a user's own config.toml can't change test results.
    import tomllib
    from pathlib import Path
    with open(Path(__file__).resolve().parents[1] / "config.example.toml", "rb") as f:
        return config.Config(tomllib.load(f))


@pytest.mark.parametrize(
    "url,expected",
    [
        (None, "none"),
        ("https://www.instagram.com/oxydental", "social_only"),
        ("https://www.justdial.com/Hyderabad/x", "directory_only"),
        ("https://swarnadental.business.site", "dead_google_site"),
        ("http://mysite.blogspot.com", "free_subdomain"),
        ("https://nysainteriors.com", None),
    ],
)
def test_classify_static(url, expected):
    assert classify_static(url) == expected


def test_pick_website_prefers_own_site():
    assert pick_website(["https://facebook.com/x", "https://own.in"]) == "https://own.in"
    assert pick_website(["https://facebook.com/x"]) == "https://facebook.com/x"


def test_phone_info_mobile_and_landline():
    assert phone_info("098480 22338") == ("+919848022338", "mobile")
    assert phone_info("+914023456789")[1] == "landline"
    assert phone_info("12") == (None, None)


def test_check_html_finds_problems_and_emails():
    html = """<html><head><meta name="generator" content="WordPress 5.2"></head><body>
    <p>Call us</p><a href="mailto:hello@clinic.in">mail</a><p>© 2016 Clinic</p></body></html>"""
    r = check_html(html)
    assert r["viewport"] == 0 and r["copyright_year"] == 2016 and r["has_whatsapp"] == 0
    assert r["emails"] == {"hello@clinic.in"}


def test_js_site_with_little_text_is_not_parked():
    assert check_html("<html><body><div id=root></div><script src=app.js></script></body></html>")["parked"] is False
    assert check_html("<html><body>Buy this domain</body></html>")["parked"] is True


def test_suppression_is_hashed_and_normalized(con):
    suppress(con, "Owner@Clinic.IN", "test")
    assert is_suppressed(con, "owner@clinic.in")
    suppress(con, "98480 22338", "test")
    assert is_suppressed(con, "+919848022338")
    stored = con.execute("select value_hash from suppression").fetchall()
    assert all("@" not in r[0] for r in stored)
    assert normalize("98480 22338") == "+919848022338"


def test_sending_window_ist(cfg):
    assert in_window(cfg.sending, datetime(2026, 11, 21, 11, 0, tzinfo=IST))  # Saturday 11:00
    assert not in_window(cfg.sending, datetime(2026, 11, 22, 11, 0, tzinfo=IST))  # Sunday
    assert not in_window(cfg.sending, datetime(2026, 11, 21, 18, 0, tzinfo=IST))


def test_warmup_cap(con, cfg):
    assert sender.daily_cap(con, cfg) == 15
    db.set_meta(con, "first_send_date", (date.today() - timedelta(days=9)).isoformat())
    assert sender.daily_cap(con, cfg) == 30
    db.set_meta(con, "first_send_date", (date.today() - timedelta(days=40)).isoformat())
    assert sender.daily_cap(con, cfg) == 50


@pytest.mark.parametrize(
    "reply,is_no",
    [("No thanks", True), ("Not interested", True), ("no.", True), ("No problem, please send the mockup", False), ("Yes send it", False),
     ("nahi chahiye", True), ("Abhi nahi", True), ("No need", True), ("not now, thanks", True), ("Please remove my email", True),
     ("We are not looking", True), ("We don't need a website", True), ("Zaroorat nahi hai", True), ("Do not contact us", True),
     ("I don't need much, just a simple site", False), ("Is there no cheaper option?", False), ("Haan, bhejiye", False)],
)
def test_reply_no_detection(reply, is_no):
    assert bool(NO_WORDS.search(reply)) is is_no


def test_template_uses_only_measured_facts(cfg):
    f = {"name": "Swarna Dental", "category": "dental_clinic", "locality": "Kukatpally", "site_class": "broken",
         "fetch_error": "dns", "website": "http://swarnadental.in"}
    p = templates.render(f, cfg)
    assert "stopped working" in p["subject"] and "swarnadental.in" in p["body"]
    assert templates.OPT_OUT in p["body"] and len(p["whatsapp"]) <= 600
    slow = {"name": "Nysa", "category": "interior_design", "locality": "KPHB", "site_class": "real", "lcp_s": 7.8,
            "perf_score": 31, "https": 1, "viewport": 1, "copyright_year": 2026, "has_whatsapp": 1}
    assert "7.8s" in templates.render(slow, cfg)["subject"]


def test_location_line_is_honest(cfg):
    local = {"name": "A", "category": "dentist", "city": "Secunderabad", "area": "Begumpet, Secunderabad", "site_class": "none"}
    away = {"name": "B", "category": "dentist", "city": "Pune", "area": "Baner, Pune", "site_class": "none"}
    home = cfg.sender["city"]  # Hyderabad in the example config
    assert f"here in {home}" in templates.render(local, cfg)["body"]
    body = templates.render(away, cfg)["body"]
    assert f"based in {home}" in body and "across India" in body and f"here in {home}" not in body
    assert "dentists in Baner" in body


def test_queue_search_validates(con):
    from leadscout import searches

    with pytest.raises(ValueError):
        searches.queue_search(con, "Pune", "", [])
    with pytest.raises(ValueError):
        searches.queue_search(con, "  ", "", ["dental"])
    sid = searches.queue_search(con, "Pune", "Baner", ["dental", "salons"])
    row = con.execute("select * from searches where id = ?", (sid,)).fetchone()
    assert row["label"] == "Baner, Pune" and row["status"] == "queued"
    assert "dentist" in row["categories"] and "Salons and spas" in row["categories"]


def test_old_database_gets_city_column(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("create table businesses (id text primary key, source text not null, name text not null, area text, fetched_at text not null)")
    old.execute("insert into businesses values ('x', 'overture', 'Old Dental', 'Kukatpally, Hyderabad', '2026-11-01')")
    old.commit()
    old.close()
    con = db.connect(path)
    assert con.execute("select city from businesses where id = 'x'").fetchone()[0] == "Hyderabad"


def _seed_lead(con, bid="b1", status="contacted", email="owner@clinic.in"):
    con.execute("insert into businesses (id, source, name, fetched_at, area, city) values (?, 'overture', 'Smile Dental', '2026-11-20', 'Baner, Pune', 'Pune')", (bid,))
    con.execute("insert into audits (business_id, site_class, audited_at) values (?, 'none', '2026-11-20')", (bid,))
    con.execute("insert into leads (business_id, score, status, email, updated_at) values (?, 80, ?, ?, '2026-11-20')", (bid, status, email))
    con.execute("insert into outreach (business_id, channel, kind, to_addr, gmail_id, thread_id, sent_at) values (?, 'email', 'first', ?, 'g1', 't1', '2026-11-20T10:00:00+05:30')", (bid, email))
    con.commit()


class FakeGmail:
    def __init__(self, messages):
        self.messages, self.sent = messages, []

    def incoming(self, thread_id, me):
        return self.messages

    def message_id_header(self, gid):
        return "<abc@mail>"

    def send(self, to, subject, body, sender, thread_id=None, in_reply_to=None):
        self.sent.append((to, subject, body, thread_id, in_reply_to))
        return {"id": f"s{len(self.sent)}", "threadId": thread_id}


def test_replies_are_saved_and_answerable(con, cfg):
    _seed_lead(con)
    gm = FakeGmail([{"id": "m1", "from": "Owner <owner@clinic.in>", "subject": "Re: Smile Dental", "body": "How much would it cost?",
                     "received_ms": 1795000000000, "kind": "replied"}])
    assert sender.check_replies(con, cfg, gm)["replied"] == 1
    assert sender.check_replies(con, cfg, gm)["replied"] == 0  # not saved twice
    assert con.execute("select status from leads").fetchone()[0] == "replied"
    sender.send_reply(con, cfg, gm, "b1", "It costs ₹15,000.")
    to, subject, body, thread, ref = gm.sent[0]
    assert to == "owner@clinic.in" and subject == "Re: Smile Dental" and thread == "t1" and ref == "<abc@mail>"
    assert sender.sent_today(con) == 0  # replies don't use the cold-email cap


def test_later_no_thanks_opts_out(con, cfg):
    _seed_lead(con, status="replied")
    gm = FakeGmail([{"id": "m2", "from": "owner@clinic.in", "subject": "Re", "body": "Not interested, thanks", "received_ms": 1795000000000, "kind": "opted_out"}])
    sender.check_replies(con, cfg, gm)
    assert con.execute("select status from leads").fetchone()[0] == "opted_out"
    assert is_suppressed(con, "owner@clinic.in")


def test_quick_replies_block_unfilled_brackets(cfg):
    from leadscout.pitch import quick_replies

    text = quick_replies.fill(quick_replies.DEFAULTS["Price"], {"name": "Smile Dental"}, cfg)
    assert "Smile Dental" in text and quick_replies.unfilled(text)
    assert not quick_replies.unfilled(quick_replies.fill(quick_replies.DEFAULTS["Not now"], {"name": "X"}, cfg))


def test_inr_grouping():
    from leadscout.web.extras import inr, rupees

    assert inr(125000) == "₹1,25,000" and inr(999) == "₹999" and inr(10000000) == "₹1,00,00,000"
    assert rupees("₹15,000") == 15000 and rupees("") is None


def test_hidden_lead_stays_hidden_after_rescoring(con, cfg):
    from leadscout.scoring import score_all

    _seed_lead(con, status="hidden")
    score_all(con, cfg)
    assert con.execute("select status from leads").fetchone()[0] == "hidden"


def test_strip_quoted_and_icon(tmp_path):
    from leadscout.launch import write_icon
    from leadscout.mailer.gmail import strip_quoted

    assert strip_quoted("Yes please\n\nOn Mon, 24 Nov 2026, Ravi <r@x.in> wrote:\n> Hi") == "Yes please"
    icon = tmp_path / "i.ico"
    write_icon(icon)
    assert icon.read_bytes()[:4] == b"\x00\x00\x01\x00" and icon.stat().st_size > 500


def test_places_find_other_names_and_show_state():
    from leadscout import places

    margao = places.search("madg")[0]
    assert margao["name"] == "Madgaon" and margao["state"] == "Goa" and "South Goa" in margao["label"]
    assert places.search("margao")[0]["id"] == margao["id"]
    assert places.search("bangalore")[0]["name"] == "Bengaluru"
    assert places.search("vizag")[0]["name"] == "Visakhapatnam"
    assert places.best_match("Margao")["state"] == "Goa"  # typed, not picked: still Goa, never Chhattisgarh
    assert places.search("zzzqqq") == []


def test_search_is_anchored_on_the_picked_place(con):
    from leadscout import places, searches

    pid = places.search("margao")[0]["id"]
    sid = searches.queue_search(con, "Margao", "", ["dental"], place_id=pid)
    s = con.execute("select * from searches where id = ?", (sid,)).fetchone()
    assert s["state"] == "Goa" and s["label"] == "Madgaon"
    xmin, ymin, xmax, ymax = searches.area_box(s)
    assert xmin < 73.96 < xmax and ymin < 15.28 < ymax  # around Margao, Goa
    with pytest.raises(ValueError):
        searches.queue_search(con, "Nowheretown", "", ["dental"])


def test_home_state_counts_its_towns_as_local():
    for city in ("Madgaon", "margao goa", "Panaji", "goa"):
        assert templates.is_local({"city": city}, "Goa"), city
    assert not templates.is_local({"city": "Pune"}, "Goa")
    assert not templates.is_local({"city": "Hyderabad"}, "Goa")


def test_signature_skips_blank_sender_details(cfg):
    cfg.sender.update(name="", phone="", portfolio="", business="Shinnen Creative", city="Goa")
    f = {"name": "Cafe X", "category": "cafe", "city": "Panaji", "site_class": "none"}
    p = templates.render(f, cfg)
    assert "Regards,\nShinnen Creative, Goa\n\n" in p["body"] and "here in Goa" in p["body"]
    assert p["whatsapp"].startswith("Hi, this is Shinnen Creative in Goa.")
    assert "Your Name" not in p["body"] and "github" not in p["body"]


# ---- Regression tests for the compliance and safety fixes ----------------------------------

def test_forget_matches_exact_email_only(con):
    from leadscout.compliance import forget

    for bid, email in (("A", "aa@shop.in"), ("B", "a@shop.in")):
        con.execute("insert into businesses (id, source, name, emails, fetched_at) values (?, 't', ?, ?, '2026-11-20')",
                    (bid, bid, f'["{email}"]'))
    con.commit()
    assert forget(con, "A@Shop.in") == 1
    assert [r[0] for r in con.execute("select id from businesses")] == ["A"]
    assert is_suppressed(con, "a@shop.in")


def test_followup_respects_phone_optout(con, cfg):
    _seed_lead(con)
    con.execute("update businesses set phone = '+919000000003'")
    con.execute("insert into pitches (business_id, subject, body, source, approved, created_at, updated_at) values ('b1', 's', 'b', 't', 1, '2026-11-20', '2026-11-20')")
    suppress(con, "90000 00003", "said no on WhatsApp")
    item = sender.next_item(con, cfg)
    assert item["kind"] == "followup"
    assert sender.send_one(con, cfg, None, item, dry_run=True).startswith("skipped")


def test_reply_no_also_blocks_the_phone(con, cfg):
    _seed_lead(con)
    con.execute("update businesses set phone = '+919000000005'")
    con.commit()
    gm = FakeGmail([{"id": "m3", "from": "owner@clinic.in", "subject": "Re", "body": "nahi chahiye", "received_ms": 1795000000000, "kind": "opted_out"}])
    sender.check_replies(con, cfg, gm)
    assert is_suppressed(con, "+919000000005")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway project folder, so CLI and dashboard use a temporary database."""
    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    con = db.connect()
    _seed_lead(con)
    con.execute("update businesses set phone = '+919000000007', phone_type = 'mobile'")
    con.commit()
    return con


def test_export_and_cli_optout_use_the_optout_list(home, tmp_path):
    from typer.testing import CliRunner

    from leadscout.cli import app as cli

    out = tmp_path / "leads.csv"
    CliRunner().invoke(cli, ["optout", "90000 00007"], catch_exceptions=False)  # by phone
    assert home.execute("select status from leads").fetchone()[0] == "opted_out"
    home.execute("update leads set status = 'new'")  # status lagging behind the list
    home.commit()
    CliRunner().invoke(cli, ["export", str(out)], catch_exceptions=False)
    assert "owner@clinic.in" not in out.read_text(encoding="utf-8-sig")


@pytest.fixture
def client(home):
    from fastapi.testclient import TestClient

    from leadscout.web.app import app

    return TestClient(app, base_url="http://127.0.0.1:8000")


def test_dashboard_blocks_other_sites(client):
    assert client.post("/pitches/approve-all", headers={"Origin": "https://evil.example"}, follow_redirects=False).status_code == 403
    assert client.post("/pitches/approve-all", headers={"Origin": "null"}, follow_redirects=False).status_code == 403
    assert client.get("/find", headers={"Host": "evil.example:8000"}).status_code == 403  # DNS rebinding
    assert client.post("/pitches/approve-all", headers={"Origin": "http://127.0.0.1:8000"}, follow_redirects=False).status_code == 303
    assert client.get("/leads/b1").status_code == 200


def test_hide_never_redirects_off_site(client):
    for back in ("//evil.example/x", r"/\evil.example", "https://evil.example"):
        r = client.post("/leads/b1/hide", data={"back": back}, follow_redirects=False)
        assert r.headers["location"] == "/leads/b1", back
    assert client.post("/leads/b1/hide", data={"back": "/leads?q=x"}, follow_redirects=False).headers["location"] == "/leads?q=x"


def test_dashboard_cannot_reopen_an_opted_out_lead(client, home):
    from leadscout.compliance import opt_out

    opt_out(home, "owner@clinic.in", "test")
    client.post("/leads/b1/status", data={"status": "new"}, follow_redirects=False)
    client.post("/leads/b1/deal", data={"status": "won", "quote_inr": "15000"}, follow_redirects=False)
    assert home.execute("select status from leads").fetchone()[0] == "opted_out"
    assert "Open WhatsApp chat" not in client.get("/leads/b1").text


def test_contact_page_is_fetched_from_the_site_root():
    import asyncio

    import httpx

    from leadscout.audit.site import audit_site

    seen = []
    home_page = "<html><head><script></script></head><body>" + "Welcome to our clinic. " * 10 + "</body></html>"

    def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/contact":
            return httpx.Response(200, html="<a href='mailto:hi@clinic.in'>Mail us</a>")
        return httpx.Response(200, html=home_page)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await audit_site(c, "http://clinic.in/home/index.html")

    assert asyncio.run(go())["found_emails"] == {"hi@clinic.in"}
    assert "/home/contact" not in seen


def test_expired_gmail_login_says_what_to_do(tmp_path, monkeypatch):
    from google.auth.exceptions import RefreshError

    from leadscout.mailer import gmail

    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    (db.data_dir() / "gmail_token.json").write_text("{}")

    class Expired:
        valid, refresh_token = False, "r"

        def refresh(self, _request):
            raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr(gmail.Credentials, "from_authorized_user_file", lambda *a: Expired())
    with pytest.raises(RuntimeError, match="gmail-login"):
        gmail.Gmail()


def test_pitch_has_no_borrowed_statistics(cfg):
    slow = {"name": "Nysa", "category": "interior_design", "locality": "KPHB", "site_class": "real", "lcp_s": 7.8,
            "perf_score": 31, "https": 1, "viewport": 1, "copyright_year": 2026, "has_whatsapp": 1}
    assert "research" not in templates.render(slow, cfg)["body"]


# ---- Improvements: pitch checks, unsubscribe, holidays, purge, WhatsApp cap, duplicates ----

def test_import_sets_aside_unmeasured_numbers(home, cfg):
    import json

    from leadscout.pitch import jobs

    _seed_lead(home, "b2")
    home.execute("update audits set site_class = 'real', lcp_s = 7.8, perf_score = 31 where business_id = 'b2'")
    home.execute("update leads set status = 'new'")  # only leads still waiting for a pitch take an imported one
    home.commit()
    jobs.results_path().write_text(json.dumps([
        {"id": "b2", "subject": "Your site takes 7.8s on mobile", "body": "It scores 31/100. Call +91 90000 00000.", "whatsapp": "7.8s"},
        {"id": "b1", "subject": "53% of visitors leave", "body": "Sites over 3 seconds lose 20 years of trust.", "whatsapp": ""},
    ]), encoding="utf-8")
    n, rejected = jobs.import_results(home, cfg)
    assert n == 1 and [r["id"] for r in rejected] == ["b1"]
    assert rejected[0]["unmeasured_numbers"] == ["3", "20", "53"]
    assert jobs.rejected_path().exists()
    assert home.execute("select count(*) from pitches").fetchone()[0] == 1


def test_cold_emails_carry_list_unsubscribe(con, cfg):
    import base64

    from leadscout.mailer.gmail import Gmail

    class Session:
        def post(self, url, json):
            self.raw = base64.urlsafe_b64decode(json["raw"]).decode()

            class R:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"id": "x", "threadId": "t"}
            return R()

    gm = Gmail.__new__(Gmail)
    gm.s = Session()
    _seed_lead(con, status="approved")
    con.execute("delete from outreach")
    con.execute("insert into pitches (business_id, subject, body, source, approved, created_at, updated_at) values ('b1', 'Hi', 'Body', 't', 1, '2026-11-20', '2026-11-20')")
    con.commit()
    sender.send_one(con, cfg, gm, sender.next_item(con, cfg))
    assert f"List-Unsubscribe: <mailto:{cfg.sender['email']}?subject=unsubscribe>" in gm.s.raw


def test_unsubscribe_button_opts_out(con, cfg):
    _seed_lead(con)

    class Gm(FakeGmail):
        def unsubscribe_requests(self, me, since=None):
            return {"owner@clinic.in"}

    assert sender.check_replies(con, cfg, Gm([]))["opted_out"] == 1
    assert con.execute("select status from leads").fetchone()[0] == "opted_out"
    assert sender.check_replies(con, cfg, Gm([]))["opted_out"] == 0  # counted once


def test_skip_dates_close_the_window(cfg):
    monday = datetime(2027, 1, 25, 11, 0, tzinfo=IST)
    assert in_window(cfg.sending, monday)
    assert not in_window({**cfg.sending, "skip_dates": ["2027-01-25"]}, monday)
    assert not in_window(cfg.sending, datetime(2027, 1, 26, 11, 0, tzinfo=IST))  # Republic Day, in the example config


def test_purge_runs_once_a_day(con, cfg):
    from leadscout.compliance import purge_if_due

    con.execute("insert into businesses (id, source, name, fetched_at) values ('old', 't', 'Old', '2020-01-01T10:00:00+05:30')")
    _seed_lead(con)  # contacted: kept however old
    con.execute("update businesses set fetched_at = '2020-01-01T10:00:00+05:30'")
    con.commit()
    assert purge_if_due(con, cfg) == 1
    assert purge_if_due(con, cfg) is None
    assert [r[0] for r in con.execute("select id from businesses")] == ["b1"]


def test_whatsapp_chats_are_counted_and_capped(client, home):
    r = client.post("/leads/b1/whatsapp", follow_redirects=False)
    assert r.headers["location"].startswith("https://wa.me/919000000007")
    assert home.execute("select count(*) from outreach where channel = 'whatsapp'").fetchone()[0] == 1
    assert "New chats today: 1 of 20" in client.get("/leads/b1").text

    _seed_lead(home, "b2")
    home.execute("update businesses set phone = '+919000000008', phone_type = 'mobile' where id = 'b2'")
    for _ in range(19):
        home.execute("insert into outreach (business_id, channel, kind, sent_at) values ('b1', 'whatsapp', 'first', ?)", (db.now(),))
    home.commit()
    blocked = client.post("/leads/b2/whatsapp", follow_redirects=False)
    assert blocked.headers["location"].startswith("/leads/b2?msg=")
    assert "Open WhatsApp chat" not in client.get("/leads/b2").text
    # Reopening a chat you already started isn't a new chat.
    assert client.post("/leads/b1/whatsapp", follow_redirects=False).headers["location"].startswith("https://wa.me/")


def test_duplicates_by_phone_or_own_site(con, cfg):
    from leadscout.scoring import score_all

    rows = [
        ("d1", "Smile Dental", "+919000000011", None, 0.9),
        ("d2", "Smile Dental Clinic Kukatpally", "+919000000011", None, 0.5),  # same phone
        ("s1", "Nysa Interiors", None, "https://nysa.in", 0.9),
        ("s2", "Nysa Interior Studio", None, "http://www.nysa.in/contact", 0.5),  # same own site
        ("g1", "Cafe One", None, "https://sites.google.com/view/cafeone", 0.9),
        ("g2", "Cafe Two", None, "https://sites.google.com/view/cafetwo", 0.9),  # shared host: different businesses
        ("g3", "Cafe Three", None, "https://sites.google.com/view/cafethree", 0.9),
    ]
    for bid, name, phone, site, conf in rows:
        con.execute("insert into businesses (id, source, name, phone, website, confidence, fetched_at) values (?, 't', ?, ?, ?, ?, '2026-11-20')",
                    (bid, name, phone, site, conf))
        con.execute("insert into audits (business_id, site_class, audited_at) values (?, ?, '2026-11-20')",
                    (bid, "free_subdomain" if site and "google" in site else "none"))
    con.commit()
    score_all(con, cfg)
    reasons = {r[0]: r[1] for r in con.execute("select business_id, reasons from leads")}
    assert {b for b, why in reasons.items() if "Duplicate" in why} == {"d2", "s2"}
    assert not any("Chain" in why for why in reasons.values())


def test_site_fetch_is_capped():
    import asyncio

    import httpx

    from leadscout.audit.site import MAX_BYTES, fetch

    big = b"<html>" + b"x" * (MAX_BYTES * 2)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=big))) as c:
            return await fetch(c, "http://big.in")

    resp, text = asyncio.run(go())
    assert resp.status_code == 200 and len(text) == MAX_BYTES


# ---- One place, one entry ------------------------------------------------------------------

def _biz(con, bid, name, lat, lon, city="Hyderabad", status=None, phone=None):
    con.execute("insert into businesses (id, source, name, lat, lon, city, phone, confidence, fetched_at) values (?, 't', ?, ?, ?, ?, ?, 0.9, '2026-11-20')",
                (bid, name, lat, lon, city, phone))
    con.execute("insert into audits (business_id, site_class, audited_at) values (?, 'none', '2026-11-20')", (bid,))
    if status:
        con.execute("insert into leads (business_id, score, status, updated_at) values (?, 80, ?, '2026-11-20')", (bid, status))
    con.commit()


def test_same_name_nearby_is_one_place(con, cfg):
    from leadscout.scoring import score_all

    _biz(con, "r1", "Rajrudra Developers", 17.4948, 78.3996, status="new")
    _biz(con, "r2", "Rajrudra Developers.", 17.4900, 78.4030, status="drafted")  # 0.6 km away, already drafted
    _biz(con, "m1", "Regalia Interiors", 15.2750, 73.9578, city="margao goa")
    _biz(con, "m2", "Regalia  interiors", 15.2650, 73.9660, city="Madgaon")  # same town, different spelling
    _biz(con, "o1", "Orthosquare", 17.44, 78.38)
    _biz(con, "o2", "Orthosquare", 15.27, 73.95, city="Madgaon")  # 530 km away: a different place
    score_all(con, cfg)
    st = {r[0]: (r[1], r[2]) for r in con.execute("select business_id, status, reasons from leads")}
    assert st["r2"][0] == "drafted" and st["r1"] == ("excluded", '["Duplicate listing"]')  # your draft is kept
    assert sum("Duplicate" in st[b][1] for b in ("m1", "m2")) == 1
    assert not any("Duplicate" in st[b][1] for b in ("o1", "o2"))


def test_duplicate_draft_is_dropped_when_twin_is_further_along(con, cfg):
    from leadscout.scoring import score_all

    _biz(con, "a", "Smile Dental", 17.49, 78.39, status="contacted")
    _biz(con, "b", "Smile Dental", 17.491, 78.391, status="approved")
    score_all(con, cfg)
    st = dict(con.execute("select business_id, status from leads").fetchall())
    assert st == {"a": "contacted", "b": "excluded"}


def test_searching_an_area_again_reuses_its_entry(con):
    from leadscout import searches

    first = searches.queue_search(con, "Madgaon", "", ["dental"])
    con.execute("update searches set status = 'done'")
    again = searches.queue_search(con, "Madgaon", "", ["salons"])
    assert first == again
    rows = con.execute("select status, categories from searches").fetchall()
    assert len(rows) == 1 and rows[0]["status"] == "queued"
    assert "Dental clinics" in rows[0]["categories"] and "Salons and spas" in rows[0]["categories"]
    assert searches.queue_search(con, "Madgaon", "Fatorda", ["dental"]) != first  # a neighbourhood is its own area
    con.execute("update searches set status = 'running' where id = ?", (first,))
    with pytest.raises(ValueError, match="right now"):
        searches.queue_search(con, "Madgaon", "", ["dental"])


def test_old_repeated_area_rows_are_merged(tmp_path):
    path = tmp_path / "old.db"
    con = db.connect(path)
    for label, lat in (("Navelim", 15.25885), ("Navelim", 15.25885), ("Madgaon", 15.27501), ("goa", None), ("Goa", None)):
        con.execute("insert into searches (city, label, categories, status, created_at, lat, lon) values (?, ?, '{}', 'done', '2026-11-21', ?, ?)",
                    (label, label, lat, lat and 73.9))
    con.commit()
    con.close()
    db._ready.clear()
    con = db.connect(path)
    assert sorted(r[0] for r in con.execute("select label from searches")) == ["Goa", "Madgaon", "Navelim"]


class SendingGmail:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def message_id_header(self, gid):
        return "<abc@mail>"

    def send(self, to, subject, body, sender, thread_id=None, in_reply_to=None, unsubscribe=None):
        if self.fail:
            raise RuntimeError("network down")
        self.sent.append(to)
        return {"id": f"s{len(self.sent)}", "threadId": "t9"}


def _approved_first(con):
    _seed_lead(con, status="approved")
    con.execute("delete from outreach")
    con.execute("insert into pitches (business_id, subject, body, source, approved, created_at, updated_at) values ('b1', 'Hi', 'Body', 't', 1, '2026-11-20', '2026-11-20')")
    con.commit()


def test_claimed_email_is_never_sent_twice(con, cfg):
    _approved_first(con)
    item = sender.next_item(con, cfg)
    con.execute("insert into meta (key, value) values ('sending:b1:first:0', 'x')")  # another sender got there first
    con.commit()
    gm = SendingGmail()
    assert "already being sent" in sender.send_one(con, cfg, gm, item)
    assert gm.sent == []
    assert sender.next_item(con, cfg) is None  # a stuck claim doesn't block or loop the queue


def test_send_error_before_gmail_takes_it_frees_the_claim(con, cfg):
    import requests

    class Rejected(SendingGmail):
        def send(self, *a, **kw):
            resp = requests.Response()
            resp.status_code = 400
            raise requests.HTTPError("bad request", response=resp)

    _approved_first(con)
    item = sender.next_item(con, cfg)
    with pytest.raises(requests.HTTPError):
        sender.send_one(con, cfg, Rejected(), item)
    assert sender.next_item(con, cfg)["business_id"] == "b1"  # surely not sent: back in the queue
    gm = SendingGmail()
    assert sender.send_one(con, cfg, gm, item).startswith("sent first")
    assert gm.sent == ["owner@clinic.in"]


def test_unclear_send_error_keeps_the_claim(con, cfg):
    _approved_first(con)
    item = sender.next_item(con, cfg)
    with pytest.raises(RuntimeError):
        sender.send_one(con, cfg, SendingGmail(fail=True), item)  # may have gone out: a 5xx, a dropped connection
    assert sender.next_item(con, cfg) is None  # held until the Sent-folder check settles it


def test_stop_event_ends_the_run(con, cfg):
    import threading

    _approved_first(con)
    stop = threading.Event()
    stop.set()
    logs = []
    sender.run(con, cfg, SendingGmail(), log=logs.append, stop=stop)
    assert logs == ["Stopped."]


def test_dashboard_starts_and_stops_sending(client, home, monkeypatch):
    import threading

    from leadscout.web import extras, sending

    home.execute("update leads set status = 'approved'")
    home.execute("delete from outreach")
    home.execute("insert into pitches (business_id, subject, body, source, approved, created_at, updated_at) values ('b1', 'Hi', 'Body', 't', 1, '2026-11-20', '2026-11-20')")
    home.commit()
    gate = threading.Event()

    def run(con, cfg, gmail, log, stop):  # stands in for sender.run: no network, waits to be stopped
        log("running")
        gate.set()
        stop.wait(5)
        log("Stopped.")

    monkeypatch.setattr(sending.sender, "run", run)
    monkeypatch.setattr(extras, "_gmail", lambda: SendingGmail())
    monkeypatch.setattr(sending, "in_window", lambda sc: True)
    assert "Start sending" in client.get("/").text
    assert client.post("/send/start", follow_redirects=False).status_code == 303
    assert gate.wait(5) and sending.running()
    assert "Already sending" in client.post("/send/start").text
    assert "Stop sending" in client.get("/").text
    client.post("/send/stop")
    sending._thread.join(5)
    assert not sending.running()
    assert "Stopped." in client.get("/").text


def test_dashboard_send_needs_gmail_login(client, monkeypatch):
    from leadscout.web import extras, sending

    def no_login():
        raise ValueError("Run leadscout login first.")

    monkeypatch.setattr(extras, "_gmail", no_login)
    monkeypatch.setattr(sending, "block_reason", lambda con, cfg: "")  # window open, something queued
    assert "Run leadscout login first." in client.post("/send/start").text
    assert not sending.running()


class SentFolderGmail(SendingGmail):
    def __init__(self, found):
        super().__init__()
        self.found = found

    def sent_to(self, to, since):
        return {"id": "g7", "threadId": "t7"} if self.found else None


def _cut_off_claim(con, minutes_ago=30):
    at = (datetime.now(IST) - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
    con.execute("insert into meta (key, value) values ('sending:b1:first:0', ?)", (at,))
    con.commit()


def test_cut_off_send_found_in_gmail_is_recorded(con, cfg):
    _approved_first(con)
    _cut_off_claim(con)
    assert [c["name"] for c in sender.stuck_claims(con)] == ["Smile Dental"]
    assert sender.resolve_stuck(con, SentFolderGmail(found=True)) == {"recorded": 1, "released": 0}
    assert con.execute("select status from leads").fetchone()[0] == "contacted"
    assert con.execute("select gmail_id, thread_id from outreach").fetchone()[:] == ("g7", "t7")
    assert sender.stuck_claims(con) == [] and sender.next_item(con, cfg) is None


def test_cut_off_send_missing_from_gmail_goes_back_in_queue(con, cfg):
    _approved_first(con)
    _cut_off_claim(con)
    assert sender.resolve_stuck(con, SentFolderGmail(found=False)) == {"recorded": 0, "released": 1}
    assert sender.next_item(con, cfg)["business_id"] == "b1"


def test_a_send_in_progress_is_not_stuck(con):
    _approved_first(con)
    _cut_off_claim(con, minutes_ago=1)
    assert sender.stuck_claims(con) == []


def test_dashboard_refuses_to_start_outside_the_window(client, monkeypatch):
    from leadscout.web import extras, sending

    monkeypatch.setattr(sending, "in_window", lambda sc: False)
    monkeypatch.setattr(extras, "_gmail", lambda: SendingGmail())
    assert "sending window is closed" in client.post("/send/start").text
    assert not sending.running()


def test_dashboard_notes_a_run_cut_off_by_closing(home):
    from leadscout.web import sending

    db.set_meta(home, sending.RUNNING_KEY, "2026-11-24T11:05:00+05:30")
    sending.note_cut_off_run(home)
    assert "started at 11:05 ended when the dashboard closed" in sending.log[-1]
    assert db.get_meta(home, sending.RUNNING_KEY) is None


def test_send_status_reloads_the_page_when_the_run_ends(client):
    r = client.get("/send/status")
    assert r.status_code == 200 and r.headers["HX-Refresh"] == "true"


def test_only_one_sender_runs_at_a_time(con, cfg):
    assert sender.take_lease(con, cfg.sending, "dashboard")
    logs = []
    sender.run(con, cfg, SendingGmail(), log=logs.append)
    assert "Another sender is already running" in logs[0]
    sender.drop_lease(con, "dashboard")
    assert sender.take_lease(con, cfg.sending, "cli")


def test_a_closed_senders_lease_is_taken_over(con, cfg):
    old = (datetime.now(IST) - timedelta(hours=1)).isoformat(timespec="seconds")
    con.execute("insert into meta (key, value) values ('sender_lease', ?)", (old + "|gone",))
    con.commit()
    assert sender.take_lease(con, cfg.sending, "cli")


def test_same_name_with_different_phones_is_two_businesses(con, cfg):
    from leadscout.scoring import score_all

    _biz(con, "s1", "Sai Dental Clinic", 17.44, 78.38, phone="+919848012345", status="approved")
    _biz(con, "s2", "Sai Dental Clinic", 17.40, 78.45, phone="+919848099999", status="approved")
    score_all(con, cfg)
    assert dict(con.execute("select business_id, status from leads").fetchall()) == {"s1": "approved", "s2": "approved"}


def test_purge_keeps_leads_you_worked_on(con):
    from leadscout.compliance import purge_stale

    for bid, status in (("p1", "new"), ("p2", "won"), ("p3", "replied")):
        con.execute("insert into businesses (id, source, name, fetched_at) values (?, 't', ?, '2025-01-01')", (bid, bid))
        con.execute("insert into leads (business_id, score, status, updated_at) values (?, 50, ?, '2025-01-01')", (bid, status))
    con.execute("update leads set quote_inr = 15000 where business_id = 'p3'")
    con.commit()
    assert purge_stale(con, 90) == 1
    assert {r[0] for r in con.execute("select id from businesses")} == {"p2", "p3"}


def test_a_bounce_is_not_an_opt_out_on_the_dashboard(con):
    from leadscout.compliance import lead_is_suppressed

    _seed_lead(con)
    suppress(con, "owner@clinic.in", "bounced")
    assert is_suppressed(con, "owner@clinic.in")  # sending still skips it
    assert not lead_is_suppressed(con, "b1")  # but you can still mark the lead won after a phone call
    suppress(con, "+919000000007", "opted_out")
    con.execute("update businesses set phone = '+919000000007'")
    assert lead_is_suppressed(con, "b1")  # a real "no" still counts


def test_unknown_charset_falls_back_to_utf8():
    from leadscout.audit.site import _codec

    assert _codec("utf8mb4") == "utf-8" and _codec("none") == "utf-8" and _codec(None) == "utf-8"
    assert _codec("ISO-8859-1") == "iso8859-1"


def test_pitch_may_quote_template_facts_and_phone_formats(con, cfg):
    from leadscout.pitch.jobs import unmeasured_numbers

    _seed_lead(con)
    con.execute("update businesses set phone = '+919848012345'")
    con.commit()
    body = "Google shut those sites down in 2024. Call 9848012345 or 09848012345."
    assert unmeasured_numbers(con, cfg, "b1", {"subject": "Hi", "body": body}) == []
    assert unmeasured_numbers(con, cfg, "b1", {"subject": "Hi", "body": "Seen by 5000 people."}) == ["5000"]


def test_remove_our_old_address_is_not_a_no():
    assert not NO_WORDS.search("Please remove our old address from the site and send a quote.")
    assert NO_WORDS.search("Please remove me from your list.")
    assert NO_WORDS.search("remove my email please")


def test_unsubscribe_check_only_reads_new_mail(con, cfg):
    calls = []

    class Gm(FakeGmail):
        def unsubscribe_requests(self, me, since=None):
            calls.append(since)
            return set()

    sender.check_replies(con, cfg, Gm([]))
    sender.check_replies(con, cfg, Gm([]))
    assert calls[0] is None and calls[1] is not None
