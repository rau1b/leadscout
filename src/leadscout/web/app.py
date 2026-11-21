"""Local dashboard: `leadscout serve` then open http://127.0.0.1:8000"""

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from leadscout import config, db, searches
from leadscout.audit.classify import LABELS
from leadscout.compliance import in_window, lead_is_suppressed, opt_out
from leadscout.config import IST
from leadscout.db import jload, now
from leadscout.mailer.sender import daily_cap, next_item, sent_today, today_ist
from leadscout.pitch import jobs, templates

HERE = Path(__file__).parent
@asynccontextmanager
async def lifespan(_app):
    from leadscout.compliance import purge_if_due

    from leadscout.web import sending

    purge_if_due(db.connect(), config.load())  # retention: drop never-contacted leads past the limit, once a day
    sending.note_cut_off_run(db.connect())
    searches.start_worker()  # runs area searches queued from the Find leads page
    yield


app = FastAPI(title="LeadScout", lifespan=lifespan)

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


@app.middleware("http")
async def local_only(request: Request, call_next):
    """The dashboard is for this computer only.

    - The Host check stops DNS rebinding, where another site points its own domain at 127.0.0.1 to read the dashboard.
    - The Origin check stops cross-site form posts, where a page you visit makes the dashboard approve or send.
    """
    if urlsplit("//" + request.headers.get("host", "")).hostname not in LOCAL_HOSTS:
        return PlainTextResponse("LeadScout only answers on 127.0.0.1.", status_code=403)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        # Match scheme, host and port exactly: another app on this computer (a different port), a sandboxed
        # page ("null") or a look-alike such as http://127.0.0.1:8000.evil.com must not pass.
        port = request.scope["server"][1]
        allowed = {f"http://{h}:{port}" for h in ("127.0.0.1", "localhost", "[::1]")}
        origin = request.headers.get("origin")
        if origin is None and request.headers.get("referer"):
            parts = urlsplit(request.headers["referer"])
            origin = f"{parts.scheme}://{parts.netloc}"
        if origin is not None and origin not in allowed:
            return PlainTextResponse("Blocked a form sent from another website.", status_code=403)
    return await call_next(request)


app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
tpl = Jinja2Templates(directory=HERE / "templates")

STATUS_LABELS = {
    "new": "New", "drafted": "Drafted", "approved": "Approved", "contacted": "Contacted", "replied": "Replied",
    "won": "Won", "lost": "Lost", "opted_out": "Opted out", "bounced": "Bounced", "excluded": "Excluded", "hidden": "Hidden",
    "send_failed": "Send failed",
}
tpl.env.globals.update(status_labels=STATUS_LABELS, site_labels=LABELS)
tpl.env.filters["nicecat"] = lambda c: (c or "").replace("_", " ").capitalize()
tpl.env.filters["fromjson"] = lambda s: __import__("json").loads(s) if s else {}
tpl.env.filters["hm"] = lambda s: s[11:16] if s else ""
tpl.env.filters["day"] = lambda s: datetime.fromisoformat(s).strftime("%d %b") if s else ""


def ctx(request: Request, **extra) -> dict:
    con = db.connect()
    cfg = config.load()
    counts = {r["status"]: r["n"] for r in con.execute("select status, count(*) n from leads group by status")}
    return {
        "request": request,
        "counts": counts,
        "sent_today": sent_today(con),
        "sent_total": con.execute("select count(*) from outreach where channel = 'email'").fetchone()[0],
        "cap": daily_cap(con, cfg),
        "cfg": cfg,
        **extra,
    }


LEAD_SQL = """
select b.id, b.name, b.category, b.locality, b.area, b.city, b.address, b.website, b.phone, b.phone_type, b.socials, b.source,
       a.site_class, a.fetch_error, a.perf_score, a.lcp_s, a.https, a.viewport, a.copyright_year, a.generator,
       a.has_whatsapp, a.has_tel, a.final_url,
       l.score, l.reasons, l.status, l.email, l.updated_at,
       p.subject, p.body, p.whatsapp, p.source as pitch_source, p.approved
from leads l join businesses b on b.id = l.business_id join audits a on a.business_id = b.id
left join pitches p on p.business_id = b.id
"""


