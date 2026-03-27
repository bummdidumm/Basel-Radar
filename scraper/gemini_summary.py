"""
Basel Radar · Weekly Briefing
Liest events_raw.json, generiert Briefing via Gemini, speichert als briefing_latest.md.
Montags: vollständiges Weekly Briefing.
Täglich: wird nicht aufgerufen (nur Mo).
"""
import json, os, sys
from datetime import date, datetime, timedelta
from pathlib import Path
import httpx

BASE = Path(__file__).parent.parent
EVENTS_FILE = BASE / "events_raw.json"
OUT_FILE = BASE / "briefing_latest.md"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

def load_events(days=14):
    events = json.loads(EVENTS_FILE.read_text())
    today = date.today().isoformat()
    cutoff = (date.today() + timedelta(days=days)).isoformat()
    return [e for e in events if today <= e.get("date", "9999") <= cutoff]

def fmt_event(ev):
    lines = [f"- {ev.get('date','?')} · {ev.get('title','?')} @ {ev.get('venue','?')}"]
    if ev.get("doors"):
        lines.append(f"  Doors {ev['doors']}" + (f" – {ev['close']}" if ev.get("close") else ""))
    if ev.get("artists"):
        lines.append(f"  Artists: {', '.join(ev['artists'])}")
    if ev.get("url"):
        lines.append(f"  {ev['url']}")
    if ev.get("ig"):
        lines.append(f"  IG: {ev['ig']}")
    for artist, urls in ev.get("artist_urls", {}).items():
        if urls.get("soundcloud"):
            lines.append(f"  SC {artist}: {urls['soundcloud']}")
        if urls.get("spotify"):
            lines.append(f"  SP {artist}: {urls['spotify']}")
    return "\n".join(lines)

def generate(events):
    if not GEMINI_API_KEY or not events:
        return generate_local(events)
    week_end = date.today() + timedelta(days=14)
    prompt = f"""Du bist Basel Radar — persönliches Event-Intelligence für Basel.

Erstelle ein kompaktes Briefing für die nächsten 2 Wochen (bis {week_end.strftime('%d.%m.%Y')}).

EVENTS:
{chr(10).join(fmt_event(e) for e in events)}

REGELN:
- Deutsch, direkt, kein Marketing-Sprech
- Keine Emojis
- Gruppiere nach Datum
- Pro Event: Titel, Venue, Uhrzeit, 1 Satz Beschreibung max
- Links direkt einbinden (Event-URL, IG, SoundCloud, Spotify)
- 2-3 Top-Picks ganz oben hervorheben
- Format: Markdown
- Beginne direkt ohne Einleitung"""

    try:
        r = httpx.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": 0.3, "maxOutputTokens": 3000}},
            timeout=30
        )
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"Gemini Fehler: {e}")
        return generate_local(events)

def generate_local(events):
    today = date.today()
    lines = [f"# Basel Radar · {today.strftime('%d.%m.%Y')}", ""]
    by_date = {}
    for ev in events:
        by_date.setdefault(ev.get("date", "?"), []).append(ev)
    for d in sorted(by_date):
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            lines.append(f"## {dt.strftime('%A, %d.%m.')}")
        except:
            lines.append(f"## {d}")
        lines.append("")
        for ev in by_date[d]:
            h = f" · {ev['doors']}" + (f"–{ev['close']}" if ev.get("close") else "") if ev.get("doors") else ""
            lines.append(f"**{ev['title']}** @ {ev['venue']}{h}")
            if ev.get("url"):
                lines.append(f"[Event]({ev['url']})")
            if ev.get("ig"):
                lines.append(f"[IG]({ev['ig']})")
            for artist, urls in ev.get("artist_urls", {}).items():
                if urls.get("soundcloud"):
                    lines.append(f"[SoundCloud {artist}]({urls['soundcloud']})")
                if urls.get("spotify"):
                    lines.append(f"[Spotify {artist}]({urls['spotify']})")
            lines.append("")
    return "\n".join(lines)

def run():
    events = load_events(days=14)
    print(f"Briefing: {len(events)} Events in 14 Tagen")
    briefing = generate(events)
    OUT_FILE.write_text(briefing, encoding="utf-8")
    print(f"Briefing gespeichert: {OUT_FILE}")
    return briefing

if __name__ == "__main__":
    run()
