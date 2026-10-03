"""A PO document's download link is signed when asked for, not on every PO load (#1339)."""

import uuid
from datetime import datetime

from app.models.enums import PODocumentType
from app.schemas.converters import po_document_to_type
from app.services import storage


class _Doc:
    def __init__(self):
        self.id = uuid.uuid4()
        self.po_id = uuid.uuid4()
        self.file_name = "quote.pdf"
        self.content_type = "application/pdf"
        self.file_size = 10
        self.document_type = PODocumentType.MISCELLANEOUS
        self.uploaded_at = datetime(2026, 10, 3)
        self.s3_key = "po-documents/x/quote.pdf"


def test_building_a_document_signs_nothing(monkeypatch):
    signed = []
    monkeypatch.setattr(storage, "generate_presigned_url", lambda key, expires_in=3600: signed.append(key) or "u")
    po_document_to_type(_Doc())
    assert signed == []


def test_the_deprecated_field_still_signs_when_asked(monkeypatch):
    monkeypatch.setattr(storage, "generate_presigned_url", lambda key, expires_in=3600: f"https://signed/{key}")
    assert po_document_to_type(_Doc()).download_url() == "https://signed/po-documents/x/quote.pdf"
