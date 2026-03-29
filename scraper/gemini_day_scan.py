import os
import re
import json
import time
import random
import hashlib
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any, Tuple
from urllib.parse import urljoin

from scraper.utils import normalize_text, uniq_list

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, ValidationError

from google import genai
from google.genai import types

# ============================================================
# BASEL RADAR · GEMINI DAY-SCAN PIPELINE v2
# Fokus:
# - 1 Tag pro Scan -> höhere Tiefe
# - URL Context first
# - Google Search nur als Recovery / Tiefenscan
# - strukturierte Outputs
# - raw + merged + reports
# - NUR Denkmal hat Speziallogik:
#   Tagesseite + automatisch gefundene Detailseiten
# ============================================================

API_KEY = os.environ.get("GEMINI_API_KEY")

if API_KEY:
    client = genai.Client(api_key=API_KEY)
else:
    client = None

MODEL_ID = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
DATE_FROM = os.environ.get("DATE_FROM", "2026-03-23")
DATE_TO = os.environ.get("DATE_TO", "2026-04-15")

WRITE_DEBUG = os.environ.get("WRITE_DEBUG", "1") not in {"0", "false", "False"}
DEBUG_DIR = os.environ.get("DEBUG_DIR", "debug_gemini_day_scan")

MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "5"))
BASE_BACKOFF_SECONDS = float(os.environ.get("BASE_BACKOFF_SECONDS", "4"))
MAX_BACKOFF_SECONDS = float(os.environ.get("MAX_BACKOFF_SECONDS", "90"))

TEMPERATURE = float(os.environ.get("TEMPERATURE", "0.05"))
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "16000"))

PASS2_MIN_EVENTS_PER_REGION = {
    "Basel": 6,
    "Zürich": 4,
    "Bern": 2,
}

TIER1_SOURCE_IDS = {
    "ra_basel", "ra_zurich",
    "denkmal_basel", "denkmal_zuerich",
    "basellive",
    "nordstern", "elysia", "kinker", "viertel", "ava_club", "heimat",
    "kaserne", "hirscheneck", "hive", "friedas", "supermarket",
    "bewegungsmelder", "kapitel", "gaskessel", "dachstock",
}

UUID_RE = re.compile(
    r"/de/(basel|zuerich)/\d{4}-\d{2}-\d{2}/[0-9a-fA-F-]{36}$"
)

DENKMAL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
}

httpx_client = httpx.Client(
    headers=DENKMAL_HEADERS,
    timeout=20.0,
    follow_redirects=True
)


class EventRecord(BaseModel):
    date: str = Field(description="ISO date YYYY-MM-DD")
    region: str
    source_id: str
    source_name: str
    venue: str
    title: str
    artists: List[str] = Field(default_factory=list)
    genres: List[str] = Field(default_factory=list)
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    price: Optional[str] = None
    currency: Optional[str] = None
    event_url: Optional[str] = None
    source_url: str
    notes: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)


class DayExtraction(BaseModel):
    scan_date: str
    region: str
    pass_name: str
    events: List[EventRecord] = Field(default_factory=list)


