"""Cheap, free email validation: syntax + the domain can receive mail (MX record).

Keeps bounces low, which protects the Gmail account.
"""

import re

import dns.exception
import dns.resolver

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")  # no empty labels like "abc..com"
FREE_PROVIDERS = {"gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "outlook.com", "rediffmail.com", "ymail.com", "live.com", "icloud.com"}


# Only definite answers are cached. A timeout during a short internet drop must not stick as "no mail".
_known: dict[str, bool] = {}


def domain_accepts_mail(domain: str) -> bool | None:
    """True/False when DNS answered, None when we couldn't tell (timeout, no reachable nameserver)."""
    if domain in FREE_PROVIDERS:
        return True
    if domain in _known:
        return _known[domain]
    try:
        dns.resolver.resolve(domain, "MX", lifetime=5)
        ok = True
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.exception.SyntaxError):
        ok = False  # the domain doesn't exist, has no MX, or isn't a valid name (e.g. EmptyLabel)
    except dns.exception.DNSException:
        return None
    _known[domain] = ok
    return ok


def is_deliverable(email: str) -> bool | None:
    """False for bad syntax or a domain that can't receive mail; None if DNS couldn't be reached."""
    if not email or not EMAIL_RE.match(email):
        return False
    return domain_accepts_mail(email.rsplit("@", 1)[1].lower())


def best_email(candidates: list[str], website_domain: str = "") -> str | None:
    """Prefer an address on the business's own domain, then any deliverable one (unknowns don't count)."""
    ordered = sorted(set(candidates), key=lambda e: (not (website_domain and e.endswith("@" + website_domain)), e))
    for e in ordered:
        if is_deliverable(e) is True:
            return e
    return None
