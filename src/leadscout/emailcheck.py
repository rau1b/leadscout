"""Cheap, free email validation: syntax + the domain can receive mail (MX record).

Keeps bounces low, which protects the Gmail account.
"""

import re
from functools import lru_cache

import dns.exception
import dns.resolver

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
FREE_PROVIDERS = {"gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "outlook.com", "rediffmail.com", "ymail.com", "live.com", "icloud.com"}


@lru_cache(maxsize=4096)
def domain_accepts_mail(domain: str) -> bool:
    if domain in FREE_PROVIDERS:
        return True
    try:
        dns.resolver.resolve(domain, "MX", lifetime=5)
        return True
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers, dns.exception.Timeout):
        return False


def is_deliverable(email: str) -> bool:
    if not email or not EMAIL_RE.match(email):
        return False
    return domain_accepts_mail(email.rsplit("@", 1)[1].lower())


def best_email(candidates: list[str], website_domain: str = "") -> str | None:
    """Prefer an address on the business's own domain, then any deliverable one."""
    ordered = sorted(set(candidates), key=lambda e: (not (website_domain and e.endswith("@" + website_domain)), e))
    for e in ordered:
        if is_deliverable(e):
            return e
    return None
