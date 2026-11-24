"""Careful sending: warm-up caps, IST sending window, random gaps, follow-ups, reply and bounce checks."""

import random
import time
from datetime import date, datetime, timedelta

from leadscout.compliance import in_window, is_suppressed, opt_out, suppress
from leadscout.config import IST
from leadscout.db import get_meta, now, set_meta
from leadscout.pitch import templates


def today_ist() -> date:
    return datetime.now(IST).date()


def daily_cap(con, cfg) -> int:
    warmup = cfg.sending["warmup"]
    first = get_meta(con, "first_send_date")
    if not first:
        return warmup[0]
    week = (today_ist() - date.fromisoformat(first)).days // 7
    return warmup[min(week, len(warmup) - 1)]


def sent_today(con) -> int:
    return con.execute(
        "select count(*) from outreach where channel = 'email' and kind != 'reply' and substr(sent_at, 1, 10) = ?",
        (today_ist().isoformat(),),
    ).fetchone()[0]


def bounce_rate(con, window: int = 40) -> float:
    rows = con.execute(
        """select l.status from outreach o join leads l on l.business_id = o.business_id
           where o.channel = 'email' and o.kind = 'first' order by o.id desc limit ?""",
        (window,),
    ).fetchall()
    if len(rows) < 10:
        return 0.0
    return sum(r["status"] == "bounced" for r in rows) / len(rows)


def next_item(con, cfg) -> dict | None:
    """A due follow-up first, else the best approved first email.

    Items with a send claim are skipped: either another sender has them, or a send crashed after Gmail took it
    and before it was recorded. Never risk sending twice; such a lead just waits for a human to look.
    """
    cutoff = (datetime.now(IST) - timedelta(days=cfg.sending["followup_after_days"])).isoformat(timespec="seconds")
    row = con.execute(
        """select l.business_id, l.email, b.name, b.phone, p.subject, o.gmail_id, o.thread_id
           from leads l join businesses b on b.id = l.business_id join pitches p on p.business_id = l.business_id
           join outreach o on o.id = (select max(id) from outreach where business_id = l.business_id and channel = 'email')
           where l.status = 'contacted' and o.sent_at < ?
             and (select count(*) from outreach where business_id = l.business_id and kind = 'followup') < ?
             and not exists (select 1 from meta where key = 'sending:' || l.business_id || ':followup:'
                             || (select count(*) from outreach where business_id = l.business_id and kind = 'followup'))
           order by o.sent_at limit 1""",
        (cutoff, cfg.sending["max_followups"]),
    ).fetchone()
    if row:
        return {**dict(row), "kind": "followup"}
    row = con.execute(
        """select l.business_id, l.email, b.name, b.phone, p.subject, p.body
           from leads l join businesses b on b.id = l.business_id join pitches p on p.business_id = l.business_id
           where l.status = 'approved' and p.approved = 1 and l.email is not null
             and not exists (select 1 from meta where key = 'sending:' || l.business_id || ':first:0')
           order by l.score desc limit 1"""
    ).fetchone()
    return {**dict(row), "kind": "first"} if row else None


def send_one(con, cfg, gmail, item: dict, dry_run: bool = False) -> str:
    if is_suppressed(con, item["email"], item.get("phone")):
        con.execute("update leads set status = 'opted_out', updated_at = ? where business_id = ?", (now(), item["business_id"]))
        con.commit()
        return f"skipped {item['name']} (opted out)"
    s = cfg.sender
    sender = f"{s.get('name') or s['business']} <{s['email']}>"
    if dry_run:
        what = f"follow-up to {item['email']}: {templates.followup(item, cfg)[0]}" if item["kind"] == "followup" else f"to {item['email']}: {item['subject']}"
        return f"[dry run] {what}"
    # Claim this email first, so two senders running at once can't both send it. Kept after sending as a record.
    n_followups = con.execute("select count(*) from outreach where business_id = ? and kind = 'followup'", (item["business_id"],)).fetchone()[0]
    claim = f"sending:{item['business_id']}:{item['kind']}:{n_followups}"
    if not con.execute("insert or ignore into meta (key, value) values (?, ?)", (claim, now())).rowcount:
        con.commit()
        return f"skipped {item['name']} (already being sent)"
    con.commit()
    try:
        if item["kind"] == "followup":
            subject, body = templates.followup(item, cfg)
            ref = gmail.message_id_header(item["gmail_id"])
            res = gmail.send(item["email"], subject, body, sender, thread_id=item["thread_id"], in_reply_to=ref, unsubscribe=s["email"])
        else:
            res = gmail.send(item["email"], item["subject"], item["body"], sender, unsubscribe=s["email"])
    except Exception:
        con.execute("delete from meta where key = ?", (claim,))  # not sent: free it for the next try
        con.commit()
        raise
    if item["kind"] == "first":
        con.execute("update leads set status = 'contacted', updated_at = ? where business_id = ?", (now(), item["business_id"]))
    con.execute(
        "insert into outreach (business_id, channel, kind, to_addr, gmail_id, thread_id, sent_at) values (?, 'email', ?, ?, ?, ?, ?)",
        (item["business_id"], item["kind"], item["email"], res["id"], res["threadId"], now()),
    )
    if not get_meta(con, "first_send_date"):
        set_meta(con, "first_send_date", today_ist().isoformat())
    con.commit()
    return f"sent {item['kind']} to {item['name']} <{item['email']}>"


