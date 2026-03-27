"""
Basel Radar · RA GraphQL Scraper
Scrapt Events von Resident Advisor via inoffizielle GraphQL API.
Gibt Liste von Event-Dicts zurück, kompatibel mit events_raw.json Format.
"""

import httpx
import json
from datetime import datetime, timezone

RA_GRAPHQL_URL = "https://ra.co/graphql"

RA_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://ra.co/events/ch/basel",
    "Origin": "https://ra.co",
    "Accept": "*/*",
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
    "ra-content-language": "en",
}

# RA Area IDs: Basel = 143, Zürich = 25
RA_SOURCES = [
    {"id": "ra_basel",  "name": "Resident Advisor Basel",  "area_id": "143"},
    {"id": "ra_zurich", "name": "Resident Advisor Zürich", "area_id": "25"},
]

RA_QUERY = """
query GET_EVENTS($filters: FilterInputDtoInput, $pageSize: Int) {
  eventListings(filters: $filters, pageSize: $pageSize, page: 1, sort: { date: { value: asc } }) {
    data {
      id
      event {
        id
        title
        date
        startTime
        endTime
        contentUrl
        images { filename }
        venue {
          name
          contentUrl
        }
        artists {
          name
          contentUrl
        }
        genres { name }
        cost
      }
    }
  }
}
"""


def scrape_ra(area_id: str, source_id: str, source_name: str, days_ahead: int = 30) -> list[dict]:
    """Scrapt RA Events für eine Area. Gibt normalisierte Event-Dicts zurück."""

    now = datetime.now(timezone.utc)
    from datetime import timedelta
    date_from = now.strftime("%Y-%m-%d")
    date_to = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    payload = {
        "query": RA_QUERY,
        "variables": {
            "pageSize": 100,
            "filters": {
                "areas": {"eq": area_id},
                "listingDate": {
                    "gte": date_from,
                    "lte": date_to,
                }
            }
        }
    }

    try:
        resp = httpx.post(RA_GRAPHQL_URL, json=payload, headers=RA_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[{source_id}] Fehler beim Abruf: {e}")
        return []

    listings = data.get("data", {}).get("eventListings", {}).get("data", [])
    events = []

    for listing in listings:
        ev = listing.get("event")
        if not ev:
            continue

        # Artists zusammenführen
        artists = [a["name"] for a in ev.get("artists", []) if a.get("name")]
        artist_urls = {
            a["name"]: f"https://ra.co{a['contentUrl']}"
            for a in ev.get("artists", [])
            if a.get("name") and a.get("contentUrl")
        }

        # Venue
        venue = ev.get("venue") or {}
        venue_name = venue.get("name", source_name)
        venue_url = f"https://ra.co{venue['contentUrl']}" if venue.get("contentUrl") else None

        # Zeiten
        start_time = ev.get("startTime", "")[:5] if ev.get("startTime") else None
        end_time = ev.get("endTime", "")[:5] if ev.get("endTime") else None

        # Genres
        genres = [g["name"].lower() for g in ev.get("genres", []) if g.get("name")]

        events.append({
            "title": ev.get("title", "").strip(),
            "date": ev.get("date", "")[:10],
            "doors": start_time,
            "close": end_time,
            "venue": venue_name,
            "venue_url": venue_url or f"https://ra.co{ev.get('contentUrl', '')}",
            "url": f"https://ra.co{ev.get('contentUrl', '')}",
            "artists": artists,
            "artist_urls": artist_urls,
            "genres": genres,
            "cost": ev.get("cost"),
            "ig": None,        # wird von sources.json ergänzt wenn venue bekannt
            "fb": None,
            "tags": genres,
            "source": source_id,
            "scraped_at": now.isoformat(),
        })

    print(f"[{source_id}] {len(events)} Events gefunden ({date_from} – {date_to})")
    return events


def run() -> list[dict]:
    """Scrapt alle RA-Quellen und gibt kombinierte Event-Liste zurück."""
    all_events = []
    for src in RA_SOURCES:
        events = scrape_ra(
            area_id=src["area_id"],
            source_id=src["id"],
            source_name=src["name"],
        )
        all_events.extend(events)
    return all_events


if __name__ == "__main__":
    events = run()
    print(f"\nTotal: {len(events)} Events")
    # Testausgabe erste 2
    for ev in events[:2]:
        print(json.dumps(ev, indent=2, ensure_ascii=False))
