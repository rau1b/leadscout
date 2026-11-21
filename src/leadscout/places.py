"""Every Indian city, town and large village (population 500+), offline, for the city picker.

Data: GeoNames (CC BY 4.0, https://www.geonames.org), built by scripts/build_places.py.
Each place has its other spellings (Madgaon = Margao), state, district, population and map position,
so a search runs at the exact place picked, never at a same-named village in another state.
"""

import gzip
import json
import unicodedata
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data" / "places_in.json.gz"


def fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()


# Names people actually use, which GeoNames may list oddly or not at all. name -> other names
COMMON_NAMES = {
    "Bengaluru": ["Bangalore"], "Mumbai": ["Bombay"], "Chennai": ["Madras"], "Kolkata": ["Calcutta"],
    "Visakhapatnam": ["Vizag", "Vishakhapatnam", "Vishakapatnam"], "Thiruvananthapuram": ["Trivandrum"],
    "Kochi": ["Cochin", "Ernakulam"], "Gurugram": ["Gurgaon"], "Puducherry": ["Pondicherry", "Pondy"],
    "Mysuru": ["Mysore"], "Mangaluru": ["Mangalore"], "Hubballi": ["Hubli"], "Belagavi": ["Belgaum"],
    "Vadodara": ["Baroda"], "Prayagraj": ["Allahabad"], "Kozhikode": ["Calicut"], "Pune": ["Poona"],
    "Madgaon": ["Margao", "Madgao"], "Panaji": ["Panjim"], "Varanasi": ["Banaras", "Benares", "Kashi"],
    "Thrissur": ["Trichur"], "Tiruchirappalli": ["Trichy", "Tiruchi"], "Kalaburagi": ["Gulbarga"],
    "Vijayawada": ["Bezawada"], "Secunderabad": ["Secundrabad"], "Mohali": ["SAS Nagar"],
    "Navi Mumbai": ["New Bombay"], "Shimla": ["Simla"], "Kanpur": ["Cawnpore"], "Ooty": ["Udhagamandalam"],
    "Udhagamandalam": ["Ooty"], "Vasco Da Gama": ["Vasco"], "Mapuca": ["Mapusa"],
}


@lru_cache(maxsize=1)
def _places() -> list[dict]:
    with gzip.open(DATA, "rt", encoding="utf-8") as f:
        places = json.load(f)
    for i, p in enumerate(places):
        p["id"] = i
        extra = [a for a in COMMON_NAMES.get(p["n"], []) if a not in p["a"]]
        p["a"] = extra + p["a"]
        p["_keys"] = [fold(p["n"])] + [fold(a) for a in p["a"]]
    return places


def label(p: dict, alt: str = "") -> str:
    """'Madgaon (Margao), South Goa, Goa': the other name only when that's what you typed; the state always."""
    if not alt and p["n"] in COMMON_NAMES:
        alt = COMMON_NAMES[p["n"]][0]
    name = f"{p['n']} ({alt})" if alt and fold(alt) != fold(p["n"]) else p["n"]
    parts = [name] + [x for x in (p["d"], p["s"]) if x and fold(x) != fold(p["n"])]
    return ", ".join(dict.fromkeys(parts))


def search(q: str, limit: int = 8) -> list[dict]:
    q = fold(q)
    if len(q) < 2:
        return []
    scored = []
    for p in _places():
        best, via = None, ""
        for i, k in enumerate(p["_keys"]):
            if k == q:
                rank = 0
            elif k.startswith(q):
                rank = 1
            elif any(w.startswith(q) for w in k.split()):
                rank = 2
            elif len(q) >= 4 and q in k:
                rank = 3
            else:
                continue
            if best is None or rank < best:
                alt = "" if i == 0 else p["a"][i - 1]
                best, via = rank, (alt if alt[:1].isupper() else "")  # never show a lowercase transliteration
        if best is not None:
            scored.append((best, -p["p"], p, via))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [public(p, via) for _, _, p, via in scored[:limit]]


def public(p: dict, alt: str = "") -> dict:
    return {"id": p["id"], "name": p["n"], "label": label(p, alt), "state": p["s"], "district": p["d"],
            "population": p["p"], "lat": p["lat"], "lon": p["lon"]}


def get(place_id: int) -> dict | None:
    places = _places()
    return public(places[place_id]) if 0 <= place_id < len(places) else None


def best_match(text: str) -> dict | None:
    """For a city typed without picking a suggestion: the biggest exact-name match, if any."""
    hits = search(text, limit=20)
    exact = [h for h in hits if fold(text) in (fold(h["name"]), *[fold(a) for a in _places()[h["id"]]["a"]])]
    return exact[0] if exact else None


def span_for(population: int) -> float:
    """Search box size in degrees (~111 km each): big cities get a wider centre, towns a tighter one."""
    if population >= 1_000_000:
        return 0.12
    if population >= 200_000:
        return 0.08
    return 0.05