def check_replies(con, cfg, gmail) -> dict:
    """Save new replies and update lead status. Ongoing conversations are checked too, so later replies show up."""
    counts = {"replied": 0, "opted_out": 0, "bounced": 0}
    rows = con.execute(
        """select l.business_id, l.email, l.status, o.thread_id, b.phone from leads l
           join businesses b on b.id = l.business_id
           join outreach o on o.id = (select max(id) from outreach where business_id = l.business_id and channel = 'email')
           where l.status in ('contacted', 'replied', 'won')"""
    ).fetchall()
    for r in rows:
        for m in gmail.incoming(r["thread_id"], cfg.sender["email"]):
            received = datetime.fromtimestamp(m["received_ms"] / 1000, IST).isoformat(timespec="seconds")
            cur = con.execute(
                "insert or ignore into replies (gmail_id, business_id, thread_id, from_addr, subject, body, received_at, kind) values (?, ?, ?, ?, ?, ?, ?, ?)",
                (m["id"], r["business_id"], r["thread_id"], m["from"], m["subject"], m["body"], received, m["kind"]),
            )
            if not cur.rowcount:
                continue  # already saved
            counts[m["kind"]] += 1
            # A first answer moves the lead on; a later "no" always wins.
            if m["kind"] in ("opted_out", "bounced") or r["status"] == "contacted":
                con.execute("update leads set status = ?, updated_at = ? where business_id = ?", (m["kind"], now(), r["business_id"]))
            if m["kind"] in ("opted_out", "bounced"):
                suppress(con, r["email"], m["kind"])
            if m["kind"] == "opted_out" and r["phone"]:
                suppress(con, r["phone"], "opted_out")  # a "no" covers WhatsApp too; a bounce is only about the address
    # The List-Unsubscribe button sends a fresh email, not a reply in the thread.
    for addr in getattr(gmail, "unsubscribe_requests", lambda _me: set())(cfg.sender["email"]):
        if not is_suppressed(con, addr):
            opt_out(con, addr, "unsubscribe button")
            counts["opted_out"] += 1
    con.commit()
    return counts


def send_reply(con, cfg, gmail, business_id: str, body: str) -> None:
    """Answer a lead's reply inside the same Gmail thread."""
    r = con.execute(
        """select l.email, rp.gmail_id, rp.thread_id, rp.subject from leads l
           join replies rp on rp.gmail_id = (select gmail_id from replies where business_id = l.business_id order by received_at desc limit 1)
           where l.business_id = ?""",
        (business_id,),
    ).fetchone()
    if not r:
        raise ValueError("No reply from this business to answer yet.")
    if is_suppressed(con, r["email"]):
        raise ValueError("This business opted out. LeadScout won't email them.")
    s = cfg.sender
    subject = r["subject"] if r["subject"].lower().startswith("re:") else f"Re: {r['subject']}"
    ref = gmail.message_id_header(r["gmail_id"])
    res = gmail.send(r["email"], subject, body, f"{s.get('name') or s['business']} <{s['email']}>", thread_id=r["thread_id"], in_reply_to=ref)
    con.execute(
        "insert into outreach (business_id, channel, kind, to_addr, gmail_id, thread_id, sent_at) values (?, 'email', 'reply', ?, ?, ?, ?)",
        (business_id, r["email"], res["id"], res["threadId"], now()),
    )
    con.commit()


def run(con, cfg, gmail, dry_run: bool = False, once: bool = False, log=print, stop=None) -> None:
    """Send until the cap, the window, the bounce limit or the queue stops it. `stop` (a threading.Event) ends it early."""
    sc = cfg.sending
    while True:
        if stop is not None and stop.is_set():
            log("Stopped.")
            return
        if not dry_run and not in_window(sc):
            log(f"Outside the sending window ({sc['window_start']}-{sc['window_end']} IST, {', '.join(sc['days'])}). Stopping.")
            return
        if not dry_run:
            replies = check_replies(con, cfg, gmail)
            if any(replies.values()):
                log(f"Inbox: {replies}")
        rate = bounce_rate(con)
        if rate > sc["max_bounce_rate"]:
            log(f"Paused: {rate:.0%} of recent emails bounced (limit {sc['max_bounce_rate']:.0%}). Check your lead emails before sending more.")
            return
        cap = daily_cap(con, cfg)
        done = sent_today(con)
        if done >= cap:
            log(f"Daily cap reached: {done}/{cap} (warm-up schedule {sc['warmup']}).")
            return
        item = next_item(con, cfg)
        if not item:
            log("Nothing left to send. Approve more pitches in the dashboard.")
            return
        log(f"[{done + 1}/{cap}] " + send_one(con, cfg, gmail, item, dry_run))
        if once or dry_run:
            return
        gap = random.randint(sc["min_gap_seconds"], sc["max_gap_seconds"])
        log(f"Next email in {gap // 60}m {gap % 60}s...")
        if stop is not None:
            if stop.wait(gap):
                log("Stopped.")
                return
        else:
            time.sleep(gap)