def headline(r) -> str:
    """The one measured fact that explains the lead, in plain words."""
    if r["site_class"] == "broken" and r["fetch_error"] == "dns":
        return "Domain expired"
    if r["site_class"] == "social_only":
        w = (r["website"] or "").lower()
        return "Instagram only" if "instagram" in w else "Facebook only" if "facebook" in w else "Social page only"
    if r["site_class"] != "real":
        return LABELS.get(r["site_class"], r["site_class"])
    if r["fetch_error"] == "bad_certificate":
        return "Security warning in browsers"
    if r["lcp_s"] and r["lcp_s"] > 4:
        return f"Loads in {r['lcp_s']}s on mobile"
    if r["perf_score"] is not None and r["perf_score"] < 50:
        return f"Speed score {r['perf_score']}/100"
    if r["viewport"] == 0:
        return "Not mobile-friendly"
    if not r["https"]:
        return "No HTTPS"
    reasons = jload(r["reasons"])
    return reasons[0] if reasons else "Working site"


tpl.env.filters["headline"] = headline


def lead_row(lead_id: str):
    con = db.connect()
    r = con.execute(LEAD_SQL + " where b.id = ?", (lead_id,)).fetchone()
    if not r:
        raise HTTPException(404, "Lead not found")
    return r


def wa_link(r) -> str | None:
    if r["phone_type"] != "mobile" or not r["phone"]:
        return None
    if lead_is_suppressed(db.connect(), r["id"]):
        return None
    text = r["whatsapp"] or ""
    return f"https://wa.me/{r['phone'].lstrip('+')}" + (f"?text={quote(text)}" if text else "")


tpl.env.globals["wa_link"] = wa_link


def sending_ctx(con, cfg) -> dict:
    """What the Start/Stop sending block on the Today page needs."""
    from leadscout.mailer.sender import stuck_claims
    from leadscout.web import sending

    return {
        "sending": sending.running(),
        "stopping": sending.stopping(),
        "send_log": list(sending.log),
        "send_block": "" if sending.running() else sending.block_reason(con, cfg),
        "stuck": stuck_claims(con),
        "open_now": in_window(cfg.sending),
    }


