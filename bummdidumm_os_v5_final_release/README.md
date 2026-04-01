# bummdidumm-OS V5 Final System

Dies ist das finale, produktionsfertige System für "bummdidumm-OS V5".
Es ist eine vollständig modulare, auf Cloud Run Jobs basierende, idempotente und wiederanlaufbare Pipeline zur sicheren Google Drive Deduplizierung und strukturierten KI-Extraktion.

## 🏗️ System-Komponenten

1.  **Pass 1 (`main_pass1.py`)**: Delta Scan via Google Drive Changes API, echter Change-Type Auswertung (NEW, UPDATED, RENAMED, MOVED, DELETED, TRASHED), Hash-basierte Deduplizierung (SHA-256 mit MD5/Size Prefilter) und Archivierung. Speichert sauberen State im Sheet.
2.  **Pass 2 (`main_pass2.py`)**: Übernimmt Original-Dateien aus Pass 1, ruft die Gemini Files API auf und extrahiert mit Pydantic strukturierte JSON-Felder. Exportiert ein sauberes `.jsonl`-File und räumt die Gemini Cloud danach auf.
3.  **Renames (`main_apply_renames.py`)**: Ein optionaler dritter Job, der aus Sicherheitsgründen vom Hauptprozess entkoppelt wurde und die Namensvorschläge anwendet.
4.  **Control Plane (`appsscript/Code.gs`)**: Das Backend deines Google Sheets, mit dem du die Cloud Run Jobs per gesichertem OAuth Token auslösen kannst.

## 🛠️ Setup & Deployment

### 1. IAM und Service Account
Es ist strikt erforderlich, einen eigenen Service Account zu verwenden.
```bash
gcloud iam service-accounts create bummdidumm-runner --display-name="Bummdidumm Job Runner"
```
Gib diesem Service Account (E-Mail: `bummdidumm-runner@<DEINE_GOOGLE_CLOUD_PROJECT_ID>.iam.gserviceaccount.com`) in den Google Drive und Google Sheet Einstellungen "Bearbeiter"-Rechte für:
- Den `TARGET_FOLDER`
- Den `ARCHIVE_FOLDER`
- Den `INDEX_FOLDER`
- Das Control Sheet

### 2. Google Sheet Initialisierung
Du brauchst nur ein leeres Google Sheet anlegen und die `CONTROL_SHEET_ID` aus der URL kopieren. Wenn du den ersten Pass-1-Run startest, baut das Skript die Tabs (`State`, `Hash_Index`, `Dedupe_Report`, `Duplicate_Groups`, `Error_Report`, `Run_Log`, `Folder_Registry`, `Sorting_Suggestions`) samt Headern automatisch auf, falls sie fehlen.

### 3. Cloud Run Deploy
Führe `bash deploy.sh` in deiner Cloud Shell aus. Das Skript wird dich interaktiv nach deiner Google Cloud `PROJECT_ID` fragen, damit keine festen Platzhalter im Quellcode verbleiben. Passe vorher in `deploy.sh` deine Ordner-IDs (`TARGET_FOLDER_ID`, etc.) an.

### 4. Apps Script UI
Kopiere den Inhalt aus `appsscript/Code.gs` in den Apps Script Editor (Erweiterungen > Apps Script in deinem Google Sheet).
Wenn du das erste Mal einen Job per Button startest, wirst du interaktiv nach deiner `PROJECT_ID` gefragt. Diese wird dann sicher im internen `PropertiesService` des Sheets verankert.
Öffne die Datei `appsscript.json` im Manifest-Editor und stelle sicher, dass die Scopes korrekt übernommen wurden. Nach dem ersten Klick musst du OAuth bestätigen.

## 🚀 Lauf-Zyklen (Run Cycles)

### 1. Der erste Lauf (Initial Seed)
Beim allerersten Start (wenn `State!B1` leer ist), führt Pass 1 einen rekursiven Komplett-Scan (`files.list`) des Target Folders durch. Er ignoriert Trashed-Dateien. Am Ende merkt er sich den Google Drive `startPageToken` und speichert diesen im Tab `State`, damit ab diesem Zeitpunkt in Zukunft alle Änderungen registriert werden können.
*Hinweis:* Nach einem sehr großen ersten Lauf muss Pass 2 manuell gestartet werden, um die angesammelten Daten zu extrahieren.

