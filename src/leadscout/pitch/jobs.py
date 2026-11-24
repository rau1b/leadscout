"""Pitch drafting: templates (offline) or Claude Code on your Pro plan (via data/pitch_jobs.json)."""

import json
import re

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


NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers(text: str) -> set[str]:
    """Every number in the text, with Indian or Western digit grouping removed ("1,25,000" -> "125000")."""
    out = set()
    for n in NUMBER_RE.findall(text or ""):
        n = n.replace(",", "").rstrip(".")
        out.add(n)
        if "." in n:
            out |= set(n.split("."))  # "7.8" also allows a bare "7" or "8" from the same fact
    return out


def unmeasured_numbers(con, cfg, business_id: str, pitch: dict) -> list[str]:
    """Numbers in a pitch that aren't in this lead's stored facts or the sender's details. Empty means it's clean."""
    # Only fields a pitch may quote. Ids, timestamps, coordinates and our internal score are left out,
    # or their digits would let invented figures like "20 years" through.
    row = con.execute(
        """select b.name, b.address, b.locality, b.area, b.city, b.website, b.phone, l.email,
                  a.final_url, a.perf_score, a.lcp_s, a.cls, a.tbt_ms, a.copyright_year, a.generator, a.status_code
           from businesses b join audits a on a.business_id = b.id join leads l on l.business_id = b.id where b.id = ?""",
        (business_id,),
    ).fetchone()
    if not row:
        return []
    known = json.dumps(dict(row), ensure_ascii=False, default=str)
    known += json.dumps({"sender": cfg.sender, "pitch": cfg.pitch}, ensure_ascii=False) + templates.OPT_OUT
    allowed = _numbers(known) | {"100", str(templates.GOOGLE_SITES_CLOSED)}  # "31/100" for a speed score
    for phone in (row["phone"], cfg.sender.get("phone")):
        digits = re.sub(r"\D", "", phone or "")
        if digits:
            allowed |= {digits, digits[-10:], "0" + digits[-10:]}  # +91 98480 12345, 9848012345, 09848012345
    written = " ".join(str(pitch.get(k) or "") for k in ("subject", "body", "whatsapp"))
    return sorted(_numbers(written) - allowed, key=lambda n: (len(n), n))


def rejected_path():
    return data_dir() / "pitch_results.rejected.json"


def import_results(con, cfg) -> tuple[int, list[dict]]:
    """Save Claude's pitches. A pitch citing a number we never measured is set aside in
    pitch_results.rejected.json with the numbers to fix, instead of being imported."""
    data = json.loads(results_path().read_text(encoding="utf-8"))
    known = {r["business_id"] for r in con.execute("select business_id from leads")}
    n, rejected = 0, []
    for item in data:
        if item.get("id") in known and item.get("subject") and item.get("body"):
            bad = unmeasured_numbers(con, cfg, item["id"], item)
            if bad:
                rejected.append({**item, "unmeasured_numbers": bad})
                continue
            save_pitch(con, item["id"], item, "claude")
            n += 1
    con.commit()
    if rejected:
        rejected_path().write_text(json.dumps(rejected, indent=2, ensure_ascii=False), encoding="utf-8")
    results_path().replace(results_path().with_suffix(".imported.json"))
    return n, rejected
