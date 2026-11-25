"""Demo sites: one static concept page per business, built only from what its businesses row holds.

Honesty rules (tests/test_demos.py checks them):
- Only facts from the businesses row. No reviews, prices, years, photos or logos.
- Every page carries a fixed banner saying it's a concept by us, not the business's official site, and a noindex tag.
- The slug is unguessable, the page expires after 30 days, and a suppressed business gets no page.
"""

import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

import phonenumbers
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from leadscout import db
from leadscout.compliance import is_suppressed

EXPIRES_AFTER_DAYS = 30

# Matched against basic_category, then category + category_path (Overture's taxonomy, e.g. "dentist", "health_and_medical > dentist").
# Clinic is checked first, so "medical_spa" gets the clinic page.
VERTICALS = {
    "clinic": ("dentist", "dental", "clinic", "doctor", "physio", "dermatolog", "hospital", "medical", "orthodont", "optometr", "eye_care", "health"),
    "salon": ("salon", "spa", "beauty", "barber", "hair", "nail", "massage", "makeup", "cosmetic"),
}
LABELS = {"clinic": "clinic", "salon": "salon", "shop": "shop"}  # "Call the clinic"

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(default=True, default_for_string=True),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


class Refused(Exception):
    """This business must not get a demo page (unknown, or on the opt-out list)."""


@dataclass
class Demo:
    slug: str
    template: str
    path: Path
    built_at: str
    expires_at: str


def folder(con) -> Path | None:
    """data/demos/ beside this database file, so pages always belong to the database that lists them
    (a test database never touches the real pages). None for an in-memory database."""
    f = db.file_of(con)
    return f.parent / "demos" if str(f) else None


def _basic(row) -> str | None:
    """Overture's plain label (contract C3). The column arrives with Jason's Phase 1 Step 1; until then it's None."""
    return (row["basic_category"] or None) if "basic_category" in row.keys() else None


def pick_template(row) -> str:
    """basic_category first (C3), then category and category_path."""
    for cat in (_basic(row), f"{row['category'] or ''} {row['category_path'] or ''}"):
        cat = (cat or "").lower()
        for name, words in VERTICALS.items():
            if any(w in cat for w in words):
                return name
    return "shop"


def _humanize(category: str | None, path: str | None) -> str | None:
    """"dental_clinic" -> "Dental clinic". Falls back to the last part of the taxonomy path."""
    raw = category or (path.split(">")[-1] if path else "")
    raw = raw.replace("_", " ").strip()
    return raw[:1].upper() + raw[1:] if raw else None


def _join(*parts) -> str | None:
    """Non-empty parts, in order, without repeats ("Kukatpally, Hyderabad, Hyderabad" -> "Kukatpally, Hyderabad")."""
    seen, out = set(), []
    for p in parts:
        p = (p or "").strip()
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return ", ".join(out) or None


