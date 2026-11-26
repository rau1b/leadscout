"""Preview host, LeadScout side (Phase 2 Step 3): publish, sync and the Demos page. Offline: wrangler and the host are faked."""

import json
from datetime import datetime, timedelta

import httpx
import pytest

from leadscout import config, db, demos
from leadscout.compliance import opt_out
from leadscout.demos import preview

SECRET = "sync-secret-sync-secret-123"


def _config() -> str:
    """config.example.toml with our sender and a filled-in [preview] section (the dashboard needs every section)."""
    text = config.EXAMPLE.read_text(encoding="utf-8")
    for old, new in (('name = "Your Name"', 'name = "Asha Rao"'), ('business = "Your Studio"', 'business = "Kite Studio"'),
                     ('phone = "+91 90000 00000"', 'phone = "+91 98765 43210"'),
                     ('email = "yourname.outreach@gmail.com"', 'email = "asha.kite@gmail.com"'),
                     ('portfolio = "https://yourname.github.io"', 'portfolio = "https://kite.example"'),
                     ('base_url = ""', 'base_url = "https://demo.kite.example/"'), ('account_id = ""', 'account_id = "acc123"'),
                     ('kv_namespace_id = ""', 'kv_namespace_id = "kv456"')):
        assert old in text, old
        text = text.replace(old, new, 1)
    return text


