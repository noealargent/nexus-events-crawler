#!/usr/bin/env python3
"""Merge matrix shard outputs into one <CC>.json per country plus summary.json.

Each shard owns the sites whose website host hashes to it (crawler/shard.py) and
shard 0 owns organisation sites. For every country, the events of a site are taken
from the shard that owns it: fresh when that shard read the site tonight, otherwise
last night's events (the shard was seeded with them).
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from shard import shard_of  # noqa: E402

COUNTRIES = ["FR", "GB", "CA", "CH", "DE", "BE", "AU", "BR", "CI", "CM", "CD", "SN", "BJ", "TG", "BF", "MG", "US"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards-dir", required=True, help="folder with one sub-folder per shard (work/ layout)")
    ap.add_argument("--shards", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--run-url", default="")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    shard_dirs = {}
    for summary_path in glob.glob(os.path.join(a.shards_dir, "*", "summary.json")):
        s = json.load(open(summary_path, encoding="utf-8"))
        shard_dirs[int(s["shard"])] = (os.path.dirname(summary_path), s)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    report = {"generatedAt": now, "runUrl": a.run_url, "shardsExpected": a.shards,
              "shardsReceived": sorted(shard_dirs), "countries": {}}
    for cc in COUNTRIES:
        sites = json.load(open(os.path.join(ROOT, "sites", f"{cc}.json"), encoding="utf-8"))
        owner = {rec["id"]: shard_of(rec.get("website") or rec["id"], a.shards) for rec in sites}
        events, seen = [], set()
        attempted = finished = refreshed = 0
        read_ok = set()
        status, stopped = {}, []
        seconds = 0.0
        for shard, (folder, summary) in sorted(shard_dirs.items()):
            info = (summary.get("countries") or {}).get(cc) or {}
            attempted += int(info.get("sitesAttempted") or 0)
            finished += int(info.get("sitesFinished") or 0)
            seconds = max(seconds, float(info.get("seconds") or 0))
            if info.get("stoppedEarly"):
                stopped.append(shard)
            for key, value in (info.get("status") or {}).items():
                status[key] = status.get(key, 0) + int(value)
            path = os.path.join(folder, "out", f"{cc}.json")
            if not os.path.exists(path):
                continue
            doc = json.load(open(path, encoding="utf-8"))
            for ev in doc.get("events") or []:
                cid = ev.get("churchId")
                mine = owner.get(cid, 0) == shard  # unknown ids (organisations) belong to shard 0
                if not mine or ev.get("id") in seen:
                    continue
                seen.add(ev.get("id"))
                events.append(ev)
            log = os.path.join(folder, "log", f"{cc}.json")
            if os.path.exists(log):
                for item in json.load(open(log, encoding="utf-8")):
                    if item.get("status") in ("ok", "not-modified"):
                        refreshed += 1
                    # Fresh read tonight by the owning shard: the site file's structured rows for it are replaced.
                    if item.get("status") == "ok" and owner.get(item.get("id"), 0) == shard:
                        read_ok.add(item.get("id"))
        events.sort(key=lambda e: (e.get("date") or "", e.get("start") or "", e.get("title") or "", e.get("id") or ""))
        missing = sorted(set(range(a.shards)) - set(shard_dirs))
        info = {"sites": len(sites), "sitesAttempted": attempted, "sitesFinished": finished,
                "sitesReadOk": refreshed, "events": len(events), "status": status,
                "shardsStoppedEarly": stopped, "shardsMissing": missing, "maxShardSeconds": seconds}
        report["countries"][cc] = info
        with open(os.path.join(a.out, f"{cc}.json"), "w", encoding="utf-8") as fh:
            json.dump({"updatedAt": now, "country": cc, "complete": not missing,
                       "siteIds": sorted(owner), "readIds": sorted(read_ok), "events": events}, fh, ensure_ascii=False, separators=(",", ":"))
            fh.write("\n")
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
