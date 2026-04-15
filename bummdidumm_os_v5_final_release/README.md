# bummdidumm-OS V5 Final Release

## Quick Start (lokal testen — keine Cloud-Infrastruktur nötig)

```bash
cd bummdidumm_os_v5_final_release
pip install -r requirements.txt
python3 -m pytest tests/ -q          # Smoke-Tests
python3 release_audit.py              # Release-Check
```

Die Tests laufen vollständig lokal mit Mocks — kein Google-Account, kein Sheets, kein Drive nötig.

---

## Setup für produktiven Betrieb

### Voraussetzungen
1. Python 3.11+
2. Google Cloud Projekt mit aktivierten APIs: **Drive API**, **Sheets API**, **Cloud Run Jobs**
3. Control-Sheet anlegen (Tabs werden beim ersten Start automatisch erstellt)
4. Service Account (`SA_EMAIL`) mit Drive- und Sheets-Schreibrechten

### Umgebungsvariablen

**Pflicht für alle Laufmodi:**
| Variable | Zweck |
|----------|-------|
| `CONTROL_SHEET_ID` | ID des Google Sheets für State, Hash-Index, Reports |
| `GOOGLE_OAUTH_CLIENT_ID` | User-OAuth Client-ID |
| `GOOGLE_OAUTH_CLIENT_SECRET` | User-OAuth Client-Secret |
| `GOOGLE_OAUTH_REFRESH_TOKEN` | User-OAuth Refresh-Token |

**Pflicht für Cloud-Deploy (`deploy.sh`):**
| Variable | Zweck |
|----------|-------|
| `PROJECT_ID` | Google Cloud Projekt-ID |
| `SA_EMAIL` | Service-Account-E-Mail für Cloud Run Jobs |
| `BRAIN_INDEX_ROOT` | Persistenter Pfad für den Brain-Index (z. B. gemountetes Volume) |
| `ARCHIVE_FOLDER_ID` | Drive-Ordner-ID für archivierte Duplikate |
| `INDEX_FOLDER_ID` | Drive-Ordner-ID für Index-Ausgaben |
| `GEMINI_API_KEY` | Gemini-API-Key für OCR |

**Optional:**
| Variable | Default | Zweck |
|----------|---------|-------|
| `TARGET_FOLDER_ID` | _(leer = Drive-Root)_ | Scan auf Unterordner beschränken |
| `ENABLE_OCR` | `true` | OCR über Gemini aktivieren/deaktivieren |
| `OCR_BUDGET_PER_RUN` | `500` | Max. OCR-Calls pro Run |
| `SKIP_OVER_MB` | `500` | Dateien über diesem Limit überspringen |
| `ENABLE_SHARED_DRIVES` | `true` | Shared-Drive-Support aktivieren |
| `ENABLE_ARCHIVE` | `true` | Duplikate archivieren statt nur markieren |

> **Hinweis für Cloud Run:** `BRAIN_INDEX_ROOT` muss explizit gesetzt werden und auf
> ein persistentes Volume zeigen. Ohne diesen Pfad wirft `main_pass2.py` beim Start eine
> `RuntimeError` — das ist bewusst, um Datenverlust durch ephemere Container zu verhindern.

---

## Deployment (Cloud Run Jobs)

```bash
cd bummdidumm_os_v5_final_release
chmod +x deploy.sh
export PROJECT_ID=...
export SA_EMAIL=...           # Service Account, der die Jobs ausführt
export BRAIN_INDEX_ROOT=...   # Persistenter Pfad oder Volume-Mount
export ARCHIVE_FOLDER_ID=...
export INDEX_FOLDER_ID=...
export CONTROL_SHEET_ID=...
export GEMINI_API_KEY=...
# Optional:
# export TARGET_FOLDER_ID=...
./deploy.sh
```

---

## APIs, IAM und PROJECT_ID-Konfiguration
- **Apps Script** liest `PROJECT_ID` aus `PropertiesService` (`Script Properties`).
- **deploy.sh** nutzt ausschließlich Environment-Variablen — keine Hardcoded-Werte.
- `TARGET_FOLDER_ID` ist optional; leer bedeutet Scan vom Drive-Root aus.

---

## Laufmodi

