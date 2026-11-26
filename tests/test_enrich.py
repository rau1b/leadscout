"""Phase 1 Step 2: Google Places enrichment within Google's terms. Offline: respx answers for Google."""

import json
import sqlite3
import tomllib
from pathlib import Path

import httpx
import pytest
import respx

from leadscout import config, db
from leadscout.enrich import places
from leadscout.scoring import score_all

SEARCH = f"{places.API}/places:searchText"
# Values only Google knows. None of them may ever reach the database.
RATING, REVIEWS, HOURS, G_PHONE, G_SITE = 4.37, 987, "Monday: 9:17 AM – 6:43 PM", "+91 99887 76655", "https://google-only.example"


def _details(status="OPERATIONAL"):
    # Google answers only the fields asked for; the extra ones here prove nothing stores them even if it did.
    return {"rating": RATING, "userRatingCount": REVIEWS, "businessStatus": status,
            "regularOpeningHours": {"weekdayDescriptions": [HOURS]},
            "nationalPhoneNumber": G_PHONE, "websiteUri": G_SITE, "location": {"latitude": 15.4999, "longitude": 73.8277}}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    return tmp_path


def _cfg(enabled=True, cap=1000):
    with open(Path(__file__).resolve().parents[1] / "config.example.toml", "rb") as f:
        raw = tomllib.load(f)
    raw["enrich"] = {"places_enabled": enabled, "monthly_request_cap": cap, "min_score_to_enrich": 50}
    return config.Config(raw)


def _lead(con, bid, name, score=70, lat=15.49, lon=73.82):
    con.execute("insert into businesses (id, source, name, category, locality, city, lat, lon, fetched_at) values (?, 'overture', ?, 'dentist', 'Panaji', 'Goa', ?, ?, '2026-11-20')",
                (bid, name, lat, lon))
    con.execute("insert into audits (business_id, site_class, audited_at) values (?, 'none', '2026-11-20')", (bid,))
    con.execute("insert into leads (business_id, score, status, updated_at) values (?, ?, 'new', '2026-11-20')", (bid, score))
    con.commit()


def _everything_stored(path) -> str:
    """Every value in every table, as text."""
    c = sqlite3.connect(path)
    tables = [r[0] for r in c.execute("select name from sqlite_master where type = 'table'")]
    return "\n".join(repr(row) for t in tables for row in c.execute(f'select * from "{t}"'))


def test_only_the_place_id_is_ever_stored(home, monkeypatch):
    con, cfg = db.connect(), _cfg()
    _lead(con, "a", "Smile Dental")
    _lead(con, "b", "Sai Clinic")
    _lead(con, "c", "Low Score", score=20)
    with respx.mock(assert_all_called=True) as g:
        search = g.post(SEARCH).mock(side_effect=lambda req: httpx.Response(200, json={
            "places": [{"id": "ChIJ-smile"}] if "Smile" in json.loads(req.content)["textQuery"] else [{"id": "x1"}, {"id": "x2"}]}))
        g.get(f"{places.API}/places/ChIJ-smile").mock(return_value=httpx.Response(200, json=_details()))
        found = places.match(con, cfg)
        score_all(con, cfg)

        body = json.loads(search.calls[0].request.content)
        assert search.calls[0].request.headers["X-Goog-FieldMask"] == "places.id"  # the IDs-only tier
        assert body["locationBias"]["circle"]["radius"] == 500.0 and body["textQuery"] in ("Smile Dental, Panaji", "Sai Clinic, Panaji")

        from fastapi.testclient import TestClient

        from leadscout.web.app import app

        monkeypatch.setattr(config, "load", lambda: cfg)  # the dashboard reads this config, with Places on
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        assert "Show Google details" in client.get("/leads/a").text
        assert "Show Google details" not in client.get("/leads/b").text  # no clear match: no button
        shown = client.get("/leads/a/google").text

    assert found == {"searched": 2, "matched": 1, "stopped": None}  # "Low Score" is under min_score_to_enrich
    assert places.place_id(con, "a") == "ChIJ-smile" and places.place_id(con, "b") is None  # two results: not clear
    assert str(RATING) in shown and str(REVIEWS) in shown and HOURS in shown and "Data from Google Maps" in shown
    reasons = con.execute("select reasons from leads where business_id = 'a'").fetchone()[0]
    assert "Well reviewed on Google" in reasons

    stored = _everything_stored(db.default_path())
    for google_only in (str(RATING), str(REVIEWS), "9:17", G_PHONE, "99887", G_SITE, "OPERATIONAL", "15.4999"):
        assert google_only not in stored, google_only
    assert "ChIJ-smile" in stored  # the one thing Google lets us keep