def _pretty(phone: str | None) -> str | None:
    """+919812345678 -> +91 98123 45678 (the same number, easier to read)."""
    if not phone:
        return None
    try:
        return phonenumbers.format_number(phonenumbers.parse(phone, "IN"), phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    except phonenumbers.NumberParseException:
        return phone


def facts(row) -> dict:
    """Everything the page may show about the business. Every value comes straight from its businesses row."""
    keys = row.keys()
    phone = row["phone"] or None
    lat, lon = row["lat"], row["lon"]
    area = _join(row["locality"], row["city"]) or _join(row["area"])
    address = _join(row["address"], row["locality"], row["city"], row["postcode"])
    if lat is not None and lon is not None:
        maps = "https://www.google.com/maps/search/?" + urlencode({"api": 1, "query": f"{lat},{lon}"})
    elif address:
        maps = "https://www.google.com/maps/search/?" + urlencode({"api": 1, "query": f"{row['name']}, {address}"})
    else:
        maps = None
    return {
        "name": row["name"],
        "what": _humanize(_basic(row) or row["category"], row["category_path"]),
        "area": area,
        "address": address,
        "hours": (row["hours"] or None) if "hours" in keys else None,  # no hours column yet; shown once a source fills one
        "phone": _pretty(phone),
        "tel": f"tel:{phone}" if phone else None,
        # WhatsApp only works on mobile numbers; a landline gets the call button alone.
        "whatsapp": f"https://wa.me/{phone.lstrip('+')}" if phone and row["phone_type"] == "mobile" else None,
        "maps": maps,
    }


def studio_of(sender: dict) -> dict:
    """Our side of the page: the banner names the studio, the enquiry section shows only our contact."""
    phone = (sender.get("phone") or "").strip()
    email = (sender.get("email") or "").strip()
    return {
        "studio": sender.get("business") or sender.get("name"),
        "person": sender.get("name"),
        "phone": phone or None,
        "tel": "tel:" + "".join(c for c in phone if c.isdigit() or c == "+") if phone else None,
        "email": email or None,
        "mailto": f"mailto:{email}?subject={quote('A website like this')}" if email else None,
    }


def render(row, sender: dict) -> tuple[str, str]:
    """(template name, page HTML) for this businesses row."""
    template = pick_template(row)
    html = _env.get_template(f"{template}.html.j2").render(biz=facts(row), us=studio_of(sender), label=LABELS[template])
    return template, html


def contact_values(con, business_id: str) -> list[str]:
    """Every email and phone stored for this business (businesses, audits, leads), to check against the opt-out list."""
    r = con.execute(
        """select b.phone, b.emails, a.found_emails, l.email from businesses b
           left join audits a on a.business_id = b.id left join leads l on l.business_id = b.id where b.id = ?""",
        (business_id,),
    ).fetchone()
    if not r:
        return []
    return [v for v in [r["phone"], r["email"], *db.jload(r["emails"]), *db.jload(r["found_emails"])] if v]


def build(con, business_id: str, sender: dict, actor: str = "cli") -> Demo:
    """Write data/demos/<slug>/index.html, record it in `demos` and log demo_built. Replaces this business's older demo."""
    row = con.execute("select * from businesses where id = ?", (business_id,)).fetchone()
    if not row:
        raise Refused(f"No business with id {business_id}.")
    status = con.execute("select status from leads where business_id = ?", (business_id,)).fetchone()
    if is_suppressed(con, *contact_values(con, business_id)) or (status and status["status"] == "opted_out"):
        raise Refused(f"{row['name']} is on the opt-out list. No demo is built for them.")

    root = folder(con)
    if root is None:
        raise Refused("Demo pages need a database file, not an in-memory one.")
    template, html = render(row, sender)
    slug = secrets.token_urlsafe(16)
    while con.execute("select 1 from demos where slug = ?", (slug,)).fetchone() or (root / slug).exists():
        slug = secrets.token_urlsafe(16)
    path = root / slug / "index.html"
    path.parent.mkdir(parents=True)
    path.write_text(html, encoding="utf-8")

    built = datetime.fromisoformat(db.now())
    built_at, expires_at = built.isoformat(timespec="seconds"), (built + timedelta(days=EXPIRES_AFTER_DAYS)).isoformat(timespec="seconds")
    old = [r["slug"] for r in con.execute("select slug from demos where business_id = ?", (business_id,))]
    try:
        con.execute("delete from demos where business_id = ?", (business_id,))
        con.execute(
            "insert into demos (slug, business_id, template, url, built_at, expires_at) values (?, ?, ?, null, ?, ?)",
            (slug, business_id, template, built_at, expires_at),
        )
        db.log_event(con, "demo_built", business_id, actor=actor, template=template)
        con.commit()
    except BaseException:
        con.rollback()
        shutil.rmtree(path.parent, ignore_errors=True)
        raise
    for s in old:
        shutil.rmtree(root / s, ignore_errors=True)
    return Demo(slug, template, path, built_at, expires_at)


def remove_orphans(con) -> int:
    """Delete demo folders whose row is gone (the business was forgotten or purged), so its details don't linger on disk.
    compliance.forget() calls this (contract C8)."""
    root = folder(con)
    if root is None or not root.exists():
        return 0
    live = {r[0] for r in con.execute("select slug from demos")}
    gone = [d for d in root.iterdir() if d.is_dir() and d.name not in live]
    for d in gone:
        shutil.rmtree(d, ignore_errors=True)
    return len(gone)
