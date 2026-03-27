"""Basel Radar - RA Scraper"""

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

BASE = Path(__file__).parent.parent
OUT = BASE / "ra_events.json"
SOURCES_FILE = BASE / "sources.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
    "Referer": "https://ra.co/",
}


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


def fetch_soup(client: httpx.Client, url: str):
    try:
        r = client.get(url, headers=HEADERS, timeout=25, follow_redirects=True)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception:
        p_soup = fetch_playwright(url)
        if p_soup is not None:
            return p_soup
        raise


def fetch_playwright(url: str):
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page()
            page.set_extra_http_headers({"Accept-Language": HEADERS["Accept-Language"]})
            page.goto(url, wait_until="networkidle", timeout=35000)
            html = page.content()
            browser.close()
        return BeautifulSoup(html, "html.parser")
    except Exception:
        return None


def extract_event_links(list_soup: BeautifulSoup, base_url: str):
    links = set()
    for a in list_soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if re.match(r"^/events/\d+", href):
            links.add(urljoin("https://ra.co", href))
        elif re.match(r"^https?://ra\.co/events/\d+", href):
            links.add(href)
    return sorted(links)


def parse_ra_event(client: httpx.Client, url: str, source: dict):
    try:
        soup = fetch_soup(client, url)
    except Exception as exc:
        print(f"[{source['id']}] WARN event fetch failed {url}: {exc}")
        return None

    ldjson_nodes = soup.select('script[type="application/ld+json"]')
    date = None
    title = None
    venue = source.get("name")
    doors = None

    for node in ldjson_nodes:
        raw = (node.string or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                continue
            t = item.get("@type")
            if t == "Event":
                title = title or (item.get("name") or "").strip()
                date = date or parse_iso_date(item.get("startDate") or "")
                loc = item.get("location") or {}
                if isinstance(loc, dict):
                    venue = (loc.get("name") or venue)

    if not title:
        t_el = soup.select_one("h1")
        title = t_el.get_text(" ", strip=True) if t_el else ""

    if not date:
        time_el = soup.select_one("time[datetime]")
        if time_el:
            date = parse_iso_date(time_el.get("datetime") or "")
        if not date:
            date = parse_iso_date(soup.get_text(" ", strip=True))

    if not doors:
        info_text = " ".join(x.get_text(" ", strip=True) for x in soup.select("time, p, li, div"))[:3000]
        doors = parse_time_fragment(info_text)

    venue_el = soup.select_one('a[href*="/clubs/"], a[href*="/venues/"]')
    if venue_el:
        venue = venue_el.get_text(" ", strip=True) or venue

    if not title or not date:
        return None

    now = datetime.now(timezone.utc).isoformat()
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
        "scraped_at": now,
    }


def scrape_source(client: httpx.Client, source: dict, days=35):
    source_id = source["id"]
    try:
        listing = fetch_soup(client, source["url"])
    except Exception as exc:
        print(f"[{source_id}] WARN listing failed: {exc}")
        return []

    links = extract_event_links(listing, source["url"])
    if not links:
        print(f"[{source_id}] WARN no event links found")
        return []

    events = []
    today = datetime.now(timezone.utc).date()
    limit_date = today + timedelta(days=days)

    for idx, link in enumerate(links[:120]):
        ev = parse_ra_event(client, link, source)
        if not ev:
            continue
        try:
            d = datetime.strptime(ev["date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if today <= d <= limit_date:
            events.append(ev)
        if idx and idx % 15 == 0:
            time.sleep(0.25)

    print(f"[{source_id}] {len(events)} Events")
    return events


def run():
    sources = load_ra_sources()
    if not sources:
        OUT.write_text("[]")
        print("[ra] keine aktiven RA-Quellen")
        return []

    all_events = []
    with httpx.Client() as client:
        for src in sources:
            try:
                all_events.extend(scrape_source(client, src))
            except Exception as exc:
                print(f"[{src['id']}] WARN source failed: {exc}")

    OUT.write_text(json.dumps(all_events, indent=2, ensure_ascii=False))
    print(f"RA total: {len(all_events)} → {OUT}")
    return all_events


if __name__ == "__main__":
    run()
