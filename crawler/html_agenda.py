#!/usr/bin/env python3
"""TRIAL: dated events from plain HTML agenda pages of French evangelical church sites.

The main importer reads structured data only. This trial reads a church's own agenda page (agenda, événements,
programme, calendrier, actualités) and keeps a dated line only when it carries a French date in the next 6 months.
Same politeness as import_events.py: identifiable User-Agent, robots.txt, TDM reservation (meta/header/tdmrep.json),
opt-outs, >= 3 s between two requests to one host, homepage + at most 2 agenda pages per site. Kept per event: title,
date, time, church, source URL, plus a confidence score (0-100) and the reasons behind it. No description, no image.

    html_agenda.py --only-file ids.json --out events.json [--cache DIR] [--months 6]
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, re, sys, unicodedata
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
import import_events as ie  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

MONTHS = {"janvier": 1, "janv": 1, "jan": 1, "fevrier": 2, "fevr": 2, "fev": 2, "mars": 3, "avril": 4, "avr": 4, "mai": 5, "juin": 6,
          "juillet": 7, "juil": 7, "aout": 8, "septembre": 9, "sept": 9, "sep": 9, "octobre": 10, "oct": 10, "novembre": 11, "nov": 11,
          "decembre": 12, "dec": 12}
DAYS = {"lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4, "samedi": 5, "dimanche": 6,
        "lun": 0, "mar": 1, "mer": 2, "jeu": 3, "ven": 4, "sam": 5, "dim": 6}
M_RX = "|".join(sorted(MONTHS, key=len, reverse=True))
D_RX = "|".join(sorted(DAYS, key=len, reverse=True))
# all matching is done on accent-folded lower-case text
DATE_RX = re.compile(rf"(?:\b(?P<wd>{D_RX})\.?\s+)?(?:du\s+)?\b(?P<d>[0-3]?\d)(?:er)?(?:\s*(?:au|-|–|et)\s*(?:(?:{D_RX})\.?\s+)?(?P<d2>[0-3]?\d)(?:er)?)?"
                     rf"\s+(?P<m>{M_RX})\.?(?:\s+(?P<y>20\d\d))?\b")
NUM_RX = re.compile(r"(?:\b(?P<wd>" + D_RX + r")\.?\s+)?\b(?P<d>[0-3]?\d)[/.](?P<m>[01]?\d)[/.](?P<y>20\d\d|\d\d)\b")
TIME_RX = re.compile(r"(?:\b(?:a|des|de)\s+)?\b(?P<h>[012]?\d)\s*(?:h|:)\s*(?P<mi>[0-5]\d)?\b(?:\s*(?:a|-|–)\s*(?P<h2>[012]?\d)\s*(?:h|:)\s*(?P<mi2>[0-5]\d)?)?")
RECURRING_RX = re.compile(r"\b(?:chaque|tous les|toutes les|hebdomadaire|chaque semaine|1er (?:et|&) 3e|un (?:dimanche|samedi) sur deux)\b")
PUBLISHED_RX = re.compile(r"(?:publie|poste|mis a jour|modifie|ecrit|par\s+\w+\s*$|commentaires?|lire la suite|en savoir plus)")
JUNK_TITLE = re.compile(r"^(?:events? for.*|aucun evenement.*|.*\baucun evenement\b.*|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|lire la suite|en savoir plus|voir plus|plus d.infos?|details?|agenda|evenements?|programme|actualites?|accueil|calendrier|"
                        r"inscription|s.inscrire|cliquez ici|ici|prochains? evenements?|a venir|archives?|\W*)$")
AGENDA_LINK = re.compile(r"agenda|[ée]v[ée]nement|calendrier|programme|actualit|rendez-vous|\bevents?\b", re.I)

PAGE_WEIGHT = re.compile(r"agenda|evenement|calendrier|programme|events?")
# Follow a handful of event permalinks after the listing page (JSON-LD often lives there).
EVENT_PAGE_CAP = 6
HTML_SITE_BUDGET = 50.0
# Site chrome only. Classes like resurrect-entry-header hold the event title and date.
CHROME_CLASS = re.compile(
    r"^(?:site|page|main|global|primary|secondary)?[-_]?(?:menu|nav|navbar|navigation|footer|sidebar|"
    r"breadcrumbs?|cookies?|comments?|widget-area)$"
    r"|^(?:site|page|main|global|masthead)[-_]header$|^header$|^masthead$",
    re.I,
)
LISTING_SLUGS = {
    "agenda", "agendas", "calendrier", "evenement", "evenements", "event", "events",
    "programme", "programmes", "actualite", "actualites", "futurs-evenements", "rendez-vous",
}
CATEGORY_PATH = re.compile(r"/event-category/|/categorie|/categor(?:y|ies)/|/tag/|/author/|/page/\d+", re.I)


def is_chrome_class(name: str) -> bool:
    return bool(CHROME_CLASS.match(name or ""))


def is_site_header(el) -> bool:
    """True for the page masthead, false for an article's own <header>."""
    if el.name != "header":
        return False
    if el.find_parent("article") or el.find_parent("main"):
        return False
    classes = el.get("class") or []
    if any(is_chrome_class(c) for c in classes):
        return True
    # A bare <header> that is not inside an article is usually the site banner.
    return el.parent is not None and el.parent.name in ("body", "html", "div") and not any(
        "entry" in c or "event" in c or "article" in c or "post" in c for c in classes
    )


