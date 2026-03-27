"""
Basel Radar · Artist Enrichment
Sucht SoundCloud + Spotify Links für Artists via Gemini.
Nur für RA-Events (die haben strukturierte Artist-Daten).
Rate limit: 4 sec zwischen Requests, max 20 Artists pro Run.
"""
import json, os, re, time
from pathlib import Path
import httpx

BASE = Path(__file__).parent.parent
EVENTS_FILE = BASE / "events_raw.json"
CACHE_FILE = BASE / "artist_cache.json"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

def load_cache():
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}

def save_cache(cache):
    CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False))

def ask_gemini(prompt, retries=3):
    if not GEMINI_API_KEY:
        return ""
    for attempt in range(retries):
        try:
            r = httpx.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"temperature": 0, "maxOutputTokens": 200}},
                timeout=15
            )
            if r.status_code == 429:
                wait = 30 * (attempt + 1)
                print(f"  Rate limit — warte {wait}s...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            print(f"  Gemini Fehler: {e}")
            time.sleep(5)
    return ""

def enrich_artist(name, cache):
    if name in cache:
        return cache[name]
    prompt = f"""Find the official SoundCloud and Spotify artist profile URLs for the DJ/artist named "{name}".
Reply ONLY in this exact format:
SoundCloud: <url or not found>
Spotify: <url or not found>
Be conservative — only include URLs you are certain about."""
    text = ask_gemini(prompt)
    result = {}
    sc = re.search(r"soundcloud\.com/[\w\-]+", text)
    sp = re.search(r"open\.spotify\.com/artist/\w+", text)
    if sc:
        result["soundcloud"] = "https://" + sc.group().rstrip("/")
    if sp:
        result["spotify"] = "https://" + sp.group()
    cache[name] = result
    if result:
        print(f"  {name}: {result}")
    time.sleep(4)  # 15 req/min limit
    return result

def run():
    if not GEMINI_API_KEY:
        print("Kein GEMINI_API_KEY — Artist Enrichment übersprungen")
        return

    events = json.loads(EVENTS_FILE.read_text())
    cache = load_cache()

    # Nur Artists aus RA-Quellen, max 20 neue pro Run
    new_artists = []
    for ev in events:
        if ev.get("source", "").startswith("ra_"):
            for a in ev.get("artists", []):
                if a and a not in cache and a not in new_artists:
                    new_artists.append(a)
    new_artists = new_artists[:20]
    print(f"Artist Enrichment: {len(new_artists)} neue Artists...")

    for artist in new_artists:
        enrich_artist(artist, cache)
    save_cache(cache)

    # Events updaten
    for ev in events:
        for artist in ev.get("artists", []):
            if artist in cache and cache[artist]:
                ev.setdefault("artist_urls", {})[artist] = cache[artist]

    EVENTS_FILE.write_text(json.dumps(events, indent=2, ensure_ascii=False))
    print(f"Artist Enrichment fertig. Cache: {len(cache)} Artists.")

if __name__ == "__main__":
    run()
