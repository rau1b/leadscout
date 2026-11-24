"""Opt-out list, sending window and data retention (see docs/INDIA_RULES.md)."""

import hashlib
from datetime import datetime, time, timedelta

import phonenumbers

from leadscout.config import IST
from leadscout.db import jload, now

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def normalize(value: str) -> str:
    """Lowercased email, or a phone number in +91 E.164 form."""
    value = value.strip()
    if "@" in value:
        return value.lower()
    try:
        return phonenumbers.format_number(phonenumbers.parse(value, "IN"), phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        return value


def _hash(value: str) -> str:
    # Stored hashed so the opt-out list itself holds no readable personal data.
    return hashlib.sha256(normalize(value).encode()).hexdigest()


def suppress(con, value: str, reason: str) -> None:
    con.execute("insert or ignore into suppression(value_hash, reason, added_at) values(?, ?, ?)", (_hash(value), reason, now()))
    con.commit()


def is_suppressed(con, *values: str | None) -> bool:
    hashes = [_hash(v) for v in values if v]
    if not hashes:
        return False
    marks = ",".join("?" * len(hashes))
    return con.execute(f"select 1 from suppression where value_hash in ({marks})", hashes).fetchone() is not None


def lead_is_suppressed(con, business_id: str) -> bool:
    """True if this lead's email or phone is on the opt-out list."""
    r = con.execute(
        "select l.email, b.phone from leads l join businesses b on b.id = l.business_id where l.business_id = ?", (business_id,)
    ).fetchone()
    return bool(r) and is_suppressed(con, r["email"], r["phone"])


def opt_out(con, value: str, reason: str) -> int:
    """Suppress an email or phone and mark every lead holding it as opted out. Returns leads updated."""
    suppress(con, value, reason)
    key = normalize(value)
    cur = con.execute(
        """update leads set status = 'opted_out', updated_at = ?
           where lower(email) = ? or business_id in (select id from businesses where phone = ?)""",
        (now(), key, key),
    )
    con.commit()
    return cur.rowcount


def forget(con, value: str) -> int:
    """Delete every business holding this email/phone; keep only the hashed opt-out entry."""
    key = normalize(value)
    rows = con.execute("select id, phone, emails from businesses").fetchall()
    # Exact matches only: a substring test would also delete aa@shop.in when asked to forget a@shop.in.
    ids = [r["id"] for r in rows if r["phone"] == key or key in {e.strip().lower() for e in jload(r["emails"])}]
    ids += [r["business_id"] for r in con.execute("select business_id from leads where lower(email) = ?", (key,))]
    ids = sorted(set(ids))
    for bid in ids:
        con.execute("delete from businesses where id = ?", (bid,))
    suppress(con, value, "forget request")
    con.commit()
    return len(ids)


def in_window(cfg_sending: dict, at: datetime | None = None) -> bool:
    at = at or datetime.now(IST)
    if DAYS[at.weekday()] not in cfg_sending["days"]:
        return False
    start = time.fromisoformat(cfg_sending["window_start"])
    end = time.fromisoformat(cfg_sending["window_end"])
    return start <= at.time() < end


def purge_stale(con, days: int) -> int:
    """Delete businesses never contacted whose data is older than `days`."""
    cutoff = (datetime.now(IST) - timedelta(days=days)).isoformat(timespec="seconds")
    cur = con.execute(
        "delete from businesses where fetched_at < ? and id not in (select business_id from outreach)", (cutoff,)
    )
    con.commit()
    return cur.rowcount
