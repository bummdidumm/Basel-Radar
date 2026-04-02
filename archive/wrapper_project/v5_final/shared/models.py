from pydantic import BaseModel, Field
from typing import Optional, List

class ExtractedDocument(BaseModel):
    doc_type: str = Field(description="Art des Dokuments (z.B. Rechnung, Brief, Foto, Vertrag, Sonstiges)")
    amount: Optional[float] = Field(description="Ein erkannter Rechnungs- oder Gesamtbetrag, falls vorhanden")
    date: Optional[str] = Field(description="Das Beleg- oder Erstelldatum im ISO Format YYYY-MM-DD")
    vendor: Optional[str] = Field(description="Der Name des Absenders, Händlers oder Ausstellers")
    summary: str = Field(description="Eine kurze, prägnante Zusammenfassung des Inhalts (1-3 Sätze)")
    full_text: Optional[str] = Field(description="Der vollständige extrahierte Text aus dem Dokument")

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

    # OCR properties
    ocr_doc_type: str = ""
    ocr_amount: str = ""
    ocr_date: str = ""
    ocr_vendor: str = ""
    ocr_summary: str = ""
    ocr_full_text: str = ""
