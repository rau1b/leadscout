"""Dashboard route for the Settings page (config.toml as a form; see leadscout/settings.py)."""

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from leadscout import config, db, settings
from leadscout.compliance import DAYS
from leadscout.enrich import places
from leadscout.mailer.sender import lease_held
from leadscout.web import sending
from leadscout.web.app import app, ctx, tpl

EMAIL_LOCKED = "Stop sending first: emails already going out come from this address."


def _sending_now(cfg) -> bool:
    """A run is going: the dashboard's thread, or anyone holding the sender lease (`leadscout send` too)."""
    return sending.running() or lease_held(db.connect(), cfg.sending)


def _render(request: Request, values: dict, errors: dict, saved: str = "", status: int = 200, partial: bool = False):
    cfg = config.load()
    has_file = (config.home() / "config.toml").exists()
    return tpl.TemplateResponse(
        request, "settings.html",
        ctx(request, nav="settings", v=values, errors=errors, saved=saved, partial=partial, days=DAYS, warmup_labels=settings.WARMUP,
            has_file=has_file, problem=config.sender_problem(cfg) if has_file else None,
            has_key=bool(cfg.google_api_key),  # only whether it's set: the key itself stays in .env
            places_used=places.used_this_month(db.connect()), places_cap=cfg.enrich["monthly_request_cap"]),
        status_code=status,
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_get(request: Request, saved: str = ""):
    return _render(request, settings.form_values(settings.current()), {}, saved)


@app.post("/settings", response_class=HTMLResponse)
async def settings_post(request: Request):
    form = await request.form()
    base = settings.current()
    raw, errors = settings.parse(form, base)
    old_email = base.get("sender", {}).get("email")
    locked = raw["sender"]["email"] != old_email and _sending_now(config.load())
    if errors:  # nothing is written; show what they typed, with the problems next to the fields
        if locked and "sender.email" not in errors:
            errors["sender.email"] = EMAIL_LOCKED
        values = {k: form.get(k) for k in form.keys()} | {"sending.days": form.getlist("sending.days")}
        return _render(request, values, errors, status=400)
    if locked:  # keep the address the run is sending from; save the rest
        raw["sender"]["email"] = old_email
        keys = settings.save(raw)
        return _render(request, settings.form_values(settings.current()), {"sender.email": EMAIL_LOCKED}, str(len(keys)), partial=True)
    keys = settings.save(raw)
    return RedirectResponse(f"/settings?saved={len(keys)}", status_code=303)
