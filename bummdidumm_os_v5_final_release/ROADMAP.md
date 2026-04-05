# ROADMAP

## Personal-Brain-Stufe (implementiert und getestet)

### P0 – Kernfixes
- [x] `_build_relation` Entity-ID-Bug: subject/object-Typ nicht mehr hardcoded auf "topic"; Lookup via per-Source entity_map
- [x] `writers.py` Read-Merge-Write: inkrementelle Runs löschen keine Daten aus früheren Runs
- [x] `main_pass2.py` Source-Ingestion: echte Drive-Downloads für JSON/HTML/TXT/ICS/CSV; `out_root` aus `BRAIN_INDEX_ROOT` env statt `Path(".")`
- [x] `source_ingestion.py`: `.ics` und `.csv` als Text-Formate lesbar
- [x] Parser Registry Reihenfolge: LLM-Parser vor generischen Google-Parsern; Kollisionstokens ("conversations", "llm", "gemini") entschärft

### P1 – Echte Parser (mit `parse_to_records`-Logik)

Implementiert (parse_to_records nicht mehr BaseParser-Default):
- [x] `parser_chatgpt_export` – Conversations + Turns, modellspezifische Entities
- [x] `parser_claude_export` – chat_messages, conv/turn-Records, Anthropic-Entities
- [x] `parser_gemini_chat_export` – Gemini Turns + createTime, Google-Entities
- [x] `parser_llm_json_transcript` – Generischer messages[]-Parser für beliebige LLM-Logs
- [x] `parser_whatsapp_export` – EU- und US-Datumsformat, Regex-basiert, person-Entities + Relationen
- [x] `parser_google_calendar` – ICS VEVENT-Parsing + Google Takeout JSON-Fallback
- [x] `parser_google_my_activity` – activity[]-Array
- [x] `parser_google_timeline` – placeVisit-Objekte mit Geo-Koordinaten
- [x] `parser_google_play_installs` – installed_apps[], App-Entities mit package_name
- [x] `parser_generic_json_export` – items[]-Pattern

Stubs (erben BaseParser.parse_to_records ohne eigene Logik):
- [ ] `parser_signal_export`
- [x] `parser_telegram_export`
- [ ] `parser_gmail_export`
- [x] `parser_google_contacts`
- [x] `parser_google_tasks`
- [ ] `parser_google_keep`
- [ ] `parser_google_maps_places`
- [ ] `parser_google_drive_export`
- [ ] `parser_google_play_*` (subscriptions, purchases, orders, devices, library)
- [x] `parser_instagram_export`, `parser_facebook_export`, `parser_messenger_export`, `parser_threads_export`
- [x] `parser_perplexity_export`, `parser_notebooklm_artifacts`, `parser_prompt_bundle`, `parser_llm_html_export`, `parser_llm_markdown_bundle`

### P2 – Tests
- [x] Contract-Compliance-Test gegen alle REQUIRED_FIELDS
- [x] Merge-Test: Run(A+B) dann Run(A) darf B nicht löschen
- [x] Source-Detection-Test: realer lokaler Dateipfad wird wirklich geparst
- [x] Claude-Parser-Test
- [x] Gemini-Chat-Parser-Test
- [x] LLM-JSON-Transcript-Parser-Test
- [x] WhatsApp-Parser-Test
- [x] Google-Calendar-ICS-Parser-Test
- [x] Relation-Entity-ID-Konsistenztest

## Nächste Ausbaustufe

- Signal/Telegram/WhatsApp: vollständige Messaging-Parser
- Gmail-Parser: mbox-/Takeout-JSON-Format
- Google Contacts: vCard / Takeout JSON
- Meta-Exporte: Instagram/Facebook JSON-Strukturen
- Profilgeneratoren pro Entity-Typ (Apps / People / Places / Services)
- LLM Context Pack Writer (13_llm_context_packs/)
- Qualitätsreporting (`CURRENT_personal_brain_quality_report.md`)
- Entity-Merge über Quellen hinweg (aktuell: last-write-wins bei gleicher entity_id)
