import re

# Update SheetManager to include Exclusions tab
with open('bummdidumm_os_v5_final_release/shared/sheets_helpers.py', 'r') as f:
    sheets_content = f.read()

sheets_content = sheets_content.replace(
    '"Sorting_Suggestions": ["run_id", "file_id", "name", "mime_type", "current_location", "current_parent_id", "folder_rule", "folder_rule_reason", "suggested_target_folder", "suggested_target_folder_id", "target_path", "action_mode", "move_result"]',
    '"Sorting_Suggestions": ["run_id", "file_id", "name", "mime_type", "current_location", "current_parent_id", "folder_rule", "folder_rule_reason", "suggested_target_folder", "suggested_target_folder_id", "target_path", "action_mode", "move_result"],\n            "Knowledge_Exclusions": ["file_id", "path_display", "status", "reason"]'
)
with open('bummdidumm_os_v5_final_release/shared/sheets_helpers.py', 'w') as f:
    f.write(sheets_content)

# Update PersonalBrainRuntime to handle exclusions/purges
with open('bummdidumm_os_v5_final_release/personal_brain/runtime.py', 'r') as f:
    pb_runtime = f.read()

# Add knowledge_exclusions parameter and filtering logic
pb_runtime = pb_runtime.replace(
    'def process_sources(self, sources: list[dict[str, Any]]) -> dict[str, int]:',
    'def process_sources(self, sources: list[dict[str, Any]], exclusions: dict = None) -> dict[str, int]:\n        if exclusions is None: exclusions = {}'
)

# Insert filtering logic inside the process_sources loop
filter_logic = """        for item in sources:
            file_id = item.get("file_id", "")
            knowledge_status = exclusions.get(file_id, "ACTIVE")
            item["knowledge_status"] = knowledge_status

            if knowledge_status in ["EXCLUDED", "PURGED"]:
                continue
"""
pb_runtime = pb_runtime.replace('        for item in sources:', filter_logic)

with open('bummdidumm_os_v5_final_release/personal_brain/runtime.py', 'w') as f:
    f.write(pb_runtime)

# Update main_pass2.py to pass exclusions
with open('bummdidumm_os_v5_final_release/main_pass2.py', 'r') as f:
    main_pass2_content = f.read()

exclusion_load = """    # Load Knowledge Exclusions
    exclusions = {}
    for row in sheet_mgr.read_all_rows("Knowledge_Exclusions", "A:C"):
        if len(row) >= 3 and row[0] != "file_id":
            exclusions[row[0]] = row[2]  # file_id -> status (EXCLUDED/PURGED)
"""
main_pass2_content = main_pass2_content.replace('    # Lese Folder-Aware Indexing Daten chunkweise aus Sorting_Suggestions', exclusion_load + '\n    # Lese Folder-Aware Indexing Daten chunkweise aus Sorting_Suggestions')

main_pass2_content = main_pass2_content.replace('pb_results = pb_runtime.process_sources(sources)', 'pb_results = pb_runtime.process_sources(sources, exclusions)')

with open('bummdidumm_os_v5_final_release/main_pass2.py', 'w') as f:
    f.write(main_pass2_content)
