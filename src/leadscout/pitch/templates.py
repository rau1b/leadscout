"""Free, offline pitch templates. Every pitch names a real, measured problem for that business."""

from leadscout import places
from leadscout.audit.site import is_outdated

OPT_OUT = "P.S. No worries if this isn't a good fit right now. Just reply \"no\" and I won't email you again."


CATEGORY_PLURALS = {
    "dentist": "dentists", "general_dentistry": "dentists", "dental_clinic": "dental clinics",
    "real_estate_service": "real estate agents", "real_estate_agent": "real estate agents",
    "home_developer": "builders", "interior_design": "interior designers", "interior_designer": "interior designers",
    "computer_coaching": "coaching centres", "educational_service": "coaching centres", "tutoring_service": "tutors",
    "beauty_salon": "beauty salons", "gym": "gyms", "restaurant": "restaurants", "school": "schools",
    "hospital": "hospitals", "clinic": "clinics", "architect": "architects", "lawyer": "lawyers",
}


GOOGLE_SITES_CLOSED = 2024  # Google Business Profile websites (business.site) stopped working in March 2024

def nice_category(cat: str | None) -> str:
    if not cat:
        return "local businesses"
    if cat in CATEGORY_PLURALS:
        return CATEGORY_PLURALS[cat]
    word = cat.replace("_", " ").strip()
    if word.endswith(("service", "store", "shop", "agency", "studio", "center", "centre", "clinic")):
        return word + "s"
    return f"{word} businesses"


def possessive(name: str) -> str:
    return name + ("'" if name.endswith("s") else "'s")


def problem(f: dict) -> tuple[str, str]:
    """(subject, problem paragraph) for this business's site class."""
    n = f["name"]
    c = f["site_class"]
    if c == "none":
        return (
            f"{n} has no website yet",
            f"When people in {place_of(f, 'your area')} search for {nice_category(f['category'])}, {n} shows up "
            "with no website to click. Most of them pick a competitor who has one.",
        )
    if c == "dead_google_site":
        return (
            f"The website link on {possessive(n)} listing is dead",
            f"Your listing still links to a business.site page. Google shut those sites down in {GOOGLE_SITES_CLOSED}, "
            "so anyone who taps \"Website\" lands on an error page.",
        )
    if c == "social_only":
        return (
            f"{n} is only on social media",
            "Right now customers can only find you through a social media page. That works for people who "
            "already follow you, but new customers searching Google expect a proper website.",
        )
    if c == "directory_only":
        return (
            f"{possessive(n)} customers land on a directory, not your site",
            "Your listing sends people to a directory page, where your competitors are listed right next to you.",
        )
    if c == "broken" and f.get("fetch_error") == "dns":
        return (
            f"{possessive(n)} website address has stopped working",
            f"The website on your listing ({f['website']}) no longer opens. The domain looks like it has "
            "expired, so every customer who taps it gets an error page.",
        )
    if c == "broken":
        return (
            f"{possessive(n)} website isn't loading",
            f"I tried to open {f['website']} and it didn't load properly. Every customer who tries it "
            "right now hits the same wall.",
        )
    if c == "free_subdomain":
        return (
            f"A proper website for {n}",
            f"Your website runs on a free subdomain ({f['website']}). It works, but it looks less "
            "trustworthy to new customers and is harder to find on Google.",
        )
    # A real site: lead with the worst measured problem.
    issues = []
    if f.get("lcp_s") and f["lcp_s"] > 4:
        issues.append(f"it takes {f['lcp_s']} seconds to show its main content on a phone")
    elif f.get("perf_score") is not None and f["perf_score"] < 50:
        issues.append(f"it scores {f['perf_score']}/100 on Google's mobile speed test")
    if f.get("viewport") == 0:
        issues.append("it isn't built for mobile screens, so phone visitors have to pinch and zoom")
    if f.get("fetch_error") == "bad_certificate":
        issues.insert(0, "its security certificate is broken, so browsers show a security warning before the page opens")
    elif not f.get("https"):
        issues.append("it has no HTTPS, so browsers mark it \"Not secure\"")
    if is_outdated(f.get("copyright_year")):
        issues.append(f"the footer still says © {f['copyright_year']}, which makes it look unmaintained")
    if not issues and f.get("has_whatsapp") == 0:
        issues.append("there's no WhatsApp button, which is how most customers here prefer to reach a business")
    if not issues:
        issues.append("a few small fixes would make it faster and easier to use on a phone")
    subject = (
        f"{possessive(n)} website takes {f['lcp_s']}s to load on mobile"
        if f.get("lcp_s") and f["lcp_s"] > 4
        else f"A few quick wins for {possessive(n)} website"
    )
    # Only what we measured for this site: no borrowed industry statistics.
    body = "I ran Google's free speed and mobile test on your website, and " + "; ".join(issues[:2]) + "."
    return subject, body


