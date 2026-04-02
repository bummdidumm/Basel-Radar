import zipfile
import json
import tempfile
import os
from bummdidumm_os_v5_final_release.personal_brain.source_ingestion import inspect_source

with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
    zip_path = tf.name

with zipfile.ZipFile(zip_path, "w") as z:
    z.writestr("Takeout/archive_browser.html", "<html><body>Archive info here</body></html>")
    z.writestr("messages.json", json.dumps({"test": "data"}))

detected = inspect_source(zip_path, mime="application/zip", ext=".zip")

assert detected["is_archive"] is True
assert "archive_files" in detected["content"]
assert "messages.json" in detected["content"]["archive_files"]
assert "Takeout/archive_browser.html" in detected["content"]["archive_files"]

assert "Archive info here" in detected["content"]["raw_text"]
print("Zip extraction tests passed.")

os.remove(zip_path)
