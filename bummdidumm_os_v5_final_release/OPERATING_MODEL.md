# OPERATING_MODEL

## Export-/LLM-Indexing Ergänzung

1. Pass 1 bleibt Scan/Dedupe-Kanon.
2. Pass 2 schreibt Delta JSONL und ruft anschließend die Parser-Registry-Runtime auf.
3. Runtime erzeugt deterministische IDs (`source_id`, `record_id`, `entity_id`, `relation_id`) aus stabilen Hashes.
4. Parserfehler sind isoliert je Quelle (Registry-Fallback auf Generic Parser).

## RAM-Guardrail (Pass 2)

Pass 2 lädt alle `records_to_index`-Einträge vor dem Brain-Runtime-Pass in Memory.
Bei > 50.000 Einträgen können 2 GiB RAM überschritten werden — Cloud Run killt den Task ohne Python-Traceback.

**Symptom:** `gcloud run jobs executions describe` zeigt `OOMKilled` ohne Logs.

**Mitigationen:**
- `OCR_BUDGET_PER_RUN` reduzieren (Default: 500), um den Ingest auf mehrere Runs zu verteilen.
- `SKIP_OVER_MB` reduzieren, um Großdateien zu überspringen.
- Cloud Run Memory erhöhen: `gcloud run jobs update bummdidumm-pass2-ocr-index --memory=4Gi --region=europe-west6`.
- Intern: `log.warning` wird ab 50.000 Einträgen ausgelöst, bevor der Runtime-Pass beginnt.