SOURCES: List[Dict[str, str]] = [
    {"id": "ra_basel", "name": "Resident Advisor Basel", "region": "Basel", "url": "https://ra.co/events/ch/basel"},
    {"id": "ra_zurich", "name": "Resident Advisor Zürich", "region": "Zürich", "url": "https://ra.co/events/ch/zurich"},
    {"id": "denkmal_basel", "name": "Denkmal Basel", "region": "Basel", "url": "https://denkmal.org/de/basel"},
    {"id": "denkmal_zuerich", "name": "Denkmal Zürich", "region": "Zürich", "url": "https://denkmal.org/de/zuerich"},
    {"id": "basellive", "name": "BaselLive", "region": "Basel", "url": "https://www.basellive.ch/kalender"},
    {"id": "nordstern", "name": "Nordstern", "region": "Basel", "url": "https://www.nordsternbasel.com"},
    {"id": "elysia", "name": "Elysia", "region": "Basel", "url": "https://elysia.ch"},
    {"id": "kinker", "name": "Kinker Club", "region": "Basel", "url": "https://www.kinker.ch/events.html"},
    {"id": "viertel", "name": "Viertel Klub", "region": "Basel", "url": "https://www.dasviertel.ch/viertelklub"},
    {"id": "ava_club", "name": "AVA Club", "region": "Basel", "url": "https://www.ava-basel.ch"},
    {"id": "basso", "name": "Basso Basel", "region": "Basel", "url": "https://www.bassoverse.space/en/beats"},
    {"id": "heimat", "name": "Heimat Basel", "region": "Basel", "url": "https://heimatbasel.com"},
    {"id": "gannet", "name": "Gannet Kulturschiff", "region": "Basel", "url": "https://gannet.lv/agenda"},
    {"id": "kaserne", "name": "Kaserne Basel", "region": "Basel", "url": "https://kaserne-basel.ch/en"},
    {"id": "hirscheneck", "name": "Hirscheneck", "region": "Basel", "url": "https://www.hirscheneck.ch/kultur"},
    {"id": "holzpark", "name": "Holzpark Klybeck", "region": "Basel", "url": "https://holzpark-klybeck.ch"},
    {"id": "sandoase", "name": "Sandoase Basel", "region": "Basel", "url": "https://sandoase.ch"},
    {"id": "portland", "name": "Port Land", "region": "Basel", "url": "https://www.portlandbasel.ch"},
    {"id": "netzwerkbasel", "name": "Netzwerk Basel", "region": "Basel", "url": "https://netzwerkbasel.com/events"},
    {"id": "hive", "name": "Hive Club", "region": "Zürich", "url": "https://hiveclub.ch"},
    {"id": "friedas", "name": "Frieda's Büxe", "region": "Zürich", "url": "https://friedasbuexe.ch"},
    {"id": "supermarket", "name": "Supermarket", "region": "Zürich", "url": "https://supermarket.li"},
    {"id": "maex", "name": "MÄX Zürich", "region": "Zürich", "url": "https://maexzuerich.com"},
    {"id": "bewegungsmelder", "name": "Bewegungsmelder Bern", "region": "Bern", "url": "https://bewegungsmelder.ch"},
    {"id": "kapitel", "name": "Kapitel Bollwerk", "region": "Bern", "url": "https://kapitel.ch"},
    {"id": "gaskessel", "name": "Gaskessel Bern", "region": "Bern", "url": "https://gaskessel.ch"},
    {"id": "dachstock", "name": "Dachstock", "region": "Bern", "url": "https://dachstock.ch"},
]


def ensure_debug_dir() -> None:
    if WRITE_DEBUG:
        os.makedirs(DEBUG_DIR, exist_ok=True)


def to_jsonable(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=str))


def write_json(path: str, payload: Any) -> None:
    if not WRITE_DEBUG:
        return
    with open(path, "w", encoding="utf-8") as f:
        json.dump(to_jsonable(payload), f, ensure_ascii=False, indent=2)


