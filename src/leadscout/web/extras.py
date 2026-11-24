"""Dashboard routes for replies, deals and hiding wrong-category leads."""

from urllib.parse import quote

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from leadscout import config, db
from leadscout.compliance import lead_is_suppressed
from leadscout.db import now
from leadscout.web.app import app, ctx, lead_row, sending_ctx, tpl

# ---- Replies -------------------------------------------------------------------------------

REPLY_SQL = """
select b.id, b.name, b.category, b.area, l.status, l.email, l.score,
       r.body as last_body, r.received_at as last_at, r.kind as last_kind,
       (select count(*) from replies where business_id = b.id) as n_replies,
       (select max(sent_at) from outreach where business_id = b.id and kind = 'reply') as answered_at
from leads l join businesses b on b.id = l.business_id
join replies r on r.gmail_id = (select gmail_id from replies where business_id = b.id order by received_at desc limit 1)
"""


@app.get("/replies", response_class=HTMLResponse)
def replies_page(request: Request, msg: str = ""):
    con = db.connect()
    rows = con.execute(REPLY_SQL + " where r.kind = 'replied' or l.status in ('replied', 'won') order by r.received_at desc").fetchall()
    return tpl.TemplateResponse(
        request, "replies.html", ctx(request, nav="replies", rows=rows, msg=msg, last_check=db.get_meta(con, "last_inbox_check"))
    )


def _gmail():
    from leadscout.mailer.gmail import Gmail

    try:
        return Gmail()
    except RuntimeError as e:
        raise ValueError(str(e)) from e  # not logged in, or the login expired: the message says what to run


@app.post("/replies/check")
def check_inbox():
    from leadscout.mailer.sender import check_replies

    con = db.connect()
    try:
        counts = check_replies(con, config.load(), _gmail())
    except ValueError as e:
        return RedirectResponse(f"/replies?msg={quote(str(e))}", status_code=303)
    db.set_meta(con, "last_inbox_check", now())
    found = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in counts.items() if n) or "no new replies"
    return RedirectResponse(f"/replies?msg={quote('Inbox checked: ' + found + '.')}", status_code=303)


@app.post("/leads/{lead_id}/reply")
def send_reply_route(lead_id: str, body: str = Form(...)):
    from leadscout.mailer.sender import send_reply
    from leadscout.pitch.quick_replies import unfilled

    con = db.connect()
    missing = unfilled(body)
    if missing:
        msg = "Fill in " + ", ".join(missing) + " before sending."
        return RedirectResponse(f"/leads/{lead_id}?msg={quote(msg)}#reply", status_code=303)
    try:
        send_reply(con, config.load(), _gmail(), lead_id, body.strip())
    except ValueError as e:
        return RedirectResponse(f"/leads/{lead_id}?msg={quote(str(e))}#reply", status_code=303)
    return RedirectResponse(f"/leads/{lead_id}?saved=replied#reply", status_code=303)


# ---- Sending from the dashboard ------------------------------------------------------------


@app.post("/send/start")
def send_start():
    from leadscout.web import sending

    con = db.connect()
    why = sending.block_reason(con, config.load())
    if why:  # the button is disabled then, but check here too
        return RedirectResponse(f"/?msg={quote(why)}", status_code=303)
    try:
        gm = _gmail()
    except ValueError as e:
        return RedirectResponse(f"/?msg={quote(str(e))}", status_code=303)
    msg = "Sending started. It stops by itself at the daily cap, the end of the window or a bounce spike." if sending.start(gm) else "Already sending."
    return RedirectResponse(f"/?msg={quote(msg)}", status_code=303)


@app.post("/send/stop")
def send_stop():
    from leadscout.web import sending

    sending.stop()
    return RedirectResponse(f"/?msg={quote('Stopping. Nothing more goes out after the email in hand.')}", status_code=303)


@app.get("/send/status", response_class=HTMLResponse)
def send_status(request: Request):
    """The sending block alone, polled while a run is going. When the run ends, reload the page to update the slots."""
    from leadscout.web import sending

    con = db.connect()
    resp = tpl.TemplateResponse(request, "_sending.html", {"request": request, **sending_ctx(con, config.load())})
    if not sending.running():
        resp.headers["HX-Refresh"] = "true"
    return resp