CONFIG = _config()
BIZ = {"source": "overture", "category": "dentist", "locality": "Panaji", "city": "Goa", "phone": "+919812345678", "phone_type": "mobile",
       "fetched_at": "2026-11-20T10:00:00+05:30"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-token")
    monkeypatch.setenv("PREVIEW_SYNC_SECRET", SECRET)
    (tmp_path / "config.toml").write_text(CONFIG, encoding="utf-8")
    fake = tmp_path / "wrangler.cmd"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setattr(preview, "wrangler", lambda: fake)  # never the real one: tests don't touch Cloudflare
    con = db.connect()
    yield con
    con.close()


def add(con, bid, name, **extra):
    row = BIZ | {"id": bid, "name": name} | extra
    con.execute(f"insert into businesses ({', '.join(row)}) values ({', '.join('?' * len(row))})", list(row.values()))
    con.commit()
    return demos.build(con, bid, config.load().sender)


class FakeWrangler:
    """Records each wrangler call and what the site folder held at deploy time."""

    def __init__(self, fail=False):
        self.calls, self.site, self.config, self.fail = [], {}, None, fail

    def __call__(self, args, input=None, **kw):
        self.calls.append((args[1:], input, kw["env"].get("CLOUDFLARE_API_TOKEN")))
        if args[1] == "deploy":
            conf = args[args.index("--config") + 1]
            self.config = json.loads(open(conf, encoding="utf-8").read())
            site = (preview.Path(conf).parent / self.config["assets"]["directory"]).resolve()
            self.site = {p.relative_to(site).as_posix(): p.read_text(encoding="utf-8") for p in site.rglob("*") if p.is_file()}
        return type("R", (), {"returncode": 1 if self.fail else 0, "stdout": "", "stderr": "Authentication error [code: 10000]"})()


def test_publish_builds_the_site_sets_urls_and_logs(home):
    a = add(home, "a", "Smile Dental")
    b = add(home, "b", "Care Clinic")
    w = FakeWrangler()
    n = preview.publish(home, config.load(), run=w)

    assert n == {"live": 2, "published": 2, "expired": 0, "blocked": 0}
    assert [c[0][0] for c in w.calls] == ["deploy", "secret"]
    assert w.calls[1][1] == SECRET and w.calls[0][2] == "cf-token"  # the secret goes in over stdin, the token via the environment
    assert set(w.site) == {"index.html", "robots.txt", f"{a.slug}/index.html", f"{b.slug}/index.html"}
    assert "Disallow: /" in w.site["robots.txt"]
    page = w.site[f"{a.slug}/index.html"]
    assert f'<img class="ping" src="/v/{a.slug}"' in page and "Not their official site." in page and 'content="noindex"' in page

    c = w.config
    assert c["preview_urls"] is False and c["workers_dev"] is False  # old versions and *.workers.dev can't serve forgotten pages
    assert c["routes"] == [{"pattern": "demo.kite.example", "custom_domain": True}]
    assert c["kv_namespaces"] == [{"binding": "EVENTS", "id": "kv456"}] and c["account_id"] == "acc123"
    assert c["assets"]["run_worker_first"] is True and c["vars"] == {"STUDIO": "Kite Studio"}
    assert SECRET not in json.dumps(c) and "cf-token" not in json.dumps(c)

    urls = dict(home.execute("select business_id, url from demos").fetchall())
    assert urls == {"a": f"https://demo.kite.example/{a.slug}/", "b": f"https://demo.kite.example/{b.slug}/"}
    ev = home.execute("select type, actor, data_json from events where type = 'demo_published' order by business_id").fetchall()
    assert [tuple(e) for e in ev] == [("demo_published", "cli", '{"template": "clinic"}')] * 2
    assert not (preview._work(home) / "site").exists()  # the local copy with business details is gone after the deploy

    preview.publish(home, config.load(), run=FakeWrangler())
    assert home.execute("select count(*) from events where type = 'demo_published'").fetchone()[0] == 2  # nothing new to log


def test_expired_and_opted_out_demos_come_down(home):
    old = add(home, "old", "Old Dental")
    gone = add(home, "gone", "Gone Dental", phone="+919800000001")
    keep = add(home, "keep", "Keep Dental", phone="+919800000002")
    preview.publish(home, config.load(), run=FakeWrangler())
    past = (datetime.fromisoformat(db.now()) - timedelta(minutes=1)).isoformat(timespec="seconds")
    home.execute("update demos set expires_at = ? where business_id = 'old'", (past,))
    home.commit()
    opt_out(home, "+919800000001", "manual")

    w = FakeWrangler()
    n = preview.publish(home, config.load(), run=w)
    assert n == {"live": 1, "published": 0, "expired": 1, "blocked": 1}
    assert set(w.site) == {"index.html", "robots.txt", f"{keep.slug}/index.html"}  # the deploy takes the other two down
    urls = dict(home.execute("select business_id, url from demos").fetchall())
    assert urls["old"] is None and urls["gone"] is None and urls["keep"]
    assert not old.path.parent.exists()  # expired: the local page is deleted too
    assert gone.path.exists()  # opted out: kept locally, never published
    assert home.execute("select count(*) from events where type = 'demo_expired'").fetchone()[0] == 1
    preview.publish(home, config.load(), run=FakeWrangler())
    assert home.execute("select count(*) from events where type = 'demo_expired'").fetchone()[0] == 1  # logged once


def test_forgotten_demo_leaves_the_next_deploy(home):
    from leadscout.compliance import forget

    d = add(home, "f", "Forget Me Dental", emails='["me@forget.in"]')
    preview.publish(home, config.load(), run=FakeWrangler())
    forget(home, "me@forget.in")
    w = FakeWrangler()
    preview.publish(home, config.load(), run=w)
    assert f"{d.slug}/index.html" not in w.site and not d.path.parent.exists()


def test_failed_deploy_changes_nothing(home):
    add(home, "a", "Smile Dental")
    with pytest.raises(preview.PreviewError, match="Authentication error"):
        preview.publish(home, config.load(), run=FakeWrangler(fail=True))
    assert home.execute("select url from demos").fetchone()[0] is None
    assert home.execute("select count(*) from events where type = 'demo_published'").fetchone()[0] == 0
    assert not (preview._work(home) / "site").exists()


def test_publish_and_sync_explain_missing_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    monkeypatch.delenv("PREVIEW_SYNC_SECRET", raising=False)
    (tmp_path / "config.toml").write_text(CONFIG.replace('base_url = "https://demo.kite.example/"', 'base_url = ""'), encoding="utf-8")
    con = db.connect()
    with pytest.raises(preview.PreviewError, match="base_url"):
        preview.publish(con, config.load(), run=FakeWrangler())
    with pytest.raises(preview.PreviewError, match="base_url"):
        preview.sync(con, config.load(), client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))


class FakeHost:
    """The Worker's /api/sync and /api/ack, holding items until they're acknowledged."""

    def __init__(self, views=(), unsubscribes=()):
        self.views, self.unsubs, self.acked, self.auth = list(views), list(unsubscribes), [], []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.auth.append(request.headers.get("authorization"))
        if request.url.path == "/api/sync":
            return httpx.Response(200, json={"views": self.views, "unsubscribes": self.unsubs})
        keys = json.loads(request.content)["keys"]
        self.acked += keys
        self.views = [v for v in self.views if v["key"] not in keys]
        self.unsubs = [u for u in self.unsubs if u["key"] not in keys]
        return httpx.Response(200, json={"deleted": len(keys)})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self))


