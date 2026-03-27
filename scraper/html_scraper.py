"""
Basel Radar · HTML Scraper (hardened)
- Zielgerichtete Parser für fragile Quellen
- parse_generic ist stark eingeschränkt (nur Fallback)
- Search-Discovery nur zur Relokalisierung von toten URLs
"""

import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

import httpx
from bs4 import BeautifulSoup
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
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

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

    # YYYY-MM-DD
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        y, mo, d = map(int, m.groups())
        return _safe_date(y, mo, d)

    # DD.MM.YYYY
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", t)
    if m:
        d, mo, y = map(int, m.groups())
        return _safe_date(y, mo, d)

    # DD.MM.  (current year)
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.?(?!\d)", t)
    if m:
        d, mo = map(int, m.groups())
        y = datetime.now().year
        return _safe_date(y, mo, d)

    # DD Month YYYY
    m = re.search(r"\b(\d{1,2})\.?\s+([a-zäöü]+)\s+(\d{4})\b", t)
    if m:
        d = int(m.group(1))
        mo = MONTHS.get(m.group(2), 0)
        y = int(m.group(3))
        return _safe_date(y, mo, d)

    # Month DD, YYYY
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

def make_event(source, title, date, url, venue=None, doors=None):
def make_event(title, date, url, source, doors=None, close=None, artists=None):
    return {
        "title": (title or "").strip(),
        "date": date,
        "doors": doors,
        "close": None,
        "venue": venue or source["name"],
        "venue_url": source["url"],
        "url": urljoin(source["url"], url or ""),
        "artists": [],
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

def fetch_static(client: httpx.Client, url: str, retries=2, backoff=1.5):
    delay = 1.0
    last_exc = None
    for _ in range(retries + 1):
        try:
            r = client.get(url, headers=HEADERS, timeout=25, follow_redirects=True)
            if r.status_code == 429:
                raise httpx.HTTPStatusError("429 rate-limited", request=r.request, response=r)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser"), r.url
        except Exception as exc:
            last_exc = exc
            time.sleep(delay)
            delay *= backoff
    raise last_exc


def fetch_playwright(url: str):
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page()
        page.set_extra_http_headers({"Accept-Language": "de-CH,de;q=0.9"})
        page.goto(url, wait_until="networkidle", timeout=30000)
        html = page.content()
        browser.close()
    return BeautifulSoup(html, "html.parser")


def discover_relocated_url(client: httpx.Client, source: dict):
    """Nur URL-Relokalisierung (keine Eventdaten aus Suchresultaten)."""
    domain = urlparse(source["url"]).netloc.replace("www.", "")
    query = f"site:{domain} {source['name']} programm kalender"
    ddg = f"https://duckduckgo.com/html/?q={httpx.QueryParams({'q': query})['q']}"
    try:
        r = client.get(ddg, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.select("a.result__a[href], a[href]"):
        href = a.get("href") or ""
        if "uddg=" in href:
            q = parse_qs(urlparse(href).query).get("uddg", [""])[0]
            href = q or href
        if not href.startswith("http"):
            continue
        h_domain = urlparse(href).netloc.replace("www.", "")
        if h_domain.endswith(domain):
            return href
    return None


def fetch_source_soup(client: httpx.Client, source: dict):
    url = source["url"]
    try:
        soup, final_url = fetch_static(client, url, retries=3 if source["id"] == "basellive" else 1)
        return soup, str(final_url)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code if exc.response else None
        if code in {404, 410}:
            relocated = discover_relocated_url(client, source)
            if relocated:
                print(f"[{source['id']}] relocated {url} -> {relocated}")
                soup, final_url = fetch_static(client, relocated, retries=1)
                return soup, str(final_url)
        if source["id"] in {"kuppel", "kaserne", "viertel_klub"}:
            p_soup = fetch_playwright(url)
            if p_soup:
                return p_soup, url
        raise


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
        for it in items:
            if not isinstance(it, dict):
                continue
            if it.get("@type") != "Event":
                continue
            title = (it.get("name") or "").strip()
            date = parse_date(it.get("startDate") or "")
            if not title or not date:
                continue
            loc = it.get("location") if isinstance(it.get("location"), dict) else {}
            venue = loc.get("name") or source["name"]
            url = it.get("url") or source["url"]
            out.append(make_event(source, title, date, url, venue=venue, doors=parse_time(json.dumps(it))))
    return out


def unique_by_title_date(events):
    seen = set()
    out = []
    for e in events:
        key = (e.get("title", "").strip().lower(), e.get("date"), e.get("source"))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def parse_denkmal(source, client):
    soup, base = fetch_source_soup(client, source)
    events = parse_from_ldjson(source, soup)

    # Tages-/Event-Struktur
    for day in soup.select("section, article, li, tr"):
        text = day.get_text(" ", strip=True)
        if "denkmal" not in (source["name"].lower()):
            pass
        date = parse_date(text)
        link = day.select_one('a[href*="/de/"][href]') or day.select_one("a[href]")
        title_el = day.select_one("h2, h3, h4, .title, strong, a")
        if not link or not title_el or not date:
            continue
        title = title_el.get_text(" ", strip=True)
        if len(title) < 4:
            continue
        events.append(make_event(source, title, date, urljoin(base, link.get("href"))))
    return unique_by_title_date(events)


def parse_basellive(source, client):
    soup, base = fetch_source_soup(client, source)
    events = parse_from_ldjson(source, soup)

    for item in soup.select("article, li, .event-item, .calendar-item, .kalender-item"):
        text = item.get_text(" ", strip=True)
        date = parse_date(text)
        if not date:
            continue
        title_el = item.select_one("h2, h3, .title, a")
        link = item.select_one("a[href]")
        if not title_el or not link:
            continue
        title = title_el.get_text(" ", strip=True)
        if len(title) < 4:
            continue
        events.append(make_event(source, title, date, urljoin(base, link.get("href")), doors=parse_time(text)))
    return unique_by_title_date(events)


def parse_kuppel(source, client):
    soup, base = fetch_source_soup(client, source)
    events = parse_from_ldjson(source, soup)

    candidates = []
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        if any(x in href.lower() for x in ["/programm", "/event", "/events", "/konzert"]):
            candidates.append((a, urljoin(base, href)))

    # erst Karten/Teaser direkt
    for a, full in candidates[:120]:
        container = a.find_parent(["article", "li", "div"])
        text = (container or a).get_text(" ", strip=True)
        date = parse_date(text)
        title = a.get_text(" ", strip=True)
        if date and len(title) > 3:
            events.append(make_event(source, title, date, full, doors=parse_time(text)))

    # falls noch dünn: detailseiten nachziehen
    if len(events) < 5:
        for _, full in candidates[:25]:
            try:
                detail, _ = fetch_static(client, full, retries=0)
            except Exception:
                continue
            title_el = detail.select_one("h1, h2")
            body = detail.get_text(" ", strip=True)
            date = parse_date(body)
            if not date:
                continue
            title = title_el.get_text(" ", strip=True) if title_el else full.rsplit("/", 1)[-1]
            events.append(make_event(source, title, date, full, doors=parse_time(body)))
    return unique_by_title_date(events)
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


def parse_viertel(source, client):
    soup, base = fetch_source_soup(client, source)
    events = parse_from_ldjson(source, soup)
    for item in soup.select("article, li, .event, .programm-item"):
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
    return unique_by_title_date(events)


def parse_radiox(source, client):
    soup, base = fetch_source_soup(client, source)
    events = []
    for row in soup.select("article, li, tr, p"):
        text = row.get_text(" ", strip=True)
        date = parse_date(text)
        if not date:
            continue
        link = row.select_one("a[href]")
        title = link.get_text(" ", strip=True) if link else text[:120]
        if len(title) < 4:
            continue
        url = urljoin(base, link.get("href")) if link else base
        events.append(make_event(source, title, date, url, doors=parse_time(text)))
    return unique_by_title_date(events)


def parse_hirscheneck(source, client):
    soup, base = fetch_source_soup(client, source)
    events = parse_from_ldjson(source, soup)
    for item in soup.select("article, li, .event"):
        text = item.get_text(" ", strip=True)
        date = parse_date(text)
        if not date:
            continue
        link = item.select_one("a[href]")
        title_el = item.select_one("h2, h3, .title, a")
        if not title_el:
        title = title_el.get_text().strip()
        if not title or len(title) < 3:
            continue
        title = title_el.get_text(" ", strip=True)
        if len(title) < 4:
            continue
        events.append(make_event(source, title, date, urljoin(base, link.get("href")) if link else base, doors=parse_time(text)))
    return unique_by_title_date(events)


def parse_kaserne(source, client):
    soup, base = fetch_source_soup(client, source)
    events = parse_from_ldjson(source, soup)

    # homepage/event cards statt /en/program hardcode
    for card in soup.select("article, .event-card, li"):
        text = card.get_text(" ", strip=True)
        date = parse_date(text)
        if not date:
            continue
        link = card.select_one("a[href]")
        title_el = card.select_one("h2, h3, .title, a")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        if len(title) < 4:
            continue
        events.append(make_event(source, title, date, urljoin(base, link.get("href")) if link else base, doors=parse_time(text)))
    return unique_by_title_date(events)


def parse_generic(source, client):
    """Stark eingeschränkter Fallback: nur offensichtliche Event-Links mit Datum."""
    soup, base = fetch_source_soup(client, source)
    events = []

    for a in soup.select("a[href]"):
        href = (a.get("href") or "").lower()
        if not any(x in href for x in ["event", "agenda", "programm", "kalender", "konzert"]):
            continue
        if any(x in href for x in ["archiv", "archive", "history", "impressum", "kontakt"]):
            continue

        container = a.find_parent(["article", "li", "tr", "section", "div"])
        text = (container or a).get_text(" ", strip=True)
        date = parse_date(text)
        if not date:
            continue

        title = a.get_text(" ", strip=True)
        if len(title) < 5:
            continue
        if re.fullmatch(r"\d{1,2}[\.\-/]\d{1,2}(?:[\.\-/]\d{2,4})?", title):
            continue

        events.append(make_event(source, title, date, urljoin(base, a.get("href")), doors=parse_time(text)))
        if len(events) >= 25:
            break

    return unique_by_title_date(events)


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


def scrape_source(client, source):
    parser = PARSERS.get(source["id"], parse_generic)
    try:
        events = parser(source, client)
    except Exception as exc:
        print(f"[{source['id']}] WARN parser failed: {exc}")
        events = []

    # harte Qualitätsfilter
    clean = []
    for e in events:
        if not e.get("title") or len(e["title"].strip()) < 3:
            continue
        if not e.get("date"):
            continue
        clean.append(e)

    print(f"[{source['id']}] {len(clean)} Events")
    return clean


def run():
    assert_parse_date()
    data = json.loads(SOURCES_FILE.read_text())
    sources = [s for s in data.get("sources", []) if s.get("platform") == "html" and s.get("active")]

    counts = Counter()
    all_events = []
    with httpx.Client() as client:
        for source in sources:
            evs = scrape_source(client, source)
            counts[source["id"]] = len(evs)
            all_events.extend(evs)
            time.sleep(0.3)

    OUT.write_text(json.dumps(all_events, indent=2, ensure_ascii=False))
    print(f"HTML total: {len(all_events)} → {OUT}")
    print("Events pro Quelle:", dict(counts))
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
