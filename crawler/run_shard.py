#!/usr/bin/env python3
"""Crawl one matrix shard of one time-zone group (or of every site without --group).

Each country runs import_events.py on this shard's sites, seeded with last night's
merged events (so 304 Not Modified pages keep their events) and writes:
  work/out/<CC>.json   importer document (events for every church, this shard's fresh)
  work/log/<CC>.json   per-site log
  work/summary.json    counts for this shard
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# US last: it is the largest list and takes whatever budget is left.
sys.path.insert(0, HERE)
from tzgroups import GROUPS, countries_of  # noqa: E402
from html_merge import run_html_shard  # noqa: E402
from collect import today_in_denver  # noqa: E402

ORDER = ["FR", "GB", "CA", "CH", "DE", "BE", "AU", "BR", "CI", "CM", "CD", "SN", "BJ", "TG", "BF", "MG", "US"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--shards", type=int, required=True)
    ap.add_argument("--previous", default=os.path.join(ROOT, "previous"), help="last night's merged <CC>.json files")
    ap.add_argument("--work", default=os.path.join(ROOT, "work"))
    ap.add_argument("--seconds", type=int, default=6000, help="total budget for this shard")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--group", default="", choices=[""] + list(GROUPS),
                    help="time-zone group (crawler/tzgroups.py): only its sites are read; empty = every site")
    ap.add_argument("--countries", default="", help="default: the group's countries, or all of them without --group")
    ap.add_argument("--limit", type=int, default=0, help="max sites per country in this shard (0 = all; for test runs)")
    ap.add_argument("--html-seconds", type=int, default=900, help="France only: budget for the html agenda pass after the structured read (0 = skip)")
    ap.add_argument("--http-cache", default=os.path.join(ROOT, "http-cache", "http-cache.json"))
    a = ap.parse_args()

    wanted = [c.strip() for c in a.countries.split(",") if c.strip()]
    if not wanted:
        wanted = [c for c in ORDER if not a.group or c in countries_of(a.group)]
    out_dir, log_dir = os.path.join(a.work, "out"), os.path.join(a.work, "log")
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)
    started = time.time()
    summary = {"shard": a.shard, "shards": a.shards, "group": a.group, "countries": {}}
    for cc in wanted:
        left = a.seconds - (time.time() - started)
        out, log = os.path.join(out_dir, f"{cc}.json"), os.path.join(log_dir, f"{cc}.json")
        prev = os.path.join(a.previous, f"{cc}.json")
        if os.path.exists(prev):
            shutil.copyfile(prev, out)
        if left < 30:
            summary["countries"][cc] = {"skipped": "no-time"}
            continue
        cmd = [
            sys.executable, os.path.join(HERE, "import_events.py"),
            "--countries", cc,
            "--shards", os.path.join(ROOT, "sites"),
            "--matrix-shard", str(a.shard), "--matrix-shards", str(a.shards),
            "--tz-group", a.group,
            "--limit", str(a.limit), "--workers", str(a.workers),
            "--coverage", "", "--hot-cap", "0", "--no-signal-days", "0",
            "--optout", os.path.join(ROOT, "sites", "optout.json"),
            # Organisation sites are read once, by shard 0.
            "--organisations", os.path.join(HERE, "organisation-sites.json") if a.shard == 0 else "",
            "--always-orgs" if a.shard == 0 else "--no-always-orgs",
            "--manual", "", "--store", "", "--public-manual", "", "--feeds", "",
            "--merge", "--out", out, "--log", log,
            "--seconds", str(int(left)),
            "--http-cache", a.http_cache,
        ]
        t0 = time.time()
        proc = subprocess.run(cmd)
        logs = json.load(open(log, encoding="utf-8")) if os.path.exists(log) else []
        html = None
        if cc == "FR" and a.html_seconds > 0:
            left_html = min(a.html_seconds, a.seconds - (time.time() - started))
            html = run_html_shard(
                out=out, log=log, html_log=os.path.join(log_dir, "FR-html.json"), sites_dir=os.path.join(ROOT, "sites"),
                organisations=os.path.join(HERE, "organisation-sites.json"), optout=os.path.join(ROOT, "sites", "optout.json"),
                today=today_in_denver(dt.datetime.now(dt.timezone.utc)),
                seconds=int(left_html), workers=a.workers, http_cache=a.http_cache, shard=a.shard, shards=a.shards)
        statuses = {}
        for item in logs:
            statuses[item.get("status")] = statuses.get(item.get("status"), 0) + 1
        doc = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else {}
        summary["countries"][cc] = {
            "exit": proc.returncode,
            "seconds": round(time.time() - t0, 1),
            "sitesAttempted": (doc.get("batch") or {}).get("sitesAttempted", 0),
            "sitesFinished": len(logs),
            "stoppedEarly": (doc.get("batch") or {}).get("stoppedEarly", False),
            "status": statuses,
        }
        if html is not None:
            summary["countries"][cc]["html"] = html
    summary["seconds"] = round(time.time() - started, 1)
    json.dump(summary, open(os.path.join(a.work, "summary.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
