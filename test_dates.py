from datetime import datetime, timezone

def sanitize_drive_date(date_str: str) -> str:
    if not date_str:
        return date_str
    try:
        # Expected format: "2023-01-01T12:00:00.000Z"
        year = int(date_str[:4])
        current_year = datetime.now(timezone.utc).year
        if year > current_year:
            return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    except Exception:
        pass
    return date_str

print(sanitize_drive_date("2040-05-10T12:00:00.000Z"))
print(sanitize_drive_date("2023-05-10T12:00:00.000Z"))