def event_permalinks(soup, base: str, already: set[str]) -> list[str]:
    """Same-host links that look like a single event page, not the listing itself."""
    host = urlparse(base).netloc.replace("www.", "")
    out = []
    for a in soup.find_all("a", href=True):
        url = urljoin(base, a["href"]).split("#")[0]
        if urlparse(url).netloc.replace("www.", "") != host:
            continue
        if url in already or url.rstrip("/") in {u.rstrip("/") for u in already}:
            continue
        path = urlparse(url).path or ""
        if CATEGORY_PATH.search(path) or re.search(r"\.(pdf|jpe?g|png|ics|docx?|mp3|mp4)$", path, re.I):
            continue
        if not (AGENDA_LINK.search(path) or AGENDA_LINK.search(a.get_text(" ", strip=True)[:60])):
            # still accept a dated slug under an events folder
            if not AGENDA_LINK.search(path):
                continue
        parts = [part for part in path.split("/") if part]
        if not parts or parts[-1].lower() in LISTING_SLUGS:
            continue
        if url not in out:
            out.append(url)
    return out


def jsonld_as_html_events(soup, page_url: str, today, months, tz, rec_name=""):
    """Turn schema.org Event blocks into html_agenda rows (high confidence)."""
    found = []
    if tz is None:
        tz = ZoneInfo("Europe/Paris")
    hi = today + dt.timedelta(days=31 * months)
    for raw in ie.jsonld_events(soup, page_url, tz):
        start = raw.get("start")
        if not start:
            continue
        local = start.astimezone(tz) if start.tzinfo else start
        day = local.date()
        if not (today <= day <= hi):
            continue
        title = ie.clean(raw.get("title") or "")
        if len(title) < 4:
            continue
        end = raw.get("end")
        end_local = end.astimezone(tz) if end and getattr(end, "tzinfo", None) else end
        found.append(dict(
            title=title[:120],
            date=day.isoformat(),
            start="" if raw.get("all_day") else local.strftime("%H:%M"),
            end="" if (raw.get("all_day") or not end_local or end_local.date() != day) else end_local.strftime("%H:%M"),
            endDate=end_local.date().isoformat() if end_local and end_local.date() > day else "",
            routine=bool(raw.get("recurring") or (ie.ROUTINE_RX.search(title) and not ie.SPECIAL_RX.search(title))),
            confidence=90,
            reasons=["jsonld"],
            snippet=title,
            sourceUrl=raw.get("url") or page_url,
        ))
    return found



def fold(s: str) -> str:
    return unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode().lower()


def agenda_links(soup, base):
    host = urlparse(base).netloc.replace("www.", "")
    out = []
    for a in soup.find_all("a", href=True):
        url = urljoin(base, a["href"]).split("#")[0]
        if urlparse(url).netloc.replace("www.", "") != host or re.search(r"\.(pdf|jpe?g|png|ics|docx?|mp3|mp4)$", url, re.I):
            continue
        text = a.get_text(" ", strip=True)[:60]
        if (AGENDA_LINK.search(text) or AGENDA_LINK.search(urlparse(url).path)) and url.rstrip("/") != base.rstrip("/") and url not in out:
            out.append(url)
    def listing_first(url: str) -> tuple:
        parts = [part for part in fold(urlparse(url).path).split("/") if part]
        path_len = len(urlparse(url).path.rstrip("/") or "/")
        if parts and parts[-1] in {fold(s) for s in LISTING_SLUGS}:
            # Shorter listing paths first (/futurs-evenements before /futurs-evenements/agenda).
            return (0, path_len)
        if PAGE_WEIGHT.search(fold(urlparse(url).path)):
            return (1, path_len)
        return (2, path_len)
    # Listing pages (agenda, futurs-evenements) before a single event permalink.
    out.sort(key=listing_first)
    return out[:3]


