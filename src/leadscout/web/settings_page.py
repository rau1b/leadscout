"""Dashboard route for the Settings page (config.toml as a form; see leadscout/settings.py)."""

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from leadscout import config, settings
from leadscout.compliance import DAYS
from leadscout.web.app import app, ctx, tpl


def _render(request: Request, values: dict, errors: dict, saved: str = "", status: int = 200):
    cfg = config.load()
    has_file = (config.home() / "config.toml").exists()
    return tpl.TemplateResponse(
        request, "settings.html",
        ctx(request, nav="settings", v=values, errors=errors, saved=saved, days=DAYS, warmup_labels=settings.WARMUP,
            has_file=has_file, problem=config.sender_problem(cfg) if has_file else None,
            has_key=bool(cfg.google_api_key)),  # only whether it's set: the key itself stays in .env
        status_code=status,
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_get(request: Request, saved: str = ""):
    return _render(request, settings.form_values(settings.current()), {}, saved)


@app.post("/settings", response_class=HTMLResponse)
async def settings_post(request: Request):
    form = await request.form()
    raw, errors = settings.parse(form, settings.current())
    if errors:  # nothing is written; show what they typed, with the problems next to the fields
        values = {k: form.get(k) for k in form.keys()} | {"sending.days": form.getlist("sending.days")}
        return _render(request, values, errors, status=400)
    keys = settings.save(raw)
    return RedirectResponse(f"/settings?saved={len(keys)}", status_code=303)
