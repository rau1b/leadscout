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


# Every frame either carries one of the verticals' labels plus "Placeholder", or is an empty decorative frame.
PLACEHOLDERS = {f"{c[k]} Placeholder" for c in demos.COPY.values() for k in ("services_ph", "photos_ph", "hours_ph")} | {""}


def without_placeholders(soup) -> BeautifulSoup:
    """The page minus its labelled empty frames: what's left must be facts from the row or our fixed copy."""
    soup = BeautifulSoup(str(soup), "html.parser")
    for ph in soup.select(".ph"):
        ph.decompose()
    return soup


def row_with(**extra):
    """A businesses-like row with extra columns (e.g. hours, basic_category) that the schema may not have yet."""
    import sqlite3

    base = {k: None for k in ("category", "category_path", "address", "locality", "city", "area", "postcode", "lat", "lon", "phone", "phone_type")}
    vals = base | {"name": "Lotus"} | extra
    m = sqlite3.connect(":memory:")
    m.row_factory = sqlite3.Row
    return m.execute("select " + ", ".join(f"? as {k}" for k in vals), list(vals.values())).fetchone()


def test_banner_noindex_and_no_scripts_or_images(con):
    add(con, **FULL)
    d = demos.build(con, "dent1", SENDER)
    soup = page(d.path)
    banner = soup.select_one(".concept")
    assert banner.get_text(strip=True) == "Concept made by Kite Studio for Smile Dental Care. Not their official site."
    assert "position:fixed" in soup.style.string.replace(" ", "")
    assert soup.find("meta", attrs={"name": "robots"})["content"] == "noindex"
    assert not soup.find_all(["script", "img", "picture", "iframe", "link"])  # no JS, no photos or logos, CSS inline
    assert d.path == demos.folder(con) / d.slug / "index.html"


def test_only_facts_from_the_row(con):
    row = add(con, **FULL)
    d = demos.build(con, "dent1", SENDER)
    soup = page(d.path)
    text = without_placeholders(soup).get_text(" ", strip=True)
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
    assert not soup.select("p.hours")  # the row has no hours: the frame stays


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
    assert [dt.get_text() for dt in soup.select("dt")] == ["Phone"]
    assert "Directions" not in text


def test_address_without_repeats_or_stray_commas():
    """Real Goa listings: the address ends in a comma, and Margao/Madgaon are one town under two names."""
    f = demos.facts(row_with(address="Daud Residency, Shop No. 15, Opp. HDFC Bank, Aquem,", locality="Margao", city="Madgaon", postcode="403601"))
    assert f["address"] == "Daud Residency, Shop No. 15, Opp. HDFC Bank, Aquem, Margao, 403601"
    assert f["area"] == "Margao"
    assert demos.facts(row_with(locality="Kukatpally", city="Hyderabad", area="Kukatpally, Hyderabad"))["area"] == "Kukatpally, Hyderabad"
    assert demos.facts(row_with(address="Shop 4, Margao", locality="Margao", city="Goa"))["address"] == "Shop 4, Margao, Goa"


def test_placeholders_are_labelled_empty_frames(con):
    """Step 1: the page reads like a website, but every frame says it's a placeholder and holds no facts or numbers."""
    add(con, **FULL)
    soup = page(demos.build(con, "dent1", SENDER).path)
    frames = soup.select(".ph")
    assert {f["data-placeholder"] for f in frames} == {"photos", "services", "hours"}
    for f in frames:
        assert f.get_text(" ", strip=True) in PLACEHOLDERS
    assert not re.search(r"\d", " ".join(f.get_text() for f in frames))
    assert not soup.find_all(["img", "picture"])


def test_a_real_fact_replaces_its_placeholder():
    _, html = demos.render(row_with(hours="Mon-Sat 10:00-20:00"), SENDER)
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select_one("p.hours").get_text() == "Mon-Sat 10:00-20:00"
    assert not soup.select('[data-placeholder="hours"]')
    assert soup.select('[data-placeholder="photos"]') and soup.select('[data-placeholder="services"]')  # never in the row


def test_template_by_category(con):
    add(con, id="s", source="t", name="Glow", category="beauty_salon", category_path="beauty_and_spa > beauty_salon")
    add(con, id="c", source="t", name="Care", category=None, category_path="health_and_medical > physiotherapist")
    add(con, id="g", source="t", name="Shree Hardware", category="hardware_store")
    assert [demos.build(con, i, SENDER).template for i in ("s", "c", "g")] == ["salon", "clinic", "shop"]


# One minimal business per vertical: a name and the category Overture would give it.
MINIMAL = {
    "clinic": "dentist", "salon": "beauty_salon", "restaurant": "south_indian_restaurant",
    "coaching": "tutoring_service", "realestate": "real_estate_agent", "shop": "hardware_store",
}


