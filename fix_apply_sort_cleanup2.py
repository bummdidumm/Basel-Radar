import re

with open('bummdidumm_os_v5_final_release/main_apply_sort.py', 'r') as f:
    apply_sort_content = f.read()

sweep_logic = """        if action_mode in ["SAFE", "SWEEP_TRASH"] and (target_folder_id or action_mode == "SWEEP_TRASH") and move_result == "PENDING":
            try:
                params = {"supportsAllDrives": True} if ENABLE_SHARED_DRIVES else {}

                if action_mode == "SWEEP_TRASH":
                    # Mark explicitly as trashed
                    drive_service.files().update(
                        fileId=file_id,
                        body={"trashed": True},
                        **params
                    ).execute()
                    result_val = "SUCCESS_TRASHED"
                else:
                    file_meta = drive_service.files().get(fileId=file_id, fields="parents", **params).execute()
                    previous_parents = ",".join(file_meta.get("parents", []))

                    drive_service.files().update(
                        fileId=file_id,
                        addParents=target_folder_id,
                        removeParents=previous_parents,
                        **params
                    ).execute()
                    result_val = "SUCCESS"
"""

apply_sort_content = apply_sort_content.replace(
"""        if action_mode == "SAFE" and target_folder_id and move_result == "PENDING":
            try:
                params = {"supportsAllDrives": True} if ENABLE_SHARED_DRIVES else {}

                file_meta = drive_service.files().get(fileId=file_id, fields="parents", **params).execute()
                previous_parents = ",".join(file_meta.get("parents", []))

                drive_service.files().update(
                    fileId=file_id,
                    addParents=target_folder_id,
                    removeParents=previous_parents,
                    **params
                ).execute()

                processed += 1
                result_val = "SUCCESS"
""",
sweep_logic + "\n                processed += 1"
)

with open('bummdidumm_os_v5_final_release/main_apply_sort.py', 'w') as f:
    f.write(apply_sort_content)
