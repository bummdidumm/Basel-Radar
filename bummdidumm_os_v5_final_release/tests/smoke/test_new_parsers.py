import unittest
from personal_brain.parsers.google.parser_google_contacts import GoogleContactsParser
from personal_brain.parsers.google.parser_google_tasks import GoogleTasksParser
from personal_brain.parsers.messaging.parser_telegram_export import TelegramExportParser
from personal_brain.parsers.meta.parser_instagram_export import InstagramExportParser
from personal_brain.parsers.llm.parser_perplexity_export import PerplexityExportParser

class TestNewParsers(unittest.TestCase):
    def test_google_contacts(self):
        parser = GoogleContactsParser()
        content = {"contacts": [{"name": "Alice", "email": "alice@test.com", "id": "1"}]}
        source = {"original_filename": "contacts.json"}
        records = parser.parse_to_records(source, content)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["record_type"], "contacts_export")
        self.assertIn("Alice", records[0]["people"])

    def test_google_contacts_null_name(self):
        parser = GoogleContactsParser()
        content = {"contacts": [{"name": None, "email": "noname@test.com", "id": "2"}]}
        source = {"original_filename": "contacts.json"}
        records = parser.parse_to_records(source, content)
        self.assertEqual(len(records), 1)
        self.assertNotIn(None, records[0]["people"])
        self.assertIn("Unknown", records[0]["people"])

    def test_google_tasks(self):
        parser = GoogleTasksParser()
        content = {"items": [{"title": "Buy milk", "updated": "2025-03-15T12:00:00Z"}]}
        source = {"original_filename": "tasks.json"}
        records = parser.parse_to_records(source, content)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["record_type"], "task")
        self.assertEqual(records[0]["title"], "Buy milk")

    def test_google_tasks_null_timestamp(self):
        parser = GoogleTasksParser()
        content = {"items": [{"title": "Buy milk", "updated": None, "due": None}]}
        source = {"original_filename": "tasks.json"}
        records = parser.parse_to_records(source, content)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["record_type"], "task")
        self.assertEqual(records[0]["event_time_start"], "")
        self.assertEqual(records[0]["event_date"], "")

    def test_telegram_can_handle_does_not_match_generic_result_json(self):
        """TelegramParser must not match a generic result.json without 'telegram' in path.

        Regression for: 'result.json' match was too broad.
        """
        from personal_brain.parsers.messaging.parser_telegram_export import TelegramExportParser
        from personal_brain.parsers.base import SourcePreview

        parser = TelegramExportParser()

        # Generic result.json — must NOT match
        meta_generic = {"original_filename": "result.json", "source_path": "exports/result.json"}
        preview_generic = SourcePreview(
            path="exports/result.json", name="result.json",
            mime="application/json", ext=".json",
            content_preview={"chats": {"list": []}, "about": "Telegram Desktop"},
            text_preview=""
        )
        self.assertFalse(parser.can_handle(meta_generic, preview_generic))

        # telegram_export.json — must match
        meta_tg = {"original_filename": "telegram_export.json", "source_path": "exports/telegram_export.json"}
        preview_tg = SourcePreview(
            path="exports/telegram_export.json", name="telegram_export.json",
            mime="application/json", ext=".json",
            content_preview={"chats": {"list": []}},
            text_preview=""
        )
        self.assertTrue(parser.can_handle(meta_tg, preview_tg))

    def test_telegram(self):
        parser = TelegramExportParser()
        content = {"chats": {"list": [{"name": "Group", "id": "C1", "messages": [{"type": "message", "from": "Bob", "text": "Hi"}]}]}}
        source = {"original_filename": "result.json"}
        records = parser.parse_to_records(source, content)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["record_type"], "message_event")
        self.assertIn("Bob", records[0]["people"])

    def test_instagram(self):
        parser = InstagramExportParser()
        content = {"messages": [{"sender_name": "Charlie", "content": "Yo", "timestamp_ms": 1672531200000}]}
        source = {"original_filename": "messages.json"}
        records = parser.parse_to_records(source, content)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["record_type"], "message_event")
        self.assertIn("Charlie", records[0]["people"])

    def test_perplexity(self):
        parser = PerplexityExportParser()
        content = {"threads": [{"id": "P1", "title": "Search", "turns": [{"role": "user", "content": "Query"}]}]}
        source = {"original_filename": "perplexity.json"}
        records = parser.parse_to_records(source, content)
        self.assertEqual(len(records), 2)  # thread + turn
        self.assertEqual(records[0]["record_type"], "llm_conversation")
        self.assertEqual(records[1]["record_type"], "llm_turn")

if __name__ == "__main__":
    unittest.main()
