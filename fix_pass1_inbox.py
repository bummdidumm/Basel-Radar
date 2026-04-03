import re

with open('bummdidumm_os_v5_final_release/main_pass1.py', 'r') as f:
    pass1_content = f.read()

# Update FileRecord instantiation in main_pass1 to identify lane
file_record_init = """        lane = "ACTIVE"
        path_disp = drive_mgr.get_parent_and_name_path(file_id, name, f.get("parents"))
        if "01_inbox_trash" in path_disp:
            lane = "INBOX_TRASH"

        rec = FileRecord(
            file_id=file_id,
            name=name,
            parent_ids_sorted=",".join(sorted(f.get("parents", []))),
            path_display=path_disp,
            mime_type=mime,
            size_bytes=size,
            md5=f.get("md5Checksum", ""),
            updated_at=f.get("modifiedTime", ""),
            created_time=f.get("createdTime", ""),
            web_link=f.get("webViewLink", ""),
            parents=f.get("parents", [])
        )
        rec.change_type = change_type
        rec.suggested_name = suggested_name
        rec.notes = f"Lane: {lane}"
"""

pass1_content = re.sub(
    r'        rec = FileRecord\([\s\S]*?rec\.suggested_name = suggested_name',
    file_record_init.strip(),
    pass1_content
)

with open('bummdidumm_os_v5_final_release/main_pass1.py', 'w') as f:
    f.write(pass1_content)
