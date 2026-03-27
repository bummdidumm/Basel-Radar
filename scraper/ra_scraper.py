"""
Basel Radar · RA Scraper
Scrapt Events von Resident Advisor via GraphQL.
Speichert Ergebnis in ra_events.json.
"""
import json, time
import httpx
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).parent.parent / "ra_events.json"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://ra.co/events/ch/basel",
    "Origin": "https://ra.co",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "ra-content-language": "en",
    "x-ra-application-id": "web",
}

QUERY = """
query GET_EVENTS($filters: FilterInputDtoInput, $pageSize: Int, $page: Int) {
  eventListings(filters: $filters, pageSize: $pageSize, page: $page, sort: { date: { value: asc } }) {
    data {
      event {
        id
        title
        date
        startTime
        endTime
        contentUrl
        venue { name contentUrl }
        artists { name contentUrl }
        genres { name }
        cost
      }
    }
    totalResults
  }
}
"""

AREAS = [
    {"id": "ra_basel",  "name": "Resident Advisor Basel",  "area_id": "143"},
    {"id": "ra_zurich", "name": "Resident Advisor Zürich", "area_id": "25"},
]

def scrape_area(area_id, source_id, source_name, days=30):
    now = datetime.now(timezone.utc)
    date_from = now.strftime("%Y-%m-%d")
    date_to = (now + timedelta(days=days)).strftime("%Y-%m-%d")
    all_events = []

    for page in range(1, 4):  # max 3 pages
        payload = {
            "query": QUERY,
            "variables": {
                "pageSize": 50,
                "page": page,
                "filters": {
                    "areas": {"eq": area_id},
                    "listingDate": {"gte": date_from, "lte": date_to}
                }
            }
        }
        try:
            r = httpx.post("https://ra.co/graphql", json=payload, headers=HEADERS, timeout=20)
            r.raise_for_status()
            data = r.json()
            listings = data.get("data", {}).get("eventListings", {}).get("data", [])
            if not listings:
                break
            for l in listings:
                ev = l.get("event")
                if not ev:
                    continue
                artists = [a["name"] for a in ev.get("artists", []) if a.get("name")]
                venue = ev.get("venue") or {}
                all_events.append({
                    "title": ev.get("title", "").strip(),
                    "date": (ev.get("date") or "")[:10],
                    "doors": (ev.get("startTime") or "")[:5] or None,
                    "close": (ev.get("endTime") or "")[:5] or None,
                    "venue": venue.get("name", source_name),
                    "venue_url": "https://ra.co" + venue.get("contentUrl", ""),
                    "url": "https://ra.co" + ev.get("contentUrl", ""),
                    "artists": artists,
                    "artist_urls": {},
                    "genres": [g["name"].lower() for g in ev.get("genres", [])],
                    "cost": ev.get("cost"),
                    "ig": None, "fb": None,
                    "tags": [g["name"].lower() for g in ev.get("genres", [])],
                    "source": source_id,
                    "scraped_at": now.isoformat(),
                })
            total = data.get("data", {}).get("eventListings", {}).get("totalResults", 0)
            if len(all_events) >= total:
                break
            time.sleep(1)
        except Exception as e:
            print(f"[{source_id}] Fehler Seite {page}: {e}")
            break

    print(f"[{source_id}] {len(all_events)} Events ({date_from}–{date_to})")
    return all_events

def run():
    events = []
    for a in AREAS:
        events.extend(scrape_area(a["area_id"], a["id"], a["name"]))
    OUT.write_text(json.dumps(events, indent=2, ensure_ascii=False))
    print(f"RA total: {len(events)} → {OUT}")
    return events

if __name__ == "__main__":
    run()
