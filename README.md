# bummdidumm-OS V5 Final Release

This repository contains the Basel-Radar / bummdidumm-OS V5 pipeline for Google Drive deduplication, OCR, folder sorting, and Personal Brain extraction.

## Quick Start (lokal testen — keine Cloud-Infrastruktur nötig)

```bash
cd bummdidumm_os_v5_final_release
pip install -r requirements.lock
PYTHONPATH=bummdidumm_os_v5_final_release python3 -m pytest bummdidumm_os_v5_final_release/tests/ -q          # Smoke-Tests
python3 bummdidumm_os_v5_final_release/release_audit.py              # Release-Check
```

---

## Architektur-Überblick

1. **Google Apps Script:** Liefert Menübefehle, Start/Stop von Run-Jobs über Cloud Run, Timeout-Poller, State-Tracking. (Code in `appsscript/Code.gs`).
2. **Cloud Run Jobs:** 5 isolierte Jobs (Pass 1, Pass 2, Safe Sort, Apply Sort, Apply Renames), die unabhängig voneinander Daten parallel von der Google Drive API streamen und verarbeiten.
3. **Google Sheets (CONTROL_SHEET_ID):** Das zentrale State-Backend. Nutzt eine eventual-consistent Sheets-API für Lock-Mechanismen und Speichern von Duplikat- und Fehlerprotokollen sowie Hashing-Indexen.
4. **Cloud Storage (BRAIN_INDEX_BUCKET):** Das Ziel von Pass 2. OCR und Entitäten-Strukturen ("Personal Brain") werden via FUSE Mount hierhin als JSONL abgelegt.

---

## Umgebungsvariablen

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

Tab `Knowledge_Exclusions` steuert `ACTIVE`, `EXCLUDED`, `PURGED` pro `file_id`.
Exclusions gelten auch für abgeleitete Archive-Subeinträge (ZIP-Inhalte via `bundle_id`).

#### Finale Lifecycle-Semantik (bindend)

| Status | Bedeutung | Brain-Records | Re-Ingest |
|--------|-----------|---------------|-----------|
| `ACTIVE` | Quelle ist aktiv im Scope und wird indiziert | Indiziert + aktualisiert | Ja |
| `EXCLUDED` | Quelle wird übersprungen (manuell oder auto bei gelöschten/scope-exited) | **Erhalten** | Nein |
| `PURGED` | Quelle vollständig aus publizierten Indizes entfernt | **Tombstoned** | Nein |

**Auto-Exclusion-Regel:** Quellen mit `change_type` in `{DELETED, TRASHED, REMOVED_OR_NO_ACCESS, MOVED_OUT_OF_SCOPE}` werden im Brain-Runtime automatisch als `EXCLUDED` behandelt — bestehende Brain-Records bleiben erhalten, neuer Ingest wird gestoppt. Explizite `Knowledge_Exclusions`-Einträge haben immer Vorrang.

#### PURGED — was konkret passiert

Wenn eine Datei auf `PURGED` gesetzt ist (oder `EXCLUDED` + manuell auf PURGED hochgestuft), entfernt der nächste Pass-2-Lauf folgendes aus den publizierten Artefakten:

| Artefakt | Entfernungslogik |
|----------|-----------------|
| `00_source_registry.jsonl` | Einträge mit `file_id` in purged_file_ids → gelöscht |
| `01_record_index.jsonl` | Einträge mit `file_id` in purged_file_ids → gelöscht |
| `02_entity_index.jsonl` | Entitäten, deren **alle** `source_ids` zu purged file_ids gehören → gelöscht |
| `03_relation_index.jsonl` | Relationen, deren **alle** `source_ids` zu purged file_ids gehören → gelöscht |
| `04_daily_memory/*.json` | Tagesdateien ohne verbleibende Records → automatisch gelöscht |
| `04_weekly_memory/*.json` | Wochendateien ohne verbleibende Tage → automatisch gelöscht |
| `file_topics.json` | Einträge für purged `file_id`s → entfernt |

