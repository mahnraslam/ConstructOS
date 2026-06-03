"""
Deterministic Conflict Detection
----------------------------------
Compares extracted facts across documents using field matching.
NO LLM involvement in the comparison step — pure value comparison.

LLM is only used if fallback topic-scan is needed (legacy path for docs
where fact extraction hasn't run yet).
"""
import re
import json
import logging
from sqlalchemy.orm import Session
from db import Fact, Conflict, ProjectDocument
from models.schemas import (
    ConflictItem, ConflictResponse,
    AllConflictsResponse, FactConflict, FactConflictResponse,
)
from services import embedder, vector_store
from services.gemini import generate_json

logger = logging.getLogger(__name__)

# Doc types that act as "blueprint" side in comparisons
BLUEPRINT_TYPES  = {"blueprint"}
SPEC_TYPES       = {"specification", "submittal", "method_statement"}


# ── Deterministic fact-based conflict detection ───────────────────────────────

def detect_fact_conflicts(project_id: str, db: Session) -> FactConflictResponse:
    """
    Compare blueprint facts vs spec facts for a project.
    Matching is deterministic: normalise values → compare → flag differences.
    """
    # Gather all facts grouped by document type
    bp_facts: list[Fact]   = []
    spec_facts: list[Fact] = []

    for fact in db.query(Fact).filter(Fact.project_id == project_id).all():
        doc = db.query(ProjectDocument).filter(ProjectDocument.id == fact.document_id).first()
        if not doc:
            continue
        if doc.document_type in BLUEPRINT_TYPES:
            bp_facts.append(fact)
        elif doc.document_type in SPEC_TYPES:
            spec_facts.append(fact)

    # Build lookup: field -> list[Fact] for each side
    bp_by_field:   dict[str, list[Fact]] = {}
    spec_by_field: dict[str, list[Fact]] = {}

    for f in bp_facts:
        bp_by_field.setdefault(_normalise_field(f.field), []).append(f)
    for f in spec_facts:
        spec_by_field.setdefault(_normalise_field(f.field), []).append(f)

    conflicts: list[FactConflict] = []
    checked_fields = set(bp_by_field.keys()) & set(spec_by_field.keys())

    for field in checked_fields:
        for bf in bp_by_field[field]:
            for sf in spec_by_field[field]:
                bp_norm = _normalise_value(bf.value)
                sp_norm = _normalise_value(sf.value)
                if bp_norm and sp_norm and bp_norm != sp_norm:
                    severity = _classify_severity(field, bf.value, sf.value)
                    conflicts.append(FactConflict(
                        field            = field,
                        blueprint_value  = bf.value,
                        spec_value       = sf.value,
                        blueprint_doc_id = bf.document_id,
                        spec_doc_id      = sf.document_id,
                        blueprint_page   = bf.page,
                        spec_page        = sf.page,
                        blueprint_sheet  = bf.sheet,
                        spec_section     = sf.section,
                        status           = "conflict",
                        severity         = severity,
                    ))

    # Persist to DB
    db.query(Conflict).filter(Conflict.project_id == project_id).delete()
    for c in conflicts:
        db.add(Conflict(
            project_id       = project_id,
            field            = c.field,
            blueprint_value  = c.blueprint_value,
            spec_value       = c.spec_value,
            blueprint_doc_id = c.blueprint_doc_id,
            spec_doc_id      = c.spec_doc_id,
            blueprint_page   = c.blueprint_page,
            spec_page        = c.spec_page,
            blueprint_sheet  = c.blueprint_sheet,
            spec_section     = c.spec_section,
            status           = c.status,
            severity         = c.severity,
        ))
    db.commit()

    return FactConflictResponse(
        project_id = project_id,
        conflicts  = conflicts,
        total      = len(conflicts),
    )


def get_stored_conflicts(project_id: str, db: Session) -> FactConflictResponse:
    """Return previously-detected conflicts from DB without re-running detection."""
    rows = db.query(Conflict).filter(Conflict.project_id == project_id).all()
    conflicts = [
        FactConflict(
            field            = r.field,
            blueprint_value  = r.blueprint_value,
            spec_value       = r.spec_value,
            blueprint_doc_id = r.blueprint_doc_id or "",
            spec_doc_id      = r.spec_doc_id or "",
            blueprint_page   = r.blueprint_page,
            spec_page        = r.spec_page,
            blueprint_sheet  = r.blueprint_sheet or "",
            spec_section     = r.spec_section or "",
            status           = r.status,
            severity         = r.severity,
        )
        for r in rows
    ]
    return FactConflictResponse(project_id=project_id, conflicts=conflicts, total=len(conflicts))


# ── Legacy LLM-based detection (kept for docs without fact extraction) ────────

_TOPICS = [
    "slab thickness concrete grade strength",
    "rebar size diameter spacing reinforcement",
    "column beam dimensions cross section",
    "wall thickness partition structural",
    "floor level elevation datum height",
    "door window opening size dimension",
    "waterproofing membrane specification material",
    "fire rating insulation protection",
    "structural load capacity bearing",
    "foundation footing depth dimension",
]

