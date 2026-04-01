# Deep Code Review (Basel-Radar)

Date: 2026-04-01

## Was geprüft wurde
- Aktive Pipeline (`scraper/gemini_day_scan.py`, `scraper/utils.py`)
- Test-Setup (`tests/`, `pytest` discoverability)
- Repo-Struktur (aktive vs. Legacy-Artefakte)

## Wichtigste Findings

### 1) Fehlende harte Validierung für `GEMINI_API_KEY` (hoch)
**Problem:** Wenn `GEMINI_API_KEY` fehlt, wird `client = None` gesetzt. Der Fehler tritt später indirekt in `run_day_scan()` auf und wird dort von einem breiten `except` geschluckt.

**Risiko:** Die Pipeline kann mit leeren Ergebnissen „erfolgreich“ wirken, statt früh und klar zu failen.

**Fix umgesetzt:**
- `ensure_client_configured()` ergänzt und in `main()` als Early Guard eingebaut.

### 2) HTTP-Client-Lifecycle (mittel)
**Problem:** Globaler `httpx.Client` wurde geöffnet, aber nicht explizit geschlossen.

**Risiko:** Resource Leaks bei langen/mehrfachen Runs oder in wiederverwendeten Prozessen.

**Fix umgesetzt:**
- `atexit.register(httpx_client.close)` ergänzt.

### 3) Test-Importpfad unstabil (mittel)
**Problem:** `pytest -q` konnte `scraper` nicht importieren (`ModuleNotFoundError`).

**Risiko:** CI/Local-Tests sind inkonsistent und brechen bei manchen Python/pytest-Setups.

**Fix umgesetzt:**
- `scraper/__init__.py` ergänzt.
- `pytest.ini` mit `pythonpath = .` ergänzt.

### 4) Legacy-/Release-Artefakte im Root vermischen aktive Codebasis (niedrig, Wartbarkeit)
**Problem:** Root enthielt parallel aktive Pipeline + mehrere Release-/Legacy-Bäume.

**Risiko:** Höheres Verwechslungsrisiko bei Deployments und Reviews.

**Fix umgesetzt:**
- Unbenutzte/legacy Dateien in `archive/` verschoben.
- ZIP im Repo archiviert und erneut nach `archive/` entpackt.

## Offene Empfehlungen (nicht in diesem Commit umgesetzt)
- In `run_day_scan()` statt `except (ValidationError, Exception)` getrennte Behandlung einführen (Validation/Transport/API sauber unterscheiden).
- Optionale typed config (z. B. Pydantic Settings) für ENV-Parsing + zentrale Validierung.
- Deterministische Tests für Dedupe-/Merge-Logik (`event_key`, `merge_two`, `merge_events`) ergänzen.
