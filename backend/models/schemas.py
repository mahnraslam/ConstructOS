from pydantic import BaseModel
from typing import List, Optional

# ── Documents ────────────────────────────────────────────────────────────────
class DocumentMeta(BaseModel):
    doc_id: str
    filename: str
    page_count: int = 0
    chunk_count: int = 0
    doc_type: str = "other"

class DeleteResponse(BaseModel):
    doc_id: str
    deleted: bool

# ── Structured Reference (replaces raw chunk citation) ───────────────────────
class Reference(BaseModel):
    document_name: str
    document_type: str = "other"
    page: int = 0
    sheet: str = ""
    section: str = ""
    detail: str = ""
    quote: str = ""
    image_url: Optional[str] = None

# ── Q&A ──────────────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    question: str
    doc_ids: Optional[List[str]] = None
    project_id: Optional[str] = None
    top_k: int = 5
    visual: bool = False

class Citation(BaseModel):
    doc_id: str
    filename: str
    page_num: int
    chunk_text: str
    relevance_score: float = 0.0
    image_url: Optional[str] = None
    doc_type: str = "other"
    # Structured reference fields
    sheet: str = ""
    section: str = ""

class QueryResponse(BaseModel):
    question: str
    answer: str
    citations: List[Citation]
    references: List[Reference] = []

# ── Facts ─────────────────────────────────────────────────────────────────────
class FactOut(BaseModel):
    id: int
    category: str
    field: str
    value: str
    unit: str = ""
    page: int = 0
    sheet: str = ""
    section: str = ""
    quote: str = ""
    document_id: str
    filename: str = ""

    class Config:
        from_attributes = True

# ── Conflicts ────────────────────────────────────────────────────────────────
class ConflictRequest(BaseModel):
    doc_id_a: str
    doc_id_b: str
    filename_a: str = ""
    filename_b: str = ""

class ConflictItem(BaseModel):
    severity: str           # "high" | "medium" | "low"
    topic: str
    description: str
    quote_a: str
    quote_b: str
    page_a: int
    page_b: int
    filename_a: str
    filename_b: str

class ConflictResponse(BaseModel):
    doc_id_a: str
    doc_id_b: str
    conflicts: List[ConflictItem]
    total: int

class AllConflictsRequest(BaseModel):
    doc_ids: List[str]

class AllConflictsResponse(BaseModel):
    conflicts: List[ConflictItem]
    total: int

# ── Structured conflict (fact-based) ─────────────────────────────────────────
class FactConflict(BaseModel):
    field: str
    blueprint_value: str
    spec_value: str
    blueprint_doc_id: str = ""
    spec_doc_id: str = ""
    blueprint_page: int = 0
    spec_page: int = 0
    blueprint_sheet: str = ""
    spec_section: str = ""
    status: str = "conflict"
    severity: str = "medium"

class FactConflictResponse(BaseModel):
    project_id: str
    conflicts: List[FactConflict]
    total: int

# ── RFI ───────────────────────────────────────────────────────────────────────
class RFIRequest(BaseModel):
    blueprint_doc_id: str
    spec_doc_id: str
    blueprint_filename: str = ""
    spec_filename: str = ""
    visual: bool = True
    top_k_per_topic: int = 2

class RFIItem(BaseModel):
    number: str
    subject: str
    body: str
    priority: str = "medium"
    references: List[Reference] = []

class RFIResponse(BaseModel):
    blueprint_doc_id: str
    spec_doc_id: str
    rfis: List[RFIItem]
    total: int

# ── Project-level RFI generation from facts ──────────────────────────────────
class ProjectRFIRequest(BaseModel):
    project_id: str
