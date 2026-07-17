"""
Fact Extraction Service
-----------------------
Extracts structured construction facts from document chunks via LLM and
stores them in SQLite. Facts are categorised as structural, architectural, or MEP.

Fact fields extracted:
  Structural : slab_thickness, beam_size, column_size, concrete_grade, rebar, foundation_depth
  Architectural: wall_type, wall_thickness, door_schedule, floor_finish, ceiling_height
  MEP         : pipe_size, cable_size, equipment, duct_size, conduit_size
"""
import re
import logging
from sqlalchemy.orm import Session
from services import vector_store
from services.gemini import generate_json
from db import Fact, ProjectDocument

logger = logging.getLogger(__name__)

# Map each field to its category
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

# Build a flat list of all fields and a reverse mapping
ALL_FIELDS = []
FIELD_TO_CATEGORY = {}
for category, fields in FACT_CATEGORIES.items():
    for f in fields:
        ALL_FIELDS.append(f)
        FIELD_TO_CATEGORY[f] = category

_EXTRACT_PROMPT = """You are a construction document parser. Extract ONLY the facts explicitly stated in the following text.

Document: {filename} (type: {doc_type}), Page {page}

TEXT:
{text}

Extract facts for these fields (each belongs to a category: structural, architectural, or MEP):
{fields}

Respond with ONLY a JSON array. Each item:
{{"field": "field_name", "category": "structural|architectural|mep", "value": "exact value as written", "unit": "mm or MPa etc", "sheet": "sheet ref if any", "section": "section ref if any", "quote": "exact phrase from text (max 100 chars)"}}

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

    # Collect raw facts from all chunks
    raw_facts: list[dict] = []
    llm_errors = 0

    for chunk in all_chunks:
        facts = _extract_all_fields_from_chunk(chunk, filename, doc_type)
        if facts is None:
            # LLM error occurred for this chunk
            llm_errors += 1
            continue
        for f in facts:
            # Ensure category is present; if missing, infer from field map
            if "category" not in f or not f["category"]:
                field_name = f.get("field", "")
                f["category"] = FIELD_TO_CATEGORY.get(field_name, "other")
            # Normalise category to lower case and strip
            cat = f["category"].strip().lower()
            if cat not in ("structural", "architectural", "mep"):
                # Fallback to mapping if LLM gave unexpected category
                field_name = f.get("field", "")
                cat = FIELD_TO_CATEGORY.get(field_name, "other")
            f["category"] = cat

            raw_facts.append({
                "project_id": project_id,
                "document_id": doc_id,
                "category": f["category"],
                "field": f.get("field", ""),
                "value": f.get("value", ""),
                "unit": f.get("unit", ""),
                "page": chunk["page"],
                "sheet": f.get("sheet", ""),
                "section": f.get("section", ""),
                "quote": f.get("quote", ""),
            })

    # Deduplicate facts (Bug 8 fix)
    deduped = _deduplicate_facts(raw_facts)

    # Persist to DB
    for f in deduped:
        db.add(Fact(**f))
    db.commit()

    logger.info(
        f"[facts] Stored {len(deduped)} unique facts "
        f"(from {len(raw_facts)} raw, {llm_errors} LLM errors) "
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


def _extract_all_fields_from_chunk(
    chunk: dict, filename: str, doc_type: str
) -> list[dict] | None:
    """
    Call LLM to extract facts for all fields from a single chunk.
    Returns list of fact dicts, or None if LLM call failed.
    """
    prompt = _EXTRACT_PROMPT.format(
        filename=filename,
        doc_type=doc_type,
        page=chunk["page"],
        text=chunk["text"][:1200],  # limit prompt size
        fields=", ".join(ALL_FIELDS),
    )
    try:
        # generate_json now does its own JSON parsing (and raises ValueError
        # on both LLM failures and malformed JSON), so we get a Python
        # object back directly instead of re-parsing a raw string here.
        result = generate_json(prompt)
    except ValueError as e:
        # Bug 6 fix: generate_json raises on Gemini/Groq error strings and
        # on invalid JSON — either way, this chunk's extraction failed.
        logger.warning(f"[facts] LLM error for chunk page={chunk['page']}: {e}")
        return None

    if not isinstance(result, list):
        logger.debug(f"[facts] Expected JSON list, got {type(result)}")
        return []

    facts: list[dict] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        field = item.get("field")
        value = item.get("value")
        if not field or not value:
            continue
        # Ensure all expected keys exist with defaults
        fact = {
            "field": field,
            "category": item.get("category", ""),
            "value": value,
            "unit": item.get("unit", ""),
            "sheet": item.get("sheet", ""),
            "section": item.get("section", ""),
            "quote": item.get("quote", ""),
        }
        # Truncate quote to 100 chars if needed
        if len(fact["quote"]) > 100:
            fact["quote"] = fact["quote"][:100]
        facts.append(fact)
    return facts