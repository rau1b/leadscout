"""Lead score 0-100 = need for a website + ability to pay, with plain-English reasons."""

import json
import math
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from leadscout import emailcheck
from leadscout.audit.classify import FREE_HOSTS
from leadscout.audit.site import is_outdated
from leadscout.compliance import is_suppressed
from leadscout.db import jload, now
from leadscout.sources.common import DIRECTORY_DOMAINS, SOCIAL_DOMAINS, domain, domain_in

NEED = {
    "none": (60, "No website at all"),
    "dead_google_site": (60, "Google listing links to a dead business.site page"),
    "social_only": (55, "Only a social media page, no website"),
    "directory_only": (50, "Only a directory listing (Justdial etc.), no website"),
    "broken": (50, "Website is broken, parked or not loading"),
    "free_subdomain": (40, "Website is on a free subdomain"),
}


def site_need(a) -> tuple[int, list[str]]:
    if a["site_class"] in NEED:
        pts, why = NEED[a["site_class"]]
        if a["site_class"] == "broken" and a["fetch_error"] == "dns":
            pts, why = 60, "Website domain no longer works (likely expired)"
        return pts, [why]
    pts, why = 0, []
    if a["perf_score"] is not None and a["perf_score"] < 50:
        pts += 30
        why.append(f"PageSpeed mobile score {a['perf_score']}/100")
    elif a["perf_score"] is not None and a["perf_score"] < 70:
        pts += 15
        why.append(f"PageSpeed mobile score {a['perf_score']}/100")
    if a["lcp_s"] and a["lcp_s"] > 4:
        pts += 10
        why.append(f"Main content takes {a['lcp_s']}s to load on mobile")
    if not a["https"]:
        pts += 15
        why.append("No HTTPS (browsers show 'Not secure')")
    if a["viewport"] == 0:
        pts += 20
        why.append("Not built for mobile screens")
    if is_outdated(a["copyright_year"]):
        pts += 10
        why.append(f"Footer still says © {a['copyright_year']}")
    if a["has_whatsapp"] == 0:
        pts += 5
        why.append("No WhatsApp chat button")
    if a["has_tel"] == 0:
        pts += 5
        why.append("No tap-to-call button")
    return min(pts, 70), why


# Which copy of a duplicated place to keep: the one furthest along with you. Opted-out, bounced and lost
# rank high too, so their twin listing never gets pitched instead.
STATUS_RANK = {"won": 9, "replied": 8, "contacted": 7, "opted_out": 7, "bounced": 7, "lost": 7, "approved": 5,
               "drafted": 4, "hidden": 3, "new": 1, "excluded": 0}
SAME_PLACE_KM = 15  # the same name this close is the same business (branches get one pitch, not two)


