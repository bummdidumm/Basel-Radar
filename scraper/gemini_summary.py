"""
Basel Radar · Gemini Summary
Liest events_raw.json und generiert ein Weekly Briefing als Markdown.
"""

import json
import os
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
import httpx

EVENTS_FILE = Path(__file__).parent.parent / "events_raw.json"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


def load_events(days_ahead: int = 7) -> list[dict]:
    """Lädt Events der nächsten N Tage aus events_raw.json."""
    with open(EVENTS_FILE) as f:
        events = json.load(f)

    today = date.today()
    cutoff = (today + timedelta(days=days_ahead)).isoformat()
    today_str = today.isoformat()

    return [
        ev for ev in events
        if ev.get("date", "") >= today_str and ev.get("date", "9999") <= cutoff
    ]


def format_event_for_prompt(ev: dict) -> str:
    """Formatiert ein Event für den Gemini-Prompt."""
    parts = []
    parts.append(f"- {ev.get('date', '?')} · {ev.get('title', '?')} @ {ev.get('venue', '?')}")

    if ev.get("doors"):
        close = f"–{ev['close']}" if ev.get("close") else ""
        parts.append(f"  Doors: {ev['doors']}{close}")

    if ev.get("artists"):
        parts.append(f"  Artists: {', '.join(ev['artists'])}")

    if ev.get("url"):
        parts.append(f"  Link: {ev['url']}")

    if ev.get("ig"):
        parts.append(f"  IG: {ev['ig']}")

    artist_urls = ev.get("artist_urls", {})
    for artist, urls in artist_urls.items():
        if urls.get("soundcloud"):
            parts.append(f"  SoundCloud {artist}: {urls['soundcloud']}")
        if urls.get("spotify"):
            parts.append(f"  Spotify {artist}: {urls['spotify']}")

    return "\n".join(parts)


def generate_briefing(events: list[dict]) -> str:
    """Generiert das Weekly Briefing via Gemini."""
    if not GEMINI_API_KEY:
        return generate_briefing_local(events)

    week_start = date.today()
    week_end = week_start + timedelta(days=7)

    events_text = "\n\n".join(format_event_for_prompt(ev) for ev in events)

    prompt = f"""Du bist Basel Radar — ein persönliches Event-Intelligence System für Basel.

Erstelle ein kompaktes Weekly Briefing für die Woche {week_start.strftime('%d.%m')} – {week_end.strftime('%d.%m.%Y')}.

EVENTS:
{events_text}

REGELN:
- Schreib auf Deutsch, direkt und konkret — kein Marketing-Sprech
- Keine Emojis
- Gruppiere nach Datum
- Pro Event: Titel, Venue, Uhrzeit (Doors/Close wenn vorhanden), kurze Beschreibung (1 Satz max)
- Alle Links direkt einbinden (Event-URL, IG, SoundCloud, Spotify)
- Highlight 2-3 Top-Picks der Woche ganz oben
- Format: Markdown

Beginne direkt mit dem Briefing, keine Einleitung."""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 2000,
        },
    }

    try:
        resp = httpx.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"Gemini Fehler: {e}")
        return generate_briefing_local(events)


def generate_briefing_local(events: list[dict]) -> str:
    """Fallback: Briefing ohne KI — strukturiertes Markdown."""
    week_start = date.today()
    lines = [
        f"# Basel Radar · Briefing {week_start.strftime('%d.%m.%Y')}",
        "",
    ]

    by_date: dict[str, list] = {}
    for ev in events:
        d = ev.get("date", "unbekannt")
        by_date.setdefault(d, []).append(ev)

    for d in sorted(by_date.keys()):
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            day_label = dt.strftime("%A, %d.%m.")
        except ValueError:
            day_label = d

        lines.append(f"## {day_label}")
        lines.append("")

        for ev in by_date[d]:
            hours = ""
            if ev.get("doors"):
                hours = f" · Doors {ev['doors']}"
                if ev.get("close"):
                    hours += f" – {ev['close']}"

            lines.append(f"**{ev['title']}** @ {ev['venue']}{hours}")

            if ev.get("url"):
                lines.append(f"[Event]({ev['url']})", )
            if ev.get("ig"):
                lines.append(f"[IG]({ev['ig']})")

            artist_urls = ev.get("artist_urls", {})
            for artist, urls in artist_urls.items():
                if urls.get("soundcloud"):
                    lines.append(f"[SoundCloud {artist}]({urls['soundcloud']})")
                if urls.get("spotify"):
                    lines.append(f"[Spotify {artist}]({urls['spotify']})")

            lines.append("")

    return "\n".join(lines)


def run(weekly: bool = False) -> str:
    """Generiert Briefing und speichert es lokal."""
    events = load_events(days_ahead=7 if weekly else 2)
    print(f"Briefing: {len(events)} Events in den nächsten {'7' if weekly else '2'} Tagen")

    briefing = generate_briefing(events)

    # Lokal speichern
    local_file = Path(__file__).parent.parent / "briefing_latest.md"
    local_file.write_text(briefing, encoding="utf-8")
    print(f"Lokal gespeichert: {local_file}")

    return briefing


if __name__ == "__main__":
    import sys
    weekly = "--weekly" in sys.argv
    briefing = run(weekly=weekly)
    print("\n--- BRIEFING PREVIEW ---")
    print(briefing[:1000])
