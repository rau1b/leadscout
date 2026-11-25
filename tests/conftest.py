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
