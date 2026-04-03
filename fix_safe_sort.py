import re

with open('bummdidumm_os_v5_final_release/main_safe_sort.py', 'r') as f:
    safe_sort_content = f.read()

action_mode_logic = """            action_mode = "SAFE"
            if folder_rule == "01_inbox_trash":
                action_mode = "SWEEP_TRASH"

            suggestions.append([
                current_run_id,
                file_id,
                name,
                mime_type,
                current_path,
                current_parent_id,
                folder_rule, folder_rule_reason, target_name, target_id, target_path, action_mode, "PENDING"
            ])"""

safe_sort_content = re.sub(
    r'suggestions\.append\(\[\s*current_run_id,\s*file_id,\s*name,\s*mime_type,\s*current_path,\s*current_parent_id,\s*folder_rule, folder_rule_reason, target_name, target_id, target_path, "SAFE", "PENDING"\s*\]\)',
    action_mode_logic.strip(),
    safe_sort_content
)

with open('bummdidumm_os_v5_final_release/main_safe_sort.py', 'w') as f:
    f.write(safe_sort_content)