def daterange(start_iso: str, end_iso: str) -> List[str]:
    start = datetime.strptime(start_iso, "%Y-%m-%d").date()
    end = datetime.strptime(end_iso, "%Y-%m-%d").date()
    out = []
    cur = start
    while cur <= end:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def event_key(ev: Dict[str, Any]) -> str:
    raw = "||".join([
        ev.get("date", ""),
        normalize_text(ev.get("region")),
        normalize_text(ev.get("venue")),
        normalize_text(ev.get("title")),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def source_priority(s: Dict[str, str]) -> Tuple[int, str]:
    return (0 if s["id"] in TIER1_SOURCE_IDS else 1, s["id"])


def backoff_sleep(attempt: int) -> None:
    delay = min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * (2 ** attempt))
    delay += random.uniform(0.0, 1.5)
    print(f"   ↳ Backoff {delay:.1f}s")
    time.sleep(delay)


def denkmal_day_url(city: str, day_iso: str, lang: str = "de") -> str:
    city = city.lower()
    if city not in {"basel", "zuerich"}:
        raise ValueError("city must be 'basel' or 'zuerich'")
    return f"https://denkmal.org/{lang}/{city}/{day_iso}"


def fetch_plain_html(url: str) -> str:
    response = httpx_client.get(url)
    response.raise_for_status()
    return response.text


def extract_denkmal_detail_urls(day_url: str, max_links: int = 12) -> List[str]:
    try:
        html = fetch_plain_html(day_url)
    except Exception:
        return []

    soup = BeautifulSoup(html, "html.parser")
    urls: List[str] = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full = urljoin(day_url, href)
        if UUID_RE.search(full) and full not in seen:
            seen.add(full)
            urls.append(full)

    return urls[:max_links]


def build_denkmal_url_pack(city: str, day_iso: str, max_detail_links: int = 12) -> List[str]:
    day_url_de = denkmal_day_url(city, day_iso, lang="de")
    detail_urls = extract_denkmal_detail_urls(day_url_de, max_links=max_detail_links)

    urls = [day_url_de] + detail_urls

    if len(urls) < 4:
        urls.append(denkmal_day_url(city, day_iso, lang="en"))

    deduped = []
    seen = set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)

    return deduped[:20]


def denkmal_prompt_hint(city: str, day_iso: str) -> str:
    city_label = "Basel" if city == "basel" else "Zürich"
    return f"""
Spezialregeln für Denkmal {city_label}:
- Arbeite primär mit der Denkmal-Tagesseite für {day_iso} und den mitgegebenen Denkmal-Detailseiten.
- Extrahiere ALLE Events exakt für {day_iso}.
- Bevorzuge die Detailseiten, wenn Felder zwischen Übersicht und Detailseite abweichen.
- venue = Veranstaltungsort auf Denkmal
- title = Eventtitel
- artists = nur echte Artist-/Band-/DJ-Namen aus Titel oder Detailseite
- genres = nur sichtbare Genrebegriffe
- start_time / end_time übernehmen, wenn sichtbar
- event_url = konkrete Denkmal-Detailseite
- source_url = die Denkmal-Seite, aus der das Event stammt
""".strip()


def build_urls_for_day(region_sources: List[Dict[str, str]], day_iso: str) -> List[str]:
    urls: List[str] = []

    for s in sorted(region_sources, key=source_priority):
        sid = s["id"]

        if sid == "denkmal_basel":
            urls.extend(build_denkmal_url_pack("basel", day_iso, max_detail_links=12))
            continue

        if sid == "denkmal_zuerich":
            urls.extend(build_denkmal_url_pack("zuerich", day_iso, max_detail_links=12))
            continue

        urls.append(s["url"])

    out = []
    seen = set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)

    return out[:20]


def build_prompt(
    day_iso: str,
    region: str,
    region_sources: List[Dict[str, str]],
    pass_name: str,
    urls: List[str],
) -> str:
    source_lines = []
    for s in sorted(region_sources, key=source_priority):
        source_lines.append(f"- source_id={s['id']} | source_name={s['name']} | url={s['url']}")
    source_block = "\n".join(source_lines)
    url_block = "\n".join(f"- {u}" for u in urls)

    search_rule = (
        "Du darfst Google Search verwenden, aber nur wenn die bereitgestellten URLs für diesen Tag zu wenig liefern "
        "oder wenn du eine klar zugehörige Tages-/Event-Unterseite der gleichen Quelle finden musst."
        if pass_name == "pass2_search"
        else
        "Benutze KEINE Google Search. Arbeite nur mit den bereitgestellten URLs."
    )

    extras = []
    source_ids = {s["id"] for s in region_sources}

    if "denkmal_basel" in source_ids:
        extras.append(denkmal_prompt_hint("basel", day_iso))
    if "denkmal_zuerich" in source_ids:
        extras.append(denkmal_prompt_hint("zuerich", day_iso))

    base_prompt = f"""
Du extrahierst Eventdaten für genau EINEN Tag.

Tag: {day_iso}
Region: {region}

Quellen:
{source_block}

Verwende diese exakten URLs als Primärkontext:
{url_block}

Regeln:
- Gib ausschließlich Events zurück, die exakt am Datum {day_iso} stattfinden.
- {search_rule}
- Bevorzuge offizielle Venue-Seiten, Denkmal, Resident Advisor und bekannte lokale Kalender.
- Gib keine Events von anderen Tagen zurück.
- Falls eine Quelle mehrere Events am selben Tag listet, extrahiere alle.
- artists = echte Performer/DJs/Bands; keine Venues, keine Labels.
- genres = nur klare Stil-/Genrebegriffe.
- confidence:
  - 1.0 = klar auf offizieller Venue-/Eventseite
  - 0.9 = klar auf gutem Aggregator
  - 0.7–0.8 = plausible Extraktion, aber einzelne Felder implizit
- venue = Veranstaltungsort
- source_url = die URL, aus der du das Event primär ableitest
- event_url = konkrete Event-Detailseite, falls erkennbar; sonst null
- Keine Duplikate innerhalb der Antwort.
- Wenn nichts belastbar vorhanden ist, gib ein leeres events-Array zurück.
""".strip()

    return base_prompt + ("\n\n" + "\n\n".join(extras) if extras else "")


