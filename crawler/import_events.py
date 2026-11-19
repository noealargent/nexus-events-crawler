#!/usr/bin/env python3
"""Nexus events importer: upcoming public events from the websites of listed evangelical churches.

Structured data only, never free-text scraping:
  * schema.org Event in JSON-LD (homepage + at most one agenda page per site),
  * iCalendar feeds (.ics / webcal) linked by the site itself, RRULE series expanded over the horizon,
  * the WordPress « The Events Calendar » REST feed (/wp-json/tribe/events/v1/events),
  * public Google Calendar embeds on the church site (iframe src or Pretty Google Calendar ids),
    fetched as the public ICS export only — never a /private- secret address,
  * agenda links a claimed church pasted in its dashboard with its consent (ICS, Google Calendar, Church Center).

Politeness and opt-outs:
  * identifiable User-Agent (see BOT_URL); robots.txt honoured on church hosts. Public Google
    Calendar ICS exports are fetched even when calendar.google.com/robots.txt disallows crawlers,
    because the church already published the calendar on its own page. Private addresses are never used,
  * text-and-data-mining reservation honoured (CPI L.122-5-3 / DSM art. 4): /.well-known/tdmrep.json,
    <meta name="tdm-reservation" content="1">, the TDM-Reservation header, and robots « noai » meta / X-Robots-Tag,
  * >= HOST_DELAY seconds between two requests to the same host; homepage + 1 agenda page + 1 feed per site,
  * public/events/optout.json and the editor store (data/nexus-store.json: eventsImportOptOut,
    plus church-created events used only to drop scraped duplicates) are skipped or de-duplicated.
  * Evangelical organisation sites in scripts/events/organisation-sites.json are read the same way
    and, by default, included in every nightly batch (they are not subject to the church cursor).
  * Church websites are covered on a rolling cursor (docs/events-archive/coverage.json): sites with
    an events page or feed are refreshed first; sites with no events signal after a successful
    check are skipped for --no-signal-days (default 14).

Kept per event: title, date, start/end time, venue (name + street + town), church, source URL. No description,
no image, no names of people. Places that look private (« chez … », « à domicile », appartement…) are dropped.
Routine services (weekly culte, prière, étude biblique…) are kept but flagged `routine` so the page hides them by default.

Only churches the directory lists are read: public/osm/c shards (never public/osm/h), cc in --countries,
not Catholic / Orthodox, and not a mainline body (EPUdF / UEPAL… by name, network or website host).

Usage:  python3 scripts/events/import_events.py [--limit N] [--countries FR] [--horizon 60] [--out public/events/index.json]
Needs:  pip install requests beautifulsoup4 python-dateutil
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import html
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib import robotparser
from urllib.parse import unquote, urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from dateutil import rrule as du_rrule

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "osm"))
sys.path.insert(0, os.path.dirname(__file__))
from evangelical import MAINLINE_TEXT, fold  # noqa: E402  (same rules as the directory pruning)
from collect import dedupe_scraped, in_horizon, load_store_state, organisation_sites, record_opted_out, still_current, today_in_denver  # noqa: E402
from coverage import (  # noqa: E402
    HOT_CAP,
    NO_SIGNAL_DAYS,
    advance_coverage,
    assemble_batch,
    empty_coverage,
    load_coverage,
    save_coverage,
)

BOT_URL = "https://nexuschurches.com/annuaire/evenements/robot"
UA_TOKEN = "NexusEventsBot"
UA = f"{UA_TOKEN}/1.0 (+{BOT_URL})"
TIMEOUT = 12
HOST_DELAY = 3.0
SITE_BUDGET = 22.0  # wall-clock cap per site so one slow host cannot consume a 12s timeout on every request
MAX_BYTES = 3_000_000
PER_CHURCH = 12
ALLOW_HTTP = os.environ.get("NEXUS_EVENTS_ALLOW_HTTP") == "1"   # https first; plain http only when asked (CI runner)
COUNTRY_NAMES = {"FR": "France", "BE": "Belgique", "CH": "Suisse", "US": "United States", "CA": "Canada", "GB": "United Kingdom"}
COUNTRY_TZ = {"FR": "Europe/Paris", "BE": "Europe/Brussels", "CH": "Europe/Zurich", "CA": "America/Toronto", "GB": "Europe/London"}
US_TZ = {
    "Alabama": "America/Chicago", "Alaska": "America/Anchorage", "Arizona": "America/Phoenix", "Arkansas": "America/Chicago",
    "California": "America/Los_Angeles", "Colorado": "America/Denver", "Connecticut": "America/New_York",
    "Delaware": "America/New_York", "District of Columbia": "America/New_York", "Florida": "America/New_York",
    "Georgia": "America/New_York", "Hawaii": "Pacific/Honolulu", "Idaho": "America/Boise", "Illinois": "America/Chicago",
    "Indiana": "America/Indiana/Indianapolis", "Iowa": "America/Chicago", "Kansas": "America/Chicago", "Kentucky": "America/New_York",
    "Louisiana": "America/Chicago", "Maine": "America/New_York", "Maryland": "America/New_York", "Massachusetts": "America/New_York",
    "Michigan": "America/Detroit", "Minnesota": "America/Chicago", "Mississippi": "America/Chicago", "Missouri": "America/Chicago",
    "Montana": "America/Denver", "Nebraska": "America/Chicago", "Nevada": "America/Los_Angeles", "New Hampshire": "America/New_York",
    "New Jersey": "America/New_York", "New Mexico": "America/Denver", "New York": "America/New_York",
    "North Carolina": "America/New_York", "North Dakota": "America/Chicago", "Ohio": "America/New_York", "Oklahoma": "America/Chicago",
    "Oregon": "America/Los_Angeles", "Pennsylvania": "America/New_York", "Rhode Island": "America/New_York",
    "South Carolina": "America/New_York", "South Dakota": "America/Chicago", "Tennessee": "America/Chicago", "Texas": "America/Chicago",
    "Utah": "America/Denver", "Vermont": "America/New_York", "Virginia": "America/New_York", "Washington": "America/Los_Angeles",
    "West Virginia": "America/New_York", "Wisconsin": "America/Chicago", "Wyoming": "America/Denver",
}
CACHE_DIR = ""
MAINLINE_LINK = re.compile(r"^https?://(?:www\.)?(?:[a-z0-9-]+\.)?(?:epudf\.org|uepal\.fr)(?:/|$)", re.I)
MAINLINE_HOSTS = re.compile(r"(?:^|\.)(?:epudf\.org|eglise-protestante-unie\.fr|uepal\.fr|protestants\.org)$", re.I)

ROUTINE_RX = re.compile(
    r"\bcultes?\b|\bmesse\b|\boffice\b|\bservice\b|\bpri[eè]re\b|\bintercession\b|\b[ée]tude biblique\b|\bbible study\b"
    r"|\bgroupes? de maison\b|\bgroupes? de quartier\b|\bcellules?\b|\b[ée]cole du dimanche\b|\bclub biblique\b|\bkt\b"
    r"|\bcat[ée]ch[eè]se\b|\bcat[ée]chisme\b|\br[ée]p[ée]tition\b|\bchorale\b|\bpermanence\b|\bsunday service\b|\bworship service\b"
    r"|\bcafé[- ]?(?:contact|partage)\b|\bjeunes du (?:vendredi|samedi)\b|\bdimanche\b", re.I)
SPECIAL_RX = re.compile(
    r"conf[ée]rence|concert|gospel|no[eë]l|p[âa]ques|pentec[ôo]te|bapt[êe]mes?\b|s[ée]minaire|convention|retraite|week-?end"
    r"|camp\b|festival|soir[ée]e|nuit de|veill[ée]e|culte (?:de|du) (?:no[eë]l|r[ée]veil|louange|gospel|mission|baptême|f[êe]te)"
    r"|f[êe]te|journ[ée]e|rassemblement|formation|colloque|spectacle|film|projection|tourn[ée]e|tour\b|inauguration|anniversaire"
    r"|mariage|assembl[ée]e g[ée]n[ée]rale|vente|brocante|march[ée] de|kermesse|sortie|randonn", re.I)
PRIVATE_RX = re.compile(
    r"\bchez (?!nous\b)[A-ZÉ]?[a-zé]|\bà domicile\b|\ba domicile\b|\bdomicile\b|\bappartement\b|\bappt\b|\bà la maison\b"
    r"|\bdans une maison\b|\bfamille [A-Z]|\badresse (?:communiqu|sur demande|envoy)|\bsur inscription uniquement\b|\bprivate home\b", re.I)
# Internal church business: never public-facing, dropped.
INTERNAL_RX = re.compile(
    r"\bconseil\b|\bcoll[èe]ge pastoral\b|\bassembl[ée]e g[ée]n[ée]rale\b|\bcomit[ée]\b|\bbureau\b|\br[ée]union (?:des )?(?:responsables|"
    r"pr[ée]sidents|pr[ée]dicateurs|anciens|diacres|leaders|serviteurs|[ée]quipes?|moniteurs)|\bstaff\b|\bcons?istoire\b|\bpresbyt[eè]re\b"
    r"|\bplanning\b|\b[ée]quipe (?:d'accueil|technique|louange|son)\b|\d+\s*일째", re.I)

# Groups that may meet in homes: dropped, not just marked routine.
HOUSE_RX = re.compile(
    r"\bgdm\b|\bgd ?maison\b|groupes? de maison|house groups?|cellules? de maison", re.I)
TYPE_RULES = [
    ("priere", re.compile(r"pri[eè]re|intercession|\bje[uû]ne\b", re.I)),
    ("louange", re.compile(r"louange|adoration|worship|gospel|concert", re.I)),
    ("jeunesse", re.compile(r"jeunes|jeunesse|ados|youth|enfants|kids", re.I)),
    ("evangelisation", re.compile(r"[ée]vang[ée]lis|mission|parcours alpha|alpha\b", re.I)),
    ("maraude", re.compile(r"maraude", re.I)),
    ("conference", re.compile(r"conf[ée]rence|s[ée]minaire|convention|formation|colloque|retraite", re.I)),
    ("culte", re.compile(r"culte|service|c[ée]l[ée]bration", re.I)),
]

S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "fr,en;q=0.5"})
_last: dict[str, float] = {}
_lock = threading.Lock()
_robots: dict[str, robotparser.RobotFileParser] = {}
_robots_lock = threading.Lock()
# Persistent validators (ETag / Last-Modified) across nightly runs. No page bodies.
HTTP_CACHE_PATH = ""
HTTP_CACHE_MAX_AGE_DAYS = 60
_http_cache: dict[str, dict] = {}
_http_cache_lock = threading.Lock()
_host_backoff_until: dict[str, float] = {}
_http_stats = {"notModified": 0, "conditionalGets": 0, "retries429": 0, "stored": 0}


def clean(text, limit=140) -> str:
    """Strip tags and HTML entities (&#8211; &rsquo; &amp;…), collapse spaces."""
    if text is None:
        return ""
    value = str(text).replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").replace("\\N", " ")
    if "<" in value:
        value = BeautifulSoup(value, "html.parser").get_text(" ")
    value = html.unescape(html.unescape(value))
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _wait(host: str) -> None:
    with _lock:
        now = time.time()
        slot = max(now, _last.get(host, 0) + HOST_DELAY)
        _last[host] = slot
    if slot > now:
        time.sleep(slot - now)


CA_TZ = {
    "Ontario": "America/Toronto",
    "Québec": "America/Toronto",
    "Quebec": "America/Toronto",
    "Nova Scotia": "America/Halifax",
    "New Brunswick": "America/Moncton",
    "Prince Edward Island": "America/Halifax",
    "Newfoundland and Labrador": "America/St_Johns",
    "Manitoba": "America/Winnipeg",
    "Saskatchewan": "America/Regina",
    "Alberta": "America/Edmonton",
    "British Columbia": "America/Vancouver",
    "Yukon": "America/Whitehorse",
    "Northwest Territories": "America/Yellowknife",
    "Nunavut": "America/Iqaluit",
}


def church_tz(rec) -> ZoneInfo:
    cc = rec.get("cc") or ""
    if cc == "US":
        return ZoneInfo(US_TZ.get(rec.get("region") or "", "America/Chicago"))
    if cc == "CA":
        return ZoneInfo(CA_TZ.get(rec.get("region") or "", "America/Toronto"))
    return ZoneInfo(COUNTRY_TZ.get(cc, "Europe/Paris"))


class CachedResponse:
    def __init__(self, status_code: int, headers: dict, text: str, url: str):
        self.status_code = status_code
        self.headers = headers
        self.text = text
        self.url = url

    def json(self):
        return json.loads(self.text)


def _cache_path(url: str) -> str:
    return os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".json")


