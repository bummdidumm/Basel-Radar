from pydantic import BaseModel, Field
from typing import Optional

class ExtractedDocument(BaseModel):
    doc_type: str = Field(description="Art des Dokuments (z.B. Rechnung, Brief, Foto, Vertrag, Sonstiges)")
    amount: Optional[float] = Field(description="Ein erkannter Rechnungs- oder Gesamtbetrag, falls vorhanden")
    date: Optional[str] = Field(description="Das Beleg- oder Erstelldatum im ISO Format YYYY-MM-DD")
    vendor: Optional[str] = Field(description="Der Name des Absenders, Händlers oder Ausstellers")
    summary: str = Field(description="Eine kurze, prägnante Zusammenfassung des Inhalts (1-3 Sätze)")
    full_text: Optional[str] = Field(description="Der vollständige extrahierte Text aus dem Dokument")

class FileRecord(BaseModel):
    """Internal model for processing files before they go to JSONL or Sheets."""
    file_id: str
    name: str
    path: str
    mime_type: str
    size_bytes: int
    md5: str
    updated_at: str
    created_time: str
    web_link: str
    parents: list[str] = []

    # Computed during Pass 1
    sha256: str = ""
    effective_mime_type: str = ""
    export_source: str = ""
    status: str = "PENDING"
    change_type: str = "UNKNOWN"
    duplicate_of: str = ""
    archive_result: str = ""
    suggested_name: str = ""
    notes: str = ""

    # Computed during Pass 2
    ocr_doc_type: str = ""
    ocr_amount: str = ""
    ocr_date: str = ""
    ocr_vendor: str = ""
    ocr_summary: str = ""
    ocr_full_text: str = ""
