"""Domain and certificate dates: RDAP (free; servers found through IANA's bootstrap file) and the TLS certificate."""

import asyncio
import json
import socket
import ssl
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from leadscout.audit.classify import FREE_HOSTS
from leadscout.config import data_dir

BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
CACHE_SECONDS = 7 * 24 * 3600
# shortcut: a short list of Indian and common second-level suffixes instead of the full public suffix list;
# add the list if RDAP misses domains under other suffixes.
SECOND_LEVEL = {"co", "org", "net", "gov", "ac", "edu", "firm", "gen", "ind", "res", "nic", "com"}


def registrable(host: str | None) -> str:
    """"www.smile.co.in" -> "smile.co.in", "shop.example.com" -> "example.com"."""
    labels = (host or "").lower().strip(".").split(".")
    if len(labels) < 2:
        return ""
    keep = 3 if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in SECOND_LEVEL else 2
    return ".".join(labels[-keep:])


async def servers(client: httpx.AsyncClient) -> dict[str, str]:
    """TLD -> RDAP base URL, from IANA's bootstrap file, cached in data/ for 7 days. Empty if it can't be had."""
    path = data_dir() / "rdap_dns.json"
    if not path.exists() or time.time() - path.stat().st_mtime > CACHE_SECONDS:
        try:
            r = await client.get(BOOTSTRAP_URL, timeout=20)
            r.raise_for_status()
            json.loads(r.text)  # only replace the cached copy with a readable one
            path.write_text(r.text, encoding="utf-8")
        except (httpx.HTTPError, OSError, ValueError):
            pass  # keep using last week's copy, if there is one
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # no domain dates this run; the audit itself carries on
    out = {}
    for tlds, urls in data.get("services", []):
        url = next((u for u in urls if u.startswith("https://")), urls[0] if urls else None)
        for tld in tlds:
            if url:
                out[tld.lower()] = url
    return out


async def rdap_dates(client: httpx.AsyncClient, name: str, rdap: dict[str, str]) -> tuple[str | None, str | None]:
    """(registered, expires) as YYYY-MM-DD from the domain's RDAP record, or None where unknown."""
    base = rdap.get(name.rsplit(".", 1)[-1])
    if not base:
        return None, None
    r = await client.get(f"{base.rstrip('/')}/domain/{name}", timeout=15, headers={"Accept": "application/rdap+json"})
    if r.status_code != 200:
        return None, None
    events = {e.get("eventAction"): (e.get("eventDate") or "")[:10] or None for e in r.json().get("events", [])}
    return events.get("registration"), events.get("expiration")


def cert_expiry(host: str) -> str | None:
    """The TLS certificate's expiry date (YYYY-MM-DD). Raises OSError/ssl.SSLError when it can't be read."""
    ctx = httpx.create_ssl_context()  # the same trust store the audit's fetch uses, so both agree on "working HTTPS"
    with socket.create_connection((host, 443), timeout=10) as raw, ctx.wrap_socket(raw, server_hostname=host) as tls:
        not_after = tls.getpeercert()["notAfter"]
    return datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), UTC).date().isoformat()


async def facts(client: httpx.AsyncClient, url: str, result: dict, rdap: dict[str, str]) -> dict:
    """domain_registered, domain_expires and cert_expires for an audited site, as far as they can be read.
    Never raises: a missing date never fails the audit."""
    host = urlparse(result.get("final_url") or (url if "://" in url else "http://" + url)).hostname or ""
    out = {}
    name = registrable(host)
    if name and not any(host == h or host.endswith("." + h) for h in FREE_HOSTS):  # a free host's domain isn't theirs
        try:
            out["domain_registered"], out["domain_expires"] = await rdap_dates(client, name, rdap)
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
    if result.get("https") and result.get("fetch_error") != "bad_certificate":
        try:
            out["cert_expires"] = await asyncio.to_thread(cert_expiry, host)
        except (OSError, ssl.SSLError, ValueError, KeyError):
            pass
    return out
