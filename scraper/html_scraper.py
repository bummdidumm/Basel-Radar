"""
Basel Radar - HTML Scraper (hardened)
- source-specific parser bleiben erhalten
- fetch layer zentral über scraper.fetching
"""

import json
import re
import time
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scraper.fetching import adaptive_select, fetch_html

SOURCES_FILE = Path(__file__).parent.parent / "sources.json"
OUT = Path(__file__).parent.parent / "html_events.json"
DEBUG_REPORT = Path(__file__).parent.parent / "debug" / "fetch_report.json"

MONTHS = {
    "januar": 1, "jan": 1, "january": 1,
    "februar": 2, "feb": 2, "february": 2,
    "märz": 3, "maerz": 3, "mrz": 3, "mar": 3, "march": 3,
    "april": 4, "apr": 4,
    "mai": 5, "may": 5,
    "juni": 6, "jun": 6, "june": 6,
    "juli": 7, "jul": 7, "july": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "okt": 10, "oct": 10, "october": 10,
    "november": 11, "nov": 11,
    "dezember": 12, "dez": 12, "dec": 12, "december": 12,
}


def parse_date(text: str):
    if not text:
        return None
    t = re.sub(r"\s+", " ", text.strip().lower())

    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        return _safe_date(*map(int, m.groups()))

    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", t)
    if m:
        d, mo, y = map(int, m.groups())
        return _safe_date(y, mo, d)

    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.?(?!\d)", t)
    if m:
        d, mo = map(int, m.groups())
        return _safe_date(datetime.now().year, mo, d)

    m = re.search(r"\b(\d{1,2})\.?\s+([a-zäöü]+)\s+(\d{4})\b", t)
    if m:
        d = int(m.group(1))
        mo = MONTHS.get(m.group(2), 0)
        y = int(m.group(3))
        return _safe_date(y, mo, d)

    m = re.search(r"\b([a-zäöü]+)\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(\d{4})\b", t)
    if m:
        mo = MONTHS.get(m.group(1), 0)
        d = int(m.group(2))
        y = int(m.group(3))
        return _safe_date(y, mo, d)

    return None


def _safe_date(year: int, month: int, day: int):
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except Exception:
        return None


def parse_time(text: str):
    if not text:
        return None
    m = re.search(r"\b(\d{1,2}:\d{2})\b", text)
    if not m:
        return None
    hh, mm = m.group(1).split(":")
    return f"{int(hh):02d}:{mm}"


