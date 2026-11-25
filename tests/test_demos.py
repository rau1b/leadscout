"""Demo builder: honesty rules (banner, noindex, only facts from the row), opt-out refusal, unguessable slugs. Offline."""

import re
from datetime import datetime
from urllib.parse import unquote

import pytest
from bs4 import BeautifulSoup
from typer.testing import CliRunner

from leadscout import db, demos
from leadscout.compliance import forget, opt_out, suppress

SENDER = {"name": "Asha Rao", "business": "Kite Studio", "phone": "+91 98765 43210", "email": "asha.kite@gmail.com"}

FULL = {
    "id": "dent1", "source": "overture", "name": "Smile Dental Care", "category": "dentist",
    "category_path": "health_and_medical > dentist", "address": "Plot 12, KPHB Colony", "locality": "Kukatpally",
    "postcode": "500072", "lat": 17.4849, "lon": 78.4138, "phone": "+919812345678", "phone_type": "mobile",
    "website": None, "emails": '["smile@clinic.in"]', "area": "Kukatpally, Hyderabad", "city": "Hyderabad",
}

# Words a page would only contain if something was invented: reviews, ratings, prices, years in business, photos.
INVENTED = re.compile(r"review|rating|stars?\b|★|₹|rs\.|price|since|years|award|best|trusted|guarantee|certified|testimonial", re.I)


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    c = db.connect()
    yield c
    c.close()


def add(con, **fields):
    row = {"fetched_at": "2026-11-20T10:00:00+05:30"} | fields
    cols = ", ".join(row)
    con.execute(f"insert into businesses ({cols}) values ({', '.join('?' * len(row))})", list(row.values()))
    con.commit()
    return row


def page(path) -> BeautifulSoup:
    return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")


def test_banner_noindex_and_no_scripts_or_images(con):
    add(con, **FULL)
    d = demos.build(con, "dent1", SENDER)
    soup = page(d.path)
    banner = soup.select_one(".concept")
    assert banner.get_text(strip=True) == "Concept made by Kite Studio for Smile Dental Care. Not their official site."
    assert "position:fixed" in soup.style.string.replace(" ", "")
    assert soup.find("meta", attrs={"name": "robots"})["content"] == "noindex"
    assert not soup.find_all(["script", "img", "picture", "iframe", "link"])  # no JS, no photos or logos, CSS inline
    assert d.path == demos.folder() / d.slug / "index.html"


def test_only_facts_from_the_row(con):
    row = add(con, **FULL)
    d = demos.build(con, "dent1", SENDER)
    soup = page(d.path)
    text = soup.get_text(" ", strip=True)
    assert not INVENTED.search(text)

    # Every number on the page is the business's phone, postcode, address or coordinates, or our own phone.
    allowed = "".join(str(row[k]) for k in ("phone", "postcode", "address", "lat", "lon")) + SENDER["phone"].replace(" ", "")
    hrefs = " ".join(unquote(a["href"]) for a in soup.find_all("a"))
    for n in re.findall(r"\d+", text.replace(" ", "") + " " + hrefs.replace("api=1", "")):
        assert n in allowed, n

    # Links go only to the business's phone/WhatsApp/map and our own contact.
    for a in soup.find_all("a"):
        assert re.match(r"(tel:\+?\d+|https://wa\.me/\d+|https://www\.google\.com/maps/search/\?|mailto:asha\.kite@gmail\.com)", a["href"]), a["href"]
    assert soup.find("a", href="tel:+919812345678")
    assert soup.find("a", href="https://wa.me/919812345678")
    assert "smile@clinic.in" not in str(soup)  # the business's own email isn't on the page; the enquiry section shows only ours
    assert "Hours" not in text  # the row has no hours


def test_missing_fields_are_left_out(con):
    add(con, id="bare", source="overture", name="Ganesh Stores", category=None, category_path=None, phone="+914023456789", phone_type="landline")
    d = demos.build(con, "bare", SENDER)
    soup = page(d.path)
    text = soup.get_text(" ", strip=True)
    assert d.template == "shop"
    assert soup.find("a", href="tel:+914023456789")
    assert not soup.select('a[href*="wa.me"]')  # a landline gets no WhatsApp link
    assert not soup.select('a[href*="google.com/maps"]')  # no coordinates or address
    assert not soup.select(".kicker") and not soup.select(".where")
    for word in ("What", "Where", "Area", "Hours", "Directions"):
        assert word not in text.split(), word