### 2. Folge-Läufe (Deltas & Leere Deltas)
Jeder Lauf ab dann holt **nur noch Änderungen** aus der Drive Delta API. Wenn keine Änderungen vorliegen (leeres Delta), schließt der Job direkt erfolgreich ab und verbraucht weder RAM noch API Quota für Hash-Vorgänge. Wenn eine Datei auftaucht, prüft die smarte Logik (siehe `shared/change_type_logic.py`), ob die Datei explizit `NEW`, `UPDATED`, `RENAMED`, `MOVED`, `DELETED`, `TRASHED` oder `REMOVED_OR_NO_ACCESS` ist.
- `MOVED`: Wird anhand einer Abweichung der `parent_id` (gespeichert als prefix im `path`) registriert.
- `UPDATED`: Wird anhand von `size`, `md5` und `modifiedTime` validiert. Ein MD5+Size Prefilter für Binaries sorgt für massive Performance.

### 3. Resume nach Abbruch (Strikte Idempotenz)
Bricht Cloud Run z.B. bei Minute 59 durch Out-Of-Memory oder Timeout ab, sorgt die State Machine für eine lückenlose Wiederaufnahme:
- Das Skript liest das `in_progress_page_token` aus dem Sheet.
- Die `run_id` bleibt erhalten, sodass Reportings konsistent als "ein Lauf" protokolliert werden.
- Werden Dateien der im Abbruch-Moment unvollständigen Pagination erneut geparst, erkennt das Skript, wenn die exakte `file_id` bereits in `Hash_Index` existiert. Die Datei wird als `ORIGINAL_RESUMED` getrackt und entgeht so einem Duplikats-Archivierungs-Fehler ("Self-Archive Bug").

## ⚙️ Google Apps Script Betriebsfunktionen

Die Google-Sheet-Steuerung enthält tiefgreifende native Mechanismen, um Cloud Run Jobs sicher zu orchestrieren, da einfache HTTP-Requests von Apps Script zu Cloud Run Jobs durch synchrone Zeitlimits von wenigen Minuten beschränkt sind.

1. **Vollautomatische Orchestrierung ("Kompletten Lauf starten"):**
   Wenn du diesen Menüpunkt anklickst, triggert Apps Script Pass 1 (Delta & Dedupe) asynchron. Gleichzeitig registriert es **vollautomatisch einen zeitgesteuerten Apps-Script-Trigger** (`ScriptApp.newTrigger`), der alle 5 Minuten das `State`-Tab prüft. Sobald dort `PASS1_DONE` steht, feuert dieser Background-Trigger selbstständig Pass 2 (OCR & Indexing) ab und löscht sich sofort auf, sodass du nie manuell nachklicken musst.
2. **Zombie-Trigger-Schutz:**
   Sollte Pass 1 durch einen Fehler (Timeout/OOM) auf Google Cloud Seite crashen und nie den Erfolgs-State schreiben, würde der Trigger theoretisch unendlich weiterlaufen. Daher überwacht Apps Script strikt die Versuche (`POLL_ATTEMPTS`). Nach 60 Minuten (12 Versuche) killt sich der Poller selbst, bereinigt den Status und wirft eine klare `TIMEOUT` Warnung in den `Error_Report`.
3. **Die Notbremse:**
   Solltest du das Gefühl haben, dass etwas in einer Pipeline-Schleife hängt, kannst du im Menü "🛑 NOTBREMSE" klicken. Dies löscht garantiert nur die für diesen Workflow spezifischen Hintergrund-Trigger (ohne andere Skripte deines Projekts zu tangieren) und resetted den internen Script-Property-State.
