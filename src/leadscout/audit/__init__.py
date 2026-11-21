"""Audit runner: classify every unaudited business, fetch real sites, run PageSpeed."""

import asyncio
import json

import httpx

from leadscout.audit import pagespeed
from leadscout.audit.classify import classify_static
from leadscout.audit.site import UA, audit_site
from leadscout.db import now

FIELDS = (
    "site_class", "final_url", "status_code", "https", "viewport", "copyright_year", "generator",
    "has_whatsapp", "has_tel", "has_maps", "has_form", "found_emails", "perf_score", "lcp_s",
    "cls", "tbt_ms", "psi_error", "fetch_error",
)


def save(con, business_id: str, result: dict) -> None:
    row = {f: result.get(f) for f in FIELDS}
    row["found_emails"] = json.dumps(sorted(result.get("found_emails") or []))
    row["business_id"] = business_id
    row["audited_at"] = now()
    cols = ", ".join(row)
    marks = ", ".join(f":{k}" for k in row)
    updates = ", ".join(f"{k} = excluded.{k}" for k in row if k != "business_id")
    con.execute(f"insert into audits ({cols}) values ({marks}) on conflict(business_id) do update set {updates}", row)


async def _audit_all(con, rows, api_key: str, run_psi: bool, progress) -> None:
    site_sem, psi_sem = asyncio.Semaphore(10), asyncio.Semaphore(4)
    headers = {"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=20) as client:

        async def one(r):
            static = classify_static(r["website"])
            if static:
                result = {"site_class": static}
            else:
                async with site_sem:
                    result = await audit_site(client, r["website"])
                if run_psi and result["site_class"] == "real":
                    async with psi_sem:
                        result.update(await pagespeed.run(client, result["final_url"], api_key))
            save(con, r["id"], result)
            con.commit()
            progress(r["name"], result["site_class"])

        await asyncio.gather(*(one(r) for r in rows))


async def _psi_retry(con, rows, api_key: str, progress) -> None:
    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient() as client:

        async def one(r):
            async with sem:
                res = await pagespeed.run(client, r["final_url"], api_key)
            sets = ", ".join(f"{k} = :{k}" for k in res)
            con.execute(f"update audits set {sets} where business_id = :id", {**res, "id": r["business_id"]})
            con.commit()
            progress(r["final_url"], f"score {res.get('perf_score')}" if not res.get("psi_error") else res["psi_error"])

        await asyncio.gather(*(one(r) for r in rows))


def retry_pagespeed(con, api_key: str = "", progress=lambda *a: None) -> int:
    """Re-run PageSpeed for working sites that have no score yet (e.g. after adding an API key)."""
    rows = con.execute(
        "select business_id, final_url from audits where site_class = 'real' and perf_score is null and final_url is not null"
    ).fetchall()
    asyncio.run(_psi_retry(con, rows, api_key, progress))
    return len(rows)


def audit_pending(con, api_key: str = "", run_psi: bool = True, limit: int | None = None, progress=lambda *a: None) -> int:
    sql = "select id, name, website from businesses where id not in (select business_id from audits)"
    rows = con.execute(sql + (f" limit {int(limit)}" if limit else "")).fetchall()
    asyncio.run(_audit_all(con, rows, api_key, run_psi, progress))
    return len(rows)
