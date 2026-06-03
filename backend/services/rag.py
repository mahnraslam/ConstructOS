import os
import re
import logging
from sqlalchemy.orm import Session
from services import embedder, vector_store
from services.gemini import generate, generate_with_images
from models.schemas import QueryResponse, Citation, Reference
from db import get_db, ProjectDocument

logger    = logging.getLogger(__name__)
PAGES_DIR = os.getenv("PAGES_PATH", "storage/pages")
MAX_VISUAL_PAGES = 3

# ── Prompt templates ─────────────────────────────────────────────────────────

_SYSTEM = """You are ConstructOS — a construction document assistant.
Answer ONLY from the document context provided.
If the answer is not in the context, say: NOT FOUND IN DOCUMENTS
Always quote the exact technical value (e.g. 200mm, C25/30, T16@150).
State which document and page each value comes from."""

_CROSS_SYSTEM = """You are ConstructOS — a construction document assistant.
You are searching BOTH a blueprint (engineering drawing) AND a specification document.

Your job:
1. Find the answer in either or both documents
2. Cross-reference them — does the blueprint match the spec?
3. State WHICH document gave each value
4. If they agree: confirm both. If they disagree: flag the discrepancy with exact values.

RULES:
- Only use information from the context — never general knowledge
- Always give exact technical value (200mm, not "about 200")
- If neither has it, say: NOT FOUND IN DOCUMENTS"""

_CROSS_FORMAT = """Answer format:

**[One sentence direct answer with the exact value]**

📐 Blueprint says: [exact value + "Page N" or "not mentioned"]
📋 Specification says: [exact value + "Page N" or "not mentioned"]
✅ Status: [Consistent / ⚠ Discrepancy — blueprint shows X but spec requires Y]"""

_SINGLE_FORMAT = """Answer format:
**[Direct answer with the exact value]**
Source: [filename, Page N]"""


# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_blueprint(chunk: dict) -> bool:
    return chunk.get("doc_type", "other") == "blueprint"

def _is_spec(chunk: dict) -> bool:
    return chunk.get("doc_type", "other") in ("specification", "submittal", "method_statement")


def _build_context(chunks: list[dict], cross: bool) -> str:
    if not cross:
        return "\n\n---\n\n".join(
            f"[Source {i+1}: {c['filename']}, Page {c['page']}]\n{c['text']}"
            for i, c in enumerate(chunks)
        )
    parts = []
    bp = [c for c in chunks if _is_blueprint(c)]
    sp = [c for c in chunks if _is_spec(c)]
    ot = [c for c in chunks if not _is_blueprint(c) and not _is_spec(c)]
    if bp:
        parts.append("── BLUEPRINT ──")
        parts += [f"[Blueprint: {c['filename']}, Page {c['page']}]\n{c['text']}" for c in bp]
    if sp:
        parts.append("── SPECIFICATION ──")
        parts += [f"[Spec: {c['filename']}, Page {c['page']}]\n{c['text']}" for c in sp]
    if ot:
        parts.append("── OTHER ──")
        parts += [f"[{c['filename']}, Page {c['page']}]\n{c['text']}" for c in ot]
    return "\n\n".join(parts)


def _image_paths(chunks: list[dict]) -> list[str]:
    seen, paths = set(), []
    ordered = sorted(chunks, key=lambda c: (0 if _is_blueprint(c) else 1, -c["relevance_score"]))
    for c in ordered:
        key = (c["doc_id"], c["page"])
        if key in seen:
            continue
        seen.add(key)
        p = os.path.join(PAGES_DIR, f"{c['doc_id']}_page_{c['page']}.png")
        if os.path.exists(p):
            paths.append(p)
        if len(paths) >= MAX_VISUAL_PAGES:
            break
    return paths


def _image_url(c: dict) -> str | None:
    p = os.path.join(PAGES_DIR, f"{c['doc_id']}_page_{c['page']}.png")
    return f"/pages/{c['doc_id']}_page_{c['page']}.png" if os.path.exists(p) else None


def _chunk_to_reference(c: dict) -> Reference:
    """Build a structured Reference from a vector-store chunk."""
    # Try to detect sheet number from text (e.g. "Sheet S-101", "Dwg No. A-201")
    sheet = ""
    sheet_match = re.search(r"\b([A-Z]-?\d{3}[A-Z]?)\b", c["text"])
    if sheet_match:
        sheet = sheet_match.group(1)

    # Try to detect section reference (e.g. "Section 03 30 00", "Clause 4.3")
    section = ""
    sec_match = re.search(r"(?:Section|Clause|Sec\.?)\s*([\d\s]+\d)", c["text"], re.I)
    if sec_match:
        section = sec_match.group(0)[:40]

    return Reference(
        document_name = c["filename"],
        document_type = c.get("doc_type", "other"),
        page          = c["page"],
        sheet         = sheet,
        section       = section,
        quote         = c["text"][:150].strip(),
        image_url     = _image_url(c),
    )


def _get_project_doc_ids(project_id: str) -> list[str]:
    """Resolve document IDs for a project from the DB."""
    from db import SessionLocal, ProjectDocument as PD
    db = SessionLocal()
    try:
        return [pd.id for pd in db.query(PD).filter(PD.project_id == project_id).all()]
    finally:
        db.close()


# ── Public API ───────────────────────────────────────────────────────────────

def answer(
    question: str,
    doc_ids:    list[str] | None,
    project_id: str | None = None,
    top_k: int = 5,
    visual: bool = False,
) -> QueryResponse:
    """
    Answer a question from construction documents.
    If project_id is given, retrieves across all project documents.
    Returns structured References alongside legacy Citations.
    """
    # Resolve doc_ids from project if needed
    effective_doc_ids = doc_ids
    if project_id and not doc_ids:
        effective_doc_ids = _get_project_doc_ids(project_id)

    q_emb  = embedder.embed_query(question)
    chunks = vector_store.query(q_emb, effective_doc_ids, n=top_k)

    if not chunks:
        return QueryResponse(
            question=question,
            answer="NOT FOUND IN DOCUMENTS — no documents uploaded yet.",
            citations=[], references=[],
        )

    has_blueprint = any(_is_blueprint(c) for c in chunks)
    has_spec      = any(_is_spec(c) for c in chunks)
    cross_mode    = has_blueprint and has_spec

    context = _build_context(chunks, cross_mode)
    system  = _CROSS_SYSTEM if cross_mode else _SYSTEM
    fmt     = _CROSS_FORMAT  if cross_mode else _SINGLE_FORMAT

    prompt = f"{system}\n\nDOCUMENT CONTEXT:\n{context}\n\nQUESTION: {question}\n\n{fmt}"

    if visual:
        img_paths = _image_paths(chunks)
        if img_paths:
            prompt += f"\n\n{len(img_paths)} blueprint page image(s) attached."
        answer_text = generate_with_images(prompt, img_paths) if (visual and img_paths) else generate(prompt)
    else:
        answer_text = generate(prompt)

    citations = [
        Citation(
            doc_id          = c["doc_id"],
            filename        = c["filename"],
            page_num        = c["page"],
            chunk_text      = c["text"][:300],
            relevance_score = c["relevance_score"],
            image_url       = _image_url(c),
            doc_type        = c.get("doc_type", "other"),
        )
        for c in chunks
    ]

    references = [_chunk_to_reference(c) for c in chunks]

    return QueryResponse(
        question   = question,
        answer     = answer_text,
        citations  = citations,
        references = references,
    )
