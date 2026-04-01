# Dein bummdidumm-OS Masterplan V5

Dieser Masterplan skizziert die Roadmap für V5. Hier geht es nicht um noch mehr lose Features, sondern um **Härtung, operativen Betrieb und architektonische Robustheit**. Wir machen aus dem Skript eine echte, wiederanlaufbare Datenpipeline für dein AI-OS.

---

## 🏗️ Phase V4.1: Basis-Härtung & Sicherheit

1. **Rename-Safe-Mode:**
   - Dateiumbenennungen werden von der Deduplizierung (Löschen/Verschieben) entkoppelt.
   - Vorschläge für neue Namen (`Suggest_Name`) werden zunächst nur in den Report (Sheet) geschrieben.
   - Eine separate Funktion (z.B. ein zweiter Job oder ein eigener API-Call per `files.update`) wendet diese Vorschläge nach menschlicher Prüfung gezielt an.
2. **MD5 + Size Vorfilter als Performance-Hilfe, nicht als Logikanker:**
   - MD5 + Größe dienen rein als schneller Vorfilter. **SHA-256 bleibt die alleinige Entscheidungsgrundlage** für Duplikate.
   - Die Drive API liefert `md5Checksum` nicht zuverlässig für alle Dateitypen (z.B. Google-native Formate wie Docs/Sheets).
3. **Konsequente Shared-Drive-Unterstützung:**
   - Parameter wie `driveId`, `includeItemsFromAllDrives=True` und `supportsAllDrives=True` werden Shared-Drive-kompatibel pro API-Call korrekt dort gesetzt, wo der jeweilige Call sie benötigt.
   - Dies verhindert inkonsistente Ergebnisse zwischen "My Drive" und "Shared Drives".
4. **Service Identity Härten:**
   - Der Cloud Run Job läuft nicht mehr unter der (zu weit gefassten) Default-Compute-Engine-Identität.
   - Es wird ein dezidierter Service Account (`bummdidumm-runner@...`) erstellt, der exakt und ausschließlich die benötigten Rechte auf das Sheet und die Ziel-Ordner in Drive hat.

---

## 🧠 Phase V4.2: Gemini & OCR Optimierung

1. **Strukturierte Gemini-Ausgabe (JSON Schema):**
   - Statt einfachem Freitext (`response.text`) wird das offizielle `google-genai` SDK genutzt, um strukturierte Daten zu erzwingen (Structured Outputs).
   - Feste Felder: `doc_type` (Rechnung, Brief, Foto), `amount` (Betrag), `date` (Belegdatum), `vendor` (Absender/Händler), `summary`.
2. **Gezieltes OCR-Targeting:**
   - OCR/Extraktion wird *nur* für relevante Kandidaten gestartet: PDFs (`application/pdf`) und Bilder (`image/*`).
   - Google Docs/Sheets/Slides werden (bei Bedarf) per Drive-Export-API als Text oder PDF heruntergeladen und dann verarbeitet. *Wichtig: Der Hash bezieht sich dann auf den exportierten Repräsentationsinhalt, nicht auf das interne Google-Dateiformat.*
3. **Gemini File-Lifecycle Management:**
   - Dateien, die via `gemini_client.files.upload()` an Google gesendet werden, bleiben sonst 48 Stunden auf den Google-Servern liegen.
   - V5 implementiert einen sauberen Lifecycle: `Upload` → `Verarbeitung (generate_content)` → `Explizites Löschen (client.files.delete)` im `finally`-Block.

---

## 🔄 Phase V4.3: Delta-Scan & Drive-Logik

1. **Robuste Delta-Logik (Idempotenz):**
   - Das Paginieren von `changes.list` wird streng abgearbeitet.
   - Der `newStartPageToken` wird erst ganz am Ende, wenn alle Chunks und Verarbeitungen (OCR, Dedupe) erfolgreich abgeschlossen sind, im Sheet gespeichert.
   - Ein Abbruch (Timeout/OOM) führt beim nächsten Start nicht zum Chaos, weil das Skript zusätzlich den In-Progress-`nextPageToken` und die jeweilige Verarbeitungsphase persistiert, um ein echtes Resume zu ermöglichen.
