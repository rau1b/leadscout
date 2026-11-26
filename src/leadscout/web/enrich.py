"""Dashboard: live Google details on the lead page (Find & qualify). Fetched on request, shown with attribution, never saved."""

import httpx
from fastapi import Request
from fastapi.responses import HTMLResponse

from leadscout import config, db
from leadscout.enrich import places
from leadscout.web.app import app, tpl

STATUS = {"OPERATIONAL": "Open", "CLOSED_TEMPORARILY": "Closed for now", "CLOSED_PERMANENTLY": "Closed for good"}


def google_place_id(business_id: str) -> str | None:
    """The lead's Google place id when Places is on, for the lead page's button."""
    return places.place_id(db.connect(), business_id) if places.enabled(config.load()) else None


tpl.env.globals["google_place_id"] = google_place_id


@app.get("/leads/{lead_id}/google", response_class=HTMLResponse)
def google_details(request: Request, lead_id: str):
    con, cfg = db.connect(), config.load()
    pid = places.place_id(con, lead_id)
    d, error = {}, None
    if not places.enabled(cfg) or not pid:
        error = "Google Places is off, or this lead has no Google match."
    else:
        try:
            d = places.details(con, cfg, pid)
        except places.CapReached as e:
            error = str(e)
        except (httpx.HTTPError, ValueError):
            error = "Google didn't answer. Try again in a minute."
    return tpl.TemplateResponse(request, "_google.html", {"request": request, "d": d, "pid": pid, "error": error, "status": STATUS})
