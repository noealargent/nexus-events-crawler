"""Pure helpers for the events importer. No network. import_events.py uses these."""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from urllib.parse import urlparse
from zoneinfo import ZoneInfo



DENVER_TZ = ZoneInfo("America/Denver")


def today_in_denver(now: dt.datetime | None = None) -> str:
    """Calendar date in America/Denver, as YYYY-MM-DD. Naive datetimes are treated as UTC."""
    stamp = now or dt.datetime.now(dt.timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.timezone.utc)
    return stamp.astimezone(DENVER_TZ).date().isoformat()


def fold_title(title: str) -> str:
    text = unicodedata.normalize("NFD", title or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _idents(item: dict) -> list[str]:
    return [value for value in (item.get("churchId"), item.get("churchSlug"), item.get("id"), item.get("slug")) if value]


def manual_keys(manual: list[dict]) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    for item in manual:
        title = fold_title(str(item.get("title") or ""))
        date = str(item.get("date") or "")
        if not title or not date:
            continue
        for ident in _idents(item):
            keys.add((str(ident), date, title))
    return keys


def is_scraped_duplicate(event: dict, keys: set[tuple[str, str, str]]) -> bool:
    """True when a scraped event repeats a manual one. Manual rows are not passed here."""
    title = fold_title(str(event.get("title") or ""))
    date = str(event.get("date") or "")
    if not title or not date:
        return False
    idents = {str(event.get("churchId") or ""), str(event.get("churchSlug") or "")} - {""}
    for ident, when, folded in keys:
        if ident not in idents or when != date:
            continue
        if folded == title:
            return True
        if len(folded) >= 8 and len(title) >= 8 and (folded in title or title in folded):
            return True
    return False


def dedupe_scraped(events: list[dict], manual: list[dict]) -> list[dict]:
    keys = manual_keys(manual)
    return [event for event in events if not is_scraped_duplicate(event, keys)]


def website_host(website: str) -> str:
    if not website:
        return ""
    raw = website if "://" in website else "https://" + website
    return urlparse(raw).netloc.lower().split(":")[0].removeprefix("www.")


def record_opted_out(rec: dict, ids: set[str], hosts: set[str]) -> bool:
    if rec.get("eventsImportOptOut") is True:
        return True
    if rec.get("id") in ids or rec.get("slug") in ids:
        return True
    host = website_host(str(rec.get("website") or rec.get("websiteUrl") or ""))
    return bool(host) and host in hosts


def still_current(event: dict, today: str) -> bool:
    """True when the event's last day is today or later. `today` is YYYY-MM-DD."""
    start = str(event.get("date") or "")
    end = str(event.get("endDate") or "")
    last = end if end > start else start
    return bool(last) and last >= today


def in_horizon(start, lo, hi) -> bool:
    """True when a parsed start sits in the importer window. Missing starts are not current."""
    if start is None or lo is None or hi is None:
        return False
    return lo <= start <= hi


def load_store_state(path: str | None) -> dict:
    """Opt-outs and manual events from the church store the editor writes (data/nexus-store.json)."""
    empty = {"ids": set(), "hosts": set(), "manual": []}
    if not path:
        return empty
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return empty
    except json.JSONDecodeError:
        return empty
    churches = data.get("churches") if isinstance(data, dict) else None
    events = data.get("events") if isinstance(data, dict) else None
    if not isinstance(churches, list):
        churches = []
    if not isinstance(events, list):
        events = []
    by_id = {}
    ids: set[str] = set()
    hosts: set[str] = set()
    for church in churches:
        if not isinstance(church, dict) or not church.get("id"):
            continue
        by_id[church["id"]] = church
        if church.get("eventsImportOptOut") is not True:
            continue
        ids.add(str(church["id"]))
        if church.get("slug"):
            ids.add(str(church["slug"]))
        host = website_host(str(church.get("websiteUrl") or ""))
        if host:
            hosts.add(host)
    manual = []
    for event in events:
        if not isinstance(event, dict):
            continue
        church_id = str(event.get("churchId") or "")
        church = by_id.get(church_id) or {}
        manual.append({
            "churchId": church_id,
            "churchSlug": church.get("slug") or "",
            "title": event.get("title") or "",
            "date": event.get("date") or "",
        })
    return {"ids": ids, "hosts": hosts, "manual": manual}


def organisation_sites(rows: list[dict]) -> list[dict]:
    """Evangelical organisation pages the importer may read. No website, no row. Not a church."""
    out = []
    for row in rows:
        website = str(row.get("website") or row.get("websiteUrl") or "").strip()
        if not website or not row.get("id"):
            continue
        out.append({
            "id": row["id"],
            "slug": row.get("slug") or row["id"],
            "name": row.get("name") or "",
            "website": website,
            "city": row.get("city") or "",
            "cc": row.get("cc") or "",
            "lat": row.get("lat") or 0,
            "lng": row.get("lng") or 0,
            "kind": "organisation",
        })
    return out
