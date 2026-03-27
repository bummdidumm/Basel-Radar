"""Basel Radar - RA Scraper"""

import json
import re
import time
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scraper.fetching import fetch_html

BASE = Path(__file__).parent.parent
OUT = BASE / "ra_events.json"
SOURCES_FILE = BASE / "sources.json"
DEBUG_REPORT = BASE / "debug" / "fetch_report.json"


def load_ra_sources():
    data = json.loads(SOURCES_FILE.read_text())
    sources = data.get("sources", [])
    return [s for s in sources if s.get("id") in {"ra_basel", "ra_zurich"} and s.get("active")]


def parse_iso_date(value: str):
    if not value:
        return None
    m = re.search(r"(\d{4}-\d{2}-\d{2})", value)
    return m.group(1) if m else None


def parse_time_fragment(text: str):
    if not text:
        return None
    m = re.search(r"\b(\d{1,2}:\d{2})\b", text)
    if not m:
        return None
    hh, mm = m.group(1).split(":")
    return f"{int(hh):02d}:{mm}"


def extract_event_links(list_soup):
    links = set()
    for a in list_soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if re.match(r"^/events/\d+", href):
            links.add(urljoin("https://ra.co", href))
        elif re.match(r"^https?://ra\.co/events/\d+", href):
            links.add(href)
    return sorted(links)


def _append_report(entries):
    DEBUG_REPORT.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if DEBUG_REPORT.exists():
        try:
            existing = json.loads(DEBUG_REPORT.read_text())
        except Exception:
            existing = {}
    existing.setdefault("ra", [])
    existing["ra"].extend(entries)
    DEBUG_REPORT.write_text(json.dumps(existing, indent=2, ensure_ascii=False))


def parse_ra_event(url: str, source: dict):
    fetched = fetch_html(url, source_id=source["id"], prefer_dynamic=True, debug_dump=True)
    soup = fetched.get("soup")
    if not soup:
        return None

    date = None
    title = None
    venue = source.get("name")
    doors = None

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
            if isinstance(item, dict) and item.get("@type") == "Event":
                title = title or (item.get("name") or "").strip()
                date = date or parse_iso_date(item.get("startDate") or "")
                loc = item.get("location") or {}
                if isinstance(loc, dict):
                    venue = loc.get("name") or venue

    if not title:
        h1 = soup.select_one("h1")
        title = h1.get_text(" ", strip=True) if h1 else ""

    if not date:
        time_el = soup.select_one("time[datetime]")
        date = parse_iso_date((time_el.get("datetime") if time_el else "") or soup.get_text(" ", strip=True))

    body = soup.get_text(" ", strip=True)
    doors = parse_time_fragment(body)

    venue_el = soup.select_one('a[href*="/clubs/"], a[href*="/venues/"]')
    if venue_el:
        venue = venue_el.get_text(" ", strip=True) or venue

    if not title or not date:
        return None

    return {
        "title": title,
        "date": date,
        "doors": doors,
        "close": None,
        "venue": venue,
        "venue_url": source.get("url"),
        "url": url,
        "artists": [],
        "artist_urls": {},
        "genres": source.get("tags", []),
        "cost": None,
        "ig": None,
        "fb": None,
        "tags": source.get("tags", []),
        "source": source["id"],
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def scrape_source(source: dict, days=35):
    listing = fetch_html(
        source["url"],
        source_id=source["id"],
        prefer_dynamic=True,
        prefer_stealth=True,
        debug_dump=True,
        debug_screenshot=False,
    )
    soup = listing.get("soup")
    print(
        f"[{source['id']}] fetch mode={listing.get('mode')} status={listing.get('status_code')} "
        f"url={listing.get('final_url')} title={listing.get('page_title')!r} reason={listing.get('block_reason')}"
    )
    if not soup:
        print(f"[{source['id']}] WARN listing failed ({listing.get('mode')}) snippet={listing.get('content_snippet')[:140]!r}")
        _append_report([{
            "source": source["id"],
            "status": "blocked",
            "mode": listing.get("mode"),
            "status_code": listing.get("status_code"),
            "final_url": listing.get("final_url"),
            "page_title": listing.get("page_title"),
            "block_reason": listing.get("block_reason"),
            "content_snippet": listing.get("content_snippet"),
            "candidate_nodes": 0,
            "parsed_events": 0,
        }])
        return []

    links = extract_event_links(soup)
    candidate_nodes = len(links)
    if not links:
        print(f"[{source['id']}] WARN no event links found")
        samples = [a.get("href", "") for a in soup.select("a[href]")[:10]]
        print(f"[{source['id']}] candidate samples: {samples}")
        _append_report([{
            "source": source["id"],
            "status": "parser_miss",
            "mode": listing.get("mode"),
            "status_code": listing.get("status_code"),
            "final_url": listing.get("final_url"),
            "page_title": listing.get("page_title"),
            "block_reason": listing.get("block_reason"),
            "content_snippet": listing.get("content_snippet"),
            "candidate_nodes": candidate_nodes,
            "parsed_events": 0,
            "candidate_samples": samples,
        }])
        return []

    events = []
    today = datetime.now(timezone.utc).date()
    limit_date = today + timedelta(days=days)

    for idx, link in enumerate(links[:120]):
        try:
            ev = parse_ra_event(link, source)
        except Exception as exc:
            print(f"[{source['id']}] WARN event parsing failed {link}: {exc}")
            ev = None
        if not ev:
            continue
        try:
            d = datetime.strptime(ev["date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if today <= d <= limit_date:
            events.append(ev)
        if idx and idx % 15 == 0:
            time.sleep(0.2)

    print(f"[{source['id']}] candidates={candidate_nodes} parsed={len(events)}")
    if len(events) == 0:
        samples = [a.get("href", "") for a in soup.select("a[href]")[:10]]
        print(f"[{source['id']}] parser miss candidates: {samples}")
    _append_report([{
        "source": source["id"],
        "status": "success" if len(events) > 0 else "parser_miss",
        "mode": listing.get("mode"),
        "status_code": listing.get("status_code"),
        "final_url": listing.get("final_url"),
        "page_title": listing.get("page_title"),
        "block_reason": listing.get("block_reason"),
        "content_snippet": listing.get("content_snippet"),
        "candidate_nodes": candidate_nodes,
        "parsed_events": len(events),
    }])
    return events


def run():
    DEBUG_REPORT.parent.mkdir(parents=True, exist_ok=True)
    if DEBUG_REPORT.exists():
        try:
            existing = json.loads(DEBUG_REPORT.read_text())
        except Exception:
            existing = {}
    else:
        existing = {}
    existing["ra"] = []
    DEBUG_REPORT.write_text(json.dumps(existing, indent=2, ensure_ascii=False))

    sources = load_ra_sources()
    if not sources:
        OUT.write_text("[]")
        print("[ra] keine aktiven RA-Quellen")
        return []

    all_events = []
    for src in sources:
        try:
            all_events.extend(scrape_source(src))
        except Exception as exc:
            print(f"[{src['id']}] WARN source failed: {exc}")

    OUT.write_text(json.dumps(all_events, indent=2, ensure_ascii=False))
    print(f"RA total: {len(all_events)} -> {OUT}")
    return all_events


if __name__ == "__main__":
    run()
