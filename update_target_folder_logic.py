import re

# Update deploy.sh
with open('bummdidumm_os_v5_final_release/deploy.sh', 'r') as f:
    deploy_content = f.read()

# Make TARGET_FOLDER_ID optional in deploy.sh
deploy_content = deploy_content.replace(': "${TARGET_FOLDER_ID:?Bitte TARGET_FOLDER_ID setzen}"', 'TARGET_FOLDER_ID="${TARGET_FOLDER_ID:-}"')
with open('bummdidumm_os_v5_final_release/deploy.sh', 'w') as f:
    f.write(deploy_content)

# Update main_pass1.py
with open('bummdidumm_os_v5_final_release/main_pass1.py', 'r') as f:
    pass1_content = f.read()

pass1_content = pass1_content.replace('TARGET_FOLDER_ID = os.environ.get("TARGET_FOLDER_ID")', 'TARGET_FOLDER_ID = os.environ.get("TARGET_FOLDER_ID", "")')
pass1_content = pass1_content.replace('if not all([TARGET_FOLDER_ID, CONTROL_SHEET_ID]):', 'if not CONTROL_SHEET_ID:')
pass1_content = pass1_content.replace('raise ValueError("Missing TARGET_FOLDER_ID or CONTROL_SHEET_ID")', 'raise ValueError("Missing CONTROL_SHEET_ID")')

with open('bummdidumm_os_v5_final_release/main_pass1.py', 'w') as f:
    f.write(pass1_content)

# Update drive_helpers.py
with open('bummdidumm_os_v5_final_release/shared/drive_helpers.py', 'r') as f:
    drive_helpers_content = f.read()

# Modify is_in_target_folder
drive_helpers_content = drive_helpers_content.replace(
"""    def is_in_target_folder(self, file_id: str, parents: List[str]) -> bool:
        if not parents: return False
        if self.target_folder_id in parents: return True""",
"""    def is_in_target_folder(self, file_id: str, parents: List[str]) -> bool:
        if not self.target_folder_id: return True
        if not parents: return False
        if self.target_folder_id in parents: return True"""
)

# Modify walk_recursive to handle empty TARGET_FOLDER_ID
drive_helpers_content = drive_helpers_content.replace(
"""    def walk_recursive(self, folder_id: str) -> List[Dict]:
        \"\"\"Performs initial recursive scan.\"\"\"
        records = []
        page_token = None

        while True:
            params = self._list_params()
            if self.enable_shared_drives:
                params["corpora"] = "allDrives"

            resp = self.drive.files().list(
                q=f"'{folder_id}' in parents and trashed = false",
                pageSize=1000,
                pageToken=page_token,
                fields="nextPageToken, files(id,name,mimeType,size,md5Checksum,parents,createdTime,modifiedTime,trashed)",
                **params
            ).execute()""",
"""    def walk_recursive(self, folder_id: str) -> List[Dict]:
        \"\"\"Performs initial recursive scan.\"\"\"
        records = []
        page_token = None

        while True:
            params = self._list_params()
            if self.enable_shared_drives:
                params["corpora"] = "allDrives"

            query = f"'{folder_id}' in parents and trashed = false" if folder_id else "trashed = false"

            resp = self.drive.files().list(
                q=query,
                pageSize=1000,
                pageToken=page_token,
                fields="nextPageToken, files(id,name,mimeType,size,md5Checksum,parents,createdTime,modifiedTime,trashed)",
                **params
            ).execute()"""
)

# Modify get_parent_and_name_path to handle empty target_folder_id (optional, maybe not needed since path might just build up to root)
with open('bummdidumm_os_v5_final_release/shared/drive_helpers.py', 'w') as f:
    f.write(drive_helpers_content)
