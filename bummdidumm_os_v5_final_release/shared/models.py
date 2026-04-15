from pydantic import BaseModel, Field
from typing import Optional, List, TypedDict

class ExtractedDocument(BaseModel):
    doc_type: str = Field(description="Art des Dokuments: Rechnung, Vertrag, Brief, Foto, Ausweis, Quittung, Versicherung, Kontoauszug, Sonstiges")
    language: str = Field(default="de", description="Hauptsprache: de, fr, en, it")
    amount: Optional[float] = Field(default=None, description="Rechnungs- oder Gesamtbetrag falls vorhanden")
    currency: Optional[str] = Field(default=None, description="Währung: CHF, EUR, USD")
    date: Optional[str] = Field(default=None, description="Hauptdatum im ISO Format YYYY-MM-DD")
    vendor: Optional[str] = Field(default=None, description="Absender, Händler oder Aussteller")
    recipient: Optional[str] = Field(default=None, description="Empfänger falls vorhanden")
    people_mentioned: List[str] = Field(default_factory=list, description="Alle genannten Personen-Namen")
    organizations_mentioned: List[str] = Field(default_factory=list, description="Alle genannten Firmen/Organisationen")
    reference_number: Optional[str] = Field(default=None, description="Referenznummer, Bestellnummer, Vertragsnummer")
    is_readable: bool = Field(default=True, description="False wenn Dokument unleserlich oder leer")
    sensitivity: str = Field(default="low", description="low / medium / high — high bei Ausweis, Kontoauszug, medizinischen Dokumenten")
    summary: str = Field(description="1-3 Sätze Zusammenfassung")
    full_text: Optional[str] = Field(default=None, description="Vollständiger extrahierter Text")

class FileRecord(BaseModel):
    """Internal model holding all state for a single file through the pipeline."""
    run_utc: str = ""
    run_id: str = ""
    path_display: str = ""
    name: str = ""
    file_id: str = ""
    parent_ids_sorted: str = ""
    mime_type: str = ""
    effective_mime_type: str = ""
    size_bytes: int = 0
    md5: str = ""
    sha256: str = ""
    status: str = "PENDING"
    change_type: str = "UNKNOWN"
    duplicate_of: str = ""
    archive_result: str = ""
    suggested_name: str = ""
    web_link: str = ""
    notes: str = ""

    # Folder Aware Indexing & Sorting
    current_parent_id: str = ""
    current_path: str = ""
    target_parent_id: str = ""
    target_path: str = ""
    folder_rule: str = ""
    folder_rule_reason: str = ""
    sort_mode: str = ""
    move_result: str = ""

    # Internal helpers (not directly in Dedupe_Report unless mapped)
    updated_at: str = ""
    created_time: str = ""
    parents: List[str] = []
    export_source: str = ""

    # OCR properties (erweitert)
    ocr_doc_type: str = ""
    ocr_amount: str = ""
    ocr_date: str = ""
    ocr_vendor: str = ""
    ocr_summary: str = ""
    ocr_full_text: str = ""
    ocr_people: List[str] = []
    ocr_organizations: List[str] = []
    ocr_sensitivity: str = "low"
    ocr_is_readable: bool = True
    ocr_language: str = ""
    ocr_currency: str = ""
    ocr_reference_number: str = ""

    # Drive metadata (erweitert)
    description: str = ""
    starred: bool = False
    owner_email: str = ""
    owner_name: str = ""
    last_modified_by_email: str = ""
    can_edit: bool = True
    can_share: bool = True
    can_download: bool = True


class KnownFileMeta(TypedDict, total=False):
    """Shape of the per-file metadata cache entry used throughout Pass 1.

    Stored in the `known_file_details` dict keyed by file_id and also
    persisted to the Sheets hash-index via StateTracker.
    """
    sha: str
    name: str
    parent_ids_sorted: str
    path_display: str
    updated_at: str
    size_bytes: int
    md5: str
    effective_mime_type: str
