"""Google PageSpeed Insights (free). Mobile strategy = mid-range phone on slow 4G."""

import asyncio

import httpx

PSI = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


async def run(client: httpx.AsyncClient, url: str, api_key: str = "") -> dict:
    params = {"url": url, "strategy": "mobile", "category": "performance"}
    if api_key:
        params["key"] = api_key
    for attempt in range(3):
        try:
            resp = await client.get(PSI, params=params, timeout=120)
        except httpx.HTTPError as e:
            err = type(e).__name__
        else:
            if resp.status_code == 200:
                return parse(resp.json())
            err = f"HTTP {resp.status_code}"
            if resp.status_code not in (429, 500, 502, 503):
                break
        await asyncio.sleep(5 * (attempt + 1))
    return {"psi_error": err}


def parse(data: dict) -> dict:
    lh = data.get("lighthouseResult", {})
    audits = lh.get("audits", {})
    score = lh.get("categories", {}).get("performance", {}).get("score")

    def num(key):
        return audits.get(key, {}).get("numericValue")

    lcp = num("largest-contentful-paint")
    tbt = num("total-blocking-time")
    cls = num("cumulative-layout-shift")
    return {
        "perf_score": round(score * 100) if score is not None else None,
        "lcp_s": round(lcp / 1000, 1) if lcp is not None else None,
        "tbt_ms": round(tbt) if tbt is not None else None,
        "cls": round(cls, 3) if cls is not None else None,
        "psi_error": None,
    }