def make_event(source, title, date, url, venue=None, doors=None):
    return {
        "title": (title or "").strip(),
        "date": date,
        "doors": doors,
        "close": None,
        "venue": venue or source["name"],
        "venue_url": source["url"],
        "url": urljoin(source["url"], url or ""),
        "artists": [],
        "artist_urls": {},
        "genres": source.get("tags", []),
        "cost": None,
        "ig": source.get("ig"),
        "fb": source.get("fb"),
        "tags": source.get("tags", []),
        "source": source["id"],
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def discover_relocated_url(source: dict):
    domain = urlparse(source["url"]).netloc.replace("www.", "")
    query = f"site:{domain} {source['name']} programm kalender"
    ddg = f"https://duckduckgo.com/html/?q={httpx.QueryParams({'q': query})['q']}"
    try:
        r = httpx.get(ddg, timeout=20)
        r.raise_for_status()
    except Exception:
        return None

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.select("a.result__a[href], a[href]"):
        href = a.get("href") or ""
        if "uddg=" in href:
            href = parse_qs(urlparse(href).query).get("uddg", [""])[0] or href
        if not href.startswith("http"):
            continue
        if urlparse(href).netloc.replace("www.", "").endswith(domain):
            return href
    return None


def fetch_source_soup(source: dict):
    force_dynamic = source["id"] in {"basellive", "denkmal", "kuppel", "kaserne"}
    force_stealth = source["id"] in {"basellive", "denkmal"}

    fetched = fetch_html(
        source["url"],
        source_id=source["id"],
        prefer_dynamic=force_dynamic,
        prefer_stealth=force_stealth,
        debug_dump=True,
        debug_screenshot=False,
    )
    if fetched.get("soup"):
        return fetched

    if fetched.get("status_code") in {404, 410}:
        relocated = discover_relocated_url(source)
        if relocated:
            print(f"[{source['id']}] relocated {source['url']} -> {relocated}")
            fetched = fetch_html(
                relocated,
                source_id=source["id"],
                prefer_dynamic=True,
                prefer_stealth=force_stealth,
                debug_dump=True,
                debug_screenshot=False,
            )
    return fetched


def _append_report(entries):
    DEBUG_REPORT.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if DEBUG_REPORT.exists():
        try:
            existing = json.loads(DEBUG_REPORT.read_text())
        except Exception:
            existing = {}
    existing.setdefault("html", [])
    existing["html"].extend(entries)
    DEBUG_REPORT.write_text(json.dumps(existing, indent=2, ensure_ascii=False))


def _candidate_diagnostics(soup):
    if not soup:
        return 0, []
    nodes = soup.select("article,li,tr,.event,.event-item,.kalender-item,a[href]")
    samples = []
    for node in nodes[:10]:
        if getattr(node, "name", "") == "a":
            txt = node.get_text(" ", strip=True)
            href = node.get("href", "")
            samples.append(f"{txt[:80]} | {href}")
        else:
            samples.append(node.get_text(" ", strip=True)[:120])
    return len(nodes), samples


def parse_from_ldjson(source, soup):
    out = []
    for node in soup.select('script[type="application/ld+json"]'):
        raw = (node.string or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict) or item.get("@type") != "Event":
                continue
            title = (item.get("name") or "").strip()
            date = parse_date(item.get("startDate") or "")
            if not title or not date:
                continue
            loc = item.get("location") if isinstance(item.get("location"), dict) else {}
            venue = loc.get("name") or source["name"]
            out.append(make_event(source, title, date, item.get("url") or source["url"], venue=venue, doors=parse_time(json.dumps(item))))
    return out


def unique_by_title_date(events):
    seen, out = set(), []
    for e in events:
        key = (e.get("title", "").strip().lower(), e.get("date"), e.get("source"))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def parse_denkmal(source):
    fetched = fetch_source_soup(source)
    soup = fetched.get("soup")
    if not soup:
        return [], fetched
    events = parse_from_ldjson(source, soup)

    # adaptive selectors gezielt nur hier
    doc = fetched.get("document")
    nodes = adaptive_select(doc, "article,li", profile_key="denkmal_cards", auto_save=True, adaptive=False)
    if not nodes:
        nodes = adaptive_select(doc, "article,li", profile_key="denkmal_cards", auto_save=False, adaptive=True)

    for day in soup.select("section, article, li, tr"):
        text = day.get_text(" ", strip=True)
        date = parse_date(text)
        link = day.select_one('a[href*="/de/"][href]') or day.select_one("a[href]")
        title_el = day.select_one("h2, h3, h4, .title, strong, a")
        if not (date and link and title_el):
            continue
        title = title_el.get_text(" ", strip=True)
        if len(title) >= 4:
            events.append(make_event(source, title, date, urljoin(fetched.get("final_url") or source["url"], link.get("href"))))
    return unique_by_title_date(events), fetched


def parse_basellive(source):
    fetched = fetch_source_soup(source)
    soup = fetched.get("soup")
    if not soup:
        return [], fetched
    events = parse_from_ldjson(source, soup)

    doc = fetched.get("document")
    nodes = adaptive_select(doc, "article,.event-item,.kalender-item", profile_key="basellive_cards", auto_save=True, adaptive=False)
    if not nodes:
        nodes = adaptive_select(doc, "article,.event-item,.kalender-item", profile_key="basellive_cards", auto_save=False, adaptive=True)

    for item in soup.select("article, li, .event-item, .calendar-item, .kalender-item"):
        text = item.get_text(" ", strip=True)
        date = parse_date(text)
        title_el = item.select_one("h2, h3, .title, a")
        link = item.select_one("a[href]")
        if not (date and title_el and link):
            continue
        title = title_el.get_text(" ", strip=True)
        if len(title) >= 4:
            events.append(make_event(source, title, date, urljoin(fetched.get("final_url") or source["url"], link.get("href")), doors=parse_time(text)))
    return unique_by_title_date(events), fetched


def _simple_parser(source, selectors):
    fetched = fetch_source_soup(source)
    soup = fetched.get("soup")
    if not soup:
        return [], fetched

    events = parse_from_ldjson(source, soup)
    base = fetched.get("final_url") or source["url"]
    for item in soup.select(selectors):
        text = item.get_text(" ", strip=True)
        date = parse_date(text)
        if not date:
            continue
        title_el = item.select_one("h2, h3, .title, a")
        link = item.select_one("a[href]")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        if len(title) < 4:
            continue
        events.append(make_event(source, title, date, urljoin(base, link.get("href")) if link else base, doors=parse_time(text)))
    return unique_by_title_date(events), fetched


def parse_kuppel(source):
    return _simple_parser(source, "article, li, .event, .programm-item, a[href*='event']")


def parse_viertel(source):
    return _simple_parser(source, "article, li, .event, .programm-item")


def parse_radiox(source):
    return _simple_parser(source, "article, li, tr, p")


def parse_hirscheneck(source):
    return _simple_parser(source, "article, li, .event")


def parse_kaserne(source):
    return _simple_parser(source, "article, .event-card, li")


def parse_generic(source):
    fetched = fetch_source_soup(source)
    soup = fetched.get("soup")
    if not soup:
        return [], fetched
    events = []
    base = fetched.get("final_url") or source["url"]

    for a in soup.select("a[href]"):
        href = (a.get("href") or "").lower()
        if not any(x in href for x in ["event", "agenda", "programm", "kalender", "konzert"]):
            continue
        if any(x in href for x in ["archiv", "archive", "history", "impressum", "kontakt"]):
            continue

        container = a.find_parent(["article", "li", "tr", "section", "div"])
        text = (container or a).get_text(" ", strip=True)
        date = parse_date(text)
        title = a.get_text(" ", strip=True)
        if not date or len(title) < 5:
            continue
        if re.fullmatch(r"\d{1,2}[\.\-/]\d{1,2}(?:[\.\-/]\d{2,4})?", title):
            continue

        events.append(make_event(source, title, date, urljoin(base, a.get("href")), doors=parse_time(text)))
        if len(events) >= 25:
            break

    return unique_by_title_date(events), fetched


PARSERS = {
    "denkmal": parse_denkmal,
    "basellive": parse_basellive,
    "kuppel": parse_kuppel,
    "viertel_klub": parse_viertel,
    "radiox": parse_radiox,
    "hirscheneck": parse_hirscheneck,
    "kaserne": parse_kaserne,
}


def assert_parse_date():
    assert parse_date("2026-04-11") == "2026-04-11"
    assert parse_date("11.04.2026") == "2026-04-11"
    assert parse_date("11.04.") == f"{datetime.now().year}-04-11"
    assert parse_date("11. März 2026") == "2026-03-11"
    assert parse_date("Apr 7, 2026") == "2026-04-07"


def scrape_source(source):
    parser = PARSERS.get(source["id"], parse_generic)
    try:
        events, fetched = parser(source)
    except Exception as exc:
        print(f"[{source['id']}] WARN parser failed: {exc}")
        _append_report([{
            "source": source["id"],
            "status": "blocked",
            "mode": "failed",
            "status_code": None,
            "final_url": source.get("url"),
            "page_title": "",
            "block_reason": f"parser_exception:{exc}",
            "candidate_nodes": 0,
            "parsed_events": 0,
        }])
        return []

    candidate_nodes, samples = _candidate_diagnostics(fetched.get("soup"))
    clean = [e for e in events if e.get("title") and e.get("date")]
    print(
        f"[{source['id']}] mode={fetched.get('mode')} status={fetched.get('status_code')} "
        f"url={fetched.get('final_url')} title={fetched.get('page_title')!r} "
        f"reason={fetched.get('block_reason')} candidates={candidate_nodes} parsed={len(clean)}"
    )
    if fetched.get("soup") is not None and len(clean) == 0:
        print(f"[{source['id']}] parser miss samples: {samples}")

    status = "success" if len(clean) > 0 else ("blocked" if fetched.get("soup") is None else "parser_miss")
    _append_report([{
        "source": source["id"],
        "status": status,
        "mode": fetched.get("mode"),
        "status_code": fetched.get("status_code"),
        "final_url": fetched.get("final_url"),
        "page_title": fetched.get("page_title"),
        "block_reason": fetched.get("block_reason"),
        "candidate_nodes": candidate_nodes,
        "parsed_events": len(clean),
        "candidate_samples": samples if len(clean) == 0 else [],
        "content_snippet": fetched.get("content_snippet"),
    }])
    return clean


def run():
    assert_parse_date()
    DEBUG_REPORT.parent.mkdir(parents=True, exist_ok=True)
    if DEBUG_REPORT.exists():
        try:
            existing = json.loads(DEBUG_REPORT.read_text())
        except Exception:
            existing = {}
    else:
        existing = {}
    existing["html"] = []
    DEBUG_REPORT.write_text(json.dumps(existing, indent=2, ensure_ascii=False))

    data = json.loads(SOURCES_FILE.read_text())
    sources = [s for s in data.get("sources", []) if s.get("platform") == "html" and s.get("active")]

    counts = Counter()
    all_events = []
    for source in sources:
        evs = scrape_source(source)
        counts[source["id"]] = len(evs)
        all_events.extend(evs)
        time.sleep(0.3)

    OUT.write_text(json.dumps(all_events, indent=2, ensure_ascii=False))
    print(f"HTML total: {len(all_events)} -> {OUT}")
    print("Events pro Quelle:", dict(counts))
    return all_events


if __name__ == "__main__":
    run()
