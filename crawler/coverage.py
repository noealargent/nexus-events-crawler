#!/usr/bin/env python3
"""Rolling nightly coverage: organisation sites every run, church sites by persistent cursor.

The church website list is too large for one GitHub Actions job on a private
repository's monthly minutes, so each run takes a slice:

  1. every organisation site (always),
  2. a small rotating refresh of sites already known to have an events page or feed,
  3. the next churches in a stable queue, skipping those that had no events signal
     on a recent successful crawl (default 14 days).

A coverage file (docs/events-archive/coverage.json) stores the cursors and the
per-site signal memory so the next run continues where this one stopped.
"""
from __future__ import annotations

import datetime as dt
import json
import os

NO_SIGNAL_DAYS = 14
HOT_CAP = 60


def empty_coverage() -> dict:
    return {
        "updatedAt": "",
        "timezone": "America/Denver",
        "noSignalDays": NO_SIGNAL_DAYS,
        "countries": {},
        "noSignal": {},
        "hasSignal": {},
    }


def load_coverage(path: str) -> dict:
    if not path or not os.path.exists(path):
        return empty_coverage()
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return empty_coverage()
    if not isinstance(data, dict):
        return empty_coverage()
    data.setdefault("timezone", "America/Denver")
    data.setdefault("noSignalDays", NO_SIGNAL_DAYS)
    data.setdefault("countries", {})
    data.setdefault("noSignal", {})
    data.setdefault("hasSignal", {})
    if not isinstance(data["countries"], dict):
        data["countries"] = {}
    if not isinstance(data["noSignal"], dict):
        data["noSignal"] = {}
    if not isinstance(data["hasSignal"], dict):
        data["hasSignal"] = {}
    return data


def save_coverage(path: str, data: dict) -> None:
    if not path:
        return
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def in_no_signal_cooldown(coverage: dict, site_id: str, today: str, days: int) -> bool:
    raw = (coverage.get("noSignal") or {}).get(site_id)
    if not raw or days <= 0:
        return False
    try:
        seen = dt.date.fromisoformat(str(raw)[:10])
        now = dt.date.fromisoformat(today)
    except ValueError:
        return False
    return (now - seen).days < days


def signal_ids(coverage: dict, previous_events=None) -> set[str]:
    ids = {str(key) for key in (coverage.get("hasSignal") or {}) if key}
    for event in previous_events or []:
        if isinstance(event, dict) and event.get("churchId"):
            ids.add(str(event["churchId"]))
    return ids


def log_has_signal(log: dict) -> bool:
    if not isinstance(log, dict):
        return False
    if log.get("hasSignal"):
        return True
    if log.get("agenda"):
        return True
    sources = log.get("sources") or []
    return bool(sources)


def shard_list(rows: list, shard: int, shards: int) -> list:
    if shards <= 1:
        return list(rows)
    shards = max(1, int(shards))
    shard = max(0, int(shard)) % shards
    # Public crawler: shard by website host (not list position) so a host never gets
    # concurrent requests from two matrix jobs.
    from shard import shard_of
    return [rec for rec in rows if shard_of(rec.get("website") or rec.get("id") or "", shards) == shard]


def take_window(queue: list, cursor: int, limit: int, already: set, coverage: dict, today: str, days: int):
    """Walk the stable queue from cursor. Skip cooldown and already-selected sites. limit 0 = one full lap."""
    n = len(queue)
    if n == 0:
        return [], {"start": 0, "plannedEnd": 0, "cooldownIds": [], "walk": [], "steps": 0}
    start = int(cursor) % n
    pos = start
    taken = []
    cooldown_ids = []
    walk = []
    steps = 0
    max_take = limit if limit and limit > 0 else n
    while steps < n and len(taken) < max_take:
        rec = queue[pos]
        pos = (pos + 1) % n
        steps += 1
        sid = rec.get("id")
        walk.append(sid)
        if sid in already:
            continue
        if in_no_signal_cooldown(coverage, sid, today, days):
            cooldown_ids.append(sid)
            continue
        taken.append(rec)
    return taken, {
        "start": start,
        "plannedEnd": pos,
        "cooldownIds": cooldown_ids,
        "walk": walk,
        "steps": steps,
    }


