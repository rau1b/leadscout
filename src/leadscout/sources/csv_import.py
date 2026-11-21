"""Import businesses you collected yourself (e.g. noted from Google Maps while browsing).

CSV columns (header row required): name, phone, website, email, category, address, locality, city
Only `name` is required.
"""

import csv
import hashlib

from leadscout.sources.common import upsert_business


def ingest(con, path: str, area_label: str) -> int:
    count = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            if not row.get("name"):
                continue
            key = f"{row['name'].lower()}|{row.get('phone', '')}|{row.get('locality', '')}"
            upsert_business(
                con,
                {
                    "id": "csv:" + hashlib.sha1(key.encode()).hexdigest()[:16],
                    "source": "csv",
                    "name": row["name"],
                    "category": row.get("category") or None,
                    "address": row.get("address") or None,
                    "locality": row.get("locality") or None,
                    "phone": row.get("phone") or None,
                    "website": row.get("website") or None,
                    "emails": [row["email"]] if row.get("email") else [],
                    "confidence": 1.0,
                    "area": area_label,
                    "city": row.get("city") or None,
                },
            )
            count += 1
    con.commit()
    return count