### Implementiert (aktuelles Release)
- **Pass 1 (Erster Lauf):** Initialer Full-Walk + Hash/Dedupe. Generiert deduplizierte Datei-Baselines.
- **Pass 2 (Zweiter Lauf):** Semantic OCR + Indexing in `20_index`. Parsed Formate und generiert den Personal Brain Output als JSONL/JSON.
- **Safe Sort:** Generierung sicherer Sortiervorschläge (inklusive OCR-Semantik).
- **Apply Sort:** Destruktive Umsetzung (Verschieben/Löschen) via Sheets-Batching.
- **Full Run:** Apps Script startet Pass 1 und pollt automatisch bis Pass 2.
- **Resume:** `in_progress_page_token` erlaubt Delta-Fortsetzung nach Abbruch.
- **Shared Drives:** über `ENABLE_SHARED_DRIVES=true` unterstützt.

### Geplant / noch nicht verdrahtet
- **Pass 3 (Vector DBs):** Embedding-Prep ist aspirational und nicht im Code verdrahtet.
- **Obsidian Export:** Personal Brain Index als Flat-JSONL vorhanden; vollständiger Vault-Export ist ein zukünftiges Roadmap-Feature.
- **Automated Dashboards:** Nicht Teil dieses Codes.

---

## Folder-Initializer und Folder Registry
`initializeFolderStructure()` arbeitet autonom:
- legt `Folder_Registry` an, falls fehlend
- erzeugt/validiert Root + komplette Zielstruktur
- schreibt `folder_key, folder_name, folder_id, parent_folder_id, full_path`

## Safe Sort / Apply Sort
- **Safe Sort (`main_safe_sort.py`)** erzeugt nur Vorschläge in `Sorting_Suggestions`.
- **Apply Sort (`main_apply_sort.py`)** führt Bewegungen aus (ohne `rows.index(...)`).
- `action_mode=SAFE` verschiebt Dateien in den Zielordner.
- `action_mode=SWEEP_TRASH` markiert Inbox-Trash-Dateien als `trashed=true`.

## Sorting-Regeln
Jede Entscheidung enthält: `folder_rule`, `folder_rule_reason`

## Folder-aware Indexing
JSONL enthält konsistent:
- `current_parent_id`, `current_path`
- `target_parent_id`, `target_path`
- `folder_rule`, `folder_rule_reason`, `sort_mode`, `move_result`

Statusereignisse ohne OCR werden dennoch geschrieben (`DELETED`, `TRASHED`, `REMOVED_OR_NO_ACCESS`, `MOVED`, `RENAMED`).

## Notbremse / Trigger / Cleanup
- „Notbremse: Alle Hintergrund-Trigger stoppen" löscht Trigger + Polling-Properties.
- Trigger-Dedupe verhindert Zombie-Trigger.
- Poll-Timeout beendet Full-Run Polling automatisch.

## Troubleshooting
- `python3 release_audit.py` ausführen.
- Bei Quota-Fehlern greifen Backoff/Retries (Sheets + Gemini).
- Bei `PASS2_BLOCKED_NO_HANDOVER` im State: Pass 1 zuerst erfolgreich abschliessen, dann Pass 2 neu starten.
- Bei fehlender `PROJECT_ID` in Apps Script: Script Property setzen.

## Bekannte Grenzen
- OCR hängt von Gemini-Quota und Dateityp ab.
- Sehr große Delta-Runs benötigen mehrere Polling-Zyklen.
- `BRAIN_INDEX_ROOT` muss in Cloud Run auf ein persistentes Volume zeigen.

## Personal Brain Index

Pass 2 erweitert den klassischen Delta-Export um export-aware Parsing nach `20_index/published/`:
- Source/Record/Entity/Relation JSONL
- Daily/Weekly Memory Shards
- Search Views für Gemini/NotebookLM-nahe Nutzung

Einstiegspunkt: `personal_brain/runtime.py`, aufgerufen aus `main_pass2.py`.

### Knowledge Lifecycle / Exclusions
- Tab `Knowledge_Exclusions` steuert `ACTIVE`, `EXCLUDED`, `PURGED` pro `file_id`.
- Exclusions gelten auch für abgeleitete Archive-Subeinträge (ZIP-Inhalte via `bundle_id`).
