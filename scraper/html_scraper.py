"""
Basel Radar · HTML Scraper
Scrapt alle HTML-Quellen aus sources.json.
Speichert Ergebnis in html_events.json.
Playwright für JS-rendered Sites, httpx für statische.
"""
import json, re, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

SOURCES_FILE = Path(__file__).parent.parent / "sources.json"
OUT = Path(__file__).parent.parent / "html_events.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

MONTHS_DE = {
    "januar":"01","februar":"02","märz":"03","april":"04",
    "mai":"05","juni":"06","juli":"07","august":"08",
    "september":"09","oktober":"10","november":"11","dezember":"12"
}

def parse_date(text):
    if not text:
        return None
    text = text.strip()
    # ISO
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return m.group()
    # DD.MM.YYYY
    m = re.search(r"(\d{1,2})\.(\d{2})\.(\d{4})", text)
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    # DD. Month YYYY (German)
    m = re.search(r"(\d{1,2})\.\s*(" + "|".join(MONTHS_DE) + r")\s*(\d{4})", text, re.IGNORECASE)
    if m:
        month = MONTHS_DE[m.group(2).lower()]
        return f"{m.group(3)}-{month}-{m.group(1).zfill(2)}"
    # DD.MM (current year assumed)
    m = re.search(r"(\d{1,2})\.(\d{2})\.?$", text.strip())
    if m:
        year = datetime.now().year
        return f"{year}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    return None

def absolute_url(url, base):
    if not url:
        return base
    if url.startswith("http"):
        return url
    p = urlparse(base)
    return f"{p.scheme}://{p.netloc}{url}"

def make_event(title, date, url, source, doors=None, close=None, artists=None):
    return {
        "title": title.strip() if title else "",
        "date": date or "",
        "doors": doors,
        "close": close,
        "venue": source["name"],
        "venue_url": source["url"],
        "url": url or source["url"],
        "artists": artists or [],
        "artist_urls": {},
        "genres": source.get("tags", []),
        "cost": None,
        "ig": source.get("ig"),
        "fb": source.get("fb"),
        "tags": source.get("tags", []),
        "source": source["id"],
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }

def get_hours(source, date):
    hours = source.get("hours") or {}
    doors, close = None, None
    if date and hours:
        try:
            d = datetime.strptime(date, "%Y-%m-%d")
            day_map = {0:"mon",1:"tue",2:"wed",3:"thu",4:"fri",5:"sat",6:"sun"}
            day_key = day_map[d.weekday()]
            h = hours.get(day_key) or hours.get("varies") or {}
            doors = h.get("doors")
            close = h.get("close")
        except:
            h = hours.get("varies") or {}
            doors = h.get("doors")
            close = h.get("close")
    elif hours.get("varies"):
        doors = hours["varies"].get("doors")
        close = hours["varies"].get("close")
    return doors, close

# ── Statischer Fetch ──────────────────────────────────────────────────────────
def fetch_static(url):
    try:
        import httpx
        from bs4 import BeautifulSoup
        r = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  HTTP Fehler {url}: {e}")
        return None

# ── Playwright Fetch ──────────────────────────────────────────────────────────
def fetch_playwright(url):
    try:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page()
            page.set_extra_http_headers({"Accept-Language": "de-CH,de;q=0.9"})
            page.goto(url, wait_until="networkidle", timeout=20000)
            html = page.content()
            browser.close()
        return BeautifulSoup(html, "html.parser")
    except Exception as e:
        print(f"  Playwright Fehler {url}: {e}")
        return fetch_static(url)  # Fallback

# ── PARSER ────────────────────────────────────────────────────────────────────

def parse_sommercasino(source):
    soup = fetch_static(source["url"])
    if not soup:
        return []
    events = []
    current_date = None
    for el in soup.select("p, h2"):
        text = el.get_text().strip()
        m = re.search(r"(\d{1,2})\.\s*(" + "|".join(MONTHS_DE) + r")\s*(\d{4})", text, re.IGNORECASE)
        if m:
            month = MONTHS_DE[m.group(2).lower()]
            current_date = f"{m.group(3)}-{month}-{m.group(1).zfill(2)}"
        elif el.name == "h2" and current_date:
            link = el.select_one("a[href]")
            if not link:
                continue
            title = link.get_text().strip()
            url = absolute_url(link["href"], source["url"])
            h4 = el.find_next("h4")
            doors = None
            if h4:
                tm = re.search(r"(\d{1,2}:\d{2})", h4.get_text())
                if tm:
                    doors = tm.group(1)
            d, c = get_hours(source, current_date)
            events.append(make_event(title, current_date, url, source, doors=doors or d, close=c))
    return events

