# OPERATING_MODEL

## Export-/LLM-Indexing Ergänzung

1. Pass 1 bleibt Scan/Dedupe-Kanon.
2. Pass 2 schreibt Delta JSONL und ruft anschließend die Parser-Registry-Runtime auf.
3. Runtime erzeugt deterministische IDs (`source_id`, `record_id`, `entity_id`, `relation_id`) aus stabilen Hashes.
4. Parserfehler sind isoliert je Quelle (Registry-Fallback auf Generic Parser).

## Bekannte RAM-Grenze: records_to_index in Pass 2

Pass 2 liest die `Dedupe_Report`-Zeilen chunk-weise (JSONL-Schreibpfad), hält aber
`records_to_index` als vollständige In-Memory-Liste für den `PersonalBrainRuntime`-Aufruf.
Bei mehr als 50.000 Einträgen loggt Pass 2 eine Warnung (`RAM-Druck möglich`).

**Empfehlung:** OCR-Budget via `OCR_BUDGET_PER_RUN` und `SKIP_OVER_MB` begrenzen,
um die Listengröße pro Run kontrolliert zu halten. Ein vollständiges Streaming des
`PersonalBrainRuntime`-Aufrufs würde einen Architekturumbau erfordern und ist
im aktuellen Release bewusst nicht implementiert (Kommentar in `main_pass2.py`).
