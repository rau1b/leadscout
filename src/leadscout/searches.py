"""Area searches started from the dashboard: find -> audit -> score, one at a time, in a background thread."""

import json
import threading
import time
import traceback

from leadscout import config, db
from leadscout.db import now

# Business types offered in the dashboard, mapped to the words matched against Overture's categories and names.
BUSINESS_TYPES = {
    "dental": ("Dental clinics", "dental,dentist,dentistry,orthodont"),
    "clinics": ("Clinics and doctors", "clinic,physiotherap,dermatolog,ayurved,homeopath,diagnostic"),
    "interior": ("Interior designers", "interior"),
    "realestate": ("Real estate and builders", "real_estate,home_developer,builder,property,realtor"),
    "coaching": ("Coaching and tuition", "coaching,tutoring,educational,training_cent"),
    "salons": ("Salons and spas", "beauty_salon,salon,day_spa,massage,bridal"),
    "fitness": ("Gyms and fitness", "gym,fitness,yoga,martial"),
    "food": ("Restaurants and cafes", "restaurant,cafe,bakery,sweet,catering"),
    "events": ("Events, weddings, photography", "event_planning,wedding,photograph,decorat"),
    "retail": ("Boutiques and jewellery", "boutique,clothing,jewel,saree,tailor"),
    "professional": ("Lawyers and CAs", "lawyer,legal,accountant,chartered,tax"),
    "auto": ("Car and bike dealers, garages", "car_dealer,motorcycle,auto_repair,garage"),
}

CITIES = [
    "Hyderabad", "Secunderabad", "Warangal", "Karimnagar", "Nizamabad", "Khammam", "Vijayawada", "Visakhapatnam",
    "Guntur", "Nellore", "Tirupati", "Kakinada", "Rajahmundry", "Bengaluru", "Mysuru", "Mangaluru", "Hubballi",
    "Chennai", "Coimbatore", "Madurai", "Tiruchirappalli", "Kochi", "Thiruvananthapuram", "Kozhikode", "Mumbai",
    "Pune", "Nagpur", "Nashik", "Aurangabad", "Delhi", "Noida", "Gurugram", "Jaipur", "Lucknow", "Kanpur",
    "Ahmedabad", "Surat", "Vadodara", "Indore", "Bhopal", "Kolkata", "Bhubaneswar", "Patna", "Chandigarh",
    "Ludhiana", "Dehradun", "Guwahati", "Raipur", "Ranchi", "Goa",
]

_wake = threading.Event()
_started = False
_lock = threading.Lock()


def queue_search(con, city: str, neighbourhood: str, type_keys: list[str], extra: str = "", place_id: int | None = None) -> int:
    from leadscout import places

    terms = [BUSINESS_TYPES[k][1] for k in type_keys if k in BUSINESS_TYPES]
    if extra.strip():
        terms.append(extra.strip())
    if not terms:
        raise ValueError("Pick at least one business type.")
    city, neighbourhood = city.strip(), neighbourhood.strip()
    if not city:
        raise ValueError("Enter a city.")
    # The exact place picked from the suggestions; typed text falls back to the biggest exact-name match.
    place = places.get(place_id) if place_id is not None else places.best_match(city)
    if not place:
        raise ValueError(f"Couldn't find '{city}' in the list of Indian places. Start typing and pick it from the suggestions.")
    label = f"{neighbourhood}, {place['name']}" if neighbourhood else place["name"]
    names = [BUSINESS_TYPES[k][0] for k in type_keys if k in BUSINESS_TYPES] + ([extra.strip()] if extra.strip() else [])
    # The same area searched again runs its existing entry again, with any new business types added, so an
    # area is never listed twice.
    same = con.execute(
        """select * from searches where abs(lat - ?) < 0.0001 and abs(lon - ?) < 0.0001
           and lower(coalesce(neighbourhood, '')) = lower(?) order by id desc limit 1""",
        (place["lat"], place["lon"], neighbourhood),
    ).fetchone()
    if same:
        if same["status"] == "running":
            raise ValueError(f"{same['label']} is being searched right now. Its results will appear when it finishes.")
        old = json.loads(same["categories"])
        merged_terms = list(dict.fromkeys(old["terms"].split(",") + ",".join(terms).split(",")))
        merged_names = list(dict.fromkeys(old["names"] + names))
        con.execute(
            """update searches set categories = ?, status = 'queued', message = 'Waiting to start (searching again)',
               created_at = ?, finished_at = null where id = ?""",
            (json.dumps({"terms": ",".join(merged_terms), "names": merged_names}), now(), same["id"]),
        )
        con.commit()
        _wake.set()
        return same["id"]
    cur = con.execute(
        """insert into searches (city, neighbourhood, label, categories, status, message, created_at, lat, lon, state, population, resolved)
           values (?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)""",
        (place["name"], neighbourhood or None, label, json.dumps({"terms": ",".join(terms), "names": names}),
         "Waiting to start", now(), place["lat"], place["lon"], place["state"], place["population"], place["label"]),
    )
    con.commit()
    _wake.set()
    return cur.lastrowid


