#!/usr/bin/env python3
"""Merge the public nightly crawl (release asset) into the Nexus site event files.

Run from the private site repo:
  python3 merge_into_site.py --crawl <dir with FR.json…summary.json> --site public/events \
      --summary docs/events-archive/public-crawl.json

For every church the crawl read successfully (readIds), structured events (jsonld, ics,
tribe, gcal, feed-*) in the site file are replaced by the crawl's events. Other
rows are kept: churches not in the crawl, HTML-agenda rows, manual rows. A
country is skipped (site file untouched) when the crawl is older than --max-age-hours,
incomplete, or would shrink that country's current events by more than --max-shrink.

Time-zone groups: a release such as "nightly-na-e" carries one group (summary.json "group").
Its crawl owns only that group's churches and organisations (siteIds, orgIds): the shrink
guard counts only those, other groups' events in the same country file are untouched, and
the last merge of every group is kept in the one --summary file ("groups"), so a group is
never merged twice and never blocks another group. Run the script once per group release.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from zoneinfo import ZoneInfo

FILES = {"FR": "index.json", "US": "us.json", "GB": "gb.json", "CA": "ca.json", "CH": "ch.json",
         # World wave 1 (Nov 2026): the site file is created on the first merge when it does not exist yet.
         **{cc: f"{cc.lower()}.json" for cc in ("DE", "BE", "AU", "BR", "CI", "CM", "CD", "SN", "BJ", "TG", "BF", "MG")}}
NEW_COUNTRIES = {"DE", "BE", "AU", "BR", "CI", "CM", "CD", "SN", "BJ", "TG", "BF", "MG"}
STRUCTURED = {"jsonld", "ics", "tribe", "gcal"}


def structured(source: str) -> bool:
    s = (source or "").strip().lower()
    return s in STRUCTURED or s.startswith("feed-")


def last_day(ev: dict) -> str:
    return ev.get("endDate") or ev.get("date") or ""


def key(ev: dict) -> tuple:
    title = " ".join((ev.get("title") or "").strip().lower().split())
    return (str(ev.get("churchId") or ""), ev.get("date") or "", title, ev.get("start") or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crawl", required=True)
    ap.add_argument("--site", required=True)
    ap.add_argument("--summary", default="")
    ap.add_argument("--max-age-hours", type=float, default=30)
    ap.add_argument("--max-shrink", type=float, default=0.30)
    a = ap.parse_args()
    today = dt.datetime.now(ZoneInfo("America/Denver")).date().isoformat()
    now = dt.datetime.now(dt.timezone.utc)
    report = {"mergedAt": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"), "countries": {}}
    try:
        report["crawl"] = json.load(open(os.path.join(a.crawl, "summary.json"), encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report["crawl"] = {}
    previous_merge = {}
    if a.summary and os.path.exists(a.summary):
        try:
            previous_merge = json.load(open(a.summary, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_merge = {}
    group = (report.get("crawl") or {}).get("group") or ""
    stamp = (report.get("crawl") or {}).get("generatedAt")
    # Per time-zone group: each group's release is merged once, independently of the others.
    # Older summaries (one global crawl) keep their single "crawl" stamp.
    groups_done = dict(previous_merge.get("groups") or {})
    if group:
        last = (groups_done.get(group) or {}).get("generatedAt")
    else:
        previous_crawl = previous_merge.get("crawl") or {}
        last = None if previous_crawl.get("group") else previous_crawl.get("generatedAt")
    if stamp and stamp == last:
        print(json.dumps({"skipped": "already-merged", "group": group, "crawl": stamp}))
        return 0
    for cc, name in FILES.items():
        crawl_path, site_path = os.path.join(a.crawl, f"{cc}.json"), os.path.join(a.site, name)
        if cc in NEW_COUNTRIES and os.path.exists(crawl_path) and not os.path.exists(site_path) and os.path.isdir(a.site):
            with open(site_path, "w", encoding="utf-8") as fh:
                json.dump({"updatedAt": "", "horizonDays": 60, "counts": {"total": 0}, "events": []}, fh, ensure_ascii=False, indent=1)
                fh.write("\n")
        if not os.path.exists(crawl_path) or not os.path.exists(site_path):
            report["countries"][cc] = {"skipped": "missing-file"}
            continue
        crawl = json.load(open(crawl_path, encoding="utf-8"))
        site = json.load(open(site_path, encoding="utf-8"))
        try:
            age = (now - dt.datetime.fromisoformat(crawl["updatedAt"].replace("Z", "+00:00"))).total_seconds() / 3600
        except (KeyError, ValueError):
            age = 1e9
        if age > a.max_age_hours:
            report["countries"][cc] = {"skipped": f"stale ({age:.0f} h)"}
            continue
        if not crawl.get("complete", False):
            report["countries"][cc] = {"skipped": "incomplete-crawl"}
            continue
        # Only churches read successfully tonight replace the site's structured rows; for the
        # rest (errors, timeouts, not reached) the site keeps its rows and gains the crawl's.
        covered = set(crawl.get("readIds") or [])
        covered_html = set(crawl.get("htmlReadIds") or [])  # France: html agenda page read fine tonight
        before = [e for e in site.get("events") or [] if isinstance(e, dict)]
        # A group crawl owns only its own churches and organisations: the shrink guard compares those,
        # and every other group's events in the same country file are left alone.
        scope = set(crawl.get("siteIds") or []) | set(crawl.get("orgIds") or []) if group else None
        before_current = sum(1 for e in before if last_day(e) >= today and (scope is None or e.get("churchId") in scope))
        kept = [e for e in before if last_day(e) >= today and not (e.get("churchId") in covered and structured(e.get("source")))
                and not (e.get("churchId") in covered_html and e.get("source") == "html")]
        incoming = [e for e in crawl.get("events") or [] if isinstance(e, dict) and last_day(e) >= today]
        incoming_ids = {e.get("id") for e in incoming}
        merged, ids, keys = [], set(), set()
        for e in incoming + kept:
            if e.get("id") in ids or key(e) in keys:
                continue
            ids.add(e.get("id"))
            keys.add(key(e))
            merged.append(e)
        after_current = len(merged) if scope is None else sum(1 for e in merged if e.get("churchId") in scope)
        if before_current and after_current < before_current * (1 - a.max_shrink):
            report["countries"][cc] = {"skipped": f"shrink {before_current} -> {after_current}"}
            continue
        merged.sort(key=lambda e: (e.get("date") or "", e.get("city") or "", e.get("title") or "", e.get("start") or "", e.get("id") or ""))
        site["events"] = merged
        # The file's stamp is the freshest group; each group's own stamp is kept for the site's
        # "last updated" line (a church shows the stamp of its own time-zone group).
        site["updatedAt"] = max(crawl["updatedAt"], site.get("updatedAt") or "") if group else crawl["updatedAt"]
        public = dict(site.get("publicCrawl") or {}) if group else {}
        public["updatedAt"] = site["updatedAt"]
        public["sites"] = len(crawl.get("siteIds") or [])
        public["events"] = len(incoming)
        if group:
            groups = dict(public.get("groups") or {})
            groups[group] = {"updatedAt": crawl["updatedAt"], "sites": len(crawl.get("siteIds") or []), "events": len(incoming)}
            public["groups"] = groups
        site["publicCrawl"] = public
        counts = dict(site.get("counts") or {})
        counts["total"] = len(merged)
        site["counts"] = counts
        with open(site_path, "w", encoding="utf-8") as fh:
            json.dump(site, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        report["countries"][cc] = {"before": before_current, "after": after_current, "fromCrawl": len(incoming),
                                   "keptOther": sum(1 for e in merged if e.get("id") not in incoming_ids)}
    if group:
        # Keep every group's last merge in one summary file: a run only rewrites its own group.
        groups_done[group] = {"generatedAt": stamp, "mergedAt": report["mergedAt"], "countries": report["countries"]}
        report["groups"] = groups_done
        report["group"] = group
        # A group run's report names the crawl it merged; the other groups stay under "groups".
    text = json.dumps(report, ensure_ascii=False, indent=1)
    print(text)
    if a.summary:
        os.makedirs(os.path.dirname(a.summary) or ".", exist_ok=True)
        open(a.summary, "w", encoding="utf-8").write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
