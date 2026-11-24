"""SQLite storage. One file: data/leadscout.db."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from leadscout.config import IST, data_dir

SCHEMA = """
create table if not exists businesses (
    id text primary key,
    source text not null,
    name text not null,
    category text,
    category_path text,
    address text,
    locality text,
    postcode text,
    lat real,
    lon real,
    phone text,
    phone_type text,
    website text,
    emails text default '[]',
    socials text default '[]',
    confidence real,
    brand text,
    area text,
    city text,
    fetched_at text not null
);
create table if not exists searches (
    id integer primary key autoincrement,
    city text not null,
    neighbourhood text,
    label text not null,
    categories text not null,
    status text not null default 'queued',
    message text,
    places integer,
    stored integer,
    created_at text not null,
    finished_at text,
    lat real,
    lon real,
    state text,
    population integer,
    resolved text
);
create table if not exists audits (
    business_id text primary key references businesses(id) on delete cascade,
    site_class text not null,
    final_url text,
    status_code integer,
    https integer,
    viewport integer,
    copyright_year integer,
    generator text,
    has_whatsapp integer,
    has_tel integer,
    has_maps integer,
    has_form integer,
    found_emails text default '[]',
    perf_score integer,
    lcp_s real,
    cls real,
    tbt_ms integer,
    psi_error text,
    fetch_error text,
    audited_at text not null
);
create table if not exists leads (
    business_id text primary key references businesses(id) on delete cascade,
    score integer not null,
    reasons text not null default '[]',
    status text not null default 'new',
    email text,
    email_ok integer,
    quote_inr integer,
    paid_inr integer,
    deal_note text,
    won_at text,
    updated_at text not null
);
create table if not exists pitches (
    business_id text primary key references businesses(id) on delete cascade,
    subject text not null,
    body text not null,
    whatsapp text,
    source text not null,
    approved integer not null default 0,
    created_at text not null,
    updated_at text not null
);
create table if not exists outreach (
    id integer primary key autoincrement,
    business_id text references businesses(id) on delete cascade,
    channel text not null,
    kind text not null,
    to_addr text,
    gmail_id text,
    thread_id text,
    sent_at text not null
);
create table if not exists suppression (
    value_hash text primary key,
    reason text,
    added_at text not null
);
create table if not exists replies (
    gmail_id text primary key,
    business_id text references businesses(id) on delete cascade,
    thread_id text,
    from_addr text,
    subject text,
    body text,
    received_at text,
    kind text
);
create table if not exists meta (key text primary key, value text);
create index if not exists idx_leads_status on leads(status);
create index if not exists idx_outreach_sent on outreach(sent_at);
"""

# Lead status flow:
# new -> drafted -> approved -> contacted -> replied | won | lost
# plus: opted_out, bounced, excluded (by scoring), hidden (by you; scoring never changes it)
STATUSES = ["new", "drafted", "approved", "contacted", "replied", "won", "lost", "opted_out", "bounced", "excluded", "hidden"]


def now() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


# Database files already migrated in this process. The dashboard connects on every request, so the
# migration and schema script run once per file instead of on every page load.
_ready: set[str] = set()


def connect(path=None) -> sqlite3.Connection:
    path = Path(path or data_dir() / "leadscout.db").resolve()
    fresh = str(path) not in _ready or not path.exists()
    # The dashboard's search worker writes while pages read: wait for locks instead of failing, and use WAL.
    con = sqlite3.connect(path, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys = on")
    if fresh:
        con.execute("pragma journal_mode = wal")  # stored in the file, so once is enough
        _migrate(con)
        con.executescript(SCHEMA)
        _ready.add(str(path))
    return con


def _migrate(con) -> None:
    """Bring databases created by older versions up to date."""
    cols = {r[1] for r in con.execute("pragma table_info(businesses)")}
    if cols and "city" not in cols:
        con.execute("alter table businesses add column city text")
        # Older rows stored "Area, City" in `area`; the city is the last part.
        for bid, area in con.execute("select id, area from businesses").fetchall():
            city = (area or "").split(",")[-1].strip() or None
            con.execute("update businesses set city = ? where id = ?", (city, bid))
        con.commit()
    search_cols = {r[1] for r in con.execute("pragma table_info(searches)")}
    for col, kind in (("lat", "real"), ("lon", "real"), ("state", "text"), ("population", "integer"), ("resolved", "text")):
        if search_cols and col not in search_cols:
            con.execute(f"alter table searches add column {col} {kind}")
    if search_cols:
        # Older versions added a new row each time an area was searched again: keep only the latest finished one.
        con.execute(
            """delete from searches where status in ('done', 'failed') and id not in (
                   select max(id) from searches
                   group by coalesce(round(lat, 4) || ',' || round(lon, 4), lower(label)), lower(coalesce(neighbourhood, '')))"""
        )
    lead_cols = {r[1] for r in con.execute("pragma table_info(leads)")}
    for col, kind in (("quote_inr", "integer"), ("paid_inr", "integer"), ("deal_note", "text"), ("won_at", "text")):
        if lead_cols and col not in lead_cols:
            con.execute(f"alter table leads add column {col} {kind}")
    con.commit()


def jload(s) -> list:
    return json.loads(s) if s else []


def get_meta(con, key, default=None):
    row = con.execute("select value from meta where key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(con, key, value) -> None:
    con.execute("insert into meta(key, value) values(?, ?) on conflict(key) do update set value = excluded.value", (key, str(value)))
    con.commit()
