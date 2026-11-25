"""Opt-out list, sending window and data retention (see docs/INDIA_RULES.md)."""

import hashlib
import json
from datetime import datetime, time, timedelta

import phonenumbers

from leadscout.config import IST, data_dir
from leadscout import backups
from leadscout.db import file_of, jload, now

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


def suppress(con, value: str | None, reason: str) -> None:
    if not value:
        return  # e.g. a bounce on a lead that has no email stored
    con.execute("insert or ignore into suppression(value_hash, reason, added_at) values(?, ?, ?)", (_hash(value), reason, now()))
    con.commit()


def is_suppressed(con, *values: str | None) -> bool:
    hashes = [_hash(v) for v in values if v]
    if not hashes:
        return False
    marks = ",".join("?" * len(hashes))
    return con.execute(f"select 1 from suppression where value_hash in ({marks})", hashes).fetchone() is not None


def is_opted_out(con, *values: str | None) -> bool:
    """Like is_suppressed, but a bounce doesn't count: a dead address says nothing about the person."""
    hashes = [_hash(v) for v in values if v]
    if not hashes:
        return False
    marks = ",".join("?" * len(hashes))
    return con.execute(f"select 1 from suppression where reason != 'bounced' and value_hash in ({marks})", hashes).fetchone() is not None


def lead_is_suppressed(con, business_id: str) -> bool:
    """True if this lead said no (email or phone). Used by the dashboard; sending still skips bounced addresses too."""
    r = con.execute(
        "select l.email, b.phone from leads l join businesses b on b.id = l.business_id where l.business_id = ?", (business_id,)
    ).fetchone()
    return bool(r) and is_opted_out(con, r["email"], r["phone"])


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
    rows = con.execute(
        """select b.id, b.phone, b.emails, a.found_emails, l.email from businesses b
           left join audits a on a.business_id = b.id left join leads l on l.business_id = b.id"""
    ).fetchall()

    def holds(r) -> bool:
        emails = {e.strip().lower() for e in jload(r["emails"]) + jload(r["found_emails"]) + [r["email"] or ""]}
        return key in emails or (r["phone"] and normalize(r["phone"]) == key)

    ids = {r["id"] for r in rows if holds(r)}
    for bid in ids:
        con.execute("delete from businesses where id = ?", (bid,))
    suppress(con, value, "forget request")
    con.commit()
    _forget_in_pitch_files(ids)
    return len(ids)


def _forget_in_pitch_files(ids: set[str]) -> None:
    """Drop these businesses from the Claude Code hand-off files too (data/pitch_jobs.json, pitch_results*.json)."""
    if not ids:
        return
    for path in data_dir().glob("pitch_*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("leads"), list):
            data["leads"] = [x for x in data["leads"] if x.get("id") not in ids]
        elif isinstance(data, list):
            data = [x for x in data if not (isinstance(x, dict) and x.get("id") in ids)]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def in_window(cfg_sending: dict, at: datetime | None = None) -> bool:
    at = at or datetime.now(IST)
    if DAYS[at.weekday()] not in cfg_sending["days"]:
        return False
    if at.date().isoformat() in cfg_sending.get("skip_dates", []):
        return False  # festivals and holidays you listed in config.toml
    start = time.fromisoformat(cfg_sending["window_start"])
    end = time.fromisoformat(cfg_sending["window_end"])
    return start <= at.time() < end


def purge_stale(con, days: int) -> int:
    """Delete businesses never contacted whose data is older than `days`.

    A lead you've moved on yourself (approved, replied, won, lost, opted out...) or put a deal amount on is kept,
    even with no email sent: you may have reached them by phone or WhatsApp.
    """
    cutoff = (datetime.now(IST) - timedelta(days=days)).isoformat(timespec="seconds")
    cur = con.execute(
        """delete from businesses where fetched_at < ? and id not in (select business_id from outreach)
           and id not in (select business_id from leads
                          where status not in ('new', 'drafted', 'excluded', 'hidden')
                             or quote_inr is not null or paid_inr is not null)""",
        (cutoff,),
    )
    con.commit()
    return cur.rowcount


def purge_if_due(con, cfg) -> int | None:
    """Run purge_stale at most once a day (the dashboard calls this on start). None if it already ran today."""
    from leadscout.db import get_meta, set_meta

    today = datetime.now(IST).date().isoformat()
    if get_meta(con, "last_purge") == today:
        return None
    n = purge_stale(con, cfg.retention["purge_uncontacted_after_days"])
    backups.prune(backups.folder(file_of(con)), cfg.backups["keep_days"])
    set_meta(con, "last_purge", today)
    return n
