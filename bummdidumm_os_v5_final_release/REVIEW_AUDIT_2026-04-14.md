# Technische Zustandsprüfung (Repo-/PR-/Verlustanalyse) — 2026-04-14

## Arbeitsweise (ausgeführt)
1. **Phase 1 – Blind Read (Code zuerst):** `README.md`, `deploy.sh`, `main_pass1.py`, `main_pass2.py`, `shared/state_helpers.py`, `shared/drive_helpers.py`, CI-Workflow.
2. **Phase 2 – Historien-/PR-Abgleich:** `git log --oneline --decorate --graph --all` auf PR-/Merge-Spuren.
3. **Phase 3 – Konsolidiertes Urteil:** nur belegte Aussagen; fehlende Nachweisbarkeit explizit als **UNSICHER**.

**Unsicherheitsprotokoll:** GitHub-CLI (`gh`) ist in der Laufumgebung nicht vorhanden, und es ist kein Remote konfiguriert. Daher ist eine verifizierte Liste *aktuell offener* PRs in dieser Umgebung nicht direkt abrufbar.

---

## 1) Gesamturteil

**BEDINGT DEPLOYBAR**

Der Kernpfad ist technisch funktionsfähig genug für kontrollierten Betrieb: lokale Tests sind grün (55/55), und der Release-Audit läuft auf PASS. Gleichzeitig existiert ein operativer Widerspruch zwischen Dokumentation und realem Deploy-Entrypoint: `deploy.sh` verlangt fail-fast `SA_EMAIL` und `BRAIN_INDEX_ROOT`, während die README-Deploy-Sequenz diese Pflichtvariablen nicht enthält. Dieser Fehler ist nicht kosmetisch, sondern führt zu reproduzierbar scheiternden Deploys bei Onboarding-/Incident-Operatoren. Zusätzlich hat Pass 2 einen bestätigten Zustandsmaschinenfehler: `current_phase` wird auf `PASS2_OCR_INDEXING` gesetzt, bevor die Übergabe (`ready_for_pass2_run_id`) geprüft wird; bei fehlender Übergabe wird nur geloggt und direkt zurückgegeben. Das erzeugt nicht zwingend Datenkorruption, aber fehlerhafte Betriebs-Signalisierung und potenziell falsche Recovery-Entscheidungen. CI und Lockfile-Nutzung sind real verdrahtet und nicht nur behauptet. Historisch sind Hardening-Änderungen aus den jüngeren PR-Linien im Code sichtbar; ein harter Nachweis für regressiv verlorene Security-Fixes im aktuell prüfbaren Scope liegt nicht vor.

---

## 2) Kritische Befunde

### Befund K1 — Deploy-Doku ist nicht deckungsgleich mit dem realen Deploy-Entrypoint
- **Klasse:** **VERSEHENTLICH FEHLEND**
- **Beleg:**
  - `deploy.sh` fordert fail-fast: `SA_EMAIL`, `BRAIN_INDEX_ROOT`.
  - README-Setup/Deploy nennt diese Variablen im Deploy-Befehl nicht.
- **Warum kritisch:** offizieller Copy/Paste-Deploy schlägt hart fehl.
- **Konsequenz im Betrieb:** Deployment-Blocker, erhöhte MTTR, vermeidbare Eskalationen.
- **Empfohlene Korrektur:** README Setup + Deploy-Command um beide Variablen ergänzen, plus knappe Zweckbeschreibung (Service Account / persistenter Indexpfad).

### Befund K2 — Pass-2-Status kann „in progress“ signalisieren obwohl nichts verarbeitet wird
- **Klasse:** **BESTÄTIGTER BUG / FEHLER**
- **Beleg:** `current_phase=PASS2_OCR_INDEXING` vor Handover-Check; bei fehlendem `ready_for_pass2_run_id` nur Fehlerlog + `return`.
- **Warum kritisch:** Betriebszustand wird unpräzise; Operatoren sehen ggf. „läuft“ statt „blockiert“.
- **Konsequenz im Betrieb:** Fehlgeleitete Retries/Stops, unklare Incident-Triage.
- **Empfohlene Korrektur:** dedizierter Zustand `PASS2_BLOCKED_NO_HANDOVER` + `log_run(..., "NO_HANDOVER", ...)` oder explizite Rücksetzung.