def assemble_batch(
    churches: list,
    org_rows: list,
    *,
    country: str,
    today: str,
    coverage: dict | None = None,
    limit: int = 0,
    always_orgs: bool = True,
    prioritize: bool = True,
    hot_cap: int = HOT_CAP,
    no_signal_days: int = NO_SIGNAL_DAYS,
    shard: int = 0,
    shards: int = 1,
    skip_ids: set | None = None,
    previous_events=None,
) -> tuple[list, dict]:
    """Return (sites_to_crawl, meta). Organisation sites are first and ignored by the church cursor."""
    coverage = coverage or empty_coverage()
    skip_ids = {str(item) for item in (skip_ids or set()) if item}
    queue = shard_list(churches, shard, shards)
    org_batch = []
    if always_orgs:
        for rec in org_rows:
            if rec.get("id") in skip_ids:
                continue
            org_batch.append(rec)
    already = {rec["id"] for rec in org_batch}

    state = dict((coverage.get("countries") or {}).get(country) or {})
    cursor = int(state.get("cursor") or 0)
    hot_cursor = int(state.get("hotCursor") or 0)

    hot_batch = []
    if prioritize and queue:
        known = signal_ids(coverage, previous_events)
        hot_pool = [
            rec for rec in queue
            if rec.get("id") in known and rec.get("id") not in already and rec.get("id") not in skip_ids
        ]
        if hot_pool:
            cap = len(hot_pool) if hot_cap <= 0 else min(len(hot_pool), hot_cap)
            off = hot_cursor % len(hot_pool)
            rotated = hot_pool[off:] + hot_pool[:off]
            hot_batch = rotated[:cap]
            already.update(rec["id"] for rec in hot_batch)

    window, walk = take_window(queue, cursor, limit, already | skip_ids, coverage, today, no_signal_days)
    batch = org_batch + hot_batch + window
    meta = {
        "country": country,
        "queueSize": len(queue),
        "cursor": cursor if queue else 0,
        "hotCursor": hot_cursor,
        "orgIds": [rec["id"] for rec in org_batch],
        "hotIds": [rec["id"] for rec in hot_batch],
        "windowIds": [rec["id"] for rec in window],
        "cooldownSkipped": walk["cooldownIds"],
        "walk": walk["walk"],
        "steps": walk["steps"],
        "plannedEnd": walk["plannedEnd"],
        "shard": max(0, int(shard)),
        "shards": max(1, int(shards)),
    }
    return batch, meta


def advance_coverage(coverage: dict, meta: dict, logs: list, today: str, now_iso: str, no_signal_days: int = NO_SIGNAL_DAYS) -> dict:
    """Update cursors and signal memory from the logs of one country batch."""
    coverage = coverage or empty_coverage()
    coverage.setdefault("noSignal", {})
    coverage.setdefault("hasSignal", {})
    coverage.setdefault("countries", {})
    finished = set()
    for log in logs or []:
        if not isinstance(log, dict):
            continue
        sid = log.get("id")
        if not sid:
            continue
        finished.add(sid)
        status = log.get("status") or ""
        if status != "ok":
            continue
        if log_has_signal(log):
            coverage["hasSignal"][sid] = today
            coverage["noSignal"].pop(sid, None)
        else:
            coverage["noSignal"][sid] = today
            coverage["hasSignal"].pop(sid, None)

    country = meta.get("country") or ""
    state = coverage["countries"].setdefault(country, {})
    queue_size = int(meta.get("queueSize") or 0)
    start = int(meta.get("cursor") or 0)
    walk = meta.get("walk") or []
    window = set(meta.get("windowIds") or [])
    new_cursor = start
    advanced = 0
    for sid in walk:
        if sid in window and sid not in finished:
            break
        if queue_size:
            new_cursor = (new_cursor + 1) % queue_size
            advanced += 1
    hot_ids = meta.get("hotIds") or []
    hot_finished = sum(1 for sid in hot_ids if sid in finished)
    state["cursor"] = new_cursor if queue_size else 0
    state["queueSize"] = queue_size
    state["hotCursor"] = int(state.get("hotCursor") or 0) + hot_finished
    state["shard"] = meta.get("shard") or 0
    state["shards"] = meta.get("shards") or 1
    state["lastRunAt"] = now_iso
    scanned = int(state.get("scannedSincePass") or 0) + advanced
    if queue_size and scanned >= queue_size:
        state["completedCycles"] = int(state.get("completedCycles") or 0) + 1
        state["lastFullPassAt"] = today
        state["scannedSincePass"] = scanned % queue_size
    else:
        state["scannedSincePass"] = scanned
    coverage["updatedAt"] = now_iso
    coverage["noSignalDays"] = no_signal_days
    return coverage
