"""Turn an area name like 'Kukatpally, Hyderabad' into a bounding box (free, via OpenStreetMap Nominatim)."""

import httpx

NOMINATIM = "https://nominatim.openstreetmap.org/search"
# Nominatim's usage policy asks for an identifying User-Agent and at most 1 request per second.
HEADERS = {"User-Agent": "LeadScout/0.1 (local lead research tool)"}

BBox = tuple[float, float, float, float]  # xmin (west), ymin (south), xmax (east), ymax (north)


def parse_bbox(text: str) -> BBox:
    xmin, ymin, xmax, ymax = (float(p) for p in text.split(","))
    return xmin, ymin, xmax, ymax


def area_bbox(area: str, max_span_deg: float = 0.12, min_span_deg: float | None = None, country: str = "IN") -> BBox:
    resp = httpx.get(
        NOMINATIM,
        params={"q": area, "format": "json", "limit": 1, "countrycodes": country.lower()},
        headers=HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    hits = resp.json()
    if not hits:
        raise ValueError(f"Couldn't find '{area.removesuffix(', India')}' on the map. Check the spelling, or try a nearby, better-known area.")
    south, north, west, east = (float(v) for v in hits[0]["boundingbox"])
    lat, lon = float(hits[0]["lat"]), float(hits[0]["lon"])
    # A whole city can be huge: clamp to a box around its centre so downloads stay quick.
    half = max_span_deg / 2
    west, south, east, north = max(west, lon - half), max(south, lat - half), min(east, lon + half), min(north, lat + half)
    # Some places are mapped as a single point: widen tiny boxes to a usable size.
    min_half = (min_span_deg if min_span_deg is not None else max_span_deg * 0.6) / 2
    return min(west, lon - min_half), min(south, lat - min_half), max(east, lon + min_half), max(north, lat + min_half)


def bbox_around(lat: float, lon: float, span_deg: float) -> BBox:
    half = span_deg / 2
    return lon - half, lat - half, lon + half, lat + half


def neighbourhood_bbox(name: str, city: str, lat: float, lon: float, span_deg: float = 0.06, country: str = "IN") -> BBox:
    """Find a neighbourhood only near the chosen city, so a same-named place elsewhere can never match."""
    view = f"{lon - 0.3},{lat + 0.3},{lon + 0.3},{lat - 0.3}"
    resp = httpx.get(
        NOMINATIM,
        params={"q": f"{name}, {city}", "format": "json", "limit": 1, "countrycodes": country.lower(), "viewbox": view, "bounded": 1},
        headers=HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    hits = resp.json()
    if not hits:
        raise ValueError(f"Couldn't find '{name}' near {city}. Check the spelling, or leave the neighbourhood empty to search the city centre.")
    return bbox_around(float(hits[0]["lat"]), float(hits[0]["lon"]), span_deg)


def locate_us_city(text: str) -> dict:
    """A US city typed as "Austin, TX" or "Austin, Texas": its centre and name, from Nominatim (one request)."""
    resp = httpx.get(
        NOMINATIM,
        params={"q": text, "format": "json", "limit": 1, "countrycodes": "us", "addressdetails": 1, "featuretype": "city"},
        headers=HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    hits = resp.json()
    if not hits:
        raise ValueError(f"Couldn't find '{text}' in the USA. Type it as city and state, e.g. Austin, TX.")
    h = hits[0]
    a = h.get("address", {})
    name = a.get("city") or a.get("town") or a.get("village") or a.get("county") or text.split(",")[0].strip()
    state = a.get("state") or ""
    return {"name": name, "state": state, "lat": float(h["lat"]), "lon": float(h["lon"]),
            "label": f"{name}, {state}" if state else name}
