"""
Basel Radar · Deduplication (hardened)
- Verwirft kaputte/undatierte Events früh.
- Behalten werden nur Events >= heute.
- Gibt Qualitätswarnungen pro Quelle aus.
"""

import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

BASE = Path(__file__).parent.parent
RA_FILE = BASE / "ra_events.json"
HTML_FILE = BASE / "html_events.json"
SOURCES_FILE = BASE / "sources.json"
OUT = BASE / "events_raw.json"

SOURCE_PRIO = {
    "ra_basel": 10, "ra_zurich": 9,
    "nordstern": 8, "ava_club": 8,
    "kuppel": 7, "viertel_klub": 7, "kaserne": 7,
    "hirscheneck": 7, "denkmal": 6, "basellive": 6,
    "radiox": 5, "proz": 4, "eventfrog": 3, "songkick": 3,
}


def norm(text):
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9äöüß\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def sim(a, b):
    wa, wb = set(a.split()), set(b.split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))


def looks_like_date_title(title: str):
    t = (title or "").strip().lower()
    return bool(re.fullmatch(r"\d{1,2}[\.\-/]\d{1,2}([\.\-/]\d{2,4})?", t) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", t))


def is_dup(a, b):
    if a.get("date") != b.get("date"):
        return False
    ta, tb = norm(a.get("title")), norm(b.get("title"))
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    if (ta in tb or tb in ta) and len(min(ta, tb, key=len)) >= 5:
        return True
    if sim(ta, tb) >= 0.72:
        return True
    va, vb = norm(a.get("venue")), norm(b.get("venue"))
    return va and vb and va == vb and sim(ta, tb) >= 0.5


def merge(a, b):
    pa = SOURCE_PRIO.get(a.get("source", ""), 0)
    pb = SOURCE_PRIO.get(b.get("source", ""), 0)
    winner, loser = (a, b) if pa >= pb else (b, a)
    winner = dict(winner)

    for k in ["doors", "close", "ig", "fb", "artists", "genres", "cost", "venue", "venue_url"]:
        if (winner.get(k) in [None, "", [], {}]) and loser.get(k):
            winner[k] = loser[k]

    winner.setdefault("artist_urls", {})
    winner["artist_urls"].update(loser.get("artist_urls", {}))

    srcs = list(dict.fromkeys((winner.get("sources") or [winner.get("source")]) + [loser.get("source")]))
    winner["sources"] = [s for s in srcs if s]
    return winner


def load_events(path: Path):
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def load_active_sources():
    if not SOURCES_FILE.exists():
        return {}
    try:
        data = json.loads(SOURCES_FILE.read_text())
    except Exception:
        return {}
    active = {}
    for s in data.get("sources", []):
        if s.get("active"):
            active[s.get("id")] = s.get("url")
    return active


def clean_event(ev):
    if not isinstance(ev, dict):
        return None
    title = (ev.get("title") or "").strip()
    event_date = (ev.get("date") or "").strip()
    source = (ev.get("source") or "").strip()

    if not title or not event_date or not source:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_date):
        return None
    if looks_like_date_title(title):
        return None

    ev = dict(ev)
    ev["title"] = title
    ev["date"] = event_date
    ev.setdefault("sources", [source])
    ev["sources"] = [s for s in ev["sources"] if s]
    return ev


def run():
    events = load_events(RA_FILE) + load_events(HTML_FILE)
    print(f"Dedup input: {len(events)}")

    cleaned = []
    dropped_invalid = 0
    today = date.today().isoformat()
    for ev in events:
        ev = clean_event(ev)
        if not ev:
            dropped_invalid += 1
            continue
        if ev["date"] < today:
            continue
        cleaned.append(ev)

    print(f"Valid upcoming events: {len(cleaned)} (dropped invalid/no-date: {dropped_invalid})")

    deduped = []
    for ev in cleaned:
        merged = False
        for i, existing in enumerate(deduped):
            if is_dup(ev, existing):
                deduped[i] = merge(existing, ev)
                merged = True
                break
        if not merged:
            deduped.append(ev)

    deduped.sort(key=lambda e: (e.get("date", "9999-99-99"), norm(e.get("title", ""))))

    # Sanity checks
    counts = Counter(e.get("source", "") for e in deduped)
    total = len(deduped) or 1
    for source, count in counts.items():
        share = count / total
        if share > 0.40:
            print(f"WARN: Quelle {source} liefert {share:.0%} aller Events ({count}/{total})")

    for ev in deduped:
        if looks_like_date_title(ev.get("title", "")):
            print(f"WARN: Titel wirkt wie Datum: {ev.get('title')} ({ev.get('source')})")

    active_sources = load_active_sources()
    for src, url in active_sources.items():
        if counts.get(src, 0) == 0 and src not in {"ra_basel", "ra_zurich"}:
            print(f"WARN: Quelle {src} liefert 0 Events (URL: {url})")

    OUT.write_text(json.dumps(deduped, indent=2, ensure_ascii=False))
    print(f"Dedup output: {len(deduped)} unique events -> {OUT}")
    return deduped


if __name__ == "__main__":
    run()