CONFLICT_PAIRS = [
    ("blueprint", "specification"),
    ("blueprint", "submittal"),
    ("specification", "submittal"),
]


def _get_docs_by_type(doc_ids: list[str]) -> dict[str, list[dict]]:
    all_docs = vector_store.list_documents()
    by_type: dict[str, list[dict]] = {}
    id_set = set(doc_ids)
    for doc in all_docs:
        if doc.doc_id not in id_set:
            continue
        by_type.setdefault(doc.doc_type, []).append({"doc_id": doc.doc_id, "filename": doc.filename})
    return by_type


def detect_all_conflicts(project_doc_ids: list[str]) -> list[ConflictItem]:
    docs_by_type = _get_docs_by_type(project_doc_ids)
    conflicts: list[ConflictItem] = []
    for type_a, type_b in CONFLICT_PAIRS:
        for doc_a in docs_by_type.get(type_a, []):
            for doc_b in docs_by_type.get(type_b, []):
                result = detect(doc_a["doc_id"], doc_b["doc_id"],
                                doc_a["filename"], doc_b["filename"])
                conflicts.extend(result.conflicts)
    return conflicts


def detect(doc_id_a: str, doc_id_b: str, filename_a: str, filename_b: str) -> ConflictResponse:
    """Legacy LLM-based topic scan. Use detect_fact_conflicts for project-level work."""
    conflicts: list[ConflictItem] = []
    for topic in _TOPICS:
        topic_emb = embedder.embed_query(topic)
        chunks_a  = vector_store.query(topic_emb, [doc_id_a], n=2)
        chunks_b  = vector_store.query(topic_emb, [doc_id_b], n=2)
        if not chunks_a or not chunks_b:
            continue
        ca, cb = chunks_a[0], chunks_b[0]
        if ca["relevance_score"] < 0.3 or cb["relevance_score"] < 0.3:
            continue
        prompt = (
            f"Compare these construction document excerpts for technical contradictions.\n\n"
            f"DOC A — {filename_a}, Page {ca['page']}:\n\"\"\"{ca['text'][:400]}\"\"\"\n\n"
            f"DOC B — {filename_b}, Page {cb['page']}:\n\"\"\"{cb['text'][:400]}\"\"\"\n\n"
            f"Topic: {topic}\n\n"
            f"If contradiction: "
            '{"conflict": true, "severity": "high|medium|low", "description": "...", "quote_a": "...", "quote_b": "..."}\n'
            'If no contradiction: {"conflict": false}'
        )
        raw = generate_json(prompt).strip()
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if result.get("conflict"):
            conflicts.append(ConflictItem(
                severity    = result.get("severity", "medium"),
                topic       = topic,
                description = result.get("description", ""),
                quote_a     = result.get("quote_a", ca["text"][:80]),
                quote_b     = result.get("quote_b", cb["text"][:80]),
                page_a      = ca["page"],
                page_b      = cb["page"],
                filename_a  = filename_a,
                filename_b  = filename_b,
            ))
    return ConflictResponse(doc_id_a=doc_id_a, doc_id_b=doc_id_b,
                            conflicts=conflicts, total=len(conflicts))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalise_field(field: str) -> str:
    """Normalise LLM-returned field names to underscore_lower for consistent matching."""
    return field.strip().lower().replace(" ", "_").replace("-", "_")


def _normalise_value(raw: str) -> str:
    """
    Normalise a fact value for comparison.
    - Lowercase + strip
    - Standardise unit spacing: "200mm" → "200 mm"
    - Keep only the leading numeric+unit token so extra words don't block matching
    """
    v = raw.strip().lower()
    v = re.sub(r"(\d)\s*(mm|cm|m|mpa|n/mm2|kn|kpa|kg|mpa)\b", r"\1 \2", v)
    v = v.rstrip(".")
    # If value starts with a number+unit, use just that token for comparison
    m = re.match(r"(\d+(?:\.\d+)?\s*(?:mm|cm|m|mpa|n/mm2|kn|kpa|kg)?)", v)
    if m:
        return m.group(1).strip()
    return v


def _classify_severity(field: str, val_a: str, val_b: str) -> str:
    """Classify conflict severity based on field type and magnitude of difference."""
    structural_critical = {"slab_thickness", "concrete_grade", "rebar", "column_size", "beam_size"}
    if field in structural_critical:
        # Try to get numeric delta
        nums_a = re.findall(r"\d+(?:\.\d+)?", val_a)
        nums_b = re.findall(r"\d+(?:\.\d+)?", val_b)
        if nums_a and nums_b:
            try:
                diff_pct = abs(float(nums_a[0]) - float(nums_b[0])) / max(float(nums_a[0]), float(nums_b[0]))
                if diff_pct > 0.2:
                    return "high"
                return "medium"
            except ZeroDivisionError:
                pass
        return "high"
    return "medium"