def run_day_scan(day_iso: str, region: str, region_sources: List[Dict[str, str]], pass_name: str) -> DayExtraction:
    urls = build_urls_for_day(region_sources, day_iso)
    prompt = build_prompt(day_iso, region, region_sources, pass_name, urls)

    tools = [types.Tool(url_context=types.UrlContext())]
    if pass_name == "pass2_search":
        tools.append(types.Tool(google_search=types.GoogleSearch()))

    cfg = types.GenerateContentConfig(
        tools=tools,
        response_mime_type="application/json",
        response_json_schema=DayExtraction.model_json_schema(),
        temperature=TEMPERATURE,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )

    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.models.generate_content(
                model=MODEL_ID,
                contents=prompt,
                config=cfg,
            )

            parsed = DayExtraction.model_validate_json(resp.text)

            if WRITE_DEBUG:
                meta = {
                    "day": day_iso,
                    "region": region,
                    "pass_name": pass_name,
                    "urls": urls,
                    "event_count": len(parsed.events),
                    "usage_metadata": getattr(resp, "usage_metadata", None),
                    "url_context_metadata": getattr(resp.candidates[0], "url_context_metadata", None) if getattr(resp, "candidates", None) else None,
                    "grounding_metadata": getattr(resp.candidates[0], "grounding_metadata", None) if getattr(resp, "candidates", None) else None,
                }
                write_json(os.path.join(DEBUG_DIR, f"{day_iso}_{region}_{pass_name}_meta.json"), meta)
                write_json(os.path.join(DEBUG_DIR, f"{day_iso}_{region}_{pass_name}_events.json"), parsed.model_dump(mode='json'))

            return parsed

        except (ValidationError, Exception) as e:
            last_err = e
            msg = str(e)
            retryable = any(t in msg for t in ["429", "503", "ResourceExhausted", "UNAVAILABLE", "Deadline"])
            print(f"[{day_iso}][{region}][{pass_name}] Fehler {attempt + 1}/{MAX_RETRIES}: {msg}")
            if retryable and attempt < MAX_RETRIES - 1:
                backoff_sleep(attempt)
                continue
            break

    if WRITE_DEBUG:
        write_json(
            os.path.join(DEBUG_DIR, f"{day_iso}_{region}_{pass_name}_error.json"),
            {"day": day_iso, "region": region, "pass_name": pass_name, "error": str(last_err), "urls": urls},
        )

    return DayExtraction(scan_date=day_iso, region=region, pass_name=pass_name, events=[])


