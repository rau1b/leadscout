"""Fetch a business website and run the cheap checks PageSpeed doesn't do."""

import re
from datetime import date
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"
)
PARKED = (
    "domain is for sale", "buy this domain", "this domain may be for sale", "domain parking",
    "parked free", "sedoparking", "hugedomains", "is parked", "under construction",
    "account suspended", "website coming soon", "index of /",
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
JUNK_EMAIL = ("example.", "sentry", "wixpress", "domain.com", "email.com", "yourname", "@2x", "user@", "name@")
YEAR_RE = re.compile(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?((?:19|20)\d{2})", re.I)
JQUERY_RE = re.compile(r"jquery[.-]?(\d+\.\d+)", re.I)


def extract_emails(html: str, soup: BeautifulSoup) -> set[str]:
    found = {a["href"][7:].split("?")[0] for a in soup.select('a[href^="mailto:"]')}
    found |= set(EMAIL_RE.findall(soup.get_text(" ")))
    clean = set()
    for e in found:
        e = e.strip().strip(".").lower()
        if EMAIL_RE.fullmatch(e) and not any(j in e for j in JUNK_EMAIL) and not e.endswith((".png", ".jpg", ".webp", ".gif", ".svg")):
            clean.add(e)
    return clean


def check_html(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    low = html.lower()
    links = [a.get("href", "") for a in soup.find_all("a")]
    years = [int(y) for y in YEAR_RE.findall(html)]
    gen = soup.find("meta", attrs={"name": re.compile("^generator$", re.I)})
    generator = (gen.get("content") or "").strip() if gen else ""
    if not generator:
        if "wp-content" in low:
            generator = "WordPress"
        elif "wix.com" in low or "wixstatic" in low:
            generator = "Wix"
        elif "blogger.com" in low:
            generator = "Blogger"
    jq = JQUERY_RE.search(html)
    if jq and jq.group(1).startswith("1."):
        generator = (generator + f" + jQuery {jq.group(1)}").strip(" +")
    if "shockwave-flash" in low or ".swf" in low:
        generator = (generator + " + Flash").strip(" +")
    return {
        "viewport": int(soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)}) is not None),
        "copyright_year": max(years) if years else None,
        "generator": generator[:80] or None,
        "has_whatsapp": int(any("wa.me" in h or "whatsapp.com" in h for h in links)),
        "has_tel": int(any(h.startswith("tel:") for h in links)),
        "has_maps": int("google.com/maps" in low or "maps.google" in low or "goo.gl/maps" in low or "maps.app.goo.gl" in low),
        "has_form": int(soup.find("form") is not None or "calendly" in low or "book now" in low or "book appointment" in low),
        "emails": extract_emails(html, soup),
        # Little text AND no scripts = an empty page. Little text WITH scripts is usually a JavaScript site.
        "parked": any(p in low for p in PARKED) or (len(soup.get_text(strip=True)) < 80 and not soup.find("script")),
    }


async def _get(client: httpx.AsyncClient, url: str) -> tuple[httpx.Response | None, str | None]:
    """Fetch, telling a dead domain apart from a slow server or a certificate quirk."""
    try:
        return await client.get(url), None
    except httpx.ConnectError as e:
        msg = str(e).lower()
        if "getaddrinfo" in msg or "name or service not known" in msg or "nodename nor servname" in msg:
            return None, "dns"  # the domain no longer resolves: expired or never set up
        if "certificate" in msg or "ssl" in msg:
            # Often a missing intermediate certificate that browsers work around; load it anyway.
            async with httpx.AsyncClient(headers=client.headers, follow_redirects=True, timeout=20, verify=False) as insecure:
                try:
                    return await insecure.get(url), None
                except httpx.HTTPError:
                    return None, "ssl"
        return None, "connect"
    except httpx.TimeoutException:
        try:
            return await client.get(url, timeout=45), None
        except httpx.HTTPError:
            return None, "timeout"
    except httpx.HTTPError as e:
        return None, type(e).__name__


async def audit_site(client: httpx.AsyncClient, url: str) -> dict:
    """Returns audit fields; site_class is 'real' or 'broken'."""
    if "://" not in url:
        url = "http://" + url
    result = {"site_class": "broken", "final_url": None, "status_code": None, "https": 0, "found_emails": set()}
    resp, err = await _get(client, url)
    if resp is None:
        result["fetch_error"] = err
        return result
    result.update(final_url=str(resp.url), status_code=resp.status_code, https=int(resp.url.scheme == "https"))
    if resp.status_code in (401, 403, 429, 503):
        # Bot protection (e.g. Cloudflare): the site exists, we just can't inspect it. PageSpeed still can.
        result["site_class"] = "real"
        result["fetch_error"] = f"blocked ({resp.status_code})"
        return result
    if resp.status_code >= 400:
        result["fetch_error"] = f"HTTP {resp.status_code}"
        return result
    if "html" not in resp.headers.get("content-type", "html"):
        result["site_class"] = "real"
        return result
    checks = check_html(resp.text)
    emails = checks.pop("emails")
    parked = checks.pop("parked")
    result.update(checks)
    result["site_class"] = "broken" if parked else "real"
    # Look for an email on the contact page if the home page has none.
    if not emails and not parked:
        for path in ("contact", "contact-us", "contactus"):
            try:
                r2 = await client.get(urljoin(str(resp.url), "/" + path))  # from the site root, not the current folder
            except httpx.HTTPError:
                continue
            if r2.status_code < 400:
                emails = extract_emails(r2.text, BeautifulSoup(r2.text, "html.parser"))
                if emails:
                    break
    result["found_emails"] = emails
    return result


def is_outdated(copyright_year: int | None) -> bool:
    return bool(copyright_year and copyright_year <= date.today().year - 3)