def _update(con, sid: int, **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    con.execute(f"update searches set {sets} where id = ?", (*fields.values(), sid))
    con.commit()


def area_box(s):
    """Map box for a search, anchored on the city that was picked."""
    from leadscout import places
    from leadscout.sources import geo

    if s["lat"] is None:  # searches queued by an older version
        query = f"{s['neighbourhood']}, {s['city']}" if s["neighbourhood"] else s["city"]
        box = geo.area_bbox(f"{query}, India", max_span_deg=0.06 if s["neighbourhood"] else 0.12)
        time.sleep(1)  # Nominatim fair use
        return box
    if not s["neighbourhood"]:
        return geo.bbox_around(s["lat"], s["lon"], places.span_for(s["population"] or 0))
    # A neighbourhood: first look in the offline list, near the chosen city only.
    for p in places.search(s["neighbourhood"], limit=20):
        if abs(p["lat"] - s["lat"]) < 0.35 and abs(p["lon"] - s["lon"]) < 0.35:
            return geo.bbox_around(p["lat"], p["lon"], 0.06)
    box = geo.neighbourhood_bbox(s["neighbourhood"], s["city"], s["lat"], s["lon"])
    time.sleep(1)  # Nominatim fair use
    return box


def _run(con, s) -> None:
    from leadscout.audit import audit_pending
    from leadscout.scoring import score_all
    from leadscout.sources import overture

    cfg = config.load()
    sid = s["id"]
    _update(con, sid, status="running", message="Finding the area on the map")
    box = area_box(s)
    _update(con, sid, message="Downloading businesses from Overture Maps")
    terms = json.loads(s["categories"])["terms"].split(",")
    places, stored = overture.ingest(con, box, terms, s["label"], city=s["city"])
    _update(con, sid, places=places, stored=stored, message=f"Checking {stored} websites")
    done = {"n": 0}

    def progress(name, site_class):
        done["n"] += 1
        if done["n"] % 10 == 0:
            _update(con, sid, message=f"Checked {done['n']} websites")

    # PageSpeed only with a key: without one Google refuses nearly every request.
    audit_pending(con, cfg.google_api_key, bool(cfg.google_api_key), None, progress)
    _update(con, sid, message="Scoring leads and checking email addresses")
    score_all(con, cfg)
    leads = con.execute(
        "select count(*) from leads l join businesses b on b.id = l.business_id where b.area = ? and l.status != 'excluded'",
        (s["label"],),
    ).fetchone()[0]
    _update(con, sid, status="done", message=f"{leads} leads ready", finished_at=now())


def _worker() -> None:
    con = db.connect()
    while True:
        s = con.execute("select * from searches where status = 'queued' order by id limit 1").fetchone()
        if not s:
            _wake.wait(timeout=30)
            _wake.clear()
            continue
        try:
            _run(con, s)
        except ValueError as e:  # e.g. the area couldn't be found
            _update(con, s["id"], status="failed", message=str(e), finished_at=now())
        except Exception as e:  # keep the worker alive whatever happens
            traceback.print_exc()
            _update(con, s["id"], status="failed", message=f"Stopped: {type(e).__name__}: {e}"[:300], finished_at=now())


def start_worker() -> None:
    global _started
    with _lock:
        if _started:
            return
        con = db.connect()
        # A search that was running when the dashboard stopped never finished: queue it again.
        con.execute("update searches set status = 'queued', message = 'Restarting after the dashboard was closed' where status = 'running'")
        con.commit()
        threading.Thread(target=_worker, name="leadscout-search", daemon=True).start()
        _started = True


def searched_areas(con) -> list:
    return con.execute(
        """select s.*,
                  (select count(*) from leads l join businesses b on b.id = l.business_id
                    where b.area = s.label and l.status not in ('excluded')) as leads,
                  (select count(*) from leads l join businesses b on b.id = l.business_id
                    where b.area = s.label and l.email is not null and l.status not in ('excluded')) as with_email,
                  (select count(*) from outreach o join businesses b on b.id = o.business_id
                    where b.area = s.label and o.channel = 'email') as emailed
           from searches s order by s.created_at desc, s.id desc"""
    ).fetchall()
