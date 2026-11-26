"""Shared helpers for every data source."""

import json
from urllib.parse import urlparse

import phonenumbers

from leadscout.db import now

SOCIAL_DOMAINS = (
    "facebook.com", "fb.com", "instagram.com", "linktr.ee", "wa.me", "whatsapp.com",
    "youtube.com", "twitter.com", "x.com", "linkedin.com", "t.me",
)
DIRECTORY_DOMAINS = (
    "justdial.com", "indiamart.com", "sulekha.com", "tradeindia.com", "practo.com",
    "zomato.com", "swiggy.com", "magicbricks.com", "99acres.com", "housing.com",
    "urbanclap.com", "urbancompany.com", "lybrate.com", "google.com", "g.page",
    "goo.gl", "maps.app.goo.gl", "booking.com", "tripadvisor.com", "tripadvisor.in",
    "makemytrip.com", "yellowpages.in", "asklaila.com",
)


def domain(url: str | None) -> str:
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def domain_in(url: str | None, domains: tuple[str, ...]) -> bool:
    d = domain(url)
    return any(d == x or d.endswith("." + x) for x in domains)


def pick_website(urls: list[str]) -> str | None:
    """Prefer the business's own site over social or directory pages."""
    urls = [u for u in urls if u]
    own = [u for u in urls if not domain_in(u, SOCIAL_DOMAINS + DIRECTORY_DOMAINS)]
    return (own or urls or [None])[0]


def phone_info(raw: str | None) -> tuple[str | None, str | None]:
    if not raw:
        return None, None
    try:
        num = phonenumbers.parse(raw, "IN")
    except phonenumbers.NumberParseException:
        return None, None
    if not phonenumbers.is_valid_number(num):
        return None, None
    kind = phonenumbers.number_type(num)
    label = {
        phonenumbers.PhoneNumberType.MOBILE: "mobile",
        phonenumbers.PhoneNumberType.FIXED_LINE: "landline",
        phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE: "mobile",
    }.get(kind, "other")
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164), label


def upsert_business(con, b: dict) -> None:
    phone, phone_type = phone_info(b.get("phone"))
    con.execute(
        """insert into businesses (id, source, name, category, category_path, basic_category, category_alternates, address,
               locality, postcode, lat, lon, phone, phone_type, website, emails, socials, confidence, brand, area, city, fetched_at)
           values (:id, :source, :name, :category, :category_path, :basic_category, :category_alternates, :address,
               :locality, :postcode, :lat, :lon, :phone, :phone_type, :website, :emails, :socials, :confidence, :brand, :area, :city, :fetched_at)
           on conflict(id) do update set
               name = excluded.name, category = excluded.category, category_path = excluded.category_path,
               basic_category = excluded.basic_category, category_alternates = excluded.category_alternates,
               address = excluded.address, locality = excluded.locality, postcode = excluded.postcode,
               phone = excluded.phone, phone_type = excluded.phone_type, website = excluded.website,
               emails = excluded.emails, socials = excluded.socials, confidence = excluded.confidence,
               brand = excluded.brand, fetched_at = excluded.fetched_at,
               area = coalesce(excluded.area, area), city = coalesce(excluded.city, city)""",
        # shortcut: a business belongs to one area, the latest search that found it, so an older overlapping
        # search's count drops; add a business<->search link table if per-search counts must stay exact.
        {
            "id": b["id"],
            "source": b["source"],
            "name": b["name"],
            "category": b.get("category"),
            "category_path": b.get("category_path"),
            "basic_category": b.get("basic_category"),
            "category_alternates": json.dumps(list(b.get("category_alternates") or [])),
            "address": b.get("address"),
            "locality": b.get("locality"),
            "postcode": b.get("postcode"),
            "lat": b.get("lat"),
            "lon": b.get("lon"),
            "phone": phone,
            "phone_type": phone_type,
            "website": b.get("website"),
            "emails": json.dumps(sorted({e.strip().lower() for e in b.get("emails") or [] if e and "@" in e})),
            "socials": json.dumps(b.get("socials") or []),
            "confidence": b.get("confidence"),
            "brand": b.get("brand"),
            "area": b.get("area"),
            "city": b.get("city") or ((b.get("area") or "").split(",")[-1].strip() or None),
            "fetched_at": now(),
        },
    )
    con.execute(
        """insert into source_records (business_id, source, source_id, fetched_at, release) values (?, ?, ?, ?, ?)
           on conflict (business_id, source) do update set source_id = excluded.source_id,
               fetched_at = excluded.fetched_at, release = excluded.release""",
        (b["id"], b["source"], b.get("source_id"), now(), b.get("release")),
    )
