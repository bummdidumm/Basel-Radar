import re

with open('bummdidumm_os_v5_final_release/shared/sorting_helpers.py', 'r') as f:
    sorting_helpers_content = f.read()

# Modify sorting logic to handle inbox_trash files properly
# Files in 01_inbox_trash should maybe stay there or be processed specifically
sorting_logic = """        if "01_inbox_trash" in path:
            key = "01_inbox_trash"
            reason = "Prio 0: Inbox Trash Lane"
        elif "DUPLICATE" in status:"""
sorting_helpers_content = sorting_helpers_content.replace('        if "DUPLICATE" in status:', sorting_logic)

with open('bummdidumm_os_v5_final_release/shared/sorting_helpers.py', 'w') as f:
    f.write(sorting_helpers_content)