def test_template_by_category(con):
    add(con, id="s", source="t", name="Glow", category="beauty_salon", category_path="beauty_and_spa > beauty_salon")
    add(con, id="c", source="t", name="Care", category=None, category_path="health_and_medical > physiotherapist")
    add(con, id="g", source="t", name="Shree Hardware", category="hardware_store")
    assert [demos.build(con, i, SENDER).template for i in ("s", "c", "g")] == ["salon", "clinic", "shop"]


def test_row_event_and_expiry(con):
    add(con, **FULL)
    d = demos.build(con, "dent1", SENDER)
    r = con.execute("select * from demos where slug = ?", (d.slug,)).fetchone()
    assert (r["business_id"], r["template"], r["url"], r["first_viewed_at"], r["view_count"]) == ("dent1", "clinic", None, None, 0)
    assert (datetime.fromisoformat(r["expires_at"]) - datetime.fromisoformat(r["built_at"])).days == 30
    ev = con.execute("select type, actor, data_json from events where business_id = 'dent1'").fetchall()
    assert [tuple(e) for e in ev] == [("demo_built", "cli", '{"template": "clinic"}')]


@pytest.mark.parametrize("how", ["phone", "email", "lead", "bounce"])
def test_suppressed_business_is_refused(con, how):
    add(con, **FULL)
    if how == "phone":
        opt_out(con, "98123 45678", "manual")
    elif how == "email":
        suppress(con, "Smile@Clinic.in", "unsubscribe link")
    elif how == "lead":
        con.execute("insert into leads (business_id, score, status, updated_at) values ('dent1', 60, 'opted_out', 'x')")
        con.commit()
    else:
        suppress(con, "smile@clinic.in", "bounced")
    with pytest.raises(demos.Refused):
        demos.build(con, "dent1", SENDER)
    assert con.execute("select count(*) from demos").fetchone()[0] == 0
    assert not demos.folder().exists() or not any(demos.folder().iterdir())


def test_slugs_are_unique_and_unguessable(con):
    for i in range(20):
        add(con, id=f"b{i}", source="t", name=f"Shop {i}")
    slugs = [demos.build(con, f"b{i}", SENDER).slug for i in range(20)]
    assert len(set(slugs)) == 20
    assert all(len(s) >= 20 and re.fullmatch(r"[A-Za-z0-9_-]+", s) for s in slugs)


def test_rebuild_replaces_old_demo_and_forgotten_pages_are_removed(con):
    add(con, **FULL)
    first = demos.build(con, "dent1", SENDER)
    second = demos.build(con, "dent1", SENDER)
    assert not first.path.parent.exists() and second.path.exists()
    assert [r[0] for r in con.execute("select slug from demos")] == [second.slug]

    forget(con, "smile@clinic.in")
    assert con.execute("select count(*) from demos").fetchone()[0] == 0  # cascade
    assert demos.remove_orphans(con) == 1
    assert not second.path.parent.exists()


def test_cli(con, tmp_path):
    from leadscout.cli import app

    add(con, **FULL)
    (tmp_path / "config.toml").write_text(
        '[sender]\nname = "Asha Rao"\nbusiness = "Kite Studio"\ncity = "Hyderabad"\nphone = "+91 98765 43210"\n'
        'email = "asha.kite@gmail.com"\nportfolio = "https://kite.example"\n',
        encoding="utf-8",
    )
    res = CliRunner().invoke(app, ["demo", "dent1"])
    assert res.exit_code == 0, res.output
    [slug] = [r[0] for r in con.execute("select slug from demos")]
    assert str(tmp_path / "data" / "demos" / slug / "index.html") in res.output

    res = CliRunner().invoke(app, ["demo", "nope"])
    assert res.exit_code == 1 and "No business" in res.output