def resolve(day, month, year, wd, today, months):
    hi = today + dt.timedelta(days=31 * months)
    cands = [year] if year else [today.year, today.year + 1]
    for y in cands:
        try:
            d = dt.date(y, month, day)
        except ValueError:
            continue
        if today <= d <= hi:
            if wd is not None and d.weekday() != wd:
                return None, "weekday-mismatch"
            return d, "explicit-year" if year else "inferred-year"
    return None, "out-of-window"


BLOCK_TAGS = ["article", "li", "tr", "p", "div", "section", "h1", "h2", "h3", "h4", "h5", "dd", "dt", "td", "span", "a"]
HEAD_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "strong", "b"]


ICON_RX = re.compile(r"\b(?:chevron|arrow|keyboard|expand|navigate)_[a-z_]+\b|\b(?:min|@)\b", re.I)
ADDRESS_RX = re.compile(r"^\d+\s*(?:bis|ter)?,?\s+(?:rue|avenue|av\.?|bd|boulevard|chemin|route|place|all[ée]e|impasse|quai|cours)\b|\b\d{5}\b", re.I)
EXTRA_ROUTINE = re.compile(r"\bgdm\b|\bgd ?maison\b|\bgdj\b|groupes? de (?:maison|jeunes|quartier|partage)|\bpri[eè]res?\b|\bcadmin\b|\br[ée]p[ée]tition|\bchorale\b", re.I)
VAGUE_TITLE = re.compile(r"^(?:en ligne|online|campus [\w-]+|eglise [\w' -]{0,25}|salle [\w' -]{0,25}|annexe|general|jeunesse|enfants|\w{1,3})$")


