#!/usr/bin/env python3
"""Build sites/<CC>.json from the Nexus directory shards (public/osm/c/*.json).

Keeps only church records that have a website, are not hidden, pass the importer's
evangelical policy and are not opted out. Only the fields the importer needs to
label an event are written (id, slug, name, website, cc, region, city, lat, lng);
all of them are already published on nexuschurches.com.

Usage: python3 crawler/build_sites.py /path/to/public/osm/c
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from import_events import listed_churches, policy_skip  # noqa: E402
from collect import record_opted_out  # noqa: E402

COUNTRIES = ["FR", "US", "GB", "CA", "CH",
             # World wave 1 (Nov 2026)
             "DE", "BE", "AU", "BR", "CI", "CM", "CD", "SN", "BJ", "TG", "BF", "MG"]
FIELDS = ("id", "slug", "name", "website", "cc", "region", "city", "lat", "lng")
ROOT = os.path.dirname(HERE)


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "..", "public", "osm", "c")
    optout = json.load(open(os.path.join(ROOT, "sites", "optout.json"), encoding="utf-8"))
    out_ids = set(optout.get("churchIds", [])) | set(optout.get("slugs", []))
    out_hosts = {h.lower().removeprefix("www.") for h in optout.get("hosts", [])}
    by_cc = {cc: [] for cc in COUNTRIES}
    skipped = {}
    for rec in listed_churches(src, set(COUNTRIES)):
        website = (rec.get("website") or "").strip()
        if not website:
            continue
        if "@" in website.split("//", 1)[-1].split("/", 1)[0] or "." not in website:
            skipped["not-a-website"] = skipped.get("not-a-website", 0) + 1   # e-mail typed as a website
            continue
        why = policy_skip(rec) or ("optout" if record_opted_out(rec, out_ids, out_hosts) else None)
        if why:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        by_cc[rec["cc"]].append({k: rec[k] for k in FIELDS if rec.get(k) not in (None, "")})
    for cc, rows in by_cc.items():
        rows.sort(key=lambda r: r["id"])
        with open(os.path.join(ROOT, "sites", f"{cc}.json"), "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, separators=(",", ":"))
            fh.write("\n")
    print(json.dumps({"sites": {cc: len(r) for cc, r in by_cc.items()}, "total": sum(map(len, by_cc.values())), "skipped": skipped}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