**Partieller Purge:** Entities/Relations, die auch auf nicht-gepurgten Quellen basieren, werden NICHT tombstoned — sie konvergieren beim nächsten Re-Index der überlebenden Quellen.

#### Scope Exit — was passiert wenn eine Datei den Scope verlässt

1. **Pass 1 / Drive-Level:** `drive_helpers.py` erkennt Dateien außerhalb des `TARGET_FOLDER_ID`-Baums und setzt synthetisch `scope_exit=True` → `change_type = MOVED_OUT_OF_SCOPE` in Dedupe_Report.
2. **Pass 2 / JSONL-Delta:** `MOVED_OUT_OF_SCOPE` wird in die `valid_statuses` aufgenommen und als `event_only_no_content_processing` weitergeleitet.
3. **Brain-Runtime:** Auto-EXCLUDED → Parser wird nicht aufgerufen, bestehende Records bleiben erhalten.
4. **Vollständige Entfernung:** Nur durch manuelles Setzen von `PURGED` in `Knowledge_Exclusions`.

### Parallelität / Job Locks

**Pass 1** schützt sich über ein vollständiges Lease-System mit Heartbeat
(`lease_owner_id`, `lease_heartbeat_at`, `lease_acquired_at`) inkl. TOCTOU-Fence (500ms).

**Downstream Jobs** (Safe Sort, Apply Sort, Apply Renames) nutzen einfache Job-Level Locks
ohne Heartbeat (kürzere Laufzeit). Implementiert via `StateTracker.acquire_job_lock()` /
`release_job_lock()` in `shared/state_helpers.py`.

| State-Key | Bedeutung |
|-----------|-----------|
| `{job_name}_lock_owner` | `owner_id` des Lock-Inhabers |
| `{job_name}_lock_at` | ISO-UTC Zeitstempel der Übernahme |

Stale Locks (älter als Timeout, Default: 600s) werden automatisch übernommen.

**Konfiguration via Env-Variablen:**

| Variable | Default | Gilt für |
|----------|---------|----------|
| `SAFE_SORT_LOCK_TIMEOUT_SEC` | 600 | Safe Sort |
| `APPLY_SORT_LOCK_TIMEOUT_SEC` | 600 | Apply Sort |
| `APPLY_RENAMES_LOCK_TIMEOUT_SEC` | 600 | Apply Renames |

Wenn ein Job geblockt wird, loggt er eine Warning und beendet sich ohne Fehler. Ein nachfolgender Cron-Lauf kann ihn erneut starten.

**Bekannte Restgrenzen:** Die Sheets-API ist eventual-consistent. Concurrent Sheets-API-Calls mit <500ms Abstand können nicht vollständig verhindert werden. Der Job-Lock bietet Schutz im Sekunden-Bereich, nicht im Millisekunden-Bereich.

### Operatives Runbook

**Datei manuell purgen:**
1. `Knowledge_Exclusions` Tab öffnen
2. `file_id` der Datei in Spalte A eintragen, Status `PURGED` in Spalte C setzen
3. Nächsten Pass-2-Lauf abwarten → Artefakte werden bereinigt

**Stale Lock manuell löschen:**
Im State-Tab die Schlüssel `{job_name}_lock_owner` und `{job_name}_lock_at` auf leer setzen.
Alternativ wartet das System nach `{JOB}_LOCK_TIMEOUT_SEC` Sekunden automatisch auf Takeover.

**Tages-Memory-Datei neu bauen:**
Pass 2 erneut ausführen. `write_daily_memory()` rebuildet immer aus dem aktuellen
`01_record_index.jsonl` und löscht dabei Tagesdateien ohne verbleibende Records.

## Governance

- Branch protection and CI rules: [`REPO_GOVERNANCE_SETUP.md`](REPO_GOVERNANCE_SETUP.md)
- Agent task constraints: [`AGENT_FINALIZATION_PROTOCOL.md`](AGENT_FINALIZATION_PROTOCOL.md)