def merge_two(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(a)

    for fld in ["start_time", "end_time", "price", "currency", "event_url", "notes"]:
        if (not out.get(fld)) and b.get(fld):
            out[fld] = b[fld]

    out["artists"] = uniq_list((out.get("artists") or []) + (b.get("artists") or []))
    out["genres"] = uniq_list((out.get("genres") or []) + (b.get("genres") or []))
    out["confidence"] = max(float(out.get("confidence") or 0), float(b.get("confidence") or 0))

    a_sid = out.get("source_id", "")
    b_sid = b.get("source_id", "")
    if a_sid.startswith("denkmal") and not b_sid.startswith("denkmal"):
        pass
    elif a_sid.startswith("ra_") and not b_sid.startswith("ra_"):
        pass
    else:
        if b_sid in TIER1_SOURCE_IDS and a_sid not in TIER1_SOURCE_IDS:
            out["source_id"] = b_sid
            out["source_name"] = b.get("source_name", out.get("source_name"))
            out["source_url"] = b.get("source_url", out.get("source_url"))

    return out


def merge_events(events: List[EventRecord]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}

    for ev in events:
        d = ev.model_dump(mode='json')
        key = event_key(d)
        if key not in merged:
            merged[key] = d
        else:
            merged[key] = merge_two(merged[key], d)

    final_list = list(merged.values())
    final_list.sort(key=lambda x: (
        x["date"],
        normalize_text(x["region"]),
        normalize_text(x["venue"]),
        normalize_text(x["title"]),
    ))
    return final_list


def scan_region_for_day(day_iso: str, region: str, region_sources: List[Dict[str, str]]) -> Dict[str, Any]:
    pass1 = run_day_scan(day_iso, region, region_sources, "pass1_url_only")
    chosen_events = pass1.events
    used_pass = "pass1_url_only"

    threshold = PASS2_MIN_EVENTS_PER_REGION.get(region, 3)
    pass2 = None

    if len(pass1.events) < threshold:
        print(f"[{day_iso}][{region}] Pass 1 dünn ({len(pass1.events)} Events) -> Pass 2 mit Search")
        pass2 = run_day_scan(day_iso, region, region_sources, "pass2_search")
        if len(pass2.events) >= len(pass1.events):
            chosen_events = pass2.events
            used_pass = "pass2_search"

    return {
        "day": day_iso,
        "region": region,
        "used_pass": used_pass,
        "pass1_count": len(pass1.events),
        "pass2_count": len(pass2.events) if pass2 else None,
        "events": [e.model_dump(mode='json') for e in chosen_events],
    }


def main() -> None:
    ensure_debug_dir()

    days = daterange(DATE_FROM, DATE_TO)
    regions = ["Basel", "Zürich", "Bern"]

    sources_by_region = {region: [s for s in SOURCES if s["region"] == region] for region in regions}

    all_raw_records: List[EventRecord] = []
    scan_reports: List[Dict[str, Any]] = []

    for day_iso in days:
        print(f"\n===== {day_iso} =====")
        for region in regions:
            region_sources = sources_by_region[region]
            result = scan_region_for_day(day_iso, region, region_sources)
            scan_reports.append({k: v for k, v in result.items() if k != "events"})

            for ev_dict in result["events"]:
                try:
                    all_raw_records.append(EventRecord.model_validate(ev_dict))
                except ValidationError:
                    continue

            print(f"  {region}: {len(result['events'])} Events via {result['used_pass']}")

        time.sleep(1.0)

    raw_json = [e.model_dump(mode='json') for e in all_raw_records]
    final_merged = merge_events(all_raw_records)

    summary = {
        "model": MODEL_ID,
        "date_from": DATE_FROM,
        "date_to": DATE_TO,
        "days_scanned": len(days),
        "raw_event_count": len(raw_json),
        "merged_event_count": len(final_merged),
        "scan_reports_count": len(scan_reports),
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    write_json(os.path.join(DEBUG_DIR, "raw_extraction.json"), raw_json)
    write_json(os.path.join(DEBUG_DIR, "merged_events.json"), final_merged)
    write_json(os.path.join(DEBUG_DIR, "scan_reports.json"), scan_reports)
    write_json(os.path.join(DEBUG_DIR, "summary.json"), summary)

    print("\n--- SUMMARY ---")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    print("\n--- MERGED EVENTS ---")
    print(json.dumps(final_merged, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
