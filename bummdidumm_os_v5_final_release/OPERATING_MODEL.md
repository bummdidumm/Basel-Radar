# OPERATING_MODEL

## Export-/LLM-Indexing Ergänzung

1. Pass 1 bleibt Scan/Dedupe-Kanon.
2. Pass 2 schreibt Delta JSONL und ruft anschließend die Parser-Registry-Runtime auf.
3. Runtime erzeugt deterministische IDs (`source_id`, `record_id`, `entity_id`, `relation_id`) aus stabilen Hashes.
4. Parserfehler sind isoliert je Quelle (Registry-Fallback auf Generic Parser).


## Pass-2 RAM-Guardrail (records_to_index)

- `main_pass2.py` materialisiert `records_to_index` im Speicher für den Brain-Runtime-Aufruf.
- Ab `records_to_index > 50_000` wird eine Warnung via `log.warning(...)` ausgegeben, um RAM-Druck früh zu signalisieren.
- Operative Gegenmaßnahmen bei Warnungen oder OOM-Risiko:
  - `OCR_BUDGET_PER_RUN` reduzieren, damit pro Lauf weniger Datensätze aufgebaut werden.
  - `SKIP_OVER_MB` senken, damit große Dateien früher ausgeschlossen werden.
