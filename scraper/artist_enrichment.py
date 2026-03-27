"""
Basel Radar · Artist Enrichment
Sucht SoundCloud + Spotify Links für Artists via Gemini.
Läuft nach dedup.py, ergänzt artist_urls in events_raw.json.
"""

import json
import os
import re
import time
from pathlib import Path
import httpx

EVENTS_FILE = Path(__file__).parent.parent / "events_raw.json"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

# Cache damit gleicher Artist nicht 2x abgefragt wird
_artist_cache: dict[str, dict] = {}


def ask_gemini(prompt: str) -> str:
    """Schickt einen Prompt an Gemini Flash und gibt Text zurück."""
    if not GEMINI_API_KEY:
        print("  Kein GEMINI_API_KEY gesetzt — Artist Enrichment übersprungen")
        return ""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 500},
    }

    try:
        resp = httpx.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"  Gemini Fehler: {e}")
        return ""


def extract_urls(text: str) -> dict:
    """Extrahiert SoundCloud + Spotify URLs aus Gemini-Antwort."""
    result = {}

    sc_match = re.search(r"https?://soundcloud\.com/[\w\-/]+", text)
    if sc_match:
        result["soundcloud"] = sc_match.group().rstrip("/")

    sp_match = re.search(r"https?://open\.spotify\.com/artist/[\w]+", text)
    if sp_match:
        result["spotify"] = sp_match.group()

    return result


def enrich_artist(artist_name: str) -> dict:
    """Gibt SoundCloud + Spotify URLs für einen Artist zurück."""
    if artist_name in _artist_cache:
        return _artist_cache[artist_name]

    prompt = f"""Find the official SoundCloud and Spotify artist profile URLs for DJ/artist: "{artist_name}"

Reply ONLY with the URLs in this exact format (no other text):
SoundCloud: <url or "not found">
Spotify: <url or "not found">

Only include URLs you are confident about. No guessing."""

    text = ask_gemini(prompt)
    urls = extract_urls(text)

    _artist_cache[artist_name] = urls

    if urls:
        print(f"  {artist_name}: {urls}")
    else:
        print(f"  {artist_name}: keine URLs gefunden")

    # Rate limiting — Gemini Free hat 15 req/min
    time.sleep(1)

    return urls


def run() -> list[dict]:
    """Liest events_raw.json, ergänzt Artist-URLs, speichert zurück."""
    with open(EVENTS_FILE) as f:
        events = json.load(f)

    # Alle einzigartigen Artists sammeln
    all_artists = set()
    for ev in events:
        for artist in ev.get("artists", []):
            if artist and len(artist) > 1:
                all_artists.add(artist)

    print(f"Artist Enrichment: {len(all_artists)} Artists...")

    # Artists anreichern
    artist_links: dict[str, dict] = {}
    for artist in sorted(all_artists):
        artist_links[artist] = enrich_artist(artist)

    # Events updaten
    for ev in events:
        ev_artist_urls = ev.get("artist_urls", {})
        for artist in ev.get("artists", []):
            if artist in artist_links and artist_links[artist]:
                ev_artist_urls[artist] = artist_links[artist]
        ev["artist_urls"] = ev_artist_urls

    # Speichern
    with open(EVENTS_FILE, "w") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)

    print(f"Artist Enrichment abgeschlossen. {len(artist_links)} Artists verarbeitet.")
    return events


if __name__ == "__main__":
    # Test ohne API Key
    print("Test-Modus (kein API Key)")
    test = enrich_artist("Colyn")
    print(f"Colyn: {test}")
