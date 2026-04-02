# PARSER_REGISTRY

Die Registry wird in `personal_brain/parser_registry.py` geführt und priorisiert domänenspezifische Parser vor Generic-Fallback.

Gruppen:
- `parsers/google/*`
- `parsers/meta/*`
- `parsers/messaging/*`
- `parsers/llm/*`
- `parsers/generic/*`

Jeder Parser implementiert die Methoden:
`can_handle`, `extract_source_metadata`, `parse_to_records`, `extract_entities`, `build_relations`, `build_profile_fragments`, `summarize_source`.
