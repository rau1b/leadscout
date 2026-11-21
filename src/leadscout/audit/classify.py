"""Classify a listing's website field before fetching anything."""

from leadscout.sources.common import DIRECTORY_DOMAINS, SOCIAL_DOMAINS, domain, domain_in

FREE_HOSTS = (
    "blogspot.com", "wixsite.com", "weebly.com", "wordpress.com", "godaddysites.com",
    "webnode.com", "jimdosite.com", "sites.google.com", "business.google.com",
    "mystrikingly.com", "carrd.co", "000webhostapp.com", "netlify.app", "vercel.app",
)

# Human-readable labels, used in the dashboard and pitches.
LABELS = {
    "none": "No website",
    "social_only": "Social page only",
    "directory_only": "Directory listing only",
    "dead_google_site": "Dead Google business.site link",
    "free_subdomain": "Free subdomain site",
    "broken": "Broken website",
    "real": "Working website",
}


def classify_static(url: str | None) -> str | None:
    """Return a class decided from the URL alone, or None if the site must be fetched."""
    if not url:
        return "none"
    d = domain(url)
    if d.endswith("business.site"):
        return "dead_google_site"  # Google shut these sites down in 2024
    if domain_in(url, SOCIAL_DOMAINS):
        return "social_only"
    if domain_in(url, DIRECTORY_DOMAINS):
        return "directory_only"
    if domain_in(url, FREE_HOSTS) or d == "sites.google.com":
        return "free_subdomain"
    return None
