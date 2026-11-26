"""Phase 1 Step 3: domain and certificate dates, technology detection, the 5-page crawl. Offline."""

import asyncio
import os
import time

import httpx
import pytest
import respx
from bs4 import BeautifulSoup

from leadscout import db
from leadscout.audit import domain
from leadscout.audit.site import audit_site, crawl, detect_tech

BOOTSTRAP = {"version": "1.0", "services": [
    [["com", "net"], ["https://rdap.verisign.com/com/v1/"]],
    [["in"], ["http://rdap.registry.in/", "https://rdap.registry.in/"]],
]}
# Trimmed from a real RDAP answer: only the parts we read, plus a few we ignore.
RDAP_SMILE = {"objectClassName": "domain", "ldhName": "SMILE.CO.IN", "status": ["client transfer prohibited"],
              "events": [{"eventAction": "registration", "eventDate": "2019-04-02T10:20:30Z"},
                         {"eventAction": "expiration", "eventDate": "2026-12-30T10:20:30Z"},
                         {"eventAction": "last changed", "eventDate": "2025-11-01T00:00:00Z"}]}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize("host,name", [("www.smile.co.in", "smile.co.in"), ("shop.example.com", "example.com"),
                                       ("clinic.in", "clinic.in"), ("a.b.org.in", "b.org.in"), ("localhost", "")])
def test_registrable_domain(host, name):
    assert domain.registrable(host) == name


@pytest.mark.real_domain_lookups
def test_rdap_dates_through_the_cached_bootstrap(home):
    async def go():
        async with httpx.AsyncClient() as c:
            servers = await domain.servers(c)
            again = await domain.servers(c)  # from the cache in data/
            return servers, again, await domain.rdap_dates(c, "smile.co.in", servers)

    with respx.mock(assert_all_called=True) as net:
        boot = net.get(domain.BOOTSTRAP_URL).mock(return_value=httpx.Response(200, json=BOOTSTRAP))
        net.get("https://rdap.registry.in/domain/smile.co.in").mock(return_value=httpx.Response(200, json=RDAP_SMILE))
        servers, again, dates = asyncio.run(go())
    assert boot.call_count == 1 and servers == again and servers["in"] == "https://rdap.registry.in/"  # https preferred
    assert dates == ("2019-04-02", "2026-12-30")


@pytest.mark.real_domain_lookups
def test_bootstrap_older_than_a_week_is_fetched_again_and_failures_are_quiet(home):
    path = home / "data" / "rdap_dns.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text('{"services": []}', encoding="utf-8")
    week_ago = time.time() - 8 * 24 * 3600
    os.utime(path, (week_ago, week_ago))

    async def go():
        async with httpx.AsyncClient() as c:
            return await domain.servers(c)

    with respx.mock() as net:
        net.get(domain.BOOTSTRAP_URL).mock(return_value=httpx.Response(200, json=BOOTSTRAP))
        assert "com" in asyncio.run(go())
    os.utime(path, (week_ago, week_ago))
    with respx.mock() as net:
        net.get(domain.BOOTSTRAP_URL).mock(side_effect=httpx.ConnectError("offline"))
        assert "com" in asyncio.run(go())  # the stale copy beats nothing


@pytest.mark.real_domain_lookups
def test_facts_for_a_site(monkeypatch):
    monkeypatch.setattr(domain, "cert_expiry", lambda host: "2027-01-15")
    servers = {"in": "https://rdap.registry.in/"}

    async def go(url, result):
        async with httpx.AsyncClient() as c:
            return await domain.facts(c, url, result, servers)

    with respx.mock() as net:
        net.get("https://rdap.registry.in/domain/smile.co.in").mock(return_value=httpx.Response(200, json=RDAP_SMILE))
        net.get("https://rdap.registry.in/domain/gone.in").mock(return_value=httpx.Response(404))
        ok = asyncio.run(go("smile.co.in", {"final_url": "https://www.smile.co.in/", "https": 1}))
        bad_cert = asyncio.run(go("smile.co.in", {"final_url": "https://smile.co.in/", "https": 0, "fetch_error": "bad_certificate"}))
        expired = asyncio.run(go("http://gone.in", {"fetch_error": "dns"}))  # dead domain: RDAP is still asked
        free_host = asyncio.run(go("https://smile.wixsite.com/clinic", {"final_url": "https://smile.wixsite.com/clinic", "https": 1}))
    assert ok == {"domain_registered": "2019-04-02", "domain_expires": "2026-12-30", "cert_expires": "2027-01-15"}
    assert "cert_expires" not in bad_cert and bad_cert["domain_expires"] == "2026-12-30"
    assert expired == {"domain_registered": None, "domain_expires": None}
    assert free_host == {"cert_expires": "2027-01-15"}  # wixsite.com's domain dates aren't the business's


