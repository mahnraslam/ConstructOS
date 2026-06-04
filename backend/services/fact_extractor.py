"""
Fact Extraction Service
-----------------------
Extracts structured construction facts from document chunks via LLM and
stores them in SQLite. Facts are categorised as structural, architectural, or MEP.

Fact fields extracted:
  Structural : slab_thickness, beam_size, column_size, concrete_grade, rebar
  Architectural: wall_type, door_schedule, floor_finish
  MEP         : pipe_size, cable_size, equipment
"""
import re
import time
import json
import logging
from sqlalchemy.orm import Session
from services import vector_store
from services.gemini import generate_json
from db import Fact, ProjectDocument

logger = logging.getLogger(__name__)

# Topics and their fact fields
FACT_CATEGORIES = {
    "structural": [
        "slab_thickness", "beam_size", "column_size",
        "concrete_grade", "rebar", "foundation_depth",
    ],
    "architectural": [
        "wall_type", "wall_thickness", "door_schedule",
        "floor_finish", "ceiling_height",
    ],
    "mep": [
        "pipe_size", "cable_size", "equipment",
        "duct_size", "conduit_size",
    ],
}

_EXTRACT_PROMPT = """You are a construction document parser. Extract ONLY the facts explicitly stated in the following text.

Document: {filename} (type: {doc_type}), Page {page}

TEXT:
{text}

Extract facts for these fields (only if clearly stated with a value):
{fields}

Respond with ONLY a JSON array. Each item:
{{"field": "field_name", "value": "exact value as written", "unit": "mm or MPa etc", "sheet": "sheet ref if any", "section": "section ref if any", "quote": "exact phrase from text (max 100 chars)"}}

If no facts found, respond with: []
Do not invent or infer values not explicitly in the text."""


def extract_facts_for_document(
    doc_id: str,
    project_id: str,
    filename: str,
    doc_type: str,
    db: Session,
) -> int:
    """
    Extract facts from ALL chunks of a document and store in DB.
    Returns count of facts stored.
    """
    # Delete existing facts for this doc to avoid duplicates on re-run
    db.query(Fact).filter(Fact.document_id == doc_id).delete()
    db.commit()

    # Retrieve ALL chunks deterministically (Bug 4/7 fix)
    all_chunks = vector_store.get_all_by_doc_id(doc_id)
    if not all_chunks:
        logger.warning(f"[facts] No chunks found for doc_id={doc_id}")
        return 0

    logger.info(f"[facts] Processing {len(all_chunks)} chunks for doc_id={doc_id}")

    # Track all extracted facts for deduplication
    all_facts: list[dict] = []
    llm_errors = 0

    for category, fields in FACT_CATEGORIES.items():
        for chunk in all_chunks:
            facts = _extract_from_chunk(chunk, filename, doc_type, fields)
            if facts is None:
                # LLM error occurred for this chunk
                llm_errors += 1
                continue
            for f in facts:
                all_facts.append({
                    "project_id":  project_id,
                    "document_id": doc_id,
                    "category":    category,
                    "field":       f.get("field", ""),
                    "value":       f.get("value", ""),
                    "unit":        f.get("unit", ""),
                    "page":        chunk["page"],
                    "sheet":       f.get("sheet", ""),
                    "section":     f.get("section", ""),
                    "quote":       f.get("quote", ""),
                })

        # Brief rate-limit pause between categories (Bug 12 fix: was 5s)
        time.sleep(1)

    # Deduplicate facts (Bug 8 fix)
    deduped = _deduplicate_facts(all_facts)

    # Persist to DB
    for f in deduped:
        db.add(Fact(**f))
    db.commit()

    logger.info(
        f"[facts] Extracted {len(deduped)} unique facts "
        f"(from {len(all_facts)} raw, {llm_errors} LLM errors) "
        f"for doc_id={doc_id}"
    )
    return len(deduped)


def _deduplicate_facts(facts: list[dict]) -> list[dict]:
    """
    Deduplicate facts by (category, field, normalized_value).
    Keeps the first occurrence (earliest page reference).
    """
    seen: set[tuple] = set()
    unique: list[dict] = []
    for f in facts:
        key = (
            f["category"],
            _normalise_field(f["field"]),
            _normalise_value(f["value"]),
        )
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def _normalise_field(field: str) -> str:
    return field.strip().lower().replace(" ", "_").replace("-", "_")


def _normalise_value(raw: str) -> str:
    v = raw.strip().lower()
    v = re.sub(r"(\d)\s*(mm|cm|m|mpa|n/mm2|kn|kpa|kg)", r"\1 \2", v)
    return v


def _extract_from_chunk(
    chunk: dict, filename: str, doc_type: str, fields: list[str]
) -> list[dict] | None:
    """
    Call LLM to extract facts from a single chunk.
    Returns list of facts, or None if LLM call failed.
    """
    prompt = _EXTRACT_PROMPT.format(
        filename = filename,
        doc_type = doc_type,
        page     = chunk["page"],
        text     = chunk["text"][:1200],
        fields   = ", ".join(fields),
    )
    try:
        raw = generate_json(prompt).strip()
    except ValueError as e:
        # Bug 6 fix: generate_json now raises on Gemini error strings
        logger.warning(f"[facts] LLM error for chunk page={chunk['page']}: {e}")
        return None

    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return [f for f in result if f.get("field") and f.get("value")]
    except json.JSONDecodeError:
        logger.debug(f"[facts] JSON parse failed: {raw[:80]}")
    return []


def get_facts_for_project(project_id: str, db: Session) -> list[dict]:
    """Return all facts for a project with document filename included."""
    facts = db.query(Fact, ProjectDocument.filename).join(
        ProjectDocument, Fact.document_id == ProjectDocument.id
    ).filter(Fact.project_id == project_id).all()

    return [
        {
            "id":          f.Fact.id,
            "category":    f.Fact.category,
            "field":       f.Fact.field,
            "value":       f.Fact.value,
            "unit":        f.Fact.unit,
            "page":        f.Fact.page,
            "sheet":       f.Fact.sheet,
            "section":     f.Fact.section,
            "quote":       f.Fact.quote,
            "document_id": f.Fact.document_id,
            "filename":    f.filename,
        }
        for f in facts
    ]
