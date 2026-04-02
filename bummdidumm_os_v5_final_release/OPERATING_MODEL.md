# OPERATING_MODEL

## Export-/LLM-Indexing Ergänzung

1. Pass 1 bleibt Scan/Dedupe-Kanon.
2. Pass 2 schreibt Delta JSONL und ruft anschließend die Parser-Registry-Runtime auf.
3. Runtime erzeugt deterministische IDs (`source_id`, `record_id`, `entity_id`, `relation_id`) aus stabilen Hashes.
4. Parserfehler sind isoliert je Quelle (Registry-Fallback auf Generic Parser).
