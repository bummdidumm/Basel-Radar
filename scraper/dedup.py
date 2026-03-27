"""
Basel Radar · Deduplication
Liest ra_events.json + html_events.json, dedup, speichert events_raw.json.
"""
import json, re
from datetime import date
from pathlib import Path

BASE = Path(__file__).parent.parent
RA_FILE = BASE / "ra_events.json"
HTML_FILE = BASE / "html_events.json"
OUT = BASE / "events_raw.json"

SOURCE_PRIO = {
    "ra_basel": 10, "ra_zurich": 9,
    "nordstern": 8, "ava_club": 8, "kinker": 8, "elysia": 8, "basso": 8,
    "kuppel": 7, "viertel_klub": 7, "kaserne": 7, "gannet": 7,
    "sommercasino": 6, "denkmal": 6, "basellive": 5,
    "proz": 4, "eventfrog": 3, "songkick": 3,
}

def norm(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9äöüß\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()

def sim(a, b):
    wa, wb = set(a.split()), set(b.split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))

def is_dup(a, b):
    if a.get("date") != b.get("date"):
        return False
    ta, tb = norm(a.get("title", "")), norm(b.get("title", ""))
    if ta == tb:
        return True
    if ta in tb or tb in ta:
        if len(min(ta, tb, key=len)) >= 4:
            return True
    if sim(ta, tb) >= 0.7:
        return True
    va, vb = norm(a.get("venue", "")), norm(b.get("venue", ""))
    if va == vb and sim(ta, tb) >= 0.5:
        return True
    return False

def merge(a, b):
    pa = SOURCE_PRIO.get(a.get("source", ""), 0)
    pb = SOURCE_PRIO.get(b.get("source", ""), 0)
    winner, loser = (a, b) if pa >= pb else (b, a)
    winner = dict(winner)
    for k in ["doors", "close", "ig", "fb", "artists", "genres", "cost"]:
        if not winner.get(k) and loser.get(k):
            winner[k] = loser[k]
    if loser.get("artist_urls"):
        winner.setdefault("artist_urls", {}).update(loser["artist_urls"])
    srcs = winner.get("sources", [winner.get("source", "")])
    if loser.get("source") not in srcs:
        srcs.append(loser["source"])
    winner["sources"] = srcs
    return winner

def run():
    events = []
    for f in [RA_FILE, HTML_FILE]:
        if f.exists():
            events.extend(json.loads(f.read_text()))

    print(f"Dedup: {len(events)} Events rein...")

    # Filter vergangene Events
    today = date.today().isoformat()
    events = [e for e in events if not e.get("date") or e["date"] >= today]
    print(f"Nach Datumsfilter: {len(events)}")

    # Deduplizieren
    result = []
    for ev in events:
        ev.setdefault("sources", [ev.get("source", "")])
        merged = False
        for i, existing in enumerate(result):
            if is_dup(ev, existing):
                result[i] = merge(existing, ev)
                merged = True
                break
        if not merged:
            result.append(ev)

    result.sort(key=lambda e: e.get("date", "9999"))
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"Dedup fertig: {len(result)} unique Events → {OUT}")
    return result

if __name__ == "__main__":
    run()