@pytest.mark.parametrize("html,headers,tech,version", [
    ('<meta name="generator" content="WordPress 6.4.2"><link href="/wp-content/x.css"><div class="elementor-section">'
     '<script src="/js/jquery-1.12.4.min.js"></script>', {}, "WordPress, Elementor, jQuery 1.12", "6.4.2"),
    ('<link href="/wp-content/themes/Divi/style.css"><div class="et_pb_section">', {}, "WordPress, Divi", None),
    ('<img src="https://static.wixstatic.com/media/a.jpg">', {}, "Wix", None),
    ("<p>Shop</p>", {"x-shopify-stage": "production"}, "Shopify", None),
    ('<link href="https://www.blogger.com/static/v1/widgets.css">', {}, "Blogger", None),
    ('<a href="https://sites.google.com/view/clinic">', {}, "Google Sites", None),
    ('<a href="https://linktr.ee/smile">Links</a>', {}, "Linktree", None),
    ('<h1>Smile Dental</h1><script src="jquery-1.8.3.js"></script>', {}, "Hand-made, jQuery 1.8", None),
    ("<h1>Smile Dental</h1>", {}, "Hand-made", None),
])
def test_technology_detection(html, headers, tech, version):
    assert detect_tech(html, headers) == {"tech": tech, "cms_version": version}


HOME = """<html><body>Welcome to Smile Dental, Panaji. Family dentistry, implants and braces since 2009, open six days a week.
<a href="/contact-us">Contact</a> <a href="/about">About us</a> <a href="/our-services">Treatments</a>
<a href="/blog">Blog</a> <a href="https://elsewhere.in/contact">Partner</a> <a href="/contact-us#map">Find us</a></body></html>"""
PAGES = {
    "/robots.txt": "User-agent: *\nDisallow: /our-services\n",
    "/contact-us": '<a href="mailto:hello@smile.in">Mail</a> <a href="tel:+919812345678">Call</a> '
                   '<iframe src="https://www.google.com/maps/embed?pb=1"></iframe>',
    "/about": '<a href="https://wa.me/919812345678">WhatsApp</a> <a href="https://calendly.com/smile">Book</a>',
    "/our-services": '<a href="mailto:hidden@smile.in">x</a>',
}


def _site(seen):
    def handler(request):
        seen.append(request.url.path)
        if request.url.host != "smile.in":
            return httpx.Response(500)
        body = PAGES.get(request.url.path, HOME if request.url.path == "/" else None)
        if body is None:
            return httpx.Response(404, text="not found")
        return httpx.Response(200, text=body, headers={"content-type": "text/plain" if request.url.path == "/robots.txt" else "text/html"})
    return httpx.MockTransport(handler)


def test_crawl_reads_linked_pages_on_the_same_host_and_obeys_robots():
    seen = []

    async def go():
        async with httpx.AsyncClient(transport=_site(seen)) as c:
            return await crawl(c, "https://smile.in/", BeautifulSoup(HOME, "html.parser"), guess_contact=False)

    found = asyncio.run(go())
    assert seen == ["/robots.txt", "/contact-us", "/about"]  # /our-services is disallowed; blog and other hosts skipped
    assert found == {"emails": {"hello@smile.in"}, "has_whatsapp": 1, "has_tel": 1, "has_maps": 1, "has_form": 1}


def test_crawl_visits_at_most_four_more_pages():
    links = "".join(f'<a href="/services-{i}">Service {i}</a>' for i in range(9))
    seen = []

    async def go():
        async with httpx.AsyncClient(transport=_site(seen)) as c:
            return await crawl(c, "https://smile.in/", BeautifulSoup(links, "html.parser"), guess_contact=True)

    asyncio.run(go())
    assert len([p for p in seen if p != "/robots.txt"]) == 4  # plus the home page = 5


def test_audit_site_combines_home_page_crawl_and_technology():
    seen = []

    async def go():
        async with httpx.AsyncClient(transport=_site(seen)) as c:
            return await audit_site(c, "https://smile.in/")

    r = asyncio.run(go())
    assert r["site_class"] == "real" and r["found_emails"] == {"hello@smile.in"} and r["tech"] == "Hand-made"
    assert (r["has_whatsapp"], r["has_tel"], r["has_maps"], r["has_form"]) == (1, 1, 1, 1)


def test_audit_saves_the_facts_and_the_lead_page_shows_them(home, monkeypatch):
    from fastapi.testclient import TestClient

    from leadscout import audit
    from leadscout.web.app import app

    async def site(client, url):
        return {"site_class": "real", "final_url": url, "https": 1, "tech": "WordPress, Elementor", "cms_version": "6.4.2"}

    async def facts(client, url, result, servers):
        return {"domain_registered": "2019-04-02", "domain_expires": "2026-12-30", "cert_expires": "2027-01-15"}

    monkeypatch.setattr(audit, "audit_site", site)
    monkeypatch.setattr(domain, "facts", facts)
    con = db.connect()
    con.execute("insert into businesses (id, source, name, website, fetched_at) values ('a', 't', 'Smile', 'https://smile.in', '2026-11-20')")
    con.commit()
    audit.audit_pending(con, run_psi=False)
    row = con.execute("select domain_registered, domain_expires, cert_expires, tech, cms_version from audits").fetchone()
    assert tuple(row) == ("2019-04-02", "2026-12-30", "2027-01-15", "WordPress, Elementor", "6.4.2")

    con.execute("insert into leads (business_id, score, status, updated_at) values ('a', 60, 'new', '2026-11-20')")
    con.commit()
    page = TestClient(app, base_url="http://127.0.0.1:8000").get("/leads/a").text
    assert "Expires 30 Dec 2026; registered 02 Apr 2019" in page and "<dt>Certificate</dt><dd>Expires 15 Jan 2027</dd>" in page
    assert "WordPress, Elementor (version 6.4.2)" in page