---

## 3) Mittlere und kleinere Lücken

### Mittlere Lücken
1. **Open-PR-Vollständigkeit nicht belegbar (UNSICHER):** ohne Remote + ohne `gh` keine harte „alle offenen PRs“-Aussage möglich.
2. **Audit-Tiefe:** `release_audit.py` ist stark als Struktur-/Marker-Check, aber kein vollständiger Produktions-Last-/Chaos-Test.

### Kleinere Lücken
1. Lokale Verifikation lief unter Python 3.10; CI-Matrix ist 3.11/3.12.
2. Historie enthält viele supersedete Automationslinien; erschwert forensische Nachvollziehbarkeit.

### Konsolidierungsfragilität
- PR-Zuordnung via Commit-Betreff `(#xx)` bleibt ohne GitHub-Metadaten partiell heuristisch (**UNSICHER**).

---

## 4) PR-Konsolidierungsbefund

| PR | Status | Inhalt | Im main vorhanden? | Vollständig / teilweise / fehlt | Relevanz heute | Empfehlung |
| -- | ------ | ------ | ------------------ | ------------------------------- | -------------- | ---------- |
| #76 | geschlossen/integriert (Commit-Hinweis) | Tempfile-Retry-Leak + README-Alignment | Code: ja | **teilweise übernommen** | hoch | README-Lücke schließen; kein zusätzlicher Code-Cherry-pick nötig |
| #75 | geschlossen/integriert (Commit-Hinweis) | Tempfile-Resource-Leak-Härtung | ja | **korrekt vorhanden** | hoch | Regressionstest erhalten |
| #72 | geschlossen/integriert (Commit-Hinweis) | Deploy/runtime/CI/compaction/audit hardening | weitgehend ja | **teilweise übernommen** (Doku-Drift) | hoch | Doku driftfrei ziehen |
| #71 | geschlossen/integriert (Commit-Hinweis) | AppScript-Confirmations für destruktive Actions | **UNSICHER** | **UNSICHER** | mittel | gezielte `Code.gs`-Tiefprüfung nachholen |
| #70 | geschlossen/integriert (Commit-Hinweis) | sorting_helpers Perf-Tuning | ja | **korrekt vorhanden** | niedrig-mittel | belassen |
| #63 | geschlossen/integriert (Commit-Hinweis) | tuple prefix/suffix optimization | ja | **korrekt vorhanden** | niedrig | belassen |
| #56 | geschlossen/integriert (Commit-Hinweis) | Finalization protocol enhancements | größtenteils ja | **teilweise übernommen** | mittel-hoch | weiter in CI härten |
| #52 | geschlossen/integriert (Commit-Hinweis) | dedupe batching/entity merge durability | ja | **korrekt vorhanden** | hoch | Lasttests ergänzen |
| #48 | gemergt (Merge-Commit) | audit/review branch | ja | **korrekt vorhanden** | mittel | archiviert lassen |
| #46 (konsolidiert #41–#45) | geschlossen/integriert | Konsolidierung mehrerer Linien | teilweise historisch verifizierbar | **UNSICHER** | mittel | nicht reaktivieren, nur Lücken gezielt übernehmen |
| Offene PRs (heute) | **UNSICHER** | mangels Remote/`gh` nicht verifizierbar | **UNSICHER** | **UNSICHER** | hoch | in GitHub-Umgebung mit PR-API ergänzen |

---

## 5) Historische Verlustanalyse

### Verlustfall V1
- **Ursprungs-PR/Branch:** #76 (laut Commit-Betreff)
- **Was dort enthalten war:** Leak-Fix + README-Alignment
- **Was heute fehlt:** vollständige README-Angleichung für Deploy-Pflichtvariablen
- **Wahrscheinliche Entstehung:** technische Fixes übernommen, Doku-Follow-up unvollständig
- **Relevanz heute:** hoch
- **Empfehlung:** sofortige Doku-Korrektur