@app.get("/", response_class=HTMLResponse)
def today(request: Request, msg: str = ""):
    con = db.connect()
    cfg = config.load()
    day = today_ist().isoformat()
    sent = con.execute(
        """select o.sent_at, o.kind, b.name, b.id from outreach o join businesses b on b.id = o.business_id
           where o.channel = 'email' and o.kind != 'reply' and substr(o.sent_at, 1, 10) = ? order by o.sent_at""",
        (day,),
    ).fetchall()
    send = sending_ctx(con, cfg)
    held = {c["business_id"] for c in send["stuck"] if c["kind"] == "first"}  # waiting on a Gmail check, not queued
    queue = [r for r in con.execute(LEAD_SQL + " where l.status = 'approved' order by l.score desc").fetchall() if r["id"] not in held]
    drafted = con.execute(LEAD_SQL + " where l.status = 'drafted' order by l.score desc limit 12").fetchall()
    replies = con.execute(LEAD_SQL + " where l.status = 'replied' order by l.updated_at desc").fetchall()
    cap = daily_cap(con, cfg)
    first = db.get_meta(con, "first_send_date")
    week = ((today_ist() - datetime.fromisoformat(first).date()).days // 7 + 1) if first else 1
    return tpl.TemplateResponse(
        request,
        "today.html",
        ctx(
            request,
            nav="today",
            sent=sent,
            queue=queue,
            drafted=drafted,
            replies=replies,
            carry=max(0, len(queue) - max(0, cap - len(sent))),
            week=week,
            now=datetime.now(IST),
            has_next=next_item(con, cfg) is not None,
            msg=msg,
            **send,
        ),
    )


@app.get("/leads", response_class=HTMLResponse)
def leads(request: Request, status: str = "active", q: str = "", sort: str = "score", has_email: int = 0, area: str = ""):
    con = db.connect()
    where, args = [], []
    if area:
        where.append("b.area = ?")
        args.append(area)
    if status == "active":
        where.append("l.status not in ('excluded', 'opted_out', 'bounced', 'lost', 'hidden')")
    elif status != "all":
        where.append("l.status = ?")
        args.append(status)
    if q:
        where.append("(b.name like ? or b.category like ? or b.locality like ?)")
        args += [f"%{q}%"] * 3
    if has_email:
        where.append("l.email is not null")
    order = {"score": "l.score desc", "name": "b.name", "updated": "l.updated_at desc"}.get(sort, "l.score desc")
    sql = LEAD_SQL + (" where " + " and ".join(where) if where else "") + f" order by {order} limit 500"
    rows = con.execute(sql, args).fetchall()
    return tpl.TemplateResponse(
        request, "leads.html", ctx(request, nav={"replied": "replies", "opted_out": "optouts"}.get(status, "leads"), rows=rows, status=status, q=q, sort=sort, has_email=has_email, area=area, areas=area_options(con))
    )


@app.get("/pitches", response_class=HTMLResponse)
def pitches(request: Request, area: str = ""):
    con = db.connect()
    sql = LEAD_SQL + " where l.status = 'drafted'" + (" and b.area = ?" if area else "") + " order by (l.email is null), l.score desc"
    rows = con.execute(sql, (area,) if area else ()).fetchall()
    return tpl.TemplateResponse(request, "pitches.html", ctx(request, nav="pitches", rows=rows, area=area, areas=area_options(con, "drafted")))


@app.get("/sent", response_class=HTMLResponse)
def sent(request: Request):
    con = db.connect()
    rows = con.execute(
        """select o.*, b.name, l.status from outreach o join businesses b on b.id = o.business_id
           join leads l on l.business_id = o.business_id where o.channel = 'email' order by o.sent_at desc limit 300"""
    ).fetchall()
    return tpl.TemplateResponse(request, "sent.html", ctx(request, nav="sent", rows=rows))


@app.get("/leads/{lead_id}", response_class=HTMLResponse)
def lead_detail(request: Request, lead_id: str, saved: str = "", msg: str = ""):
    from leadscout.pitch import quick_replies

    r = lead_row(lead_id)
    con = db.connect()
    cfg = config.load()
    history = con.execute("select * from outreach where business_id = ? order by sent_at", (lead_id,)).fetchall()
    convo = con.execute("select * from replies where business_id = ? order by received_at", (lead_id,)).fetchall()
    quick = {k: quick_replies.fill(v, dict(r), cfg) for k, v in quick_replies.all_replies(cfg).items()} if convo else {}
    deal = con.execute("select quote_inr, paid_inr, deal_note, won_at from leads where business_id = ?", (lead_id,)).fetchone()
    return tpl.TemplateResponse(
        request,
        "lead.html",
        ctx(request, nav="leads", r=r, reasons=jload(r["reasons"]), socials=jload(r["socials"]), history=history, saved=saved,
            msg=msg, convo=convo, quick=quick, deal=deal, wa_today=whatsapp_today(con), wa_cap=whatsapp_cap(cfg),
            wa_opened=any(h["channel"] == "whatsapp" for h in history)),
    )


@app.post("/leads/{lead_id}/pitch")
def save_pitch(lead_id: str, subject: str = Form(...), body: str = Form(...), whatsapp: str = Form(""), action: str = Form("save")):
    con = db.connect()
    lead_row(lead_id)
    jobs.save_pitch(con, lead_id, {"subject": subject.strip(), "body": body.strip(), "whatsapp": whatsapp.strip()[:600]}, "edited")
    if action == "approve":
        _approve(con, lead_id)
    con.commit()
    return RedirectResponse(f"/leads/{lead_id}?saved={action}", status_code=303)


@app.post("/leads/{lead_id}/draft")
def draft_from_template(lead_id: str):
    con = db.connect()
    cfg = config.load()
    r = lead_row(lead_id)
    problem = config.sender_problem(cfg)
    if problem:
        return RedirectResponse(f"/leads/{lead_id}?msg={quote(problem)}", status_code=303)
    try:
        pitch = templates.render(dict(r), cfg)
    except ValueError as e:  # nothing measured on this site
        return RedirectResponse(f"/leads/{lead_id}?msg={quote(str(e))}", status_code=303)
    jobs.save_pitch(con, lead_id, pitch, "template")
    con.commit()
    return RedirectResponse(f"/leads/{lead_id}?saved=drafted", status_code=303)


def _approve(con, lead_id: str) -> None:
    con.execute("update pitches set approved = 1, updated_at = ? where business_id = ?", (now(), lead_id))
    con.execute("update leads set status = 'approved', updated_at = ? where business_id = ? and status = 'drafted'", (now(), lead_id))


@app.post("/leads/{lead_id}/approve", response_class=HTMLResponse)
def approve(request: Request, lead_id: str):
    con = db.connect()
    _approve(con, lead_id)
    con.commit()
    return tpl.TemplateResponse(request, "_pitch_card.html", {"request": request, "r": lead_row(lead_id)})


@app.post("/leads/{lead_id}/unapprove", response_class=HTMLResponse)
def unapprove(request: Request, lead_id: str):
    con = db.connect()
    con.execute("update pitches set approved = 0 where business_id = ?", (lead_id,))
    con.execute("update leads set status = 'drafted', updated_at = ? where business_id = ? and status = 'approved'", (now(), lead_id))
    con.commit()
    return tpl.TemplateResponse(request, "_pitch_card.html", {"request": request, "r": lead_row(lead_id)})


@app.post("/pitches/approve-all")
def approve_all(area: str = Form("")):
    con = db.connect()
    sql = "select l.business_id from leads l join businesses b on b.id = l.business_id where l.status = 'drafted' and l.email is not null"
    ids = [r[0] for r in con.execute(sql + (" and b.area = ?" if area else ""), (area,) if area else ())]
    for i in ids:
        _approve(con, i)
    con.commit()
    return RedirectResponse(f"/pitches?area={quote(area)}" if area else "/pitches", status_code=303)


@app.post("/leads/{lead_id}/status")
def set_status(lead_id: str, status: str = Form(...)):
    if status not in ("won", "lost", "replied", "new"):
        raise HTTPException(400, "Unknown status")
    con = db.connect()
    if lead_is_suppressed(con, lead_id):
        msg = "This business opted out. Their status stays Opted out."
        return RedirectResponse(f"/leads/{lead_id}?msg={quote(msg)}", status_code=303)
    con.execute("update leads set status = ?, updated_at = ? where business_id = ?", (status, now(), lead_id))
    con.commit()
    return RedirectResponse(f"/leads/{lead_id}", status_code=303)


def whatsapp_today(con) -> int:
    return con.execute(
        "select count(*) from outreach where channel = 'whatsapp' and substr(sent_at, 1, 10) = ?", (today_ist().isoformat(),)
    ).fetchone()[0]


def whatsapp_cap(cfg) -> int:
    return int(cfg.sending.get("whatsapp_daily_cap", 20))


@app.post("/leads/{lead_id}/whatsapp")
def open_whatsapp(lead_id: str):
    """Count the chat, then hand over to WhatsApp. You still write and send the message yourself."""
    con = db.connect()
    r = lead_row(lead_id)
    link = wa_link(r)
    if not link or r["status"] in ("opted_out", "bounced"):
        return RedirectResponse(f"/leads/{lead_id}?msg={quote('No WhatsApp chat for this lead.')}", status_code=303)
    done, cap = whatsapp_today(con), whatsapp_cap(config.load())
    already = con.execute("select 1 from outreach where business_id = ? and channel = 'whatsapp'", (lead_id,)).fetchone()
    if not already:
        if done >= cap:
            msg = f"You've opened {done} new WhatsApp chats today (limit {cap}). Try again tomorrow."
            return RedirectResponse(f"/leads/{lead_id}?msg={quote(msg)}", status_code=303)
        con.execute(
            "insert into outreach (business_id, channel, kind, to_addr, sent_at) values (?, 'whatsapp', 'first', ?, ?)",
            (lead_id, r["phone"], now()),
        )
        con.commit()
    return RedirectResponse(link, status_code=303)


@app.post("/leads/{lead_id}/optout")
def optout(lead_id: str):
    con = db.connect()
    r = lead_row(lead_id)
    for v in (r["email"], r["phone"]):
        if v:
            opt_out(con, v, "dashboard")  # also marks other listings with the same email or phone
    con.execute("update leads set status = 'opted_out', updated_at = ? where business_id = ?", (now(), lead_id))
    con.commit()
    return RedirectResponse(f"/leads/{lead_id}?saved=optout", status_code=303)


def area_options(con, status: str | None = None) -> list:
    """Searched areas with their lead counts, for the area filter."""
    sql = """select b.area, count(*) n from leads l join businesses b on b.id = l.business_id
             where b.area is not null and l.status != 'excluded'""" + (" and l.status = ?" if status else "") + """
             group by b.area order by b.area"""
    return con.execute(sql, (status,) if status else ()).fetchall()


@app.get("/find", response_class=HTMLResponse)
def find_page(request: Request, error: str = ""):
    con = db.connect()
    return tpl.TemplateResponse(
        request,
        "find.html",
        ctx(request, nav="find", areas=searches.searched_areas(con), types=searches.BUSINESS_TYPES,
            cities=searches.CITIES, error=error, has_key=bool(config.load().google_api_key)),
    )


@app.get("/find/list", response_class=HTMLResponse)
def find_list(request: Request):
    con = db.connect()
    return tpl.TemplateResponse(request, "_areas.html", {"request": request, "areas": searches.searched_areas(con)})


@app.get("/places")
def place_suggestions(q: str = ""):
    from leadscout import places

    return places.search(q, limit=8)


@app.post("/find")
def start_find(city: str = Form(""), neighbourhood: str = Form(""), types: list[str] = Form([]), extra: str = Form(""),
               place_id: str = Form("")):
    con = db.connect()
    try:
        searches.queue_search(con, city, neighbourhood, types, extra, int(place_id) if place_id.isdigit() else None)
    except ValueError as e:
        return RedirectResponse(f"/find?error={quote(str(e))}", status_code=303)
    return RedirectResponse("/find", status_code=303)


# Routes for replies, deals and hiding live in extras.py.
from leadscout.web import extras  # noqa: E402,F401
