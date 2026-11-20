"""France HTML agenda step for one matrix shard (moved here from the private site repo's nightly_refresh.py,
so every French site is read every night on the free public runners, not a rolling slice of them).

After the structured read of FR, the sites that were read fine but showed no structured events (JSON-LD, ICS,
Tribe, Google Calendar, feeds) are read again by html_agenda.py, which keeps dated lines of the church's own agenda
page (confidence >= 70). Those rows (source "html") are merged into the shard's FR.json; the churches whose agenda
page was read fine are listed in log/FR-html.json, so the site merge can replace their previous html rows.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from collect import still_current

HERE = os.path.dirname(os.path.abspath(__file__))
STRUCTURED_SOURCES = {"jsonld", "ics", "tribe", "gcal"}


def is_structured_source(value: str) -> bool:
    source = (value or "").strip().lower()
    return source in STRUCTURED_SOURCES or source.startswith("feed-")


def event_key(event: dict) -> tuple[str, str, str, str]:
    title = " ".join((event.get("title") or "").strip().lower().split())
    return (str(event.get("churchId") or ""), str(event.get("date") or ""), title, str(event.get("start") or ""))


def html_candidates(logs: list) -> list[str]:
    """Church ids read fine by the structured pass that had no structured events."""
    ids, seen = [], set()
    for log in logs:
        if not isinstance(log, dict) or not log.get("id") or log["id"] in seen:
            continue
        if str(log.get("status") or "") != "ok":
            continue
        if any(is_structured_source(str(item)) for item in (log.get("sources") or [])):
            continue
        seen.add(log["id"])
        ids.append(log["id"])
    return ids


def merge_html_events(doc: dict, html_doc: dict, recrawled: set[str], today: str) -> int:
    """Add html rows to the shard's FR document, keeping structured rows. Previous html rows of churches whose
    agenda page was just read fine are replaced. Returns the number of rows added."""
    incoming = [e for e in html_doc.get("events") or [] if isinstance(e, dict) and e.get("id") and still_current(e, today)]
    kept, seen_ids, seen_keys = [], set(), set()
    for event in doc.get("events") or []:
        if not isinstance(event, dict) or not event.get("id") or not still_current(event, today):
            continue
        if event.get("source") == "html" and event.get("churchId") in recrawled:
            continue
        kept.append(event)
        seen_ids.add(event["id"])
        seen_keys.add(event_key(event))
    added = 0
    for event in incoming:
        if event["id"] in seen_ids or event_key(event) in seen_keys:
            continue
        kept.append(event)
        seen_ids.add(event["id"])
        seen_keys.add(event_key(event))
        added += 1
    kept.sort(key=lambda e: (e.get("date") or "", e.get("city") or "", e.get("title") or "", e.get("start") or "", e.get("id") or ""))
    doc["events"] = kept
    return added


def run_html_shard(*, out: str, log: str, html_log: str, sites_dir: str, organisations: str, optout: str, today: str,
                   seconds: int, workers: int, http_cache: str, shard: int, shards: int) -> dict:
    """Read the html agenda pages of this shard's candidate sites and merge them into `out` (the shard's FR.json)."""
    if seconds < 30 or not os.path.exists(log):
        return {"skipped": "no-time" if seconds < 30 else "no-log"}
    logs = json.load(open(log, encoding="utf-8"))
    logs = logs.get("logs") if isinstance(logs, dict) else logs
    ids = html_candidates(logs or [])
    if not ids:
        return {"candidates": 0}
    work = os.path.dirname(out)
    only_file, html_out = os.path.join(work, f"html-ids-{shard}.json"), os.path.join(work, f"html-FR-{shard}.json")
    raw_log = os.path.join(work, f"html-raw-log-{shard}.json")
    json.dump(ids, open(only_file, "w", encoding="utf-8"))
    cmd = [
        sys.executable, os.path.join(HERE, "html_agenda.py"),
        "--only-file", only_file, "--publish", "--min-score", "70",
        "--shards", sites_dir, "--organisations", organisations, "--optout", optout,
        "--dedupe-with", out, "--out", html_out, "--log", raw_log, "--today", today,
        "--workers", str(workers), "--seconds", str(int(seconds)),
    ]
    if http_cache:
        cmd += ["--http-cache", http_cache + ".html"]
    proc = subprocess.run(cmd, env={**os.environ, "NEXUS_EVENTS_ALLOW_HTTP": "1"})
    if proc.returncode != 0 or not os.path.exists(html_out):
        return {"candidates": len(ids), "ok": False, "error": f"html_agenda.py exited {proc.returncode}"}
    raw = json.load(open(raw_log, encoding="utf-8")) if os.path.exists(raw_log) else []
    raw = raw.get("logs") if isinstance(raw, dict) else raw
    recrawled = {item["id"] for item in raw or [] if isinstance(item, dict) and item.get("id") and item.get("status") in ("ok", "html-ok")}
    doc = json.load(open(out, encoding="utf-8"))
    added = merge_html_events(doc, json.load(open(html_out, encoding="utf-8")), recrawled, today)
    json.dump(doc, open(out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump([{"id": i, "status": "ok"} for i in sorted(recrawled)], open(html_log, "w", encoding="utf-8"))
    return {"candidates": len(ids), "ok": True, "recrawled": len(recrawled), "added": added}