def place_of(f: dict, home: str) -> str:
    """Where the lead is: the searched neighbourhood, else its locality or city."""
    area = f.get("area") or ""
    if "," in area:
        return area.split(",")[0].strip()
    return f.get("locality") or f.get("city") or home


def is_local(f: dict, home: str) -> bool:
    city = (f.get("city") or f.get("locality") or "").strip().lower()
    home = home.strip().lower()
    # Hyderabad and Secunderabad are one metro; treat twin names as local.
    twins = {"secunderabad": "hyderabad", "bangalore": "bengaluru", "bombay": "mumbai", "gurgaon": "gurugram", "new delhi": "delhi"}
    if not city or twins.get(city, city) == twins.get(home, home):
        return True
    # Home can be a state (e.g. "Goa"): any town in that state is local.
    if home in city.split():
        return True
    place = places.best_match(city)
    return bool(place) and place["state"].strip().lower() == home


def signature(s: dict) -> str:
    """Sign-off from whichever sender details are filled in; blank ones are left out."""
    studio = ", ".join(x for x in (s.get("business"), s.get("city")) if x)
    lines = [s.get("name"), studio, s.get("phone"), s.get("portfolio")]
    return "Regards,\n" + "\n".join(x for x in lines if x)


def intro(s: dict) -> str:
    """'Hi, I'm Asha from Shinnen Creative in Goa.' or, with no name, 'Hi, this is Shinnen Creative in Goa.'"""
    where = f"{s['business']} in {s['city']}" if s.get("city") else s["business"]
    return f"Hi, I'm {s['name']} from {where}." if s.get("name") else f"Hi, this is {where}."


def location_line(f: dict, cfg) -> str:
    """Honest about where you are: never claims to be local to a lead in another city."""
    s, p = cfg.sender, cfg.pitch
    if is_local(f, s["city"]):
        return f"{p['pitch_line']} here in {s['city']}."
    return f"{p['pitch_line']}. I'm based in {s['city']} and work with businesses across India, all online."


def render(f: dict, cfg) -> dict:
    s = cfg.sender
    p = cfg.pitch
    subject, prob = problem(f)
    body = (
        f"Hi {f['name']} team,\n\n"
        f"I came across {f['name']} while looking at {nice_category(f['category'])} in {place_of(f, s['city'])}.\n\n"
        f"{prob}\n\n"
        f"{location_line(f, cfg)} Would you like {p['offer']}? No cost and no obligation; "
        "if you like it, we can talk about the rest.\n\n"
        f"{signature(s)}\n\n"
        f"{OPT_OUT}"
    )
    whatsapp = (
        f"{intro(s)} {prob} "
        f"Would you like {p['offer']}? No cost. If not, just say no and I won't message again."
    )
    return {"subject": subject, "body": body, "whatsapp": whatsapp[:600]}


def followup(f: dict, cfg) -> tuple[str, str]:
    s = cfg.sender
    return (
        f"Re: {f['subject']}",
        f"Hi {f['name']} team,\n\nJust checking you saw my note below. Happy to send over "
        f"{cfg.pitch['offer']} for {f['name']} this week, free.\n\n"
        f"{signature(s)}\n\n{OPT_OUT}",
    )