@app.post("/send/resolve")
def send_resolve():
    from leadscout.mailer.sender import resolve_stuck

    con = db.connect()
    try:
        counts = resolve_stuck(con, _gmail())
    except ValueError as e:
        return RedirectResponse(f"/?msg={quote(str(e))}", status_code=303)
    except Exception:
        return RedirectResponse(f"/?msg={quote('Could not reach Gmail. Nothing was changed; try again in a minute.')}", status_code=303)
    msg = f"Checked Gmail: {counts['recorded']} had gone out and are now recorded, {counts['released']} had not and are back in the queue."
    return RedirectResponse(f"/?msg={quote(msg)}", status_code=303)


# ---- Deals ---------------------------------------------------------------------------------

def rupees(text: str) -> int | None:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


@app.post("/leads/{lead_id}/deal")
def save_deal(lead_id: str, quote_inr: str = Form(""), paid_inr: str = Form(""), deal_note: str = Form(""), status: str = Form("")):
    con = db.connect()
    lead_row(lead_id)
    con.execute(
        "update leads set quote_inr = ?, paid_inr = ?, deal_note = ?, updated_at = ? where business_id = ?",
        (rupees(quote_inr), rupees(paid_inr), deal_note.strip() or None, now(), lead_id),
    )
    if status in ("won", "lost", "replied") and not lead_is_suppressed(con, lead_id):
        con.execute(
            "update leads set status = ?, won_at = case when ? = 'won' then ? else won_at end where business_id = ?",
            (status, status, now(), lead_id),
        )
    con.commit()
    return RedirectResponse(f"/leads/{lead_id}?saved=deal#deal", status_code=303)


@app.get("/deals", response_class=HTMLResponse)
def deals(request: Request):
    con = db.connect()
    rows = con.execute(
        """select b.id, b.name, b.area, l.status, l.quote_inr, l.paid_inr, l.deal_note, l.won_at, l.updated_at
           from leads l join businesses b on b.id = l.business_id
           where l.quote_inr is not null or l.paid_inr is not null or l.status in ('won', 'replied')
           order by case l.status when 'won' then 0 when 'replied' then 1 else 2 end, l.updated_at desc"""
    ).fetchall()
    won = [r for r in rows if r["status"] == "won"]
    talking = [r for r in rows if r["status"] == "replied"]
    totals = {
        "won": len(won),
        "won_value": sum(r["quote_inr"] or 0 for r in won),
        "paid": sum(r["paid_inr"] or 0 for r in rows),
        "due": sum(max((r["quote_inr"] or 0) - (r["paid_inr"] or 0), 0) for r in won),
        "talking": len(talking),
        "talking_value": sum(r["quote_inr"] or 0 for r in talking),
    }
    return tpl.TemplateResponse(request, "deals.html", ctx(request, nav="deals", rows=rows, t=totals))


def inr(n) -> str:
    """Indian digit grouping: 125000 -> ₹1,25,000."""
    if n is None:
        return ""
    s = str(int(n))
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "₹" + ",".join(groups + [tail])


tpl.env.filters["inr"] = inr


# ---- Hide wrong-category leads -------------------------------------------------------------

@app.post("/leads/{lead_id}/hide")
def hide(lead_id: str, back: str = Form("")):
    con = db.connect()
    con.execute(
        "update leads set status = 'hidden', updated_at = ? where business_id = ? and status in ('new', 'drafted', 'approved', 'excluded')",
        (now(), lead_id),
    )
    con.commit()
    return RedirectResponse(local_path(back) or f"/leads/{lead_id}", status_code=303)


def local_path(url: str) -> str | None:
    """`url` if it stays on this dashboard. "//evil.in" and "/\\evil.in" are other sites to a browser."""
    if url.startswith("/") and not url.startswith(("//", "/\\")) and "\\" not in url:
        return url
    return None


@app.post("/leads/{lead_id}/unhide")
def unhide(lead_id: str):
    from leadscout.scoring import score_all

    con = db.connect()
    con.execute("update leads set status = 'new', updated_at = ? where business_id = ? and status = 'hidden'", (now(), lead_id))
    con.commit()
    score_all(con, config.load())  # back to new or excluded, on its merits
    return RedirectResponse(f"/leads/{lead_id}", status_code=303)