def _recall(url: str):
    if not CACHE_DIR:
        return None
    path = _cache_path(url)
    if not os.path.exists(path):
        return None
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return CachedResponse(int(data.get("status") or 0), data.get("headers") or {}, data.get("body") or "", data.get("url") or url)


def _remember(url: str, response) -> None:
    if not CACHE_DIR or response is None:
        return
    try:
        text = response.text
    except Exception:
        return
    os.makedirs(CACHE_DIR, exist_ok=True)
    payload = {
        "url": getattr(response, "url", url),
        "status": response.status_code,
        "headers": {str(k).lower(): str(v) for k, v in response.headers.items()},
        "body": text[:MAX_BYTES],
        "fetchedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    dest = _cache_path(url)
    tmp = dest + ".part"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(tmp, dest)


def _http_cache_key(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlparse(raw)
    return parts._replace(fragment="").geturl()


def http_cache_stats() -> dict:
    with _http_cache_lock:
        stored = sum(1 for item in _http_cache.values() if item.get("etag") or item.get("lastModified"))
        stats = dict(_http_stats)
        stats["stored"] = stored
        return stats


def load_http_cache(path: str) -> None:
    """Load validators from a small JSON file. Empty path disables persistence."""
    global HTTP_CACHE_PATH, _http_cache
    HTTP_CACHE_PATH = path or ""
    with _http_cache_lock:
        _http_cache = {}
        _http_stats["notModified"] = 0
        _http_stats["conditionalGets"] = 0
        _http_stats["retries429"] = 0
        _http_stats["stored"] = 0
        if not HTTP_CACHE_PATH or not os.path.exists(HTTP_CACHE_PATH):
            return
        try:
            data = json.load(open(HTTP_CACHE_PATH, encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return
        urls = data.get("urls") if isinstance(data, dict) else None
        if not isinstance(urls, dict):
            return
        cutoff = None
        try:
            today = dt.date.fromisoformat(today_in_denver())
            cutoff = today - dt.timedelta(days=HTTP_CACHE_MAX_AGE_DAYS)
        except ValueError:
            cutoff = None
        kept = {}
        for raw_key, item in urls.items():
            if not isinstance(item, dict):
                continue
            key = _http_cache_key(str(raw_key))
            if not key:
                continue
            checked = str(item.get("checkedAt") or "")[:10]
            if cutoff and checked:
                try:
                    if dt.date.fromisoformat(checked) < cutoff:
                        continue
                except ValueError:
                    pass
            entry = {}
            if item.get("etag"):
                entry["etag"] = str(item["etag"])
            if item.get("lastModified"):
                entry["lastModified"] = str(item["lastModified"])
            children = [str(u) for u in (item.get("children") or []) if u]
            if children:
                entry["children"] = children
            if item.get("checkedAt"):
                entry["checkedAt"] = str(item["checkedAt"])
            if entry:
                kept[key] = entry
        _http_cache = kept


def save_http_cache() -> None:
    if not HTTP_CACHE_PATH:
        return
    folder = os.path.dirname(HTTP_CACHE_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with _http_cache_lock:
        urls = {key: dict(val) for key, val in _http_cache.items()}
    payload = {
        "updatedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "timezone": "America/Denver",
        "urls": urls,
    }
    dest = HTTP_CACHE_PATH
    tmp = dest + ".part"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, dest)


def _http_lookup(url: str) -> dict:
    key = _http_cache_key(url)
    if not key:
        return {}
    with _http_cache_lock:
        item = _http_cache.get(key)
        return dict(item) if item else {}


def _http_store(url: str, **fields) -> None:
    key = _http_cache_key(url)
    if not key:
        return
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with _http_cache_lock:
        current = dict(_http_cache.get(key) or {})
        for field, value in fields.items():
            if value is None:
                continue
            current[field] = value
        current["checkedAt"] = now
        _http_cache[key] = current


def http_cache_add_children(parent: str, children: list[str]) -> None:
    urls = []
    seen = set()
    for item in children:
        key = _http_cache_key(item)
        if key and key not in seen and key != _http_cache_key(parent):
            seen.add(key)
            urls.append(key)
    if urls:
        _http_store(parent, children=urls)


def http_cache_children(parent: str) -> list[str]:
    return list(_http_lookup(parent).get("children") or [])


def _remember_validators(url: str, response) -> None:
    if response is None or getattr(response, "status_code", 0) == 304:
        return
    headers = {str(k).lower(): str(v) for k, v in (getattr(response, "headers", {}) or {}).items()}
    etag = headers.get("etag") or ""
    last_modified = headers.get("last-modified") or ""
    if not etag and not last_modified:
        return
    final = getattr(response, "url", None) or url
    fields = {}
    if etag:
        fields["etag"] = etag
    if last_modified:
        fields["lastModified"] = last_modified
    _http_store(url, **fields)
    if _http_cache_key(final) != _http_cache_key(url):
        _http_store(final, **fields)


def _retry_after_seconds(response, cap: float = 8.0) -> float:
    raw = ""
    headers = getattr(response, "headers", {}) or {}
    for key, value in headers.items():
        if str(key).lower() == "retry-after":
            raw = str(value).strip()
            break
    delay = 2.0
    if raw:
        try:
            delay = float(raw)
        except ValueError:
            try:
                target = dt.datetime.strptime(raw, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=dt.timezone.utc)
                delay = max(0.0, (target - dt.datetime.now(dt.timezone.utc)).total_seconds())
            except ValueError:
                delay = 2.0
    return max(0.2, min(cap, delay))


def _set_host_backoff(host: str, seconds: float) -> None:
    host = (host or "").lower()
    if not host:
        return
    with _lock:
        _host_backoff_until[host] = max(_host_backoff_until.get(host, 0), time.time() + seconds)


def _wait_backoff(host: str, remain: float) -> bool:
    """Sleep while this host is in a 429 backoff. False if the wait would exceed the request budget."""
    host = (host or "").lower()
    with _lock:
        until = _host_backoff_until.get(host, 0)
    delay = until - time.time()
    if delay <= 0:
        return True
    if remain and delay > remain:
        return False
    time.sleep(min(delay, 8.0))
    return True


def robots_for(url: str) -> robotparser.RobotFileParser:
    parts = urlparse(url)
    key = f"{parts.scheme}://{parts.netloc}"
    with _robots_lock:
        if key in _robots:
            return _robots[key]
    rp = robotparser.RobotFileParser()
    r, _err = polite_get(key + "/robots.txt", check_robots=False, conditional=False)
    if r is None:
        rp.parse([])
    elif r.status_code in (401, 403):
        rp.disallow_all = True           # robots.txt itself refused: stay out
    elif r.status_code >= 400:
        rp.parse([])                     # no robots.txt: allowed
    else:
        rp.parse(r.text.splitlines())
    with _robots_lock:
        _robots[key] = rp
    return rp


def polite_get(url: str, check_robots=True, timeout: float | None = None, conditional: bool = True):
    if check_robots and not robots_for(url).can_fetch(UA_TOKEN, url):
        return None, "robots"
    cached = _recall(url)
    if cached is not None:
        return cached, None
    budget = TIMEOUT if timeout is None else max(2.0, min(float(TIMEOUT), float(timeout)))
    host = urlparse(url).netloc
    if not _wait_backoff(host, budget):
        return None, "http-429"
    headers = {}
    if conditional:
        validators = _http_lookup(url)
        if validators.get("etag"):
            headers["If-None-Match"] = validators["etag"]
        if validators.get("lastModified"):
            headers["If-Modified-Since"] = validators["lastModified"]
    retries = 0
    started = time.time()
    while True:
        remain = budget - (time.time() - started)
        if remain < 1.5 and retries:
            return None, "http-429"
        if retries and not _wait_backoff(host, max(remain, 0)):
            return None, "http-429"
        _wait(host)
        remain = max(2.0, budget - (time.time() - started))
        try:
            r = S.get(url, timeout=remain, allow_redirects=True, stream=True, headers=headers or None)
        except Exception as exc:
            return None, type(exc).__name__
        if r.status_code == 429:
            wait = _retry_after_seconds(r)
            try:
                r.close()
            except Exception:
                pass
            _set_host_backoff(host, wait)
            with _http_cache_lock:
                _http_stats["retries429"] += 1
            retries += 1
            if retries > 2:
                return None, "http-429"
            time.sleep(wait)
            continue
        if r.status_code == 304:
            try:
                r.close()
            except Exception:
                pass
            _http_store(url, **{k: v for k, v in _http_lookup(url).items() if k in ("etag", "lastModified", "children")})
            with _http_cache_lock:
                _http_stats["notModified"] += 1
                if headers:
                    _http_stats["conditionalGets"] += 1
            return CachedResponse(304, {str(k): str(v) for k, v in r.headers.items()}, "", getattr(r, "url", None) or url), None
        try:
            body = r.raw.read(MAX_BYTES, decode_content=True)
            r._content = body
        except Exception as exc:
            return None, type(exc).__name__
        _remember(url, r)
        _remember_validators(url, r)
        if headers:
            with _http_cache_lock:
                _http_stats["conditionalGets"] += 1
        return r, None


def tdm_reserved(response, soup) -> bool:
    """True when the page reserves text-and-data mining (TDMRep meta/header, robots noai)."""
    headers = {k.lower(): v for k, v in response.headers.items()}
    if headers.get("tdm-reservation", "").strip() == "1":
        return True
    if re.search(r"\bnoai\b|\bnoimageai\b", headers.get("x-robots-tag", ""), re.I):
        return True
    if soup is not None:
        meta = soup.find("meta", attrs={"name": re.compile(r"^tdm-reservation$", re.I)})
        if meta and str(meta.get("content", "")).strip() == "1":
            return True
        for robots in soup.find_all("meta", attrs={"name": re.compile(r"^(robots|" + UA_TOKEN.lower() + r")$", re.I)}):
            if re.search(r"\bnoai\b|\bnone\b", str(robots.get("content", "")), re.I):
                return True
    return False


def tdmrep_reserved(base: str) -> bool:
    """/.well-known/tdmrep.json: [{"location": "/path*", "tdm-reservation": 1}]."""
    url = urljoin(base, "/.well-known/tdmrep.json")
    r, _ = polite_get(url, conditional=False)
    if r is None or r.status_code >= 400:
        return False
    try:
        rules = r.json()
    except Exception:
        return False
    for rule in rules if isinstance(rules, list) else []:
        if isinstance(rule, dict) and str(rule.get("tdm-reservation", "0")) == "1":
            loc = str(rule.get("location", "/*"))
            if loc in ("", "/", "*", "/*") or urlparse(base).path.startswith(loc.rstrip("*")):
                return True
    return False


# ---- date handling -------------------------------------------------------------------------------------------------

def parse_when(value, tz: ZoneInfo):
    """-> (aware datetime, all_day) or (None, False). Lenient with malformed values like 2026-11-29UTC09:30:00."""
    if not value:
        return None, False
    s = str(value).strip()
    if re.fullmatch(r"\d{8}", s):
        return dt.datetime.strptime(s, "%Y%m%d").replace(tzinfo=tz), True
    m = re.fullmatch(r"(\d{8}T\d{6})(Z?)", s)
    if m:
        d = dt.datetime.strptime(m.group(1), "%Y%m%dT%H%M%S")
        return (d.replace(tzinfo=dt.timezone.utc) if m.group(2) else d.replace(tzinfo=tz)), False
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return dt.datetime.fromisoformat(s).replace(tzinfo=tz), True
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T"))
        return (d if d.tzinfo else d.replace(tzinfo=tz)), False
    except ValueError:
        pass
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})\D*?(\d{2}):(\d{2})", s)
    if m:
        utc = "UTC" in s or s.endswith("Z")
        d = dt.datetime(*[int(x) for x in m.groups()])
        return (d.replace(tzinfo=dt.timezone.utc) if utc else d.replace(tzinfo=tz)), False
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return dt.datetime(*[int(x) for x in m.groups()]).replace(tzinfo=tz), True
    return None, False


def ics_value(lines: dict, key: str):
    """(params, value) of the first KEY line."""
    return lines.get(key, ("", None))


def ics_when(params: str, value, tz: ZoneInfo):
    if value is None:
        return None, False
    m = re.search(r"TZID=([^;:]+)", params or "")
    zone = tz
    if m:
        try:
            zone = ZoneInfo(m.group(1).strip('"'))
        except Exception:
            zone = tz
    return parse_when(value, zone)


def parse_ics(text: str, src: str, tz: ZoneInfo, window: tuple[dt.datetime, dt.datetime]):
    text = re.sub(r"\r?\n[ \t]", "", text)
    out = []
    overridden = set()
    blocks = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S)
    parsed = []
    for block in blocks:
        lines: dict[str, tuple[str, str]] = {}
        exdates = []
        for line in block.strip().splitlines():
            if ":" not in line:
                continue
            head, value = line.split(":", 1)
            name, _, params = head.partition(";")
            name = name.upper()
            if name == "EXDATE":
                exdates.extend((params, v) for v in value.split(","))
            lines.setdefault(name, (params, value.strip()))
        parsed.append((lines, exdates))
        if "RECURRENCE-ID" in lines:
            overridden.add((lines.get("UID", ("", ""))[1], lines["RECURRENCE-ID"][1]))
    lo, hi = window
    for lines, exdates in parsed:
        if ics_value(lines, "STATUS")[1] in ("CANCELLED",) or ics_value(lines, "CLASS")[1] in ("PRIVATE", "CONFIDENTIAL"):
            continue
        start, all_day = ics_when(*ics_value(lines, "DTSTART"), tz)
        if start is None:
            continue
        end, _ = ics_when(*ics_value(lines, "DTEND"), tz)
        duration = (end - start) if end else None
        base = {
            "title": clean(ics_value(lines, "SUMMARY")[1]),
            "place": clean(ics_value(lines, "LOCATION")[1], 160),
            "url": (ics_value(lines, "URL")[1] or "").strip(),
            "description": clean(ics_value(lines, "DESCRIPTION")[1], 400),
            "all_day": all_day,
        }
        rule = ics_value(lines, "RRULE")[1]
        if rule:
            try:
                rs = du_rrule.rruleset()
                rs.rrule(du_rrule.rrulestr(rule, dtstart=start))
                for params, value in exdates:
                    ex, _ = ics_when(params, value, tz)
                    if ex is not None:
                        rs.exdate(ex)
                occurrences = rs.between(lo, hi, inc=True)[:8]
            except Exception:
                occurrences = []
            uid = ics_value(lines, "UID")[1] or ""
            for occ in occurrences:
                key = occ.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                if (uid, key) in overridden:
                    continue
                out.append({**base, "start": occ, "end": occ + duration if duration else None, "recurring": True, "via": "ics"})
        elif lo <= start <= hi:
            out.append({**base, "start": start, "end": end, "recurring": False, "via": "ics"})
    return out


# ---- extraction ----------------------------------------------------------------------------------------------------

VAGUE_PLACE = re.compile(r"^(?:sur site|pr[ée]sentiel|en pr[ée]sentiel|sur place|à l'[ée]glise|salle|tbc|tba|-)$", re.I)


def tidy_place(place: str, title: str = "") -> str:
    parts, seen = [], set()
    for part in (p.strip() for p in place.split(",")):
        key = fold(part)
        if not part or key in seen or VAGUE_PLACE.match(part) or (title and key == fold(title)):
            continue
        seen.add(key)
        parts.append(part)
    return ", ".join(parts)[:160]


def place_of(location) -> str:
    if isinstance(location, list):
        location = location[0] if location else None
    if isinstance(location, str):
        return clean(location, 160)
    if not isinstance(location, dict):
        return ""
    if str(location.get("@type", "")).lower().startswith("virtual"):
        return "En ligne"
    name = clean(location.get("name", ""), 80)
    address = location.get("address")
    if isinstance(address, dict):
        street = clean(address.get("streetAddress", ""), 80)
        town = clean(address.get("addressLocality", ""), 60)
        return ", ".join(x for x in (name, street, town) if x)
    if isinstance(address, str):
        return ", ".join(x for x in (name, clean(address, 100)) if x)
    return name


def wall_clock(value: dt.datetime | None, tz: ZoneInfo):
    """WordPress plugins often print the local time with a stale offset (+02:00 in November). When the written
    offset is within an hour of the church's own zone, trust the wall-clock time a visitor reads on the page."""
    if value is None or value.tzinfo is None:
        return value
    local = value.replace(tzinfo=tz)
    written = value.utcoffset() or dt.timedelta(0)
    if abs(written - (local.utcoffset() or dt.timedelta(0))) <= dt.timedelta(hours=1):
        return local
    return value


def jsonld_events(soup, page_url: str, tz: ZoneInfo):
    out = []
    for tag in soup.find_all("script", type=re.compile(r"ld\+json", re.I)):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except Exception:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if any(isinstance(t, str) and t.endswith("Event") for t in types) and node.get("startDate"):
                status = str(node.get("eventStatus", ""))
                if "Cancelled" not in status and "Postponed" not in status:
                    start, all_day = parse_when(node.get("startDate"), tz)
                    end, _ = parse_when(node.get("endDate"), tz)
                    start, end = wall_clock(start, tz), wall_clock(end, tz)
                    if start and not all_day and start.strftime("%H:%M") == "00:00" and (not end or end.strftime("%H:%M") in ("00:00", "23:59")):
                        all_day = True
                    if start:
                        url = node.get("url") if isinstance(node.get("url"), str) else ""
                        out.append({"title": clean(node.get("name")), "start": start, "end": end, "all_day": all_day,
                                    "place": place_of(node.get("location")), "url": urljoin(page_url, url) if url else page_url,
                                    "description": clean(node.get("description"), 400), "recurring": False, "via": "jsonld"})
            for key in ("@graph", "itemListElement", "item", "subEvent", "mainEntity"):
                if key in node:
                    stack.append(node[key])
    return out


def tribe_events(payload, tz: ZoneInfo):
    out = []
    for e in (payload or {}).get("events", []) if isinstance(payload, dict) else []:
        if e.get("status") not in (None, "publish"):
            continue
        utc = e.get("utc_start_date")
        start, all_day = (parse_when(utc.replace(" ", "T") + "Z", tz) if utc else parse_when(e.get("start_date"), tz))
        utc_end = e.get("utc_end_date")
        end, _ = (parse_when(utc_end.replace(" ", "T") + "Z", tz) if utc_end else parse_when(e.get("end_date"), tz))
        if e.get("all_day"):
            all_day = True
        venue = e.get("venue") if isinstance(e.get("venue"), dict) else {}
        place = ", ".join(x for x in (clean(venue.get("venue"), 80), clean(venue.get("address"), 80), clean(venue.get("city"), 60)) if x)
        if start:
            out.append({"title": clean(e.get("title")), "start": start, "end": end, "all_day": all_day, "place": place,
                        "url": e.get("url") or "", "description": clean(e.get("excerpt") or e.get("description"), 400),
                        "recurring": False, "via": "tribe"})
    return out


ICS_RX = re.compile(r"(?:webcal://[^\"'\s<>]+|https://[^\"'\s<>]+\.ics(?:\?[^\"'\s<>]*)?)", re.I)
TRIBE_RX = re.compile(r"tribe-events|/wp-json/tribe/events", re.I)
GCAL_RX = re.compile(r"calendar\.google\.com/calendar/", re.I)
CHURCHCENTER_RX = re.compile(r"[a-z0-9-]+\.churchcenter\.com", re.I)
AGENDA_RX = re.compile(r"agenda|[ée]v[ée]nement|calendrier|\bevents?\b|programme|activit[ée]s|rendez-vous", re.I)


def find_agenda(soup, base: str):
    host = urlparse(base).netloc.replace("www.", "")
    for a in soup.find_all("a", href=True):
        url = urljoin(base, a["href"]).split("#")[0]
        if urlparse(url).netloc.replace("www.", "") != host:
            continue
        text = a.get_text(" ", strip=True)[:60]
        if (AGENDA_RX.search(text) or AGENDA_RX.search(urlparse(url).path)) and not re.search(r"\.(pdf|jpe?g|png|ics|docx?)$", url, re.I):
            if url.rstrip("/") != base.rstrip("/"):
                return url
    return None


def feed_url(link: str) -> tuple[str, str] | None:
    """An agenda link pasted by a church -> (kind, ICS url). Mirrors src/nexus/lib/agenda.ts."""
    link = link.strip().replace("&amp;", "&")
    if link.startswith("webcal://"):
        link = "https://" + link[len("webcal://"):]
    parts = urlparse(link)
    if parts.scheme != "https":
        return None
    if parts.netloc == "calendar.google.com":
        if "/private-" in parts.path:
            return None                      # secret address: never accepted, the church must share the public one
        m = re.search(r"/calendar/ical/([^/]+)/public/basic\.ics", parts.path)
        if m:
            return "google", link
        m = re.search(r"[?&]src=([^&]+)", link) or re.search(r"[?&]cid=([^&]+)", link)
        if m:
            src = unquote(m.group(1))
            return "google", f"https://calendar.google.com/calendar/ical/{requests.utils.quote(src, safe='@.')}/public/basic.ics"
        return None
    if parts.netloc.endswith("planningcenteronline.com") or parts.netloc.endswith("churchcenter.com"):
        return ("churchcenter", link) if "/icals/" in parts.path or parts.path.endswith(".ics") else None
    return "ics", link



GCAL_EMBED_RX = re.compile(
    r"https?://(?:www\.)?calendar\.google\.com/calendar/[^\"'\s<>]+", re.I)
PGCAL_RX = re.compile(r'"gcal"\s*:\s*"([^"]+)"')


def public_google_calendar_ics(html_text: str) -> list[str]:
    """Public ICS URLs derived from Google Calendar embeds on a church page.

    Only public calendars: a /private- secret address is never accepted. The
    returned URLs are the documented public export
    (.../calendar/ical/<id>/public/basic.ics).
    """
    found: list[str] = []
    seen: set[str] = set()

    def add(url: str | None):
        if not url or "/private-" in url.lower() or url in seen:
            return
        seen.add(url)
        found.append(url)

    for raw in GCAL_EMBED_RX.findall(html_text or ""):
        parsed = feed_url(html.unescape(raw.replace("&amp;", "&")))
        if parsed and parsed[0] == "google":
            add(parsed[1])
    for match in PGCAL_RX.finditer(html_text or ""):
        for cal_id in match.group(1).split(","):
            cal_id = cal_id.strip()
            if not cal_id or "/private-" in cal_id.lower():
                continue
            add(
                "https://calendar.google.com/calendar/ical/"
                + requests.utils.quote(cal_id, safe="@.")
                + "/public/basic.ics"
            )
    return found


def fetch_public_google_ics(ics_url: str, tz: ZoneInfo, window, page: str, deadline: float):
    """Fetch a public Google Calendar ICS. robots.txt on calendar.google.com is not applied."""
    if not ics_url or "/private-" in ics_url.lower():
        return []
    parsed = feed_url(ics_url)
    if not parsed or parsed[0] != "google":
        return []
    r, _err = polite_get(parsed[1], check_robots=False, timeout=_remaining(deadline))
    if r is not None and r.status_code == 304:
        return None
    if r is None or r.status_code >= 400 or "BEGIN:VCALENDAR" not in (r.text or "")[:3000]:
        return []
    got = parse_ics(r.text, parsed[1], tz, window)
    for event in got:
        event["page"] = page
        event["via"] = "gcal"
        event["url"] = page
    return got


# ---- policy --------------------------------------------------------------------------------------------------------

def listed_churches(shards: str, countries: set[str]):
    for path in sorted(glob.glob(os.path.join(shards, "*.json"))):
        data = json.load(open(path, encoding="utf-8"))
        for rec in (data.values() if isinstance(data, dict) else data):
            if not isinstance(rec, dict) or rec.get("hid") or rec.get("cc") not in countries:
                continue
            yield rec


def policy_skip(rec) -> str | None:
    """Why this church stays out of the importer even though it has a website (None = in)."""
    if rec.get("den") in ("catholic", "orthodox"):
        return "non-evangelical"
    host = urlparse(rec.get("website") if "//" in (rec.get("website") or "") else "https://" + (rec.get("website") or "")).netloc.lower()
    if MAINLINE_HOSTS.search(host.split(":")[0]):
        return "mainline-website"
    text = fold(" | ".join(str(rec.get(k) or "") for k in ("name", "denOther", "network")))
    if MAINLINE_TEXT.search(text):
        return "mainline-name"
    return None


def is_private(event) -> bool:
    return bool(PRIVATE_RX.search(" ".join([event.get("place", ""), event.get("title", ""), event.get("description", "")])))


def is_routine(event) -> bool:
    title = event.get("title", "")
    if SPECIAL_RX.search(title):
        return False
    return bool(event.get("recurring") or ROUTINE_RX.search(title))


def guess_type(title: str) -> str:
    for kind, rx in TYPE_RULES:
        if rx.search(title):
            return kind
    return "autre"


def church_slug(rec) -> str:
    return rec.get("slug") or rec["id"]


# ---- per site ------------------------------------------------------------------------------------------------------

def _remaining(deadline: float) -> float:
    return deadline - time.time()



def _parse_changed_children(changed, rec, page, tz, window):
    """Parse secondary URLs that changed after a 304 homepage. Homepage body is not available."""
    events, sources = [], []
    child_urls = []
    for child, resp in changed:
        child_urls.append(child)
        text = resp.text or ""
        ctype = (resp.headers or {}).get("content-type", "")
        if "BEGIN:VCALENDAR" in text[:3000]:
            got = parse_ics(text, child, tz, window)
            via = "gcal" if "calendar.google.com" in child else "ics"
            for event in got:
                event["page"] = page
                if via == "gcal":
                    event["via"] = "gcal"
                    event["url"] = page
            events += got
            if via not in sources:
                sources.append(via)
            continue
        if "json" in ctype or child.rstrip("/").endswith("/events"):
            try:
                got = [dict(e, page=page) for e in tribe_events(resp.json(), tz)]
                events += got
                if "tribe" not in sources:
                    sources.append("tribe")
                continue
            except Exception:
                pass
        if "html" in ctype or "<" in text[:200]:
            soup = BeautifulSoup(text, "html.parser")
            if tdm_reserved(resp, soup):
                continue
            events += [dict(e, page=resp.url) for e in jsonld_events(soup, resp.url, tz)]
            if events and "jsonld" not in sources:
                sources.append("jsonld")
    return events, sources, child_urls


def crawl_site(rec, window, optout_hosts, previous_events=None):
    tz = church_tz(rec)
    website = rec["website"] if rec["website"].startswith("http") else "https://" + rec["website"]
    base = re.sub(r"^http://", "https://", website)
    log = {"id": rec["id"], "website": base, "status": "ok", "sources": [], "agenda": False, "hasSignal": False}
    host = urlparse(base).netloc.lower().removeprefix("www.")
    deadline = time.time() + SITE_BUDGET
    if record_opted_out(rec, set(), optout_hosts):
        log["status"] = "optout"
        return [], log
    if not robots_for(base).can_fetch(UA_TOKEN, base):
        log["status"] = "robots"
        return [], log
    r, err = polite_get(base, check_robots=False, timeout=_remaining(deadline))
    if r is None and err in ("SSLError", "ConnectionError") and ALLOW_HTTP:
        fallback = "http://" + base.split("://", 1)[1]
        if robots_for(fallback).can_fetch(UA_TOKEN, fallback):
            r, err = polite_get(fallback, check_robots=False, timeout=_remaining(deadline))
    if r is None or r.status_code >= 400:
        log["status"] = err or f"http-{r.status_code}"
        return [], log
    if r.status_code == 304:
        children = http_cache_children(base) or http_cache_children(r.url)
        changed = []
        all_not_modified = True
        for child in children:
            if _remaining(deadline) < 3:
                break
            cr, _cerr = polite_get(child, timeout=_remaining(deadline))
            if cr is not None and cr.status_code == 304:
                continue
            if cr is not None and cr.status_code < 400:
                all_not_modified = False
                changed.append((child, cr))
        if all_not_modified or not children:
            log["status"] = "not-modified"
            return [], log
        events, sources, child_urls = _parse_changed_children(changed, rec, r.url, tz, window)
        log["sources"] = sources
        log["keepPreviousSources"] = [name for name in ("jsonld", "ics", "tribe", "gcal") if name not in sources]
        log["hasSignal"] = bool(log["sources"] or log.get("agenda"))
        return events, log
    ctype = r.headers.get("content-type", "")
    if "html" not in ctype:
        log["status"] = "not-html"
        return [], log
    soup = BeautifulSoup(r.text, "html.parser")
    final_host = urlparse(r.url).netloc.lower().split(":")[0]
    identity = " ".join(filter(None, [soup.title.get_text(" ") if soup.title else "",
                                      *(m.get("content", "") for m in soup.find_all("meta", attrs={"property": "og:site_name"}))]))
    if MAINLINE_HOSTS.search(final_host) or MAINLINE_TEXT.search(fold(identity)) or soup.find("a", href=MAINLINE_LINK):
        log["status"] = "mainline-site"
        return [], log
    if tdm_reserved(r, soup) or tdmrep_reserved(r.url):
        log["status"] = "tdm-reserved"
        return [], log
    html_text = r.text
    events = [dict(e, page=r.url) for e in jsonld_events(soup, r.url, tz)]
    agenda = find_agenda(soup, r.url)
    log["agenda"] = bool(agenda)
    if agenda and _remaining(deadline) >= 3:
        r2, _ = polite_get(agenda, timeout=_remaining(deadline))
        if r2 is not None and r2.status_code == 304:
            log.setdefault("keepPreviousSources", [])
            if "jsonld" not in log["keepPreviousSources"]:
                log["keepPreviousSources"].append("jsonld")
        elif r2 is not None and r2.status_code < 400 and "html" in r2.headers.get("content-type", ""):
            soup2 = BeautifulSoup(r2.text, "html.parser")
            if tdm_reserved(r2, soup2):
                log["status"] = "tdm-reserved"
                return [], log
            html_text += r2.text
            events += [dict(e, page=r2.url) for e in jsonld_events(soup2, r2.url, tz)]
    if events:
        log["sources"].append("jsonld")
    # One church-hosted feed at most: the site's own .ics, else its WordPress events REST feed.
    # Public Google Calendar embeds are read after that (public ICS only; never a private address).
    ics = [u for u in ICS_RX.findall(html_text) if not GCAL_RX.search(u)]
    if ics and _remaining(deadline) >= 3:
        url = feed_url(ics[0])
        if url:
            r3, _ = polite_get(url[1], timeout=_remaining(deadline))
            if r3 is not None and r3.status_code == 304:
                log.setdefault("keepPreviousSources", [])
                if "ics" not in log["keepPreviousSources"]:
                    log["keepPreviousSources"].append("ics")
                log["sources"].append("ics")
            elif r3 is not None and r3.status_code < 400 and "BEGIN:VCALENDAR" in r3.text[:3000]:
                got = parse_ics(r3.text, url[1], tz, window)
                for e in got:
                    e["page"] = r.url
                events += got
                log["sources"].append("ics")
    elif TRIBE_RX.search(html_text) and _remaining(deadline) >= 3:
        url = urljoin(r.url, f"/wp-json/tribe/events/v1/events?per_page=50&start_date={window[0].date().isoformat()}")
        r3, _ = polite_get(url, timeout=_remaining(deadline))
        if r3 is not None and r3.status_code == 304:
            log.setdefault("keepPreviousSources", [])
            if "tribe" not in log["keepPreviousSources"]:
                log["keepPreviousSources"].append("tribe")
            log["sources"].append("tribe")
        elif r3 is not None and r3.status_code < 400:
            try:
                got = [dict(e, page=r.url) for e in tribe_events(r3.json(), tz)]
                events += got
                log["sources"].append("tribe")
            except ValueError:
                pass
    if "ics" not in log["sources"] and _remaining(deadline) >= 3:
        for ics_url in public_google_calendar_ics(html_text)[:2]:
            if _remaining(deadline) < 3:
                break
            got = fetch_public_google_ics(ics_url, tz, window, r.url, deadline)
            if got is None:
                log.setdefault("keepPreviousSources", [])
                if "gcal" not in log["keepPreviousSources"]:
                    log["keepPreviousSources"].append("gcal")
                if "gcal" not in log["sources"]:
                    log["sources"].append("gcal")
            elif got:
                events += got
                if "gcal" not in log["sources"]:
                    log["sources"].append("gcal")
    child_urls = []
    if agenda:
        child_urls.append(agenda)
    child_urls += [u for u in ICS_RX.findall(html_text) if not GCAL_RX.search(u)]
    child_urls += public_google_calendar_ics(html_text)[:2]
    if TRIBE_RX.search(html_text):
        child_urls.append(urljoin(r.url, f"/wp-json/tribe/events/v1/events?per_page=50&start_date={window[0].date().isoformat()}"))
    if child_urls:
        http_cache_add_children(base, child_urls)
        http_cache_add_children(r.url, child_urls)
    log["hasSignal"] = bool(log["sources"] or log.get("agenda"))
    return events, log


def crawl_feed(rec, link, window):
    """Opted-in agenda link from the church's dashboard (consent recorded on its page)."""
    tz = church_tz(rec)
    parsed = feed_url(link)
    log = {"id": rec["id"], "website": link, "status": "ok", "sources": []}
    if not parsed:
        log["status"] = "bad-link"
        return [], log
    kind, url = parsed
    # The church asked for this subscription, like adding it to a calendar app: one GET of its own feed.
    r, err = polite_get(url, check_robots=False)
    if r is not None and r.status_code == 304:
        log["status"] = "not-modified"
        return [], log
    if r is None or r.status_code >= 400 or "BEGIN:VCALENDAR" not in (r.text or "")[:3000]:
        log["status"] = err or "no-calendar"
        return [], log
    events = parse_ics(r.text, url, tz, window)
    for e in events:
        e["via"] = "feed-" + kind
        if not e["url"].startswith("https://"):
            e["url"] = rec.get("website") or ""
    log["sources"].append("feed-" + kind)
    return events, log


def tkey(title: str) -> str:
    """Title key for de-duplication; fold() drops non-Latin scripts, so keep them when nothing else is left."""
    return fold(title) or re.sub(r"\s+", " ", title).strip().lower()


def same_site(url: str, website: str) -> bool:
    a = urlparse(url).netloc.lower().removeprefix("www.")
    b = urlparse(website if "//" in website else "https://" + website).netloc.lower().removeprefix("www.")
    return bool(a) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def normalise(rec, raw, window, imported_at):
    lo, hi = window
    tz = church_tz(rec)
    out, seen = [], set()
    for e in sorted(raw, key=lambda x: x["start"]):
        start = e["start"].astimezone(tz)
        if not in_horizon(e.get("start"), lo, hi) or not e.get("title"):
            continue
        if is_private(e) or INTERNAL_RX.search(e["title"]) or HOUSE_RX.search(e["title"]):
            continue
        key = (tkey(e["title"]), start.strftime("%Y-%m-%dT%H:%M"))
        day_key = (tkey(e["title"]), start.date().isoformat())
        if key in seen or day_key in seen:     # same event read twice (JSON-LD + REST feed)
            continue
        seen.add(key)
        seen.add(day_key)
        end = e["end"].astimezone(tz) if e.get("end") else None
        all_day = e.get("all_day")
        event_id = "imp-" + hashlib.sha1(f"{rec['id']}|{key[1]}|{key[0]}".encode()).hexdigest()[:12]
        website = rec.get("website") or ""
        source_url = e.get("url") or ""
        if not source_url or not (same_site(source_url, website) or e["via"].startswith("feed-") or same_site(source_url, e.get("page") or "")):
            source_url = e.get("page") or website       # never a meeting link (Teams, Zoom…) or a third-party page
        if not source_url.startswith("http"):
            source_url = "https://" + source_url
        source_url = re.sub(r"^http://", "https://", source_url)
        out.append({
            "id": event_id,
            "title": e["title"],
            "type": guess_type(e["title"]),
            "date": start.date().isoformat(),
            "start": "" if all_day else start.strftime("%H:%M"),
            "end": "" if (all_day or not end or end.date() != start.date()) else end.strftime("%H:%M"),
            "endDate": end.date().isoformat() if end and end.date() > start.date() else "",
            "place": "" if e.get("place") == "En ligne" else tidy_place(e.get("place", ""), e["title"]),
            "online": e.get("place") == "En ligne",
            "city": rec.get("city") or "",
            "country": COUNTRY_NAMES.get(rec.get("cc"), rec.get("cc") or ""),
            "lat": rec.get("lat") or 0,
            "lng": rec.get("lng") or 0,
            "churchId": rec["id"],
            "churchSlug": church_slug(rec),
            "churchName": rec.get("name") or "",
            "sourceUrl": source_url,
            "source": e["via"],
            "routine": is_routine(e),
            "importedAt": imported_at,
        })
    titles, slots = {}, {}
    for x in out:
        titles[tkey(x["title"])] = titles.get(tkey(x["title"]), 0) + 1
        slots[x["start"]] = slots.get(x["start"], set()) | {x["date"]}
    for x in out:
        if titles[tkey(x["title"])] >= 3 and not SPECIAL_RX.search(x["title"]):
            x["routine"] = True
        if x["start"] and len(slots[x["start"]]) >= 5 and not SPECIAL_RX.search(x["title"]):
            x["routine"] = True
    # Cap per church: keep the non-routine ones first, then the nearest routine occurrences.
    special = [x for x in out if not x["routine"]]
    routine = [x for x in out if x["routine"]]
    return sorted(special[:PER_CHURCH] + routine[: max(0, PER_CHURCH - len(special))][:4], key=lambda x: (x["date"], x["start"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", default=os.path.join(ROOT, "public/osm/c"))
    ap.add_argument("--countries", default="FR")
    ap.add_argument("--horizon", type=int, default=60, help="days ahead")
    ap.add_argument("--limit", type=int, default=0, help="crawl at most N church sites in the rolling window (0 = one full lap or the time budget)")
    ap.add_argument("--offset", type=int, default=0, help="start the church cursor at N when no --coverage file is used")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--always-orgs", action=argparse.BooleanOptionalAction, default=True,
                    help="include every organisation site in this country every run (default on)")
    ap.add_argument("--coverage", default="", help="rolling cursor and signal memory (JSON). Empty skips persistence.")
    ap.add_argument("--no-signal-days", type=int, default=NO_SIGNAL_DAYS,
                    help="skip church sites with no events signal after a successful crawl for this many days")
    ap.add_argument("--hot-cap", type=int, default=HOT_CAP, help="max known event-page sites to refresh before the rolling window")
    ap.add_argument("--prioritize-events", action=argparse.BooleanOptionalAction, default=True,
                    help="refresh sites already known to have an events page or feed before the rolling window")
    ap.add_argument("--matrix-shard", type=int, default=0, help="0-based shard of the church list (for a matrix job)")
    ap.add_argument("--matrix-shards", type=int, default=1, help="number of church-list shards")
    ap.add_argument("--optout", default=os.path.join(ROOT, "public/events/optout.json"))
    ap.add_argument("--organisations", default=os.path.join(ROOT, "scripts/events/organisation-sites.json"),
                    help="evangelical organisation sites (id, slug, name, website). Empty file skips them.")
    ap.add_argument("--manual", default=os.path.join(ROOT, "scripts/events/manual.local.json"),
                    help="church-created events [{churchId, churchSlug, title, date}] used only to drop scraped duplicates")
    ap.add_argument("--store", default=os.path.join(ROOT, "data", "nexus-store.json"),
                    help="editor database: eventsImportOptOut and church-created events are read from here")
    ap.add_argument("--only", default="", help="comma-separated church or organisation ids/slugs (bounded run)")
    ap.add_argument("--only-file", default="", help="JSON list of ids/slugs, so a long batch does not depend on the shell")
    ap.add_argument("--cities", default="", help="comma-separated city names; organisation rows stay included")
    ap.add_argument("--seconds", type=int, default=0, help="stop after this many seconds and write what finished (0 = no budget)")
    ap.add_argument("--cache", default="", help="directory of raw responses; a later batch reuses them")
    ap.add_argument("--http-cache", default="", dest="http_cache",
                    help="JSON file of ETag / Last-Modified validators persisted between nightly runs")
    ap.add_argument("--skip-log", default="", help="per-site log from an earlier batch; those ids are not fetched again")
    ap.add_argument("--merge", action="store_true", help="keep still-current events from --out for churches this batch did not refresh")
    ap.add_argument("--public-manual", default=os.path.join(ROOT, "public/events/manual-events.json"),
                    help="hand-added events; scraped copies of the same church, date and title are dropped")
    ap.add_argument("--feeds", default=os.path.join(ROOT, "scripts/events/feeds.local.json"),
                    help="opted-in agenda links [{churchId|slug, url, consentAt}] exported from claimed pages "
                         "(agendaUrl + agendaConsentAt); kept out of git and out of public/")
    ap.add_argument("--out", default=os.path.join(ROOT, "public/events/index.json"))
    ap.add_argument("--log", default="", help="optional per-site log (JSON) for review; never committed")
    args = ap.parse_args()
    global CACHE_DIR
    CACHE_DIR = args.cache
    load_http_cache(args.http_cache)

    now = dt.datetime.now(dt.timezone.utc)
    window = (now - dt.timedelta(hours=6), now + dt.timedelta(days=args.horizon))
    imported_at = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    optout = json.load(open(args.optout, encoding="utf-8")) if os.path.exists(args.optout) else {}
    store_state = load_store_state(args.store)
    out_ids = set(optout.get("churchIds", [])) | set(optout.get("slugs", [])) | store_state["ids"]
    out_hosts = {h.lower().removeprefix("www.") for h in optout.get("hosts", [])} | store_state["hosts"]
    feeds = json.load(open(args.feeds, encoding="utf-8")) if os.path.exists(args.feeds) else []
    feeds = [f for f in feeds if f.get("url") and f.get("consentAt")]

    church_rows, skipped = [], {}
    by_key = {}
    countries = [item.strip() for item in args.countries.split(",") if item.strip()]
    allowed = set(countries)
    for rec in listed_churches(args.shards, allowed):
        by_key[rec["id"]] = rec
        by_key[church_slug(rec)] = rec
        if not rec.get("website"):
            continue
        if record_opted_out(rec, out_ids, out_hosts):
            skipped["optout"] = skipped.get("optout", 0) + 1
            continue
        why = policy_skip(rec)
        if why:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        church_rows.append(rec)
    org_rows = []
    if args.organisations and os.path.exists(args.organisations):
        org_rows = organisation_sites(json.load(open(args.organisations, encoding="utf-8")))
    org_allowed = []
    for rec in org_rows:
        by_key[rec["id"]] = rec
        by_key[rec["slug"]] = rec
        if rec.get("cc") and rec["cc"] not in allowed:
            continue
        if record_opted_out(rec, out_ids, out_hosts):
            skipped["optout"] = skipped.get("optout", 0) + 1
            continue
        why = policy_skip(rec)
        if why:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        org_allowed.append(rec)
    want = {item.strip() for item in args.only.split(",") if item.strip()}
    if args.only_file and os.path.exists(args.only_file):
        listed = json.load(open(args.only_file, encoding="utf-8"))
        want |= {str(item) for item in listed}
    skip_done = set()
    if args.skip_log and os.path.exists(args.skip_log):
        skip_done = {item.get("id") for item in json.load(open(args.skip_log, encoding="utf-8")) if isinstance(item, dict) and item.get("id")}
    previous_events = []
    previous_doc_early = {}
    if os.path.exists(args.out):
        try:
            previous_doc_early = json.load(open(args.out, encoding="utf-8"))
            previous_events = previous_doc_early.get("events") or []
        except (OSError, json.JSONDecodeError, AttributeError):
            previous_doc_early, previous_events = {}, []
    persist = bool(args.coverage) and not want and not args.cities
    coverage = load_coverage(args.coverage) if persist else empty_coverage()
    metas = []
    if want:
        pool = church_rows + org_allowed
        churches = [rec for rec in pool if rec.get("id") in want or rec.get("slug") in want]
        if skip_done:
            churches = [rec for rec in churches if rec.get("id") not in skip_done]
    elif args.cities:
        names = {item.strip().casefold() for item in args.cities.split(",") if item.strip()}
        churches = [rec for rec in org_allowed + church_rows if rec.get("kind") == "organisation" or (rec.get("city") or "").casefold() in names]
        if skip_done:
            churches = [rec for rec in churches if rec.get("id") not in skip_done]
    else:
        churches = []
        for cc in countries:
            ch = [rec for rec in church_rows if rec.get("cc") == cc]
            og = [rec for rec in org_allowed if not rec.get("cc") or rec.get("cc") == cc]
            if not persist and args.offset:
                coverage.setdefault("countries", {}).setdefault(cc, {})["cursor"] = args.offset
            batch, meta = assemble_batch(
                ch, og, country=cc, today=today_in_denver(now), coverage=coverage,
                limit=args.limit, always_orgs=args.always_orgs, prioritize=args.prioritize_events,
                hot_cap=args.hot_cap, no_signal_days=args.no_signal_days,
                shard=args.matrix_shard, shards=args.matrix_shards,
                skip_ids=skip_done, previous_events=previous_events,
            )
            churches.extend(batch)
            metas.append(meta)
    print(
        f"{len(churches)} sites to read ({len(org_allowed)} organisation sites in this country set), "
        f"skipped by policy: {skipped}",
        file=sys.stderr,
    )
    for meta in metas:
        print(
            f"  {meta['country']}: orgs={len(meta['orgIds'])} hot={len(meta['hotIds'])} "
            f"window={len(meta['windowIds'])} queue={meta['queueSize']} cursor={meta['cursor']} "
            f"cooldown={len(meta['cooldownSkipped'])} shard={meta['shard']}/{meta['shards']}",
            file=sys.stderr,
        )

    previous_by_church = {}
    for ev in previous_events:
        if isinstance(ev, dict) and ev.get("churchId"):
            previous_by_church.setdefault(ev["churchId"], []).append(ev)
    today_as_of = today_in_denver(now)

    def one(rec):
        try:
            raw, log = crawl_site(rec, window, out_hosts, previous_by_church.get(rec["id"]) or [])
            events = normalise(rec, raw, window, imported_at)
            keep = set(log.get("keepPreviousSources") or [])
            if keep:
                seen = {e.get("id") for e in events}
                for ev in previous_by_church.get(rec["id"]) or []:
                    if ev.get("source") in keep and ev.get("id") not in seen and still_current(ev, today_as_of):
                        events.append(ev)
                        seen.add(ev["id"])
            return events, log
        except Exception as exc:  # one broken site never stops the run
            return [], {"id": rec["id"], "status": "error:" + type(exc).__name__, "sources": []}

    results = []
    started = time.time()
    pending = list(churches)
    stopped = False
    while pending:
        if args.seconds and time.time() - started > args.seconds:
            stopped = True
            print(f"time budget reached, {len(pending)} sites not started", file=sys.stderr)
            break
        chunk, pending = pending[: max(1, args.workers)], pending[max(1, args.workers):]
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            results.extend(pool.map(one, chunk))
    events = [e for evts, _ in results for e in evts]
    logs = [log for _, log in results]
    for feed in feeds:
        rec = by_key.get(feed.get("churchId") or feed.get("slug"))
        if not rec or record_opted_out(rec, out_ids, out_hosts) or policy_skip(rec):
            continue
        raw, log = crawl_feed(rec, feed["url"], window)
        events = [e for e in events if e["churchId"] != rec["id"] or e["source"] == "jsonld"]
        events += normalise(rec, raw, window, imported_at)
        logs.append(log)

    unique, seen_global = [], set()
    for e in sorted(events, key=lambda e: (e["date"], e["start"], e["title"], e["churchId"])):
        key = (e["sourceUrl"], e["date"], e["start"], tkey(e["title"]))
        if key in seen_global:
            continue
        seen_global.add(key)
        unique.append(e)
    manual = json.load(open(args.manual, encoding="utf-8")) if os.path.exists(args.manual) else []
    if not isinstance(manual, list):
        manual = []
    public_manual = []
    if args.public_manual and os.path.exists(args.public_manual):
        loaded = json.load(open(args.public_manual, encoding="utf-8"))
        public_manual = loaded.get("events") if isinstance(loaded, dict) else loaded
        if not isinstance(public_manual, list):
            public_manual = []
    before = len(unique)
    events = dedupe_scraped(unique, list(manual) + list(public_manual) + list(store_state["manual"]))
    duplicates_dropped = before - len(events)
    previous_doc = {}
    previous = []
    if os.path.exists(args.out):
        try:
            previous_doc = json.load(open(args.out, encoding="utf-8"))
            previous = previous_doc.get("events") or []
        except (OSError, json.JSONDecodeError, AttributeError):
            previous_doc, previous = {}, []
    today = today_in_denver(now)
    expired_dropped = 0
    kept_previous = []
    if args.merge:
        refreshed = {log.get("id") for log in logs if log.get("status") == "ok"}
        for event in previous:
            if not isinstance(event, dict):
                continue
            if not still_current(event, today):
                expired_dropped += 1
                continue
            if event.get("churchId") in refreshed:
                continue
            kept_previous.append(event)
        merged, seen_ids = [], set()
        for event in kept_previous + events:
            if event.get("id") in seen_ids:
                continue
            seen_ids.add(event.get("id"))
            merged.append(event)
        events = merged
    previous_ids = {item.get("id"): item for item in previous if isinstance(item, dict)}
    added = sum(1 for event in events if event["id"] not in previous_ids)
    updated = sum(1 for event in events if event["id"] in previous_ids and previous_ids[event["id"]] != event)
    unchanged = len(events) - added - updated
    failed = sum(1 for log in logs if log.get("status") not in ("ok", "optout", "not-modified"))
    by_source, statuses = {}, {}
    for e in events:
        by_source[e["source"]] = by_source.get(e["source"], 0) + 1
    for log in logs:
        statuses[log["status"]] = statuses.get(log["status"], 0) + 1
    coverage_summary = []
    if persist and metas:
        finished_logs = logs  # includes only started sites
        for meta in metas:
            ids = set(meta.get("orgIds") or []) | set(meta.get("hotIds") or []) | set(meta.get("windowIds") or [])
            country_logs = [log for log in finished_logs if log.get("id") in ids]
            coverage = advance_coverage(coverage, meta, country_logs, today, imported_at, args.no_signal_days)
            state = (coverage.get("countries") or {}).get(meta["country"]) or {}
            coverage_summary.append({
                "country": meta["country"],
                "queueSize": meta["queueSize"],
                "cursor": meta["cursor"],
                "nextCursor": state.get("cursor"),
                "orgs": len(meta["orgIds"]),
                "hot": len(meta["hotIds"]),
                "window": len(meta["windowIds"]),
                "cooldownSkipped": len(meta["cooldownSkipped"]),
                "completedCycles": state.get("completedCycles") or 0,
                "lastFullPassAt": state.get("lastFullPassAt") or "",
                "scannedSincePass": state.get("scannedSincePass") or 0,
                "shard": meta["shard"],
                "shards": meta["shards"],
            })
        save_coverage(args.coverage, coverage)
    payload = dict(previous_doc) if args.merge else {}
    payload.update({
        "updatedAt": imported_at,
        "generator": UA,
        "horizonDays": args.horizon,
        "sitesRead": previous_doc.get("sitesRead") if args.merge else len(churches),
        "sitesWithEvents": len({e["churchId"] for e in events}),
        "batch": {"sitesAttempted": len(churches), "sitesFinished": len(logs), "stoppedEarly": stopped,
                  "seconds": args.seconds, "asOf": today, "coverage": coverage_summary},
        "counts": {"total": len(events), "added": added, "updated": updated, "unchanged": unchanged,
                   "duplicatesDropped": duplicates_dropped, "expiredDropped": expired_dropped,
                   "keptFromPrevious": len(kept_previous), "failedSites": failed,
                   "routine": sum(e["routine"] for e in events), "bySource": by_source,
                   "siteStatus": statuses, "skippedByPolicy": skipped,
                   "optOutFromStore": len(store_state["ids"]), "manualFromStore": len(store_state["manual"]),
                   "httpCache": http_cache_stats()},
        "events": events,
    })
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    if args.log:
        json.dump(logs, open(args.log, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    save_http_cache()
    print(json.dumps(payload["counts"], ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()
