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
    return config.load()


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
    [("No thanks", True), ("Not interested", True), ("no.", True), ("No problem, please send the mockup", False), ("Yes send it", False)],
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
