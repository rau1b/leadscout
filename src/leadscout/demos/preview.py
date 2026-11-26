"""The preview host: publish demo pages to a Cloudflare Worker, and sync views and unsubscribes back.

- `publish()` copies every live demo (not expired, business not suppressed) into a build folder and deploys it with wrangler.
  Expired and forgotten demos are left out, so the deploy also takes them down (contract C8). It sets `demos.url` (C1).
- `sync()` pulls views and unsubscribes from the host, stores them, acknowledges them, then applies them: views update
  `demos.first_viewed_at` / `view_count`; unsubscribes go to Find & qualify's `outreach.unsubscribe.resolve()` and
  `compliance.opt_out_business()` (C4, C5). Until those exist, unsubscribes wait in `preview_items`.

Settings: [preview] in config.toml (base_url, worker_name, account_id, kv_namespace_id). Secrets in .env only:
CLOUDFLARE_API_TOKEN (publish) and PREVIEW_SYNC_SECRET (publish and sync). Setup steps: docs/STACK.md, "Preview host".
"""

import json
import logging
import os
import secrets
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from leadscout import config, db, demos
from leadscout.compliance import is_suppressed
from leadscout.config import IST

log = logging.getLogger(__name__)

WORKER = Path(__file__).resolve().parents[3] / "preview"  # the repo's preview/ folder (Worker source, wrangler install)
COMPATIBILITY_DATE = "2025-09-01"
PING = '<img class="ping" src="/v/{slug}" alt="" width="1" height="1" style="position:absolute;left:0;bottom:0">'
HOLDING = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="robots" content="noindex">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Nothing here</title></head>
<body style="font:17px/1.5 system-ui,sans-serif;max-width:32rem;margin:15vh auto;padding:0 16px">
<p>Nothing to see here. If someone sent you a link, open that link instead.</p></body></html>
"""


class PreviewError(Exception):
    """Publishing or syncing couldn't run; the message says what to fix."""


def settings(cfg) -> dict:
    p = cfg.raw.get("preview", {})
    return {
        "base_url": (p.get("base_url") or "").strip().rstrip("/"),
        "worker_name": (p.get("worker_name") or "leadscout-preview").strip(),
        "account_id": (p.get("account_id") or "").strip(),
        "kv_namespace_id": (p.get("kv_namespace_id") or "").strip(),
        "api_token": os.environ.get("CLOUDFLARE_API_TOKEN", ""),
        "sync_secret": os.environ.get("PREVIEW_SYNC_SECRET", ""),
        "studio": cfg.sender.get("business") or cfg.sender.get("name") or "",
    }


def sync_problem(cfg) -> str | None:
    s = settings(cfg)
    if not s["base_url"].startswith("https://"):
        return "Set base_url in the [preview] section of config.toml (for example https://demo.yourstudio.in)."
    if len(s["sync_secret"]) < 16:
        return "Set PREVIEW_SYNC_SECRET in .env (at least 16 characters; see docs/STACK.md)."
    return None


def publish_problem(cfg) -> str | None:
    if p := sync_problem(cfg):
        return p
    s = settings(cfg)
    if not s["account_id"] or not s["kv_namespace_id"]:
        return "Set account_id and kv_namespace_id in the [preview] section of config.toml (see docs/STACK.md)."
    if not s["api_token"]:
        return "Set CLOUDFLARE_API_TOKEN in .env (see docs/STACK.md)."
    if not wrangler().exists():
        return f"Wrangler isn't installed. Run `npm ci` in {WORKER} once (needs Node.js)."
    return config.sender_problem(cfg)


def wrangler() -> Path:
    return WORKER / "node_modules" / ".bin" / ("wrangler.cmd" if os.name == "nt" else "wrangler")


def _work(con) -> Path:
    """data/preview/ beside the database: the generated wrangler config and the site folder."""
    root = demos.folder(con)
    if root is None:
        raise PreviewError("Publishing needs a database file, not an in-memory one.")
    return root.parent / "preview"


# ---- publish ----

def _state(con) -> dict[str, list]:
    """Sort every demo row into live (goes on the host), expired and blocked (both come off it)."""
    now = datetime.fromisoformat(db.now())
    out = {"live": [], "expired": [], "blocked": []}
    rows = con.execute(
        """select d.slug, d.business_id, d.template, d.url, d.expires_at, l.status from demos d
           left join leads l on l.business_id = d.business_id order by d.built_at"""
    ).fetchall()
    for r in rows:
        page = demos.folder(con) / r["slug"] / "index.html"
        if datetime.fromisoformat(r["expires_at"]) <= now:
            out["expired"].append(r)
        elif r["status"] == "opted_out" or is_suppressed(con, *demos.contact_values(con, r["business_id"])) or not page.exists():
            out["blocked"].append(r)
        else:
            out["live"].append(r)
    return out


