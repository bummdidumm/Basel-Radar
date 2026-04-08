import unittest
from shared.hash_helpers import HashingSink

class TestHashingSink(unittest.TestCase):
    def test_sink_resets_on_seek(self):
        sink = HashingSink()
        sink.write(b"partial data ")
        self.assertEqual(sink.tell(), 13)

        # Simulate Google API downloader retry / reset
        sink.seek(0)
        self.assertEqual(sink.tell(), 0)

        sink.write(b"correct data")
        import hashlib
        expected = hashlib.sha256(b"correct data").hexdigest()
        self.assertEqual(sink.sha.hexdigest(), expected)

    def test_sink_rejects_arbitrary_seek(self):
        sink = HashingSink()
        sink.write(b"data")
        with self.assertRaises(NotImplementedError):
            sink.seek(2)

if __name__ == "__main__":
    unittest.main()
