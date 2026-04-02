from __future__ import annotations

from .parsers.base import BaseParser, SourcePreview
from .parsers.google.parser_google_play_installs import GooglePlayInstallsParser
from .parsers.google.parser_google_play_subscriptions import GooglePlaySubscriptionsParser
from .parsers.google.parser_google_play_purchases import GooglePlayPurchasesParser
from .parsers.google.parser_google_play_orders import GooglePlayOrdersParser
from .parsers.google.parser_google_play_devices import GooglePlayDevicesParser
from .parsers.google.parser_google_play_library import GooglePlayLibraryParser
from .parsers.google.parser_google_my_activity import GoogleMyActivityParser
from .parsers.google.parser_google_maps_places import GoogleMapsPlacesParser
from .parsers.google.parser_google_timeline import GoogleTimelineParser
from .parsers.google.parser_google_calendar import GoogleCalendarParser
from .parsers.google.parser_google_tasks import GoogleTasksParser
from .parsers.google.parser_google_contacts import GoogleContactsParser
from .parsers.google.parser_google_keep import GoogleKeepParser
from .parsers.google.parser_gmail_export import GmailExportParser
from .parsers.google.parser_google_drive_export import GoogleDriveExportParser
from .parsers.google.parser_gemini_exports import GeminiExportsParser
from .parsers.meta.parser_instagram_export import InstagramExportParser
from .parsers.meta.parser_facebook_export import FacebookExportParser
from .parsers.meta.parser_messenger_export import MessengerExportParser
from .parsers.meta.parser_threads_export import ThreadsExportParser
from .parsers.messaging.parser_whatsapp_export import WhatsAppExportParser
from .parsers.messaging.parser_telegram_export import TelegramExportParser
from .parsers.messaging.parser_signal_export import SignalExportParser
from .parsers.llm.parser_chatgpt_export import ChatGPTExportParser
from .parsers.llm.parser_claude_export import ClaudeExportParser
from .parsers.llm.parser_gemini_chat_export import GeminiChatExportParser
from .parsers.llm.parser_perplexity_export import PerplexityExportParser
from .parsers.llm.parser_notebooklm_artifacts import NotebookLMArtifactsParser
from .parsers.llm.parser_prompt_bundle import PromptBundleParser
from .parsers.llm.parser_llm_markdown_bundle import LlmMarkdownBundleParser
from .parsers.llm.parser_llm_json_transcript import LlmJsonTranscriptParser
from .parsers.llm.parser_llm_html_export import LlmHtmlExportParser
from .parsers.generic.parser_generic_json_export import GenericJsonExportParser
from .parsers.generic.parser_generic_csv_export import GenericCsvExportParser
from .parsers.generic.parser_generic_html_export import GenericHtmlExportParser
from .parsers.generic.parser_generic_txt_export import GenericTxtExportParser
from .parsers.generic.parser_generic_zip_bundle import GenericZipBundleParser


class ParserRegistry:
    def __init__(self) -> None:
        # Order matters: first match wins.
        # Rule: specific service parsers (with custom can_handle) before generic ones.
        # LLM chat parsers come BEFORE Google "gemini" catch-all and generic parsers
        # to prevent "gemini" / "llm" token collisions from stealing matches.
        self.parsers: list[BaseParser] = [
            # --- LLM / AI service exports (specific, ordered by specificity) ---
            ChatGPTExportParser(), ClaudeExportParser(), GeminiChatExportParser(),
            LlmJsonTranscriptParser(), PerplexityExportParser(),
            NotebookLMArtifactsParser(), PromptBundleParser(),
            LlmHtmlExportParser(), LlmMarkdownBundleParser(),
            # --- Google structured exports ---
            GooglePlayInstallsParser(), GooglePlaySubscriptionsParser(), GooglePlayPurchasesParser(),
            GooglePlayOrdersParser(), GooglePlayDevicesParser(), GooglePlayLibraryParser(),
            GoogleMyActivityParser(), GoogleMapsPlacesParser(), GoogleTimelineParser(),
            GoogleCalendarParser(), GoogleTasksParser(), GoogleContactsParser(), GoogleKeepParser(),
            GmailExportParser(), GoogleDriveExportParser(), GeminiExportsParser(),
            # --- Social / messaging ---
            InstagramExportParser(), FacebookExportParser(), MessengerExportParser(), ThreadsExportParser(),
            WhatsAppExportParser(), TelegramExportParser(), SignalExportParser(),
            # --- Generic fallbacks ---
            GenericJsonExportParser(), GenericCsvExportParser(), GenericHtmlExportParser(),
            GenericTxtExportParser(), GenericZipBundleParser(),
        ]

    def resolve(self, source_meta: dict, preview: SourcePreview) -> BaseParser:
        for parser in self.parsers:
            if parser.can_handle(source_meta, preview):
                return parser
        return GenericTxtExportParser()
