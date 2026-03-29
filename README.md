# Basel Radar · Gemini Day Scan

Ein minimales GitHub-Repo für einen tagweisen Event-Scan mit Gemini.

## Was dieses Repo macht

- scannt jeden Tag einzeln für Basel, Zürich und Bern
- nutzt **Gemini URL Context** als Primärweg
- nutzt **Google Search** nur als Recovery-Zweitpass
- hat eine **Speziallogik nur für Denkmal**:
  - baut die Tagesseite deterministisch
  - zieht zusätzliche Denkmal-Detailseiten vorab
  - gibt genau diese URLs an Gemini weiter
- schreibt Debug- und Ergebnisdateien in `debug_gemini_day_scan/`

## Warum die Denkmal-Logik sinnvoll ist

Gemini URL Context liest nur die URLs, die explizit im Prompt angegeben werden, und folgt keinen verschachtelten Links. Deshalb bringt bei Denkmal die reine Stadtseite wenig; besser ist `Tagesseite + Detailseiten`.

## Setup lokal

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY="dein_key"
python scraper/gemini_day_scan.py
```

## Dashboard starten

Um das HTML-Dashboard zu starten:

```bash
python server.py
```

Danach ist das Dashboard unter [http://localhost:8000](http://localhost:8000) erreichbar.
Über den Button "Neuer Scan" kann ein neuer Scan-Vorgang im Hintergrund gestartet werden.

## Wichtige ENV-Variablen

- `GEMINI_API_KEY` – erforderlich
- `GEMINI_MODEL` – optional, Default: `gemini-3-flash-preview`
- `DATE_FROM` – optional, Default: `2026-03-23`
- `DATE_TO` – optional, Default: `2026-04-15`
- `WRITE_DEBUG` – optional, `1` oder `0`, Default: `1`
- `DEBUG_DIR` – optional, Default: `debug_gemini_day_scan`

## GitHub Actions

Das Workflow-File startet manuell und täglich. Die erzeugten JSON-Dateien werden als Artifact hochgeladen.