def build_site(con, live, site: Path) -> None:
    """The folder wrangler uploads: one <slug>/index.html per live demo (with its view ping), a holding page and robots.txt."""
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    (site / "index.html").write_text(HOLDING, encoding="utf-8")
    (site / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    for r in live:
        html = (demos.folder(con) / r["slug"] / "index.html").read_text(encoding="utf-8")
        html = html.replace("</body>", PING.format(slug=r["slug"]) + "\n</body>", 1)
        (site / r["slug"]).mkdir()
        (site / r["slug"] / "index.html").write_text(html, encoding="utf-8")


def wrangler_config(s: dict, site: Path, config_dir: Path) -> dict:
    """The Worker's wrangler config. Preview URLs stay off, so only the current deploy is reachable (old ones can't leak)."""
    host = urlsplit(s["base_url"]).hostname or ""
    main = WORKER / "src" / "index.js"
    cfg = {
        "name": s["worker_name"],
        "main": os.path.relpath(main, config_dir) if main.drive == config_dir.drive else str(main),
        "compatibility_date": COMPATIBILITY_DATE,
        "account_id": s["account_id"],
        "workers_dev": host.endswith(".workers.dev"),
        "preview_urls": False,
        "assets": {"directory": os.path.relpath(site, config_dir), "binding": "ASSETS", "run_worker_first": True},
        "kv_namespaces": [{"binding": "EVENTS", "id": s["kv_namespace_id"]}],
        "vars": {"STUDIO": s["studio"]},
        "observability": {"enabled": False},  # no request logs on Cloudflare's side either
    }
    if not host.endswith(".workers.dev"):
        cfg["routes"] = [{"pattern": host, "custom_domain": True}]
    return cfg


def publish(con, cfg, run=subprocess.run, actor: str = "cli") -> dict:
    """Deploy every live demo and take down the rest. Returns counts. Raises PreviewError when it can't deploy."""
    if p := publish_problem(cfg):
        raise PreviewError(p)
    s = settings(cfg)
    demos.remove_orphans(con)
    state = _state(con)
    work = _work(con)
    site, config_dir = work / "site", work
    config_dir.mkdir(parents=True, exist_ok=True)
    build_site(con, state["live"], site)
    conf = config_dir / "wrangler.json"
    conf.write_text(json.dumps(wrangler_config(s, site, config_dir), indent=2), encoding="utf-8")
    env = os.environ | {"CLOUDFLARE_API_TOKEN": s["api_token"], "CLOUDFLARE_ACCOUNT_ID": s["account_id"], "WRANGLER_SEND_METRICS": "false"}
    try:
        for args, stdin in (
            (["deploy", "--config", str(conf)], None),
            (["secret", "put", "SYNC_SECRET", "--config", str(conf)], s["sync_secret"]),  # the Worker's copy of the sync secret
        ):
            res = run([str(wrangler()), *args], input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                      env=env, cwd=str(WORKER), timeout=300)
            if res.returncode != 0:
                tail = "\n".join((res.stderr or res.stdout or "").strip().splitlines()[-8:])
                raise PreviewError(f"wrangler {args[0]} failed:\n{tail}")
    finally:
        shutil.rmtree(site, ignore_errors=True)  # it holds business details; Cloudflare has its copy now

    published = expired = 0
    for r in state["live"]:
        url = f"{s['base_url']}/{r['slug']}/"
        if r["url"] != url:
            con.execute("update demos set url = ? where slug = ?", (url, r["slug"]))
            db.log_event(con, "demo_published", r["business_id"], actor=actor, template=r["template"])
            published += 1
    for r in state["expired"]:
        folder = demos.folder(con) / r["slug"]
        if r["url"] is not None or folder.exists():  # first publish since it aged out
            con.execute("update demos set url = null where slug = ?", (r["slug"],))
            db.log_event(con, "demo_expired", r["business_id"], actor=actor, template=r["template"])
            shutil.rmtree(folder, ignore_errors=True)
            expired += 1
    for r in state["blocked"]:
        con.execute("update demos set url = null where slug = ?", (r["slug"],))
    con.commit()
    return {"live": len(state["live"]), "published": published, "expired": expired, "blocked": len(state["blocked"])}


# ---- sync ----

def _unsubscribe_api():
    """Find & qualify's side of contracts C4 and C5, or None while it isn't built yet."""
    try:
        from leadscout.compliance import opt_out_business
        from leadscout.outreach.unsubscribe import resolve
    except ImportError:
        return None
    return resolve, opt_out_business


def _ist(at) -> str | None:
    """The host reports UTC ("2026-11-26T10:00:00.000Z"); the database keeps IST like every other time."""
    try:
        return datetime.fromisoformat(at).astimezone(IST).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


def sync(con, cfg, client: httpx.Client | None = None) -> dict:
    """Pull views and unsubscribes from the host, store them, acknowledge them, then apply what can be applied."""
    if p := sync_problem(cfg):
        raise PreviewError(p)
    s = settings(cfg)
    headers = {"authorization": f"Bearer {s['sync_secret']}"}
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        try:
            r = client.get(f"{s['base_url']}/api/sync", headers=headers)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise PreviewError(f"Couldn't reach the preview host: {e}") from None
        received = db.now()
        keys = []
        for kind, items, field in (("view", data.get("views", []), "slug"), ("unsub", data.get("unsubscribes", []), "token")):
            for it in items:
                if isinstance(it, dict) and it.get("key") and it.get(field):
                    con.execute(
                        "insert or ignore into preview_items (key, kind, value, at, received_at) values (?, ?, ?, ?, ?)",
                        (it["key"], kind, it[field], _ist(it.get("at")) or received, received),
                    )
                    keys.append(it["key"])
        con.commit()  # stored here before the host forgets them
        if keys:
            try:
                client.post(f"{s['base_url']}/api/ack", headers=headers, json={"keys": keys}).raise_for_status()
            except httpx.HTTPError as e:
                log.warning("Preview host didn't take the acknowledgement (%s); the next sync sees the same items and skips them.", e)
    finally:
        if own:
            client.close()
    return apply_pending(con) | {"received": len(keys)}


def apply_pending(con) -> dict:
    """Apply stored items not yet done. Unsubscribes stay queued until Find & qualify's resolve() exists."""
    counts = {"views": 0, "opted_out": 0, "unknown": 0, "queued": 0}
    now = db.now()
    for it in con.execute("select * from preview_items where done_at is null and kind = 'view' order by at").fetchall():
        d = con.execute("select business_id from demos where slug = ?", (it["value"],)).fetchone()
        if d:
            con.execute(
                "update demos set first_viewed_at = coalesce(first_viewed_at, ?), view_count = view_count + 1 where slug = ?",
                (it["at"], it["value"]),
            )
            db.log_event(con, "demo_viewed", d["business_id"], actor="preview-host")
            counts["views"] += 1
        note = None if d else "no such demo (forgotten or rebuilt)"
        con.execute("update preview_items set done_at = ?, note = ? where key = ?", (now, note, it["key"]))
    con.commit()

    pending = con.execute("select * from preview_items where done_at is null and kind = 'unsub' order by at").fetchall()
    api = _unsubscribe_api()
    if pending and api is None:
        con.execute("update preview_items set note = 'waiting for outreach.unsubscribe (contract C4)' where done_at is null and kind = 'unsub'")
        con.commit()
        log.warning("%d unsubscribe(s) queued: outreach.unsubscribe.resolve() isn't built yet (contract C4).", len(pending))
        counts["queued"] = len(pending)
        return counts
    for it in pending:
        resolve, opt_out_business = api
        business_id = resolve(con, it["value"])
        if business_id:
            opt_out_business(con, business_id, "unsubscribe link")
            counts["opted_out"] += 1
        else:
            counts["unknown"] += 1
        con.execute("update preview_items set done_at = ?, note = ? where key = ?",
                    (now, None if business_id else "unknown or forgotten token", it["key"]))
        con.commit()
    return counts


def queued_unsubscribes(con) -> int:
    return con.execute("select count(*) from preview_items where done_at is null and kind = 'unsub'").fetchone()[0]


# ---- hourly sync from the dashboard ----

_started = False


def start_hourly_sync() -> None:
    """Sync every hour while the dashboard runs. Does nothing until [preview] base_url and PREVIEW_SYNC_SECRET are set."""
    global _started
    if _started or sync_problem(config.load()):
        return
    _started = True

    def loop():
        stop = threading.Event()
        while not stop.wait(3600):
            try:
                sync(db.connect(), config.load())
            except Exception as e:  # noqa: BLE001 - the next hour tries again; the Demos page has a button meanwhile
                log.warning("Hourly preview sync failed: %s", e)

    threading.Thread(target=loop, name="preview-sync", daemon=True).start()


def new_secret() -> str:
    """A sync secret for .env (`leadscout demos secret`)."""
    return secrets.token_urlsafe(32)