4. **Auto-Cleanup für transiente Ordner:**
   Google Drive wird über die Zeit zugemüllt. Das Skript bringt die Funktion `autoCleanupTransientFolder()` mit.
   - Gehe im Skripteditor auf das **Zahnrad (Projekteinstellungen)** und setze unten eine Script Property mit dem Namen `TRANSIENT_FOLDER_ID` und der Ordner-ID deines Schrott-Ordners. Optional setze `TRANSIENT_RETENTION_DAYS` (Standard: 7).
   - Lege über das "Uhr"-Icon (Trigger) in der linken Sidebar einen neuen zeitgesteuerten Trigger an, der z.B. 1x täglich die Funktion `autoCleanupTransientFolder` aufruft. Alte Dateien werden dann strikt nach dem Datum ihrer letzten Änderung (Last Updated) aussortiert und in den Papierkorb verschoben.

## 📁 Folder Initializer & Sorting Layer (Safe Mode / Apply Mode)

Das System enthält nun eine native Ordnerverwaltung und Sortierungs-Logik:
1. **Ordnerstruktur initialisieren:** Über das Menü kannst du vollautomatisch die vorgegebene bummdidumm Zielstruktur (z.B. `00_inbox`, `10_decisions`, `40_docs/...`) erzeugen lassen. Fehlende Ordner werden angelegt und ihre internen Drive-IDs sicher in den Apps Script Properties (`FOLDER_MAP_JSON`) hinterlegt.
2. **Safe Mode (Sortier-Vorschläge):** Ein eigener Job bewertet Dateien des aktuellen Laufs nach 8 Prioritäten (u.a. Duplikate -> Archiv, Bilddateien -> Media, Skripte -> Scripts, etc.). Im Safe Mode verschiebt das Skript **nichts**, sondern dokumentiert nur den aktuellen und vorgeschlagenen Ort, sowie den Regel-Grund im Tab `Sorting_Suggestions`.
3. **Apply Mode (Sortierung anwenden):** Wenn du die Vorschläge im Sheet gesichtet hast, kannst du im Menü "Sortierung anwenden" klicken. Ein weiterer Cloud Run Job verschiebt die Dateien dann verlässlich über die Drive API.

## 📈 Performance & Scaling
- **Pass 1 (Deltas & Hashes):** Liest nur Änderungen seit dem letzten Sync. Grosse Binaries, die `SKIP_OVER_MB` überschreiten, werden direkt mit dem Hash-Marker `HASH_SKIPPED` in den `Hash_Index` übertragen. Bei zukünftigen Delta-Läufen weiß Pass 1 dann sofort, dass er diese nicht endlos neu downloaden muss, kann aber dennoch `MOVED` und `RENAMED` Metadaten-Updates verarbeiten.
- **Pass 2 (OCR & RAM-Load):** Um bei >100,000 Dateien Memory-Crashes im Container zu vermeiden, liest Pass 2 den `Dedupe_Report` nun in kleinen Batches (`chunk_size=1000`) per Iterator ein, anstatt die gesamte Tabelle in den RAM zu verfrachten. Zudem schützt ein Exponential-Backoff die App vor Google Sheet `429 Too Many Requests` API-Fehlern.

## 🗂️ Shared Drive Support
Das Projekt ist strikt "Shared Drive" kompatibel. Es nutzt `supportsAllDrives=True` bei direkten Datei-Aktionen (`get`, `update`, `export`) und kombiniert dies mit `includeItemsFromAllDrives=True` bei Listenabfragen (`changes.list`, `files.list`). So wird inkonsistentes Verhalten vermieden.

## 🔧 Troubleshooting

- **Google-Native Files Crashen:** Wenn Docs/Sheets extrahiert werden, wird der Inhalt nach PDF exportiert, worauf der Streaming-SHA256 basiert. Achte darauf, dass der Service Account Export-Berechtigungen in dem Workspace hat.
- **Pass 2 startet nicht automatisch:** Wenn "Kompletten Lauf starten" genutzt wurde, aber Pass 1 fehlgeschlagen ist (`PASS1_FAILED`), löscht sich der Zeit-Trigger, um keine Endlos-Schleifen auszulösen. Prüfe im `Error_Report`, warum Pass 1 abgestürzt ist.
- **Quota Error (Gemini):** Nutzt du die Free Tier API von Gemini, könnte Pass 2 das Limit reissen. Der Job bricht dann ab. Reduziere in diesem Fall die Taktung.
