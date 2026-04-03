import re

pass1_file = 'bummdidumm_os_v5_final_release/main_pass1.py'

with open(pass1_file, 'r') as f:
    content = f.read()

date_logic = """
def sanitize_drive_date(date_str: str) -> str:
    if not date_str:
        return date_str
    try:
        # Expected format: "2023-01-01T12:00:00.000Z"
        year = int(date_str[:4])
        current_year = datetime.now(timezone.utc).year
        if year > current_year:
            # If the date is in the future, it's clearly wrong. Fallback to current year but keep format.
            # A more robust fallback could be to use a valid parsed date, but simple replace works.
            # We can just return the current timestamp.
            return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        if year < 1980:
            # Unix epoch or weird times, fallback to safe date or return original
            pass
    except Exception:
        pass
    return date_str

def suggest_rename(name: str, created_time: str) -> str:
"""

content = content.replace('def suggest_rename(name: str, created_time: str) -> str:', date_logic.strip())

# Apply sanitization to the createdTime and modifiedTime when reading from f
process_logic = """
        c_time = sanitize_drive_date(f.get("createdTime", ""))
        m_time = sanitize_drive_date(f.get("modifiedTime", ""))
        suggested_name = suggest_rename(name, c_time)
"""

content = re.sub(
    r'suggested_name = suggest_rename\(name, f\.get\("createdTime", ""\)\)',
    process_logic.strip(),
    content
)

content = content.replace('updated_at=f.get("modifiedTime", "")', 'updated_at=m_time')
content = content.replace('created_time=f.get("createdTime", "")', 'created_time=c_time')

with open(pass1_file, 'w') as f:
    f.write(content)
