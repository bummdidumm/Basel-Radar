"""
Basel Radar · HTML Scraper
Scrapt Events von allen HTML-Quellen in sources.json.
Jede Quelle hat einen eigenen Parser — neuer Club = neue parse_* Funktion.
"""

import httpx
import json
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from pathlib import Path

SOURCES_FILE = Path(__file__).parent.parent / "sources.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
}


def get(url: str) -> BeautifulSoup | None:
    """HTTP GET mit Fehlerbehandlung. Gibt BeautifulSoup zurück oder None."""
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"  Fehler beim Abruf {url}: {e}")
        return None


def parse_date(text: str) -> str | None:
    """Versucht gängige Datumsformate in ISO YYYY-MM-DD zu parsen."""
    text = text.strip()
    patterns = [
        ("%d.%m.%Y", r"\d{2}\.\d{2}\.\d{4}"),
        ("%d.%m.%y", r"\d{2}\.\d{2}\.\d{2}"),
        ("%Y-%m-%d", r"\d{4}-\d{2}-\d{2}"),
        ("%d/%m/%Y", r"\d{2}/\d{2}/\d{4}"),
    ]
    for fmt, pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return datetime.strptime(match.group(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return None


def make_event(title, date, url, source, venue, ig=None, fb=None, doors=None, close=None, artists=None, tags=None) -> dict:
    """Erstellt ein normalisiertes Event-Dict."""
    return {
        "title": title.strip() if title else "",
        "date": date or "",
        "doors": doors,
        "close": close,
        "venue": venue,
        "venue_url": url,
        "url": url,
        "artists": artists or [],
        "artist_urls": {},
        "genres": tags or [],
        "cost": None,
        "ig": ig,
        "fb": fb,
        "tags": tags or [],
        "source": source["id"],
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── PARSER PRO QUELLE ────────────────────────────────────────────────────────

def parse_basellive(source: dict) -> list[dict]:
    soup = get(source["url"])
    if not soup:
        return []
    events = []
    for item in soup.select(".event-item, .event, article"):
        title_el = item.select_one("h2, h3, .title, .event-title")
        date_el = item.select_one(".date, time, .event-date")
        link_el = item.select_one("a[href]")
        if not title_el:
            continue
        date = parse_date(date_el.get_text() if date_el else "")
        url = link_el["href"] if link_el else source["url"]
        if url.startswith("/"):
            url = "https://www.basellive.ch" + url
        events.append(make_event(
            title=title_el.get_text(),
            date=date,
            url=url,
            source=source,
            venue="BaselLive",
            ig=source.get("ig"),
            fb=source.get("fb"),
            tags=source.get("tags", []),
        ))
    return events


def parse_proz(source: dict) -> list[dict]:
    soup = get(source["url"])
    if not soup:
        return []
    events = []
    for item in soup.select(".event, .veranstaltung, article, .listing-item"):
        title_el = item.select_one("h2, h3, .title")
        date_el = item.select_one(".date, time, .datum")
        link_el = item.select_one("a[href]")
        if not title_el:
            continue
        date = parse_date(date_el.get_text() if date_el else "")
        url = link_el["href"] if link_el else source["url"]
        if url.startswith("/"):
            url = "https://www.proz.online" + url
        events.append(make_event(
            title=title_el.get_text(),
            date=date,
            url=url,
            source=source,
            venue="Proz",
            ig=source.get("ig"),
            fb=source.get("fb"),
            tags=source.get("tags", []),
        ))
    return events


def parse_denkmal(source: dict) -> list[dict]:
    soup = get(source["url"])
    if not soup:
        return []
    events = []
    # Denkmal hat eine spezifische Struktur — Events in Tabellen oder Listen
    for item in soup.select("tr, .event, li.event, .program-item"):
        cells = item.select("td")
        if cells and len(cells) >= 2:
            date = parse_date(cells[0].get_text())
            title = cells[1].get_text().strip()
            link_el = item.select_one("a[href]")
            url = link_el["href"] if link_el else source["url"]
            if url.startswith("/"):
                url = "https://denkmal.org" + url
        else:
            title_el = item.select_one("h2, h3, .title, a")
            date_el = item.select_one(".date, time")
            link_el = item.select_one("a[href]")
            if not title_el:
                continue
            title = title_el.get_text().strip()
            date = parse_date(date_el.get_text() if date_el else "")
            url = link_el["href"] if link_el else source["url"]
            if url.startswith("/"):
                url = "https://denkmal.org" + url
        if title:
            events.append(make_event(
                title=title,
                date=date,
                url=url,
                source=source,
                venue="Denkmal",
                ig=source.get("ig"),
                tags=source.get("tags", []),
            ))
    return events


def parse_generic_venue(source: dict) -> list[dict]:
    """
    Generischer Parser für Venue-Websites.
    Funktioniert für: nordstern, ava_club, viertel_klub, kuppel, kinker,
    elysia, humbug, kaserne, gannet, holzpark, 8bar, basso, parterre,
    tinguely, hirscheneck, sommercasino, portlandbasel, netzwerkbasel,
    summe, stadtkonzerte, radiox, eventfrog, songkick
    """
    soup = get(source["url"])
    if not soup:
        return []

    events = []
    hours = source.get("hours") or {}

    # Selektoren die bei den meisten Venue-Sites funktionieren
    selectors = [
        "article", ".event", ".event-item", ".program-item",
        ".listing", "li.item", ".card", ".veranstaltung",
        "tr[class*=event]", "div[class*=event]",
    ]

    items = []
    for sel in selectors:
        items = soup.select(sel)
        if len(items) > 1:
            break

    # Fallback: alle Links mit Datumshinweis
    if not items:
        for a in soup.select("a[href]"):
            text = a.get_text()
            if parse_date(text) or re.search(r"\d{2}\.\d{2}", text):
                items.append(a)

    for item in items:
        title_el = item.select_one("h1, h2, h3, h4, .title, .name, strong")
        date_el = item.select_one(".date, time, .datum, [class*=date], [class*=datum]")
        link_el = item.select_one("a[href]")

        if not title_el:
            continue

        title = title_el.get_text().strip()
        if not title or len(title) < 2:
            continue

        date = parse_date(date_el.get_text() if date_el else "")

        # Fallback: Datum im ganzen Item-Text suchen
        if not date:
            date = parse_date(item.get_text())

        url = link_el["href"] if link_el else source["url"]
        # Relative URLs ergänzen
        if url.startswith("/"):
            from urllib.parse import urlparse
            base = urlparse(source["url"])
            url = f"{base.scheme}://{base.netloc}{url}"

        # Öffnungszeiten aus source als Fallback
        doors = None
        close = None
        if hours:
            # Wochentag aus Datum ermitteln wenn vorhanden
            if date:
                try:
                    d = datetime.strptime(date, "%Y-%m-%d")
                    day_map = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}
                    day_key = day_map[d.weekday()]
                    day_hours = hours.get(day_key) or hours.get("varies")
                    if day_hours:
                        doors = day_hours.get("doors")
                        close = day_hours.get("close")
                except ValueError:
                    pass
            if not doors and hours.get("varies"):
                doors = hours["varies"].get("doors")
                close = hours["varies"].get("close")

        events.append(make_event(
            title=title,
            date=date,
            url=url,
            source=source,
            venue=source["name"],
            ig=source.get("ig"),
            fb=source.get("fb"),
            doors=doors,
            close=close,
            tags=source.get("tags", []),
        ))

    return events


# ─── DISPATCHER ───────────────────────────────────────────────────────────────

PARSERS = {
    "basellive": parse_basellive,
    "proz": parse_proz,
    "denkmal": parse_denkmal,
}


def scrape(source: dict) -> list[dict]:
    """Wählt den richtigen Parser für eine Quelle."""
    parser = PARSERS.get(source["id"], parse_generic_venue)
    try:
        events = parser(source)
        print(f"[{source['id']}] {len(events)} Events")
        return events
    except Exception as e:
        print(f"[{source['id']}] Parser-Fehler: {e}")
        return []


def run() -> list[dict]:
    """Scrapt alle aktiven HTML-Quellen aus sources.json."""
    with open(SOURCES_FILE) as f:
        sources = json.load(f)["sources"]

    html_sources = [s for s in sources if s.get("platform") == "html" and s.get("active")]
    print(f"Starte HTML-Scraping für {len(html_sources)} Quellen...")

    all_events = []
    for source in html_sources:
        events = scrape(source)
        all_events.extend(events)

    print(f"\nTotal HTML-Events: {len(all_events)}")
    return all_events


if __name__ == "__main__":
    events = run()
    for ev in events[:2]:
        print(json.dumps(ev, indent=2, ensure_ascii=False))
