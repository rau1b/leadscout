"""Google Places (API New) for the best leads, within Google's terms.

Google lets us keep only the Places `place_id` permanently. Ratings, review counts, phone numbers, websites,
opening hours and coordinates from Google are never written to the database: they are fetched when needed,
used in memory (scoring) or shown with attribution (the lead page), and dropped. Off unless [enrich]
places_enabled is true and GOOGLE_API_KEY is set. Every request counts against [enrich] monthly_request_cap.
"""

from datetime import datetime

import httpx

from leadscout import db
from leadscout.config import IST

API = "https://places.googleapis.com/v1"
SOURCE = "google"
DETAIL_FIELDS = "rating,userRatingCount,businessStatus,regularOpeningHours"
BIAS_METRES = 500.0


class CapReached(RuntimeError):
    pass


def enabled(cfg) -> bool:
    return bool(cfg.enrich["places_enabled"] and cfg.google_api_key)


def _month_key() -> str:
    return f"places_requests_{datetime.now(IST):%Y-%m}"


def used_this_month(con) -> int:
    return int(db.get_meta(con, _month_key(), 0))


def cap_message(cfg) -> str:
    return (f"Google Places stopped: this month's {cfg.enrich['monthly_request_cap']} requests are used up. "
            "It starts again on the 1st, or raise the cap in Settings.")


def _request(con, cfg, method: str, url: str, field_mask: str, **kw) -> dict:
    used, cap = used_this_month(con), cfg.enrich["monthly_request_cap"]
    if used >= cap:
        raise CapReached(cap_message(cfg))
    db.set_meta(con, _month_key(), used + 1)  # counted before sending: a request that fails may still be billed
    # shortcut: two processes enriching at the same moment can each count the same number once; fine for a soft cap.
    r = httpx.request(method, url, headers={"X-Goog-Api-Key": cfg.google_api_key, "X-Goog-FieldMask": field_mask}, timeout=15, **kw)
    r.raise_for_status()
    return r.json()


def place_id(con, business_id: str) -> str | None:
    r = con.execute("select source_id from source_records where business_id = ? and source = ?", (business_id, SOURCE)).fetchone()
    return r[0] if r else None


def find_place_id(con, cfg, name: str, where: str, lat: float, lon: float) -> str | None:
    """Text Search, IDs only: the place id when exactly one place comes back, else None (not a clear match)."""
    body = {"textQuery": f"{name}, {where}" if where else name, "pageSize": 2,
            "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lon}, "radius": BIAS_METRES}}}
    places = _request(con, cfg, "POST", f"{API}/places:searchText", "places.id", json=body).get("places") or []
    return places[0]["id"] if len(places) == 1 and places[0].get("id") else None


def match(con, cfg, area: str | None = None) -> dict:
    """Look up a Google place id for each lead at or above min_score_to_enrich that has none yet (one area, or all).
    Stores only the id, in source_records. Returns counts, plus the cap message if the month's cap was hit."""
    out = {"searched": 0, "matched": 0, "stopped": None}
    if not enabled(cfg):
        return out
    where_area = " and b.area = ?" if area else ""
    rows = con.execute(
        f"""select b.id, b.name, b.locality, b.city, b.lat, b.lon from leads l join businesses b on b.id = l.business_id
            where l.score >= ? and l.status not in ('excluded', 'hidden', 'opted_out', 'bounced')
              and b.lat is not null and b.lon is not null{where_area}
              and not exists (select 1 from source_records s where s.business_id = b.id and s.source = ?)
            order by l.score desc""",
        (cfg.enrich["min_score_to_enrich"], *([area] if area else []), SOURCE),
    ).fetchall()
    for r in rows:
        try:
            pid = find_place_id(con, cfg, r["name"], r["locality"] or r["city"], r["lat"], r["lon"])
        except CapReached as e:
            out["stopped"] = str(e)
            break
        except httpx.HTTPError:
            continue  # this one failed; the next run tries it again
        out["searched"] += 1
        if pid:
            con.execute(
                """insert into source_records (business_id, source, source_id, fetched_at) values (?, ?, ?, ?)
                   on conflict (business_id, source) do update set source_id = excluded.source_id, fetched_at = excluded.fetched_at""",
                (r["id"], SOURCE, pid, db.now()),
            )
            con.commit()
            out["matched"] += 1
    return out


def details(con, cfg, pid: str) -> dict:
    """Live Place Details: rating, userRatingCount, businessStatus, regularOpeningHours. Never store the result."""
    return _request(con, cfg, "GET", f"{API}/places/{pid}", DETAIL_FIELDS)
