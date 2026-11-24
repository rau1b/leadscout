"""Overture Maps places: free, openly licensed business data (Meta, Microsoft, Foursquare and others).

Docs: https://docs.overturemaps.org/guides/places
"""

import duckdb
from overturemaps import core

from leadscout.sources.common import pick_website, upsert_business
from leadscout.sources.geo import BBox


def download(bbox: BBox):
    """Download every place in the box as an Arrow table (only the matching files are fetched)."""
    reader = core.record_batch_reader("place", bbox=bbox)
    if reader is None:
        raise RuntimeError("Overture returned no data for this area.")
    return reader.read_all()


QUERY = """
select
    id,
    names.primary as name,
    taxonomy.primary as category,
    array_to_string(taxonomy.hierarchy, ' > ') as category_path,
    coalesce(websites, []) as websites,
    coalesce(phones, []) as phones,
    coalesce(emails, []) as emails,
    coalesce(socials, []) as socials,
    confidence,
    brand.names.primary as brand,
    addresses[1].freeform as address,
    addresses[1].locality as locality,
    addresses[1].postcode as postcode,
    (bbox.ymin + bbox.ymax) / 2 as lat,
    (bbox.xmin + bbox.xmax) / 2 as lon,
    operating_status
from places
where names.primary is not null
  and coalesce(operating_status, 'open') = 'open'
  and confidence >= ?
"""


def matches(row: dict, terms: list[str]) -> bool:
    if not terms:
        return True
    hay = " ".join(str(row.get(k) or "") for k in ("category", "category_path", "name")).lower()
    return any(t in hay for t in terms)


def ingest(con, bbox: BBox, categories: list[str], area_label: str, min_confidence: float = 0.5, city: str | None = None,
           country: str = "IN") -> tuple[int, int]:
    """Store matching places. Returns (places in area, places stored)."""
    places = download(bbox)  # noqa: F841 (read by duckdb below)
    duck = duckdb.connect()
    duck.register("places", places)
    cur = duck.execute(QUERY, [min_confidence])
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    terms = [c.strip().lower().replace(" ", "_") for c in categories if c.strip() and c.strip().lower() != "all"]
    # Also match the plain words ("dental clinic" -> "dental", "clinic").
    terms += [w for c in categories for w in c.lower().split() if len(w) > 3 and w != "all"]
    stored = 0
    for r in rows:
        if not matches(r, terms):
            continue
        upsert_business(
            con,
            {
                "id": r["id"],
                "source": "overture",
                "name": r["name"],
                "category": r["category"],
                "category_path": r["category_path"],
                "address": r["address"],
                "locality": r["locality"],
                "postcode": r["postcode"],
                "lat": r["lat"],
                "lon": r["lon"],
                "phone": (r["phones"] or [None])[0],
                # With no own site, a social page becomes the "website" so it classifies as social_only.
                "website": pick_website(list(r["websites"]) + list(r["socials"])),
                "emails": list(r["emails"]),
                "socials": list(r["socials"]),
                "confidence": r["confidence"],
                "brand": r["brand"],
                "area": area_label,
                "city": city,
                "country": country,
            },
        )
        stored += 1
    con.commit()
    return len(rows), stored
