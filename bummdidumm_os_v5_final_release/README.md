# bummdidumm-OS V5 Final Release

## Setup
1. Python 3.11+, `pip install -r requirements.txt`.
2. Google Cloud Projekt mit aktivierten APIs: Drive API, Sheets API, Cloud Run Jobs.
3. Service Account mit mindestens:
   - `roles/drive.admin` (oder granular: Drive File/Folder Zugriff passend zum Scope)
   - `roles/sheets.editor`
   - `roles/run.developer`
   - `roles/iam.serviceAccountUser`
4. Ein Control-Sheet anlegen (Tabs werden automatisch erstellt).

## APIs, IAM und PROJECT_ID-Konfiguration
- **Apps Script** liest `PROJECT_ID` aus `PropertiesService` (`Script Properties`).
- **deploy.sh** nutzt ausschließlich Environment Variablen (`PROJECT_ID`, `TARGET_FOLDER_ID`, `ARCHIVE_FOLDER_ID`, `INDEX_FOLDER_ID`, `CONTROL_SHEET_ID`, `GEMINI_API_KEY`).
- Keine Hardcoded-Projekt-ID und keine Platzhalter wie `<keine_hardcoded_project_id>`.

## Deployment
```bash
cd bummdidumm_os_v5_final_release
chmod +x deploy.sh
PROJECT_ID=... TARGET_FOLDER_ID=... ARCHIVE_FOLDER_ID=... INDEX_FOLDER_ID=... CONTROL_SHEET_ID=... GEMINI_API_KEY=... ./deploy.sh
```

## Laufmodi
- **Erster Lauf (Pass 1):** Initialer Full-Walk + Hash/Dedupe.
- **Zweiter Lauf (Pass 2):** OCR + JSONL Delta-Export in `20_index`.
- **Full Run:** Apps Script startet Pass 1 und pollt automatisch bis Pass 2 Trigger.
- **Resume:** `in_progress_page_token` erlaubt Delta-Fortsetzung nach Abbruch.
- **Shared Drives:** über `ENABLE_SHARED_DRIVES=true` unterstützt.

## Folder-Initializer und Folder Registry
`initializeFolderStructure()` arbeitet autonom:
- legt `Folder_Registry` an, falls fehlend,
- erzeugt/validiert Root + komplette Zielstruktur,
- schreibt `folder_key, folder_name, folder_id, parent_folder_id, full_path`.

## Safe Sort / Apply Sort
- **Safe Sort (`main_safe_sort.py`)** erzeugt nur Vorschläge in `Sorting_Suggestions`.
- **Apply Sort (`main_apply_sort.py`)** führt Bewegungen aus und schreibt Resultate per robuster Zeilenadressierung (ohne `rows.index(...)`).

## Sorting-Regeln
Jede Entscheidung enthält:
- `folder_rule`
- `folder_rule_reason`

## Folder-aware Indexing
JSONL enthält konsistent:
- `current_parent_id`, `current_path`
- `target_parent_id`, `target_path`
- `folder_rule`, `folder_rule_reason`
- `sort_mode`, `move_result`

Statusereignisse ohne OCR werden dennoch geschrieben (u. a. `DELETED`, `TRASHED`, `REMOVED_OR_NO_ACCESS`, `MOVED`, `RENAMED`, metadata-only Updates).

## Notbremse / Trigger / Cleanup
- Menüpunkt „Notbremse: Alle Hintergrund-Trigger stoppen“ löscht Trigger + Polling-Properties.
- Trigger-Dedupe verhindert Zombie-Trigger.
- Poll-Timeout beendet Full-Run Polling automatisch.
- `autoCleanupTransientFolder()` bleibt vorhanden.

## Troubleshooting
- `release_audit.py` ausführen.
- Bei Quota-Fehlern greifen Backoff/Retries (Sheets + Gemini).
- Bei fehlender `PROJECT_ID` in Apps Script: Script Property setzen.

## Bekannte Grenzen
- OCR hängt von Gemini-Quota und Dateityp ab.
- Sehr große Delta-Runs benötigen mehrere Polling-Zyklen.

## Archivierung von Altlasten
Nicht zum Release gehörende Alt-/Wrapper-Dateien wurden in `archive/` verschoben und sind **nicht** Teil des Release-ZIPs.

## Personal Brain Index

Pass 2 erweitert den klassischen Delta-Export um export-aware Parsing nach `20_index/published/`:
- Source/Record/Entity/Relation JSONL
- Daily Memory Shards
- Search Views für Gemini/NotebookLM-nahe Nutzung

Der Einstiegspunkt ist `personal_brain/runtime.py` und wird in `main_pass2.py` nach Delta-Erzeugung ausgeführt.