def test_a_place_google_marks_closed_for_good_is_excluded(home):
    con, cfg = db.connect(), _cfg()
    _lead(con, "a", "Smile Dental")
    con.execute("insert into source_records (business_id, source, source_id, fetched_at) values ('a', 'google', 'ChIJ-smile', 'x')")
    con.commit()
    with respx.mock() as g:
        g.get(f"{places.API}/places/ChIJ-smile").mock(return_value=httpx.Response(200, json=_details("CLOSED_PERMANENTLY")))
        score_all(con, cfg)
    status, reasons = con.execute("select status, reasons from leads where business_id = 'a'").fetchone()
    assert status == "excluded" and "Closed for good, according to Google" in reasons


def test_the_monthly_cap_stops_requests(home):
    con, cfg = db.connect(), _cfg(cap=3)
    for i in range(5):
        _lead(con, f"l{i}", f"Shop {i}", lat=15.49 + i / 100)
    db.set_meta(con, places._month_key(), 1)  # one request already made this month
    with respx.mock() as g:
        search = g.post(SEARCH).mock(return_value=httpx.Response(200, json={"places": []}))
        found = places.match(con, cfg)
    assert search.call_count == 2 and places.used_this_month(con) == 3
    assert found["searched"] == 2 and "requests are used up" in found["stopped"]
    with pytest.raises(places.CapReached):
        places.details(con, cfg, "ChIJ-anything")


@pytest.mark.parametrize("enabled,key", [(False, "test-key"), (True, "")])
def test_off_or_no_key_means_no_requests(home, monkeypatch, enabled, key):
    monkeypatch.setenv("GOOGLE_API_KEY", key)
    con, cfg = db.connect(), _cfg(enabled=enabled)
    _lead(con, "a", "Smile Dental")
    con.execute("insert into source_records (business_id, source, source_id, fetched_at) values ('a', 'google', 'ChIJ-smile', 'x')")
    con.commit()
    with respx.mock(assert_all_mocked=True) as g:  # any request would fail the test: none is mocked
        assert places.match(con, cfg) == {"searched": 0, "matched": 0, "stopped": None}
        score_all(con, cfg)
        assert g.calls.call_count == 0
    assert places.used_this_month(con) == 0


def test_settings_shows_this_months_count_and_saves_the_switch(home):
    from fastapi.testclient import TestClient

    from leadscout.web.app import app

    (home / "config.toml").write_bytes((Path(__file__).resolve().parents[1] / "config.example.toml").read_bytes())
    con = db.connect()
    db.set_meta(con, places._month_key(), 42)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    page = client.get("/settings").text
    assert "<b>42</b> of 1000" in page and 'name="enrich.places_enabled" value="1" >' in page

    from leadscout import settings
    form = settings.form_values(tomllib.loads((home / "config.toml").read_text(encoding="utf-8")))
    client.post("/settings", data={**form, "enrich.places_enabled": "1", "enrich.monthly_request_cap": "500"})
    saved = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))["enrich"]
    assert saved["places_enabled"] is True and saved["monthly_request_cap"] == 500