def test_sync_records_views_once(home):
    d = add(home, "a", "Smile Dental")
    host = FakeHost(views=[
        {"key": f"view:1:{d.slug}", "slug": d.slug, "at": "2026-11-26T04:30:00.000Z"},
        {"key": f"view:2:{d.slug}", "slug": d.slug, "at": "2026-11-27T04:30:00.000Z"},
        {"key": "view:3:NoSuchDemoSlugAnymore1", "slug": "NoSuchDemoSlugAnymore1", "at": "2026-11-26T05:00:00.000Z"},
    ])
    n = preview.sync(home, config.load(), client=host.client())
    assert n["views"] == 2 and n["received"] == 3
    r = home.execute("select first_viewed_at, view_count from demos").fetchone()
    assert tuple(r) == ("2026-11-26T10:00:00+05:30", 2)  # UTC from the host, stored in IST
    assert host.auth == [f"Bearer {SECRET}"] * 2 and len(host.acked) == 3
    ev = home.execute("select actor, data_json from events where type = 'demo_viewed'").fetchall()
    assert [tuple(e) for e in ev] == [("preview-host", None)] * 2

    # The host didn't get the ack and sends the same items again: nothing is counted twice.
    again = FakeHost(views=[{"key": f"view:1:{d.slug}", "slug": d.slug, "at": "2026-11-26T04:30:00.000Z"}])
    assert preview.sync(home, config.load(), client=again.client())["views"] == 0
    assert home.execute("select view_count from demos").fetchone()[0] == 2


def test_unsubscribes_wait_until_resolve_exists(home, monkeypatch):
    add(home, "a", "Smile Dental")
    tok = {"key": "unsub:tokentokentoken12345", "token": "tokentokentoken12345", "at": "2026-11-26T04:30:00.000Z"}
    monkeypatch.setattr(preview, "_unsubscribe_api", lambda: None)  # contract C4 not built yet
    n = preview.sync(home, config.load(), client=FakeHost(unsubscribes=[tok]).client())
    assert n["queued"] == 1 and preview.queued_unsubscribes(home) == 1
    assert "contract C4" in home.execute("select note from preview_items").fetchone()[0]

    calls = []
    monkeypatch.setattr(preview, "_unsubscribe_api", lambda: (lambda con, t: "a" if t == tok["token"] else None,
                                                              lambda con, bid, reason: calls.append((bid, reason))))
    n = preview.sync(home, config.load(), client=FakeHost().client())  # nothing new on the host: the queue drains
    assert n["opted_out"] == 1 and calls == [("a", "unsubscribe link")] and preview.queued_unsubscribes(home) == 0


def test_real_unsubscribe_api_is_used_when_present_else_none():
    api = preview._unsubscribe_api()
    try:
        from leadscout.outreach.unsubscribe import resolve  # noqa: F401
    except ImportError:
        assert api is None
    else:
        assert api is not None


def test_host_down_is_a_clear_error_and_stores_nothing(home):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(preview.PreviewError, match="Couldn't reach the preview host"):
        preview.sync(home, config.load(), client=client)
    assert home.execute("select count(*) from preview_items").fetchone()[0] == 0


def test_hourly_sync_stays_off_without_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADSCOUT_HOME", str(tmp_path))
    monkeypatch.delenv("PREVIEW_SYNC_SECRET", raising=False)
    monkeypatch.setattr(preview, "_started", False)
    preview.start_hourly_sync()
    assert preview._started is False


def test_demos_page_and_buttons(home, monkeypatch):
    from fastapi.testclient import TestClient

    from leadscout.web.app import app

    d = add(home, "a", "Smile Dental")
    monkeypatch.setattr(preview, "start_hourly_sync", lambda: None)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        page = client.get("/demos").text
        assert "Smile Dental" in page and "Not online" in page and 'href="/demos"' in page

        monkeypatch.setattr(preview, "publish", lambda con, cfg, actor: {"live": 1, "published": 1, "expired": 0, "blocked": 0})
        r = client.post("/demos/publish", follow_redirects=False)
        assert r.status_code == 303 and "Published" in r.headers["location"]

        def down(con, cfg):
            raise preview.PreviewError("Couldn't reach the preview host: 503")

        monkeypatch.setattr(preview, "sync", down)
        page = client.post("/demos/sync").text
        assert "Couldn&#39;t reach the preview host" in page or "Couldn't reach the preview host" in page
        assert client.post("/demos/sync", headers={"Origin": "https://evil.example"}).status_code == 403  # dashboard rule still holds
    assert d.slug not in page  # slugs (the unguessable part of the link) aren't shown until there's a url