@pytest.mark.parametrize("vertical", list(MINIMAL))
def test_each_vertical_renders_from_a_minimal_row(vertical):
    template, html = demos.render(row_with(category=MINIMAL[vertical]), SENDER)
    assert template == vertical
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select_one(".concept").get_text(strip=True) == "Concept made by Kite Studio for Lotus. Not their official site."
    assert soup.find("meta", attrs={"name": "robots"})["content"] == "noindex"
    assert soup.body["class"] == [f"v-{vertical}"]
    assert soup.select(".wrap")[-1].find_all(recursive=False)[-1].name == "footer"  # the "not checked by them" note closes the page
    # With nothing but a name, every frame is a placeholder, and there's no call, WhatsApp or map link to invent.
    assert {f["data-placeholder"] for f in soup.select(".ph")} == {"photos", "services", "hours"}
    assert all(f.get_text(" ", strip=True) in PLACEHOLDERS for f in soup.select(".ph"))
    assert [a["href"] for a in soup.select('a[href^="tel:"]')] == ["tel:+919876543210"]  # ours, in the enquiry section
    assert not soup.select('a[href*="wa.me"], a[href*="google.com/maps"]')
    assert not INVENTED.search(without_placeholders(soup).get_text(" ", strip=True))


@pytest.mark.parametrize("vertical", list(MINIMAL))
def test_performance_budget_and_no_external_requests(vertical):
    """Under 30 KB, no JavaScript, and nothing the browser would fetch: no scripts, images, stylesheets, fonts or frames."""
    row = row_with(category=MINIMAL[vertical], name="Sri Lakshmi Venkateswara Enterprises and Sons", address="Shop 4, Main Road",
                   locality="Panaji", city="Goa", postcode="403001", lat=15.4909, lon=73.8278, phone="+919812345678", phone_type="mobile",
                   hours="Mon-Sat 09:00-21:00")
    _, html = demos.render(row, SENDER)
    assert len(html.encode("utf-8")) < 30_000
    soup = BeautifulSoup(html, "html.parser")
    assert not soup.find_all(["script", "img", "picture", "iframe", "link", "object", "embed", "video", "audio", "source"])
    assert not [t for t in soup.find_all(True) if t.has_attr("src") or t.has_attr("srcset") or any(a.startswith("on") for a in t.attrs)]
    css = soup.style.string
    assert "@import" not in css and "@font-face" not in css and not re.search(r"url\(", css)
    for svg_ref in soup.find_all(attrs={"href": True}):  # only plain links a person taps; no <use href> or xlink to outside files
        assert svg_ref.name == "a", svg_ref.name


def test_the_six_verticals_look_different():
    """Two demos in the same street shouldn't look identical: each vertical has its own colours and section order."""
    pages = {v: BeautifulSoup(demos.render(row_with(category=c, phone="+919812345678", phone_type="mobile"), SENDER)[1], "html.parser")
             for v, c in MINIMAL.items()}
    accents = {v: re.search(r"--accent:(#[0-9a-f]+)", s.style.string).group(1) for v, s in pages.items()}
    orders = {v: tuple(sec.get("class", ["?"])[0] for sec in s.find_all("section")) for v, s in pages.items()}
    headers = {v: s.select_one("header")["class"][0] for v, s in pages.items()}
    assert len(set(accents.values())) == 6, accents
    assert len(set(orders.values())) == 6, orders
    assert len(set(headers.values())) == 6, headers


@pytest.mark.parametrize(
    "category, path, expected",
    [
        ("dentist", None, "clinic"),
        (None, "health_and_medical > physiotherapist", "clinic"),
        ("medical_spa", None, "clinic"),
        ("hair_salon", None, "salon"),
        ("barber", None, "salon"),  # "bar" is a whole-word match, so a barber isn't a restaurant
        ("spanish_restaurant", None, "restaurant"),  # "spa" is a whole-word match too
        ("cafe", None, "restaurant"),
        (None, "eat_and_drink > bakery", "restaurant"),
        ("beauty_school", None, "coaching"),
        ("tutoring_service", None, "coaching"),
        ("real_estate_agent", None, "realestate"),
        ("musical_instrument_store", None, "shop"),
        ("pet_food_store", None, "shop"),
        ("software_developer", None, "shop"),
        (None, None, "shop"),
    ],
)
def test_template_by_category_fallback(category, path, expected):
    assert demos.pick_template(row_with(category=category, category_path=path)) == expected


@pytest.mark.parametrize("basic, expected", [("restaurant", "restaurant"), ("education", "coaching"), ("real_estate", "realestate"),
                                             ("dentist", "clinic"), ("beauty_salon", "salon"), ("clothing_store", "shop")])
def test_template_by_basic_category(basic, expected):
    """C3: basic_category decides even when category says something else."""
    assert demos.pick_template(row_with(category="hardware_store", basic_category=basic)) == expected


def test_basic_category_wins_when_the_column_exists(con):
    """Contract C3: Jason's migration adds businesses.basic_category; until then category and category_path are used."""
    row = row_with(category="shopping", basic_category="beauty_salon")
    assert demos.pick_template(row) == "salon"
    assert demos.facts(row)["what"] == "Beauty salon"
    assert demos.pick_template(row_with(category="dentist", basic_category=None)) == "clinic"  # null falls back


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
    assert not demos.folder(con).exists() or not any(demos.folder(con).iterdir())


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
    assert not second.path.parent.exists()  # forget() called remove_orphans (contract C8)


def test_pages_belong_to_their_database(con, tmp_path):
    """A second database (a test, a restored copy) never deletes the first one's pages."""
    add(con, **FULL)
    d = demos.build(con, "dent1", SENDER)
    (tmp_path / "elsewhere").mkdir()
    other = db.connect(tmp_path / "elsewhere" / "other.db")  # empty: every page of the first database looks orphaned to it
    assert demos.remove_orphans(other) == 0
    assert d.path.exists()


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