2. **Statusklassifizierung im Delta:**
   - Geänderte Dateien werden im Report und im JSONL klar unterschieden in:
     - `NEW` (neue Datei)
     - `UPDATED` (Inhalt geändert)
     - `RENAMED` (nur Name geändert)
     - `MOVED` (Pfad/Ordner geändert)
     - `DELETED` / `TRASHED` (Datei entfernt)
3. **Optimierter Ancestor-Cache:**
   - Die Prüfung `is_in_target_folder` wird über einen Cache optimiert, der Hierarchien (Pfade) im RAM hält. Das reduziert die Drive-API Lookups massiv, wenn viele Dateien im gleichen Unterordner geändert wurden.

---

## 📊 Phase V4.4: Erweitertes Reporting & JSONL

1. **Erweiterter JSONL-Kanon:**
   - Das Datenmodell in `20_index/` wird ausgebaut für besseres RAG/BigQuery-Ingest:
     - `effective_mime_type`, `export_source` (Drive/Native), `duplicate_of` (Hash/ID), `archive_result` (Erfolg/Fehler), `change_type` (New/Update), `run_id` (Job-Instanz-ID).
2. **Neue Sheets für operativen Betrieb:**
   - **`Duplicate_Groups`**: Ein Tab, der Duplikate nicht als flache Liste zeigt, sondern pro Hash gruppiert (Original-ID vs. Kopien).
   - **`Error_Report`**: Ein dedizierter Tab für Fehler (Export fehlgeschlagen, Rechte fehlen, Gemini-Quota erreicht), getrennt vom regulären Dedupe-Report.

---

## 🚀 Phase V5: Die Zwei-Pass-Pipeline (Echter Betriebsmodus)

V5 verlässt den Zustand eines einfachen Skripts und wird zu einem operativen System.

### 1. Die State-Architektur im Google Sheet
Dein Control-Sheet wird das Dashboard mit folgenden Tabs:
- `State` (enthält `Page Token`, `Run IDs`, Timestamps)
- `Hash_Index` (persistente Datenbank aller Hashes)
- `Dedupe_Report` (die flache Liste des aktuellen Laufs)
- `Duplicate_Groups` (Gruppierte Ansicht)
- `Error_Report` (Fehler-Log)
- `Run_Log` (Historie: Wann lief welcher Job wie lange?)

### 2. Die Zwei-Pass-Pipeline
Um Idempotenz und Performance zu garantieren, wird der Job in zwei Pässe geteilt:
- **Pass 1: Fast Dedupe & Delta**
  - Holt Deltas, berechnet Hashes (oder nutzt MD5-Filter), aktualisiert den `Hash_Index`, verschiebt Duplikate ins Archiv. *Hier passiert noch keine langsame KI-Extraktion.*
- **Pass 2: Heavy OCR & Indexing**
  - Nimmt nur die *verbleibenden Originale* aus Pass 1, führt die teure Gemini-OCR/Extraktion durch, erzeugt die strukturierten Felder und schreibt die fertigen `.jsonl` Index-Dateien.

### 3. Konfigurierbare Policies (Env Vars)
Sämtliche Logik wird über das Environment steuerbar:
- `SKIP_OVER_MB` (z.B. 500)
- `ENABLE_OCR` (true/false)
- `ENABLE_ARCHIVE` (true/false)
- `ENABLE_SHARED_DRIVES` (true/false)

### 4. Ausgebautes Apps Script Menü (Control Plane)
Deine Schaltzentrale in Google Sheets (die strikt als Control Plane agiert, während Cloud Run die Processing Plane bleibt) bekommt mehr Knöpfe:
- `🚀 Fast Delta-Scan starten` (Nur Pass 1)
- `🧠 OCR & Indexing starten` (Nur Pass 2)
- `🔄 Kompletten Lauf starten` (Pass 1 + 2)
- `🗑️ Error Reports leeren`

---

**Fazit:** V5 ist der Weg vom Skript zur Plattform. Es fokussiert sich auf sauberes Error-Handling, exakte Rechte, Kosteneffizienz bei der API-Nutzung und eine architektonisch skalierbare Pipeline. *(Hinweis: Für den Hash_Index ist das Google Sheet bei sehr großen Beständen jenseits der 100.000+ Dateien langfristig der erste Engpass und sollte später in SQLite, BigQuery oder Cloud SQL ausgelagert werden).*
