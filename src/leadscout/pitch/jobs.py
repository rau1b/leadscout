"""Pitch drafting: templates (offline) or Claude Code on your Pro plan (via data/pitch_jobs.json)."""

import json

from leadscout.config import data_dir
from leadscout.db import jload, now
from leadscout.pitch import templates

FACTS_SQL = """
select b.id, b.name, b.category, b.locality, b.area, b.city, b.website, b.phone, b.phone_type,
       a.site_class, a.perf_score, a.lcp_s, a.https, a.viewport, a.copyright_year,
       a.has_whatsapp, a.has_tel, a.fetch_error, l.score, l.reasons, l.email
from leads l join businesses b on b.id = l.business_id join audits a on a.business_id = b.id
where l.status = 'new' and l.score >= ?
order by (l.email is null), l.score desc
limit ?
"""


def pending_facts(con, min_score: int, limit: int) -> list[dict]:
    rows = con.execute(FACTS_SQL, (min_score, limit)).fetchall()
    out = []
    for r in rows:
        f = dict(r)
        f["reasons"] = jload(f["reasons"])
        out.append(f)
    return out


def save_pitch(con, business_id: str, pitch: dict, source: str) -> None:
    con.execute(
        """insert into pitches (business_id, subject, body, whatsapp, source, approved, created_at, updated_at)
           values (?, ?, ?, ?, ?, 0, ?, ?)
           on conflict(business_id) do update set subject = excluded.subject, body = excluded.body,
               whatsapp = excluded.whatsapp, source = excluded.source, approved = 0, updated_at = excluded.updated_at""",
        (business_id, pitch["subject"], pitch["body"], pitch.get("whatsapp"), source, now(), now()),
    )
    con.execute("update leads set status = 'drafted', updated_at = ? where business_id = ?", (now(), business_id))


def draft_with_templates(con, cfg, limit: int) -> int:
    facts = pending_facts(con, cfg.scoring["min_score"], limit)
    for f in facts:
        save_pitch(con, f["id"], templates.render(f, cfg), "template")
    con.commit()
    return len(facts)


def jobs_path():
    return data_dir() / "pitch_jobs.json"


def results_path():
    return data_dir() / "pitch_results.json"


def prepare_jobs(con, cfg, limit: int) -> int:
    """Write the facts Claude Code needs; the /pitch-today command reads this file."""
    facts = pending_facts(con, cfg.scoring["min_score"], limit)
    payload = {
        "sender": cfg.sender,
        "offer": cfg.pitch["offer"],
        "pitch_line": cfg.pitch["pitch_line"],
        "opt_out_line": templates.OPT_OUT,
        "leads": [{**f, "template_draft": templates.render(f, cfg)} for f in facts],
    }
    jobs_path().write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return len(facts)


def import_results(con) -> int:
    data = json.loads(results_path().read_text(encoding="utf-8"))
    known = {r["business_id"] for r in con.execute("select business_id from leads")}
    n = 0
    for item in data:
        if item.get("id") in known and item.get("subject") and item.get("body"):
            save_pitch(con, item["id"], item, "claude")
            n += 1
    con.commit()
    results_path().replace(results_path().with_suffix(".imported.json"))
    return n
