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
import json
import logging
from sqlalchemy.orm import Session
from services import embedder, vector_store
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
    Extract facts from all chunks of a document and store in DB.
    Returns count of facts stored.
    """
    # Delete existing facts for this doc to avoid duplicates on re-run
    db.query(Fact).filter(Fact.document_id == doc_id).delete()
    db.commit()

    # Retrieve all chunks for this doc via vector_store
    all_chunks = _get_all_chunks(doc_id)
    if not all_chunks:
        logger.warning(f"[facts] No chunks found for doc_id={doc_id}")
        return 0

    total = 0
    for category, fields in FACT_CATEGORIES.items():
        category_query = " ".join(fields)
        q_emb  = embedder.embed_query(category_query)
        # Increased n to 15 to capture more of the document
        chunks = vector_store.query(q_emb, [doc_id], n=15)

        for chunk in chunks:
            if chunk["relevance_score"] < 0.15:   # lowered threshold
                continue
            facts = _extract_from_chunk(chunk, filename, doc_type, fields)
            for f in facts:
                db.add(Fact(
                    project_id  = project_id,
                    document_id = doc_id,
                    category    = category,
                    field       = f.get("field", ""),
                    value       = f.get("value", ""),
                    unit        = f.get("unit", ""),
                    page        = chunk["page"],
                    sheet       = f.get("sheet", ""),
                    section     = f.get("section", ""),
                    quote       = f.get("quote", ""),
                ))
                total += 1

    db.commit()
    logger.info(f"[facts] Extracted {total} facts for doc_id={doc_id}")
    return total


def _get_all_chunks(doc_id: str) -> list[dict]:
    """Retrieve all chunks for a doc via a broad semantic query."""
    q_emb = embedder.embed_query("construction specification dimensions material grade")
    return vector_store.query(q_emb, [doc_id], n=20)


def _extract_from_chunk(chunk: dict, filename: str, doc_type: str, fields: list[str]) -> list[dict]:
    """Call LLM to extract facts from a single chunk."""
    prompt = _EXTRACT_PROMPT.format(
        filename = filename,
        doc_type = doc_type,
        page     = chunk["page"],
        text     = chunk["text"][:1200],
        fields   = ", ".join(fields),
    )
    raw = generate_json(prompt).strip()
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
