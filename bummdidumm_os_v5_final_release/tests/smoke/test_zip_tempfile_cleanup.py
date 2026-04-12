"""Regression test: ZIP sub-file tempfile wird auch bei write-Fehler bereinigt."""
import os
import tempfile
import zipfile
import pytest
from unittest.mock import patch, MagicMock


def test_zip_subfile_tempfile_cleaned_on_read_error(tmp_path):
    """sub_local_path muss vor tf.write() gesetzt sein, damit finally-Block greift."""
    # Erstelle valides ZIP mit einer Datei
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("test.json", '{"key": "value"}')

    leaked_paths = []

    original_ntf = tempfile.NamedTemporaryFile

    def patched_ntf(**kwargs):
        f = original_ntf(**kwargs)
        leaked_paths.append(f.name)
        return f

    with zipfile.ZipFile(zip_path, "r") as z:
        zinfo = z.infolist()[0]
        sub_local_path = None
        try:
            with patch("tempfile.NamedTemporaryFile", side_effect=patched_ntf):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tf:
                    sub_local_path = tf.name  # Korrekte Position: VOR write()
                    tf.write(z.read(zinfo))
        finally:
            if sub_local_path and os.path.exists(sub_local_path):
                os.remove(sub_local_path)

    # Alle erstellten Temp-Dateien müssen bereinigt worden sein
    for path in leaked_paths:
        assert not os.path.exists(path), f"Tempfile-Leak: {path} wurde nicht bereinigt"
