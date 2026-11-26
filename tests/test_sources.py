"""Phase 1 Step 1: Overture's basic_category and alternates, source_records, CSV duplicates. Offline."""

import tomllib
from pathlib import Path

import pyarrow as pa
import pytest

from leadscout import config, db
from leadscout.searches import BUSINESS_TYPES
from leadscout.sources import csv_import, overture


@pytest.fixture
def con(tmp_path):
    return db.connect(tmp_path / "t.db")


@pytest.fixture
def cfg():
    with open(Path(__file__).resolve().parents[1] / "config.example.toml", "rb") as f:
        return config.Config(tomllib.load(f))


def _place(id_="gers-1", name="Smile Dental", basic="dentist", primary="dentist", alternates=("orthodontist",), phone="+91 98123 45678"):
    """One place shaped like Overture's 2026-09 schema (no `categories`; basic_category and taxonomy instead)."""
    return {"id": id_, "names": {"primary": name}, "basic_category": basic,
            "taxonomy": {"primary": primary, "hierarchy": ["health_and_medical", primary], "alternates": list(alternates)},
            "websites": None, "phones": [phone], "emails": None, "socials": None, "confidence": 0.9, "brand": None,
            "addresses": [{"freeform": "1 MG Road", "locality": "Panaji", "postcode": "403001"}],
            "bbox": {"xmin": 73.82, "xmax": 73.82, "ymin": 15.49, "ymax": 15.49}, "operating_status": "open"}


def _ingest(con, monkeypatch, places, release="2026-11-19.0", types=("dental",)):
    monkeypatch.setattr(overture, "download", lambda bbox: (pa.Table.from_pylist(places), release))
    terms = ",".join(BUSINESS_TYPES[t][1] for t in types).split(",")  # as searches._run passes them
    return overture.ingest(con, None, terms, "Panaji, Goa", city="Goa")


def test_overture_fields_and_source_record_are_stored(con, monkeypatch):
    assert _ingest(con, monkeypatch, [_place()]) == (1, 1)
    b = con.execute("select basic_category, category, category_alternates from businesses").fetchone()
    assert tuple(b) == ("dentist", "dentist", '["orthodontist"]')
    s = con.execute("select business_id, source, source_id, release from source_records").fetchone()
    assert tuple(s) == ("gers-1", "overture", "gers-1", "2026-11-19.0")

    _ingest(con, monkeypatch, [_place()], release="2026-12-17.0")  # found again in a later release: one row, updated
    assert con.execute("select count(*), max(release) from source_records").fetchone()[:] == (1, "2026-12-17.0")


@pytest.mark.parametrize("place,hit", [
    # basic_category says dentist although the taxonomy and name are vague: found
    ({"basic_category": "dentist", "category": "health_and_medical", "name": "Smile Care"}, True),
    # only an alternate category matches: found
    ({"basic_category": "doctor", "category": "doctor", "category_alternates": ["dentist"], "name": "Dr. Rao"}, True),
    # nothing but the name: still found, as before
    ({"basic_category": None, "category": None, "name": "Rao Dental Clinic"}, True),
    ({"basic_category": "taxi_service", "category": "taxi_service", "name": "City Cabs"}, False),
])
def test_matching_reads_basic_category_then_taxonomy_then_name(place, hit):
    assert overture.matches(place, BUSINESS_TYPES["dental"][1].split(",")) is hit


def test_csv_import_writes_its_own_source_record(con, tmp_path):
    f = tmp_path / "mine.csv"
    f.write_text("name,phone,city\nRao Opticals,+91 98000 11111,Goa\n", encoding="utf-8")
    assert csv_import.ingest(con, str(f), "manual") == 1
    assert con.execute("select source, source_id, release from source_records").fetchone()[:] == ("csv", None, None)


def _audit_all(con):
    con.execute("insert into audits (business_id, site_class, audited_at) select id, 'none', '2026-11-20' from businesses")
    con.commit()


def test_csv_copy_of_an_overture_business_is_a_duplicate(con, cfg, monkeypatch, tmp_path):
    from leadscout.scoring import score_all

    _ingest(con, monkeypatch, [_place()])
    f = tmp_path / "mine.csv"
    f.write_text("name,phone,city\nSmile Dental Clinic,098123 45678,Goa\n", encoding="utf-8")  # same phone, typed differently
    csv_import.ingest(con, str(f), "manual")
    _audit_all(con)
    con.execute("insert into leads (business_id, score, status, updated_at) values ('gers-1', 60, 'contacted', '2026-11-20')")
    con.commit()

    score_all(con, cfg)
    rows = dict(con.execute("select b.source, l.status || ':' || l.reasons from leads l join businesses b on b.id = l.business_id").fetchall())
    assert rows["overture"].startswith("contacted")  # the copy with history is kept
    assert rows["csv"] == 'excluded:["Duplicate listing"]'


def test_source_records_go_when_the_business_is_forgotten(con, monkeypatch, tmp_path):
    from leadscout.compliance import forget

    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))  # forget also cleans pitch files under data/
    _ingest(con, monkeypatch, [_place()])
    assert forget(con, "+91 98123 45678") == (1, [])
    assert con.execute("select count(*) from source_records").fetchone()[0] == 0


def test_lead_page_shows_basic_category_and_find_page_suggests_it(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from leadscout.web.app import app

    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    con = db.connect()
    _ingest(con, monkeypatch, [_place(basic="dental_clinic")])
    _audit_all(con)
    con.execute("insert into leads (business_id, score, status, updated_at) values ('gers-1', 60, 'new', '2026-11-20')")
    con.commit()
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    assert "<dt>Type</dt><dd>Dental clinic</dd>" in client.get("/leads/gers-1").text
    assert '<option value="dental_clinic">Dental clinic</option>' in client.get("/find").text


def test_migration_backfills_source_records_for_existing_businesses(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    for _, f in db.migrations()[:2]:  # a database at version 2, from before this step
        old.executescript(f.read_text(encoding="utf-8"))
    old.execute("pragma user_version = 2")
    old.execute("insert into businesses (id, source, name, fetched_at) values ('gers-1', 'overture', 'A', '2026-11-01'), ('csv:1', 'csv', 'B', '2026-11-02')")
    old.commit()
    old.close()
    con = db.connect(path)
    assert [tuple(r) for r in con.execute("select business_id, source, source_id, release from source_records order by 1")] == [
        ("csv:1", "csv", None, None), ("gers-1", "overture", "gers-1", None)]
