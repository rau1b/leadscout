"""Build src/leadscout/data/places_in.json.gz from the GeoNames dump (CC BY 4.0, https://www.geonames.org).

Usage (downloads go in their own folder):
    curl -O https://download.geonames.org/export/dump/cities500.zip   (unzip it)
    curl -O https://download.geonames.org/export/dump/admin1CodesASCII.txt
    curl -O https://download.geonames.org/export/dump/admin2Codes.txt
    python -I scripts/build_places.py <that folder> src/leadscout/data/places_in.json.gz
"""

import gzip
import json
import re
import sys
import unicodedata
from pathlib import Path

LATIN = re.compile(r"^[A-Za-z][A-Za-z .'\-()]*$")


def ascii_fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def main(src: Path, out: Path) -> None:
    states = {}
    for line in (src / "admin1CodesASCII.txt").read_text(encoding="utf-8").splitlines():
        code, name, *_ = line.split("\t")
        if code.startswith("IN."):
            states[code[3:]] = ascii_fold(name)
    districts = {}
    for line in (src / "admin2Codes.txt").read_text(encoding="utf-8").splitlines():
        code, name, *_ = line.split("\t")
        if code.startswith("IN."):
            districts[code[3:]] = ascii_fold(name)
    places = []
    with open(src / "cities500.txt", encoding="utf-8") as f:
        for line in f:
            c = line.rstrip("\n").split("\t")
            if c[8] != "IN" or not c[7].startswith("PPL"):
                continue
            name = c[2] or ascii_fold(c[1])  # GeoNames ascii name: "Hyderabad", not "Hyderābād"
            alts = set()
            for a in [c[2], *c[3].split(",")]:
                a = ascii_fold(a.strip())
                if a and LATIN.match(a) and a.lower() != name.lower() and len(a) <= 40:
                    alts.add(a)
            places.append({
                "n": name,
                "a": sorted(alts, key=str.lower)[:25],
                "s": states.get(c[10], ""),
                "d": districts.get(f"{c[10]}.{c[11]}", ""),
                "p": int(c[14] or 0),
                "lat": round(float(c[4]), 5),
                "lon": round(float(c[5]), 5),
            })
    places.sort(key=lambda p: -p["p"])
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump(places, f, separators=(",", ":"), ensure_ascii=False)
    print(f"{len(places)} places -> {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
