import unittest
from shared.hash_helpers import calculate_sha256_streaming
from googleapiclient.errors import HttpError
from unittest import mock

class DummyDriveServiceNative:
    def files(self):
        class DummyFiles:
            def export_media(self, *args, **kwargs):
                raise HttpError(mock.Mock(status=403), b'Forbidden')
        return DummyFiles()

class DummyDriveServiceBinary:
    def files(self):
        class DummyFiles:
            def get_media(self, *args, **kwargs):
                raise HttpError(mock.Mock(status=404), b'Not Found')
        return DummyFiles()

class DummyDriveServiceUnexpected:
    def files(self):
        class DummyFiles:
            def get_media(self, *args, **kwargs):
                raise ValueError("Totally unexpected error")
        return DummyFiles()

class TestHashErrorHandling(unittest.TestCase):
    def test_http_error_caught_gracefully(self):
        # Native export
        sha, src = calculate_sha256_streaming(DummyDriveServiceNative(), "123", "application/vnd.google-apps.document", {})
        self.assertIsNone(sha)
        self.assertEqual(src, "Error")

        # Binary download
        sha, src = calculate_sha256_streaming(DummyDriveServiceBinary(), "123", "application/pdf", {})
        self.assertIsNone(sha)
        self.assertEqual(src, "Error")

    def test_unexpected_error_not_caught_silently(self):
        # Broad Exception shouldn't catch ValueError or at least it should log differently if we changed the logic.
        # Oh wait, we caught (HttpError, OSError, IOError). ValueError should RAISE!
        with self.assertRaises(ValueError):
            calculate_sha256_streaming(DummyDriveServiceUnexpected(), "123", "application/pdf", {})

if __name__ == '__main__':
    unittest.main()
