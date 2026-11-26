import dns.resolver
import pytest


@pytest.fixture(autouse=True)
def no_real_dns(monkeypatch):
    """Tests never hit the network: every DNS lookup answers 'no such domain' unless a test fakes it."""

    def resolve(*a, **k):
        raise dns.resolver.NXDOMAIN()

    monkeypatch.setattr(dns.resolver, "resolve", resolve)
    from leadscout import emailcheck

    emailcheck._known.clear()


@pytest.fixture(autouse=True)
def no_real_domain_lookups(request, monkeypatch):
    """Tests never hit the network: the audit's RDAP and certificate lookups find nothing. A test marked
    real_domain_lookups gets the real functions and must mock every request itself (respx)."""
    from leadscout.audit import domain

    if request.node.get_closest_marker("real_domain_lookups"):
        return

    async def nothing(*a, **k):
        return {}

    monkeypatch.setattr(domain, "servers", nothing)
    monkeypatch.setattr(domain, "facts", nothing)
