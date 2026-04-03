import re

with open('bummdidumm_os_v5_final_release/main_apply_sort.py', 'r') as f:
    apply_sort_content = f.read()

# Make sure action_mode handles INBOX_TRASH / CLEANUP gracefully if needed, or if it says MOVED it should track it correctly.
# Currently action_mode MOVE triggers drive_service.files().update
# Let's just make sure action_mode handles SWEEP / TRASH if sorting rules emitted it.
# Actually, the user asked for A. Inbox-Trash-Dateien -> können danach in einen klaren Processed-/Trash-/Retention-Zustand überführt werden
# Let's add an action_mode 'SWEEP_TRASH' or similar.

sweep_logic = """        if action_mode in ["MOVE", "SWEEP_TRASH"]:
            current_parent_id = row[5]

            try:
                params = {"supportsAllDrives": True} if ENABLE_SHARED_DRIVES else {}

                if action_mode == "SWEEP_TRASH":
                    # Mark explicitly as trashed or move to a retention folder
                    drive_service.files().update(
                        fileId=file_id,
                        body={"trashed": True},
                        **params
                    ).execute()
                    result = "SUCCESS_TRASHED"
                else:
                    drive_service.files().update(
                        fileId=file_id,
                        addParents=target_folder_id,
                        removeParents=current_parent_id,
                        fields="id, parents",
                        **params
                    ).execute()
                    result = "SUCCESS_MOVED"
"""

apply_sort_content = apply_sort_content.replace(
"""        if action_mode == "MOVE":
            current_parent_id = row[5]

            try:
                params = {"supportsAllDrives": True} if ENABLE_SHARED_DRIVES else {}
                drive_service.files().update(
                    fileId=file_id,
                    addParents=target_folder_id,
                    removeParents=current_parent_id,
                    fields="id, parents",
                    **params
                ).execute()
                result = "SUCCESS"
""",
sweep_logic
)

apply_sort_content = apply_sort_content.replace('result = "SUCCESS"', 'result = "SUCCESS_MOVED"')

with open('bummdidumm_os_v5_final_release/main_apply_sort.py', 'w') as f:
    f.write(apply_sort_content)
