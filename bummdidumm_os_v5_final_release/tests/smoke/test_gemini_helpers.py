"""Targeted unit tests for shared/gemini_helpers.py.

Covers:
- is_ocr_worthy: image, pdf, native doc, json, csv → correct booleans
- extract_structured_data: no-client short-circuit, non-worthy MIME, retry on 429,
  temp-file cleanup on success and on exception
"""
import sys
import os
import tempfile
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from shared.gemini_helpers import GeminiOCR


# ---------------------------------------------------------------------------
# is_ocr_worthy
# ---------------------------------------------------------------------------

class TestIsOcrWorthy:
    def test_jpeg_is_worthy(self):
        assert GeminiOCR.is_ocr_worthy("image/jpeg") is True

    def test_png_is_worthy(self):
        assert GeminiOCR.is_ocr_worthy("image/png") is True

    def test_pdf_is_worthy(self):
        assert GeminiOCR.is_ocr_worthy("application/pdf") is True

    def test_google_doc_is_worthy(self):
        assert GeminiOCR.is_ocr_worthy("application/vnd.google-apps.document") is True

    def test_json_not_worthy(self):
        assert GeminiOCR.is_ocr_worthy("application/json") is False

    def test_csv_not_worthy(self):
        assert GeminiOCR.is_ocr_worthy("text/csv") is False

    def test_generic_image_prefix_worthy(self):
        assert GeminiOCR.is_ocr_worthy("image/heic") is True


# ---------------------------------------------------------------------------
# extract_structured_data
# ---------------------------------------------------------------------------

class TestExtractStructuredData:
    def _make_ocr(self, client=None):
        drive = MagicMock()
        ocr = GeminiOCR(drive, enable_shared_drives=False)
        ocr.client = client
        return ocr

    def test_returns_none_when_no_client(self):
        ocr = self._make_ocr(client=None)
        result, mime = ocr.extract_structured_data("file_id", "application/pdf")
        assert result is None

    def test_returns_none_for_non_worthy_mime(self):
        ocr = self._make_ocr(client=MagicMock())
        result, mime = ocr.extract_structured_data("file_id", "application/json")
        assert result is None

    def test_retries_on_429_then_succeeds(self):
        from google.genai.errors import APIError

        # Build a real exception subclass so `raise err` works.
        # Pass the status code directly so APIError sets self.code = 429.
        class FakeRateLimitError(APIError):
            def __init__(self):
                super().__init__(429, "resourceexhausted", {"code": 429})

        client = MagicMock()
        ocr = self._make_ocr(client=client)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tf:
            tmp_path = tf.name
            tf.write(b"%PDF fake")

        call_count = {"n": 0}

        def fake_generate(**kwargs):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise FakeRateLimitError()
            resp = MagicMock()
            resp.text = '{"title": "test"}'
            return resp

        client.models.generate_content.side_effect = fake_generate
        client.files.upload.return_value = MagicMock(name="files/abc")

        with patch.object(ocr, "_download_for_ocr", return_value=(tmp_path, "application/pdf")):
            with patch("time.sleep"):
                result, _ = ocr.extract_structured_data("file_id", "application/pdf")

        assert result == {"title": "test"}
        assert call_count["n"] == 3
        assert not os.path.exists(tmp_path)

    def test_temp_file_deleted_on_exception(self):
        client = MagicMock()
        ocr = self._make_ocr(client=client)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tf:
            tmp_path = tf.name
            tf.write(b"%PDF fake")

        client.files.upload.side_effect = RuntimeError("upload failed")

        with patch.object(ocr, "_download_for_ocr", return_value=(tmp_path, "application/pdf")):
            result, _ = ocr.extract_structured_data("file_id", "application/pdf")

        assert result is None
        assert not os.path.exists(tmp_path)

    def test_gemini_file_deleted_after_success(self):
        client = MagicMock()
        ocr = self._make_ocr(client=client)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tf:
            tmp_path = tf.name
            tf.write(b"%PDF")

        gemini_file = MagicMock()
        gemini_file.name = "files/xyz"
        client.files.upload.return_value = gemini_file

        resp = MagicMock()
        resp.text = '{"title": "doc"}'
        client.models.generate_content.return_value = resp

        with patch.object(ocr, "_download_for_ocr", return_value=(tmp_path, "application/pdf")):
            ocr.extract_structured_data("file_id", "application/pdf")

        client.files.delete.assert_called_once_with(name="files/xyz")