def name_key(name: str | None) -> str:
    """"Rajrudra Developers." and "rajrudra  developers" are the same name."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).split())


def km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


class DuplicateFinder:
    """Remembers kept leads; a later listing with the same phone, own website, or name nearby is a duplicate."""

    def __init__(self):
        self.keys: set[tuple] = set()
        self.names: dict[str, list[tuple]] = {}

    def seen_before(self, r, site_domain: str) -> bool:
        keys = set()
        if r["phone"]:
            keys.add(("phone", r["phone"]))
        if site_domain and site_domain not in FREE_HOSTS and not domain_in(r["website"], SOCIAL_DOMAINS + DIRECTORY_DOMAINS):
            keys.add(("site", site_domain))
        name = name_key(r["name"])
        here = (r["lat"], r["lon"]) if r["lat"] is not None and r["lon"] is not None else None
        city = (r["city"] or "").strip().lower()
        same_name_nearby = any(
            km_between(here, there) <= SAME_PLACE_KM if here and there else city == other_city
            for there, other_city in self.names.get(name, [])
        )
        dup = same_name_nearby or bool(keys & self.keys)
        self.keys |= keys
        if name:
            self.names.setdefault(name, []).append((here, city))
        return dup


def chain_domains(con, min_count: int = 3) -> set[str]:
    """Domains used by several listings are chains, hospitals or aggregators: skip them."""
    counts = Counter()
    for (w,) in con.execute("select website from businesses where website is not null"):
        if not domain_in(w, SOCIAL_DOMAINS + DIRECTORY_DOMAINS) and domain(w) not in FREE_HOSTS:
            counts[domain(w)] += 1  # sites.google.com etc. host many unrelated businesses
    return {d for d, n in counts.items() if n >= min_count}


def score_all(con, cfg) -> dict:
    sc = cfg.scoring
    chains = chain_domains(con)
    rows = con.execute(
        """select b.*, a.site_class, a.perf_score, a.lcp_s, a.https, a.viewport, a.copyright_year,
                  a.has_whatsapp, a.has_tel, a.found_emails, a.fetch_error, l.status as lead_status
           from businesses b join audits a on a.business_id = b.id
           left join leads l on l.business_id = b.id"""
    ).fetchall()
    # Check every email domain in parallel up front (cached), instead of one slow DNS lookup at a time.
    domains = {e.rsplit("@", 1)[1].lower() for r in rows for e in jload(r["emails"]) + jload(r["found_emails"]) if "@" in e}
    with ThreadPoolExecutor(max_workers=32) as pool:
        list(pool.map(emailcheck.domain_accepts_mail, domains))
    leads = []
    for r in rows:
        cat = f"{r['category'] or ''} {r['category_path'] or ''}".lower()
        site_domain = domain(r["website"])
        candidates = jload(r["emails"]) + jload(r["found_emails"])
        email = emailcheck.best_email(candidates, site_domain) if candidates else None
        excluded = None
        if any(x in cat for x in sc["excluded"]):
            excluded = "Category not worth pitching"
        elif r["brand"]:
            excluded = f"Brand/chain ({r['brand']})"
        elif site_domain in chains:
            excluded = f"Chain or aggregator domain ({site_domain})"
        elif is_suppressed(con, email, r["phone"]):
            excluded = "On the opt-out list"

        need, reasons = site_need(r)
        value = 0
        if any(x in cat for x in sc["high_value"]):
            value += 15
            reasons.append("High-value category")
        if (r["confidence"] or 0) >= 0.8:
            value += 5
        if email:
            value += 10
            reasons.append("Email address found")
        if r["phone_type"] == "mobile":
            value += 5
        leads.append({"r": r, "email": email, "excluded": excluded, "score": min(100, need + value), "reasons": reasons,
                      "site": site_domain})

    # One place, one lead. Keep the copy you've already worked on, else the best lead; the rest are duplicates.
    leads.sort(key=lambda x: (-STATUS_RANK.get(x["r"]["lead_status"], 0), x["excluded"] is not None, -x["score"],
                              x["email"] is None, -(x["r"]["confidence"] or 0)))
    finder = DuplicateFinder()
    stats = Counter()
    for x in leads:
        r = x["r"]
        is_dup = finder.seen_before(r, x["site"])
        excluded = "Duplicate listing" if is_dup else x["excluded"]
        score, reasons = (0, [excluded]) if excluded else (x["score"], x["reasons"])

        status = r["lead_status"]
        if status in (None, "new", "excluded") or (is_dup and status in ("drafted", "approved")):
            # A duplicate's draft is dropped too: nothing was sent, and its twin carries on.
            status = "excluded" if excluded or score < sc["min_score"] else "new"
        stats[status] += 1
        con.execute(
            """insert into leads (business_id, score, reasons, status, email, email_ok, updated_at)
               values (?, ?, ?, ?, ?, ?, ?)
               on conflict(business_id) do update set score = excluded.score, reasons = excluded.reasons,
                   status = excluded.status, email = excluded.email, email_ok = excluded.email_ok,
                   updated_at = excluded.updated_at""",
            (r["id"], score, json.dumps(reasons), status, x["email"], int(bool(x["email"])), now()),
        )
    con.commit()
    return dict(stats)
