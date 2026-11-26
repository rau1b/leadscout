"""Dashboard area for demo pages (Show & close): the list, Publish and Sync now. Registered by one import line in web/app.py."""

from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from leadscout import config, db
from leadscout.demos import preview
from leadscout.web.app import app, ctx, tpl

ROWS = """select d.slug, d.business_id, d.template, d.url, d.built_at, d.expires_at, d.first_viewed_at, d.view_count,
                 b.name, coalesce(b.locality, b.city, b.area) as area
          from demos d join businesses b on b.id = d.business_id order by d.built_at desc"""


@app.get("/demos", response_class=HTMLResponse)
def demos_page(request: Request, done: str = "", error: str = ""):
    con = db.connect()
    cfg = config.load()
    now = db.now()
    rows = [dict(r) | {"expired": r["expires_at"] <= now} for r in con.execute(ROWS)]
    return tpl.TemplateResponse(
        request, "demos.html",
        ctx(request, nav="demos", rows=rows, done=done, error=error, queued=preview.queued_unsubscribes(con),
            publish_problem=preview.publish_problem(cfg), sync_problem=preview.sync_problem(cfg)),
    )


def _back(**msg) -> RedirectResponse:
    k, v = next(iter(msg.items()))
    return RedirectResponse(f"/demos?{k}={quote(v)}", status_code=303)


@app.post("/demos/publish")
def demos_publish():
    try:
        n = preview.publish(db.connect(), config.load(), actor="dashboard")
    except preview.PreviewError as e:
        return _back(error=str(e))
    return _back(done=f"Published: {n['live']} demo(s) online, {n['expired']} expired and taken down, {n['blocked']} left out (opted out).")


@app.post("/demos/sync")
def demos_sync():
    try:
        n = preview.sync(db.connect(), config.load())
    except preview.PreviewError as e:
        return _back(error=str(e))
    queued = f" {n['queued']} unsubscribe(s) are waiting for the unsubscribe code (contract C4)." if n["queued"] else ""
    return _back(done=f"Synced: {n['views']} new view(s), {n['opted_out']} unsubscribe(s) applied.{queued}")