def parse_nordstern(source):
    soup = fetch_static(source["url"])
    if not soup:
        return []
    events = []
    for li in soup.select("li"):
        h2 = li.select_one("h2")
        if not h2:
            continue
        h2text = h2.get_text().strip()
        # Format: "Fr, 27.03 / 23:00" or "Fr, 27.03 / 20:00"
        m = re.search(r"(\w{2}),?\s*(\d{1,2})\.(\d{2})(?:\.(\d{4}))?\s*/\s*(\d{2}:\d{2})", h2text)
        if not m:
            continue
        day = m.group(2).zfill(2)
        month = m.group(3)
        year = m.group(4) or str(datetime.now().year)
        doors = m.group(5)
        date = f"{year}-{month}-{day}"
        artists = [h.get_text().strip() for h in li.select("h3, h4") if h.get_text().strip()]
        # Remove h2 text from artists
        title = " / ".join(a for a in artists if a) or h2text
        link = li.select_one("a[href]")
        url = link["href"] if link and link["href"].startswith("http") else source["url"]
        d, c = get_hours(source, date)
        events.append(make_event(title, date, url, source, doors=doors or d, close=c))
    return events

def parse_denkmal(source):
    soup = fetch_static(source["url"])
    if not soup:
        return []
    events = []
    # Denkmal: Events in rows with date and title
    for row in soup.select("tr, .event-row, li"):
        cells = row.select("td")
        if len(cells) >= 2:
            date = parse_date(cells[0].get_text())
            title_el = cells[1].select_one("a") or cells[1]
            title = title_el.get_text().strip()
            link = cells[1].select_one("a[href]")
            url = absolute_url(link["href"] if link else "", source["url"])
        else:
            date_el = row.select_one(".date, time, [class*=date]")
            title_el = row.select_one("h2, h3, .title, a")
            if not title_el:
                continue
            date = parse_date(date_el.get_text() if date_el else "")
            title = title_el.get_text().strip()
            link = row.select_one("a[href]")
            url = absolute_url(link["href"] if link else "", source["url"])
        if title and len(title) > 2:
            d, c = get_hours(source, date)
            events.append(make_event(title, date, url, source, doors=d, close=c))
    return events

def parse_basellive(source):
    soup = fetch_static(source["url"])
    if not soup:
        return []
    events = []
    for item in soup.select("article, .event-item, .kalender-item, li[class*=event]"):
        title_el = item.select_one("h2, h3, .title, .event-title")
        date_el = item.select_one("time, .date, .datum, [class*=date]")
        link_el = item.select_one("a[href]")
        if not title_el:
            continue
        title = title_el.get_text().strip()
        date = parse_date(date_el.get_text() if date_el else "") or parse_date(item.get_text())
        url = absolute_url(link_el["href"] if link_el else "", source["url"])
        if title and len(title) > 2:
            d, c = get_hours(source, date)
            events.append(make_event(title, date, url, source, doors=d, close=c))
    return events

def parse_generic(source):
    """Generischer Parser — versucht Events aus jeder HTML-Struktur zu extrahieren."""
    # JS-rendered Sites brauchen Playwright
    js_sites = {"ava_club", "gannet", "basso", "portlandbasel", "netzwerkbasel", "viertel_klub"}
    if source["id"] in js_sites:
        soup = fetch_playwright(source["url"])
    else:
        soup = fetch_static(source["url"])
    if not soup:
        return []

    events = []

    # Selektoren der Reihe nach probieren
    candidates = []
    for sel in ["article", ".event", ".program-item", ".event-item", ".veranstaltung",
                "li[class*=event]", "div[class*=event]", ".card", "tr"]:
        found = soup.select(sel)
        if len(found) >= 2:
            candidates = found
            break

    if not candidates:
        # Fallback: alle Links mit Datumshinweis im Text
        for a in soup.select("a[href]"):
            if parse_date(a.get_text()):
                candidates.append(a)

    for item in candidates:
        title_el = item.select_one("h1, h2, h3, h4, .title, .name, strong")
        date_el = item.select_one("time, .date, .datum, [class*=date], [class*=datum]")
        link_el = item.select_one("a[href]")

        if not title_el:
            continue
        title = title_el.get_text().strip()
        if not title or len(title) < 3:
            continue

        date = parse_date(date_el.get_text() if date_el else "") or parse_date(item.get_text())
        url = absolute_url(link_el["href"] if link_el else "", source["url"])
        d, c = get_hours(source, date)
        events.append(make_event(title, date, url, source, doors=d, close=c))

    return events

# ── DISPATCHER ────────────────────────────────────────────────────────────────
PARSERS = {
    "sommercasino": parse_sommercasino,
    "nordstern": parse_nordstern,
    "denkmal": parse_denkmal,
    "basellive": parse_basellive,
}

def scrape(source):
    parser = PARSERS.get(source["id"], parse_generic)
    try:
        events = parser(source)
        print(f"[{source['id']}] {len(events)} Events")
        return events
    except Exception as e:
        print(f"[{source['id']}] Fehler: {e}")
        return []

def run():
    with open(SOURCES_FILE) as f:
        sources = json.load(f)["sources"]
    active = [s for s in sources if s.get("platform") == "html" and s.get("active")]
    print(f"HTML-Scraping: {len(active)} Quellen...")
    all_events = []
    for s in active:
        all_events.extend(scrape(s))
        time.sleep(0.5)  # Rate limiting
    OUT.write_text(json.dumps(all_events, indent=2, ensure_ascii=False))
    print(f"HTML total: {len(all_events)} → {OUT}")
    return all_events

if __name__ == "__main__":
    run()
