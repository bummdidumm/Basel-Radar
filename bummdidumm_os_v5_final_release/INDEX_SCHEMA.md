# INDEX_SCHEMA

Personal Brain Index erweitert den bestehenden Delta-Index um:
- Source Registry (`00_source_registry.jsonl`)
- Record Index (`01_record_index.jsonl`)
- Entity Index (`02_entity_index.jsonl`)
- Relation Index (`03_relation_index.jsonl`)
- Daily Memory (`04_daily_memory/YYYY-MM-DD.json`)
- Search Views (`12_search_views/*.jsonl`)

Siehe die spezifischen Schemas in den separaten Dateien.

## Profile Layer (10_profile / 11_inventory)
Static context layer extracted from specific parsers like devices, subs, and accounts.

## Exclusions & Aliases
`20_index/user_settings/exclusions.json` handles ephemeral and purged items from views.
`20_index/user_settings/entity_aliases.json` merges aliases.

## LLM Context Pack
`13_llm_context_packs/gemini_daily_context.json` creates a 50kb prompt block.

## Embed Ready
`14_embed_ready/records_for_embedding.jsonl` contains formatted text prepared for Qdrant.
