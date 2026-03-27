"""
Basel Radar · Deduplication
Entfernt doppelte Events aus verschiedenen Quellen.
Strategie: gleicher Titel (fuzzy) + gleiches Datum + ähnliche Venue → Duplikat.
Behält die "beste" Version (mehr Felder ausgefüllt, bevorzugt RA als Quelle).
"""

import json
import re
from pathlib import Path

OUTPUT_FILE = Path(__file__).parent.parent / "events_raw.json"
RA_EVENTS_FILE = Path(__file__).parent.parent / "ra_events.json"
HTML_EVENTS_FILE = Path(__file__).parent.parent / "html_events.json"

# Quellen-Priorität: höher = besser (wird behalten bei Duplikat)
SOURCE_PRIORITY = {
    "ra_basel": 10,
    "ra_zurich": 9,
    "nordstern": 8,
    "ava_club": 8,
    "kinker": 8,
    "elysia": 8,
    "humbug": 8,
    "basso": 8,
    "kuppel": 7,
    "viertel_klub": 7,
    "kaserne": 7,
    "gannet": 7,
    "basellive": 5,
    "denkmal": 6,
    "proz": 4,
    "eventfrog": 3,
    "songkick": 3,
}


def normalize_title(title: str) -> str:
    """Titel normalisieren für Vergleich: lowercase, nur alphanum."""
    title = title.lower()
    title = re.sub(r"[^a-z0-9äöüß\s]", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def normalize_venue(venue: str) -> str:
    """Venue-Name normalisieren."""
    venue = venue.lower()
    venue = re.sub(r"[^a-z0-9\s]", "", venue)
    return re.sub(r"\s+", " ", venue).strip()


def similarity(a: str, b: str) -> float:
    """Einfache Ähnlichkeit: gemeinsame Wörter / max Wörter."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    return len(intersection) / max(len(words_a), len(words_b))


def is_duplicate(ev_a: dict, ev_b: dict, threshold: float = 0.7) -> bool:
    """Prüft ob zwei Events Duplikate sind."""
    # Gleiches Datum ist Pflicht
    if ev_a.get("date") != ev_b.get("date"):
        return False

    title_a = normalize_title(ev_a.get("title", ""))
    title_b = normalize_title(ev_b.get("title", ""))

    # Exakter Titel-Match
    if title_a == title_b:
        return True

    # Fuzzy Match bei gleichem Datum + ähnlichem Titel
    if similarity(title_a, title_b) >= threshold:
        return True

    # Einer ist Teilstring des anderen (z.B. "Colyn" in "Colyn @ Nordstern")
    if title_a in title_b or title_b in title_a:
        if len(min(title_a, title_b, key=len)) >= 4:
            return True

    # Gleiche Venue + Datum → wahrscheinlich dasselbe Event
    venue_a = normalize_venue(ev_a.get("venue", ""))
    venue_b = normalize_venue(ev_b.get("venue", ""))
    if venue_a == venue_b and similarity(title_a, title_b) >= 0.5:
        return True

    return False


def best_event(ev_a: dict, ev_b: dict) -> dict:
    """Gibt das 'bessere' Event zurück — mehr Felder + höhere Quellen-Priorität."""
    prio_a = SOURCE_PRIORITY.get(ev_a.get("source", ""), 0)
    prio_b = SOURCE_PRIORITY.get(ev_b.get("source", ""), 0)

    # Höhere Priorität gewinnt
    winner = ev_a if prio_a >= prio_b else ev_b
    loser = ev_b if prio_a >= prio_b else ev_a

    # Fehlende Felder vom Verlierer ergänzen
    for key in ["doors", "close", "ig", "fb", "artists", "genres", "cost"]:
        if not winner.get(key) and loser.get(key):
            winner[key] = loser[key]

    # Artist-URLs zusammenführen
    if loser.get("artist_urls"):
        winner.setdefault("artist_urls", {}).update(loser["artist_urls"])

    # Alle Quellen tracken
    sources = winner.get("sources", [winner.get("source", "")])
    if loser.get("source") not in sources:
        sources.append(loser.get("source", ""))
    winner["sources"] = sources

    return winner


def dedup(events: list[dict]) -> list[dict]:
    """Dedupliziert eine Liste von Events."""
    deduplicated = []

    for ev in events:
        merged = False
        for i, existing in enumerate(deduplicated):
            if is_duplicate(ev, existing):
                deduplicated[i] = best_event(existing, ev)
                merged = True
                break
        if not merged:
            ev.setdefault("sources", [ev.get("source", "")])
            deduplicated.append(ev)

    return deduplicated


def filter_past(events: list[dict]) -> list[dict]:
    """Entfernt Events ohne Datum oder in der Vergangenheit."""
    from datetime import date
    today = date.today().isoformat()
    result = []
    for ev in events:
        d = ev.get("date", "")
        if d and d >= today:
            result.append(ev)
        elif not d:
            result.append(ev)  # Datum unbekannt → behalten
    return result


def run(events: list[dict]) -> list[dict]:
    """Dedupliziert und filtert Events. Speichert events_raw.json."""
    print(f"Dedup: {len(events)} Events rein...")

    events = filter_past(events)
    print(f"Nach Datum-Filter: {len(events)}")

    events = dedup(events)
    print(f"Nach Dedup: {len(events)} unique Events")

    # Nach Datum sortieren
    events.sort(key=lambda e: e.get("date", "9999"))

    # Speichern
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)
    print(f"Gespeichert: {OUTPUT_FILE}")

    return events


if __name__ == "__main__":
    from ra_scraper import run as run_ra_scraper
    from html_scraper import run as run_html_scraper

    ra_events = run_ra_scraper()
    html_events = run_html_scraper()
    scraped_events = ra_events + html_events

    result = run(scraped_events)
    print(f"\nResult: {len(result)} Events")
    for ev in result:
        print(f"  {ev['date']} · {ev['title']} · {ev['venue']} · sources: {ev.get('sources')}")