### Verlustfall V2
- **Ursprungs-PR/Branch:** offen/unbekannt
- **Was dort enthalten war:** **UNSICHER**
- **Was heute fehlt:** belegte Open-PR-vs-main-Verlustmatrix
- **Wahrscheinliche Entstehung:** lokale Umgebung ohne PR-Metadatenzugang
- **Relevanz heute:** hoch (für vollständige forensische PR-Verlustanalyse)
- **Empfehlung:** einmalige Nachprüfung in GitHub-Umgebung

---

## 6) Priorisierte To-do-Liste

### Kritisch
1. README-Deployanleitung mit `deploy.sh` synchronisieren (`SA_EMAIL`, `BRAIN_INDEX_ROOT`).
2. Pass-2-Fehlpfad ohne Handover mit explizitem Blocked-Status + Run-Log schließen.

### Wichtig
1. Open-PR-Abgleich gegen `main` via GitHub-API nachziehen.
2. Betriebsrunbook um neuen Pass-2-Blocked-Status erweitern.

### Nachgelagert sinnvoll
1. Last-/Stresstests für große `Sorting_Suggestions` und `Dedupe_Report` ergänzen.
2. PR-Konsolidierungsentscheidungen (superseded/cherry-picked/nicht übernommen) als Mapping dokumentieren.

---

## 7) Belegbasis

### Code-/Doku-Belege
- `bummdidumm_os_v5_final_release/deploy.sh`
- `bummdidumm_os_v5_final_release/README.md`
- `bummdidumm_os_v5_final_release/main_pass2.py`
- `.github/workflows/personal-brain-gates.yml`

### Verwendete Befehle
- `python3 bummdidumm_os_v5_final_release/release_audit.py` → PASS
- `PYTHONPATH=bummdidumm_os_v5_final_release pytest bummdidumm_os_v5_final_release/tests/ -q` → 55 passed
- `git log --oneline --decorate --graph --all`
- `git remote -v` (kein Remote ausgegeben)
- `gh pr list --state all --limit 30` (fehlgeschlagen: `gh: command not found`)

---

## 8) Harte Endtrennung

### Korrekt vorhanden
- CI nutzt `requirements.lock` explizit.
- Tempfile-Cleanup im Pass-2-Downloadpfad ist vorhanden.
- Testsuite + Release-Audit laufen in der lokalen Prüfung erfolgreich.

### Bewusst nicht implementiert
- Pass 3 / Vector-DB-Integration.
- Vollständiger Obsidian-Vault-Export.

### Versehentlich fehlend
- Vollständige Dokumentation aller Deploy-Pflichtvariablen in README.

### Teilweise übernommen
- PR-Linie #76: technischer Fix vorhanden, Doku-Angleichung unvollständig.
- PR-Linie #72: Hardening großteils vorhanden, Doku-Konsistenz nicht vollständig.

### Regressiv verloren
- Kein harter Nachweis für regressiv verlorene Security-Fixes im prüfbaren lokalen Scope.
- Open-PR-Verlustbefunde bleiben ohne GitHub-PR-Metadaten **UNSICHER**.

---

## Klassifikationsmatrix (harte Zuordnung)
- **FAKTISCH BESTÄTIGT:** CI-Lockfile-Verdrahtung; Pass-2-Tempfile-Cleanup; lokale Test-/Audit-Pässe.
- **BESTÄTIGTER BUG / FEHLER:** Pass-2-Phase-Set vor Handover-Validierung mit frühem Return.
- **PLAUSIBLES RISIKO:** forensische Unschärfe durch fehlende Open-PR-Metadaten.
- **BEWUSST NICHT IMPLEMENTIERT:** Pass 3 / Obsidian-Vault laut README.
- **VERSEHENTLICH FEHLEND:** README-Deploy-Pflichtvariablen unvollständig.
- **TEILWEISE ÜBERNOMMEN:** deklarierter README-Alignment-Teil aus #76 nicht vollständig sichtbar.
- **REGRESSIV VERLOREN:** kein belegter Fall im lokalen, verifizierbaren Scope.
- **KORREKT VORHANDEN:** Kern-Qualitätsgates (lokal) und wesentliche Hardening-Linien.
