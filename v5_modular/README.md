# bummdidumm-OS V5 Modular System

Dies ist das vollständige, produktionsnahe System für V5 basierend auf Cloud Run Jobs, Google Drive, Google Sheets und Apps Script.

## Architektur

Das System wurde in zwei entkoppelte Pässe aufgeteilt, um Idempotenz und Ressourcen-Effizienz zu gewährleisten.

*   `main_pass1.py`: Holt Deltas von Google Drive, dedupliziert über `SHA-256`, aktualisiert den `Hash_Index`, verschiebt Duplikate in den `ARCHIVE_FOLDER_ID` und loggt detailliert in `Dedupe_Report`.
*   `main_pass2.py`: Liest den `Dedupe_Report` für den letzten erfolgreichen Pass 1 Run, holt Originale ab, führt strukturierte Gemini OCR aus und exportiert den `JSONL` Index.
*   `main_apply_renames.py`: Optionaler dritter Job, der lediglich die `suggested_names` aus dem Report auf Google Drive anwendet.

## Ordnerstruktur

```text
v5_modular/
├── appsscript/           # Control Plane (Google Sheets UI)
│   ├── Code.gs
│   └── appsscript.json
├── shared/               # Modulare Python-Komponenten
│   ├── drive_helpers.py  # Drive API & Caching Logik
│   ├── gemini_helpers.py # google-genai OCR API
│   ├── hash_helpers.py   # Streaming SHA-256
│   ├── models.py         # Pydantic Schemas (ExtractedDocument)
│   ├── sheets_helpers.py # Google Sheets Basic Wrapper
│   └── state_helpers.py  # StateTracker für Idempotenz und Reporting
├── deploy.sh             # Deployment Skript für Cloud Run
├── Dockerfile.*          # Drei getrennte Dockerfiles pro Job
├── main_pass1.py         # Pass 1 Entrypoint
├── main_pass2.py         # Pass 2 Entrypoint
├── main_apply_renames.py # Rename Job Entrypoint
└── requirements.txt      # Abhängigkeiten
```

## Google Sheet Vorbereitung

Erstelle ein leeres Google Sheet. Du musst die Tabs nicht zwingend manuell anlegen, das System initialisiert sie bei Bedarf über den `SheetManager`. Wenn du sie manuell anlegst, lauten die Namen:

*   `State`
*   `Hash_Index`
*   `Dedupe_Report`
*   `Duplicate_Groups`
*   `Error_Report`
*   `Run_Log`

## Deployment

1.  Passe in `deploy.sh` deine Variablen an (z.B. `DEIN_PROJEKT_ID`).
2.  Erstelle einen Service Account (wie in `deploy.sh` angegeben) und gib ihm Edit-Rechte auf dein Google Sheet sowie Zugriff auf Drive.
3.  Führe `bash deploy.sh` aus.
4.  Kopiere den Inhalt aus `appsscript/Code.gs` in den Skripteditor deines Google Sheets und passe auch dort die `PROJECT_ID` an. Erteile dem Apps Script Projekt die OAuth Berechtigungen.