def clean_title(t):
    t = ICON_RX.sub(" ", t)
    t = re.sub(r"^\s*events? for\b", " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" -–—|:•·,.")
    t = re.sub(r"^(?:\d{1,2}\s+)+(?=[A-Za-zÀ-ÿ])", "", t)          # leftover minutes / day numbers
    t = re.sub(r"^(?:le|la|du|au|les|ce|cette|,)\s*,?\s+", "", t, flags=re.I).strip(" -–—|:•·,.")
    return t[:120]


def strip_dates(text):
    f = fold(text)
    spans = [m.span() for rx in (DATE_RX, NUM_RX, TIME_RX) for m in rx.finditer(f)]
    keep = list(text)
    for a, b in spans:
        for i in range(a, min(b, len(keep))):
            keep[i] = " "
    return clean_title("".join(keep))


def extract(soup, page_url, today, months, tz, rec_name=""):
    for bad in soup(["script", "style", "noscript", "nav", "footer", "form", "aside", "iframe", "svg"]):
        bad.decompose()
    for bad in list(soup.find_all("header")):
        if is_site_header(bad) and not bad.decomposed:
            bad.decompose()
    for bad in [e for e in soup.find_all(class_=True) if e.name not in ("body", "html", "main", "article")
                and any(is_chrome_class(c) for c in e.get("class", []))]:
        if not bad.decomposed:
            bad.decompose()
    found, seen_nodes = [], set()
    years = [int(y) for y in re.findall(r"\b(20[12]\d)\b", soup.get_text(" ") + " " + page_url)]
    stale = bool(years) and sum(1 for y in years if y < today.year) > sum(1 for y in years if y >= today.year)
    stale = stale or bool(re.search(r"/(20[12]\d)/|-(20[12]\d)\b", page_url) and int(re.search(r"(20[12]\d)", page_url).group(1)) < today.year)
    els = [e for e in soup.find_all(BLOCK_TAGS)]
    els.sort(key=lambda e: len(e.get_text(" ", strip=True)))
    chosen = []
    for el in els:
        text = el.get_text(" ", strip=True)
        if not (6 <= len(text) <= 700):
            continue
        f = fold(text)
        m = DATE_RX.search(f) or NUM_RX.search(f)
        if not m:
            continue
        if any(c is el or el in c.parents for c in chosen):
            continue
        # a date-only element: climb to a parent that also carries a title
        node, rest = el, strip_dates(text)
        while len(re.sub(r"\W", "", rest)) < 4 and node.parent is not None and node.parent.name not in ("body", "html", "[document]"):
            node = node.parent
            t2 = node.get_text(" ", strip=True)
            if len(t2) > 700:
                break
            rest = strip_dates(t2)
        if len(re.sub(r"\W", "", rest)) < 4 or id(node) in seen_nodes:
            continue
        if any(node is c or node in c.parents or c in node.parents for c in chosen):
            continue
        chosen.append(node)
        seen_nodes.add(id(node))
    for node in chosen:
        text = node.get_text(" ", strip=True)
        f = fold(text)
        dates = list(DATE_RX.finditer(f)) or []
        num = list(NUM_RX.finditer(f))
        m = (dates or num)[0]
        g = m.groupdict()
        try:
            day = int(g["d"]); month = MONTHS[g["m"]] if not g["m"].isdigit() else int(g["m"])
            year = int(g["y"]) if g.get("y") else None
            if year and year < 100: year += 2000
        except (KeyError, ValueError):
            continue
        wd = DAYS.get(g.get("wd") or "", None) if g.get("wd") else None
        date, why = resolve(day, month, year, wd, today, months)
        if not date:
            continue
        if stale and not year:
            continue                                  # undated line on a page mostly about past years
        before = f[max(0, m.start() - 40):m.start()]
        reasons, score = [why], 30
        if PUBLISHED_RX.search(before):
            continue                                  # a news post's publication date, not an event
        heads = [h.get_text(" ", strip=True) for h in node.find_all(HEAD_TAGS) if len(h.get_text(strip=True)) >= 4]
        heads = [h for h in heads if len(re.sub(r"\W", "", strip_dates(h))) >= 4 and not JUNK_TITLE.match(fold(strip_dates(h)))]
        title = strip_dates(heads[0]) if heads else strip_dates(text)
        if heads: score += 15; reasons.append("heading")
        if not heads and len(text) > 160:
            title = strip_dates(text[:160]); score -= 10; reasons.append("long-text")
        if JUNK_TITLE.match(fold(title)) or len(title) < 4 or len(title.split()) > 18 or ADDRESS_RX.search(title):
            continue
        if VAGUE_TITLE.match(fold(title)) or fold(title) in fold(rec_name):
            score -= 25; reasons.append("vague-title")
        if title[:1].islower():
            score -= 10; reasons.append("sentence-fragment")
        if wd is not None: score += 15; reasons.append("weekday-ok")
        if year: score += 10; reasons.append("year")
        tm = None
        for t in TIME_RX.finditer(f[m.end(): m.end() + 60]):
            h = int(t.group("h"))
            if 6 <= h <= 23 and (t.group("mi") or re.search(r"h", t.group(0))):
                tm = t; break
        start = end = ""
        if tm:
            start = f"{int(tm.group('h')):02d}:{tm.group('mi') or '00'}"
            if tm.group("h2") and 0 <= int(tm.group("h2")) <= 23:
                end = f"{int(tm.group('h2')):02d}:{tm.group('mi2') or '00'}"
            score += 10; reasons.append("time")
        if ie.SPECIAL_RX.search(title): score += 10; reasons.append("special")
        recurring = bool(RECURRING_RX.search(fold(text)))
        routine = recurring or bool((ie.ROUTINE_RX.search(title) or EXTRA_ROUTINE.search(title)) and not ie.SPECIAL_RX.search(title))
        if recurring: score -= 25; reasons.append("recurring")
        if PAGE_WEIGHT.search(fold(urlparse(page_url).path)): score += 10; reasons.append("agenda-page")
        if len(dates) + len(num) > 3: score -= 10; reasons.append("many-dates")
        if ie.is_private({"place": "", "title": title, "description": text}) or ie.INTERNAL_RX.search(title):
            continue
        endd = ""
        if g.get("d2"):
            try:
                e2 = dt.date(date.year, date.month, int(g["d2"]))
                if e2 > date: endd = e2.isoformat(); reasons.append("range")
            except ValueError:
                pass
        found.append(dict(title=title, date=date.isoformat(), start=start, end=end, endDate=endd, routine=routine,
                          confidence=max(0, min(100, score)), reasons=reasons, snippet=text[:220], sourceUrl=page_url))
    return found


def crawl(rec, today, months, optout_hosts):
    tz = ie.church_tz(rec)
    base = re.sub(r"^http://", "https://", rec["website"] if rec["website"].startswith("http") else "https://" + rec["website"])
    log = {"id": rec["id"], "website": base, "status": "ok", "pages": []}
    if ie.record_opted_out(rec, set(), optout_hosts):
        return [], dict(log, status="optout")
    if not ie.robots_for(base).can_fetch(ie.UA_TOKEN, base):
        return [], dict(log, status="robots")
    deadline = time.time() + HTML_SITE_BUDGET
    r, err = ie.polite_get(base, check_robots=False, timeout=ie._remaining(deadline))
    if r is not None and r.status_code == 304:
        return [], dict(log, status="not-modified")
    if r is None or r.status_code >= 400 or "html" not in r.headers.get("content-type", ""):
        return [], dict(log, status=err or f"http-{getattr(r, 'status_code', 0)}")
    soup = BeautifulSoup(r.text, "html.parser")
    if ie.tdm_reserved(r, soup) or ie.tdmrep_reserved(r.url):
        return [], dict(log, status="tdm-reserved")
    events = []
    seen_pages = {r.url}
    events += jsonld_as_html_events(soup, r.url, today, months, tz, rec.get("name") or "")
    events += extract(soup, r.url, today, months, tz, rec.get("name") or "")
    pending_event_pages: list[str] = []
    for link in agenda_links(soup, r.url):
        if ie._remaining(deadline) < 3:
            break
        r2, err2 = ie.polite_get(link, timeout=ie._remaining(deadline))
        if r2 is None or r2.status_code >= 400 or "html" not in r2.headers.get("content-type", ""):
            log["pages"].append([link, err2 or getattr(r2, "status_code", 0)]); continue
        s2 = BeautifulSoup(r2.text, "html.parser")
        if ie.tdm_reserved(r2, s2):
            return [], dict(log, status="tdm-reserved")
        jsonld = jsonld_as_html_events(s2, r2.url, today, months, tz, rec.get("name") or "")
        got = extract(s2, r2.url, today, months, tz, rec.get("name") or "")
        log["pages"].append([r2.url, len(jsonld) + len(got)])
        events += jsonld + got
        seen_pages.add(r2.url)
        pending_event_pages += event_permalinks(s2, r2.url, seen_pages)
    pending_event_pages += event_permalinks(soup, r.url, seen_pages)
    followed = 0
    for link in pending_event_pages:
        if followed >= EVENT_PAGE_CAP or ie._remaining(deadline) < 3:
            break
        if link in seen_pages or link.rstrip("/") in {u.rstrip("/") for u in seen_pages}:
            continue
        r2, err2 = ie.polite_get(link, timeout=ie._remaining(deadline))
        followed += 1
        if r2 is None or r2.status_code >= 400 or "html" not in r2.headers.get("content-type", ""):
            log["pages"].append([link, err2 or getattr(r2, "status_code", 0)]); continue
        s2 = BeautifulSoup(r2.text, "html.parser")
        if ie.tdm_reserved(r2, s2):
            continue
        jsonld = jsonld_as_html_events(s2, r2.url, today, months, tz, rec.get("name") or "")
        got = jsonld or extract(s2, r2.url, today, months, tz, rec.get("name") or "")
        log["pages"].append([r2.url, len(got)])
        events += got
        seen_pages.add(r2.url)
    # de-duplicate (same title + date); keep the best score, and a start time when JSON-LD omitted one
    best = {}
    for e in events:
        k = (fold(e["title"])[:60], e["date"])
        prev = best.get(k)
        if prev is None:
            best[k] = e
            continue
        if e["confidence"] > prev["confidence"]:
            if not e.get("start") and prev.get("start"):
                e = dict(e, start=prev["start"], end=e.get("end") or prev.get("end"))
            best[k] = e
        elif e.get("start") and not prev.get("start") and e["confidence"] >= prev["confidence"] - 20:
            best[k] = dict(prev, start=e["start"], end=e.get("end") or prev.get("end"))
    out = []
    for e in sorted(best.values(), key=lambda e: (e["date"], e["start"])):
        e.update(id="html-" + hashlib.sha1(f"{rec['id']}|{e['date']}|{fold(e['title'])}".encode()).hexdigest()[:12],
                 churchId=rec["id"], churchSlug=ie.church_slug(rec), churchName=rec.get("name") or "", city=rec.get("city") or "",
                 country="France", lat=rec.get("lat") or 0, lng=rec.get("lng") or 0, type=ie.guess_type(e["title"]), source="html",
                 place="", online=False)
        out.append(e)
    # a title repeated on many dates is a routine series
    from collections import Counter
    c = Counter(fold(e["title"]) for e in out)
    for e in out:
        if c[fold(e["title"])] >= 3 and not ie.SPECIAL_RX.search(e["title"]):
            e["routine"] = True
    return out, log


AMPM_RX = re.compile(r"\s*,\s*(?:am|pm)\s*-\s*(?:am|pm)\s*$", re.I)
WEEKDAY_ONLY_RX = re.compile(r"^(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)(?:\s+(?:\d{1,2}|matin|soir|apr[eè]s-midi))?$", re.I)
PLACE_TITLE_RX = re.compile(r"^en ligne\b|\b\d{1,4}\s*(?:bis\s+)?(?:rue|avenue|av\.|bd|boulevard|chemin|place|all[ée]e|impasse|route)\b", re.I)
TAIL_RX = re.compile(r"\s+(?:La|Le|Les|Rendez-vous|Venez|Un|Une|Nous|Pour|Ce|Cette|Rejoignez)\s+\S+\s+\S+\s+\S+.*$")
SPECIAL_ONEOFF_RX = re.compile(r"no[eë]l|concert|thanksgiving|conf[ée]rence|kermesse|march[ée]|bapt[eê]me|f[eê]te|week-end|retraite|camp\b|spectacle|soir[ée]e|cours", re.I)
WEEKLY_WORDS_RX = re.compile(r"^(?:culte|c[ée]l[ée]bration|rassemblement dominical|rassemblement de pri[eè]re|[ée]tude biblique|r[ée]union de pri[eè]re|temps de pri[eè]re|journ[ée]e de pri[eè]re|je[uû]ne et pri[eè]re|pri[eè]re|permanence|[ée]vang[ée]lisation)\b", re.I)


def polish(events: list[dict]) -> list[dict]:
    """Publish-time cleanup: tidy titles, drop place/weekday-only titles, regularity from repeats, cross-record dupes."""
    out, seen = [], set()
    for e in events:
        t = AMPM_RX.sub("", e["title"]).strip()
        if len(t) > 50:
            t = re.split(r"\s*[!?]\s+|\.\s+|,\s+", t, maxsplit=1)[0].strip()
        if len(t) > 50:
            t = TAIL_RX.sub("", t).strip()
        t = t.strip(" \"'«»—-·")
        if len(t) < 4 or WEEKDAY_ONLY_RX.match(t) or PLACE_TITLE_RX.search(t):
            continue
        key = (urlparse(e["sourceUrl"]).netloc.lower().removeprefix("www."), e["date"], e.get("start", ""), fold(t))
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(e, title=t))
    counts: dict = {}
    for e in out:
        counts[(e["churchId"], fold(e["title"]))] = counts.get((e["churchId"], fold(e["title"])), 0) + 1
    for e in out:
        if SPECIAL_ONEOFF_RX.search(e["title"]):
            e["routine"] = False
        elif counts[(e["churchId"], fold(e["title"]))] >= 2 or WEEKLY_WORDS_RX.match(e["title"]):
            e["routine"] = True
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-file", default="")
    ap.add_argument("--all", action="store_true", help="every French church with a website")
    ap.add_argument("--organisations", default=os.path.join(ie.ROOT, "scripts/events/organisation-sites.json"))
    ap.add_argument("--shards", default=os.path.join(ie.ROOT, "public/osm/c"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--log", default="")
    ap.add_argument("--cache", default="")
    ap.add_argument("--http-cache", default="", dest="http_cache")
    ap.add_argument("--months", type=int, default=6)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seconds", type=int, default=0, help="stop after this many seconds and write what finished (0 = no budget)")
    ap.add_argument("--today", default="")
    ap.add_argument("--min-score", type=int, default=0, help="publish mode: keep events scoring at least this (70 recommended)")
    ap.add_argument("--publish", action="store_true", help="write importer-format rows (imp- ids, no snippet), drop house groups")
    ap.add_argument("--dedupe-with", default="", help="comma-separated importer outputs; churches with structured events there are skipped and same-day titles dropped")
    ap.add_argument("--matrix-shard", type=int, default=0)
    ap.add_argument("--matrix-shards", type=int, default=1)
    ap.add_argument("--optout", default=os.path.join(ie.ROOT, "public/events/optout.json"))
    a = ap.parse_args()
    ie.CACHE_DIR = a.cache
    ie.load_http_cache(a.http_cache)
    want = set(json.load(open(a.only_file))) if a.only_file else set()
    recs = [r for r in ie.listed_churches(a.shards, {"FR"}) if (a.all or r["id"] in want) and r.get("website") and not ie.policy_skip(r)]
    if a.organisations and os.path.exists(a.organisations):
        from collect import organisation_sites
        orgs = [r for r in organisation_sites(json.load(open(a.organisations, encoding="utf-8"))) if r.get("cc") == "FR" and not ie.policy_skip(r)]
        if not a.all:
            orgs = [r for r in orgs if r["id"] in want] if want else []
        recs += orgs
    optout = json.load(open(a.optout)) if os.path.exists(a.optout) else {}
    hosts = {h.lower().removeprefix("www.") for h in optout.get("hosts", [])}
    out_ids = set(optout.get("churchIds", [])) | set(optout.get("slugs", []))
    recs = [r for r in recs if r["id"] not in out_ids and r.get("slug") not in out_ids]
    if a.matrix_shards > 1:
        recs = [r for i, r in enumerate(sorted(recs, key=lambda r: r["id"])) if i % a.matrix_shards == a.matrix_shard]
    structured, existing = set(), set()
    for path in [x for x in a.dedupe_with.split(",") if x and os.path.exists(x)]:
        for ev in (json.load(open(path, encoding="utf-8")).get("events") or []):
            source = str(ev.get("source") or "")
            if source in ("jsonld", "ics", "tribe") or source.startswith("feed-"):
                structured.add(ev.get("churchId"))
            existing.add((ev.get("churchId"), ev.get("date"), fold(ev.get("title", ""))[:40]))
            existing.add(("*", ev.get("date"), fold(ev.get("title", ""))[:40]))
    recs = [r for r in recs if r["id"] not in structured]
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    events, logs = [], []
    started = time.time()
    stopped = False
    with ThreadPoolExecutor(a.workers) as ex:
        if a.seconds:
            futures = {}
            for rec in recs:
                if time.time() - started > a.seconds:
                    stopped = True
                    break
                futures[ex.submit(crawl, rec, today, a.months, hosts)] = rec
            for fut in as_completed(futures):
                got, log = fut.result()
                events += got
                logs.append(log)
        else:
            for got, log in ex.map(lambda r: crawl(r, today, a.months, hosts), recs):
                events += got
                logs.append(log)
    if a.publish:
        house = ie.HOUSE_RX
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        kept = []
        for e in events:
            if e["confidence"] < a.min_score or house.search(e["title"]):
                continue
            k = fold(e["title"])[:40]
            if (e["churchId"], e["date"], k) in existing or ("*", e["date"], k) in existing:
                continue
            kept.append({"id": "imp-" + e["id"], "title": e["title"], "type": e["type"], "date": e["date"], "start": e["start"], "end": e["end"],
                         "endDate": e["endDate"], "place": "", "online": False, "city": e["city"], "country": "France", "lat": e["lat"], "lng": e["lng"],
                         "churchId": e["churchId"], "churchSlug": e["churchSlug"], "churchName": e["churchName"], "sourceUrl": e["sourceUrl"],
                         "source": "html", "routine": e["routine"], "confidence": e["confidence"], "importedAt": now})
        events = polish(kept)
    json.dump({"generator": "html_agenda.py (trial)", "today": today.isoformat(), "sites": len(recs), "events": events},
              open(a.out, "w"), ensure_ascii=False, indent=1)
    if a.publish:   # html- statuses: the structured run decides which churches count as refreshed when shards merge
        logs = [dict(l, status="html-" + l["status"]) for l in logs]
    if a.log: json.dump({"logs": logs} if a.publish else logs, open(a.log, "w"), ensure_ascii=False, indent=1)
    ie.save_http_cache()
    print(json.dumps({"sites": len(recs), "sitesFinished": len(logs), "stoppedEarly": stopped,
                      "withEvents": len({e["churchId"] for e in events}), "events": len(events),
                      "high": sum(1 for e in events if e.get("confidence", 0) >= 60 and not e.get("routine"))}))


if __name__ == "__main__":
    main()
