import os
import logging
from services import embedder, vector_store
from services.gemini import generate, generate_with_images
from models.schemas import QueryResponse, Citation

logger  = logging.getLogger(__name__)
PAGES_DIR = os.getenv("PAGES_PATH", "storage/pages")
MAX_VISUAL_PAGES = 3

# ── Prompt templates ────────────────────────────────────────────────────────

_SINGLE_DOC_SYSTEM = """You are ConstructOS — a construction document assistant.
Answer ONLY from the document context provided.
If the answer is not in the context, say exactly: NOT FOUND IN DOCUMENTS
Always quote the exact technical value (e.g. 200mm, C25/30, T16@150).
Be concise. Engineers need facts."""

_SINGLE_DOC_FORMAT = """Answer format:
**[Direct answer in one sentence with the exact value]**
Source: [filename, Page N]"""

# ─────────────────────────────────────────────────────────────────────────────
# Cross-document system — this is the one that gives answers like
# "Slab thickness is 200mm per Blueprint Page 3, confirmed by Spec Section 4.2"
# ─────────────────────────────────────────────────────────────────────────────
_CROSS_DOC_SYSTEM = """You are ConstructOS — a construction document assistant.
You are searching BOTH a blueprint (engineering drawing) AND a specification document.

Your job:
1. Find the answer in either or both documents
2. Cross-reference them — does the blueprint match the spec?
3. Always state WHICH document (blueprint or spec) gave each value
4. If they agree: confirm both
5. If they disagree: clearly flag the discrepancy with exact values from each

RULES:
- Only use information from the context provided — never general knowledge
- Always give the exact technical value (200mm, not "about 200")
- If only one doc has the answer, say so and cite that doc
- If neither has it, say: NOT FOUND IN DOCUMENTS"""

_CROSS_DOC_FORMAT = """Answer format (use exactly this structure):

**[One sentence direct answer with the exact value]**

📐 Blueprint says: [exact value from drawing + "Page N" or "not mentioned"]
📋 Specification says: [exact value from spec + "Page N" or "not mentioned"]
✅ Status: [Consistent / ⚠ Discrepancy — blueprint shows X but spec requires Y]"""


# ── Helpers ─────────────────────────────────────────────────────────────────

def _is_blueprint(chunk: dict) -> bool:
    return chunk.get("doc_type", "other") == "blueprint"

def _is_spec(chunk: dict) -> bool:
    return chunk.get("doc_type", "other") in ("specification", "submittal", "om_manual")


def _build_cross_context(chunks: list[dict]) -> str:
    """
    Build a context block that clearly separates blueprint chunks from spec
    chunks so Gemini knows which document type said what.
    """
    bp_chunks   = [c for c in chunks if _is_blueprint(c)]
    spec_chunks = [c for c in chunks if _is_spec(c)]
    other       = [c for c in chunks if not _is_blueprint(c) and not _is_spec(c)]

    parts = []

    if bp_chunks:
        parts.append("── BLUEPRINT (Engineering Drawing) ──")
        for i, c in enumerate(bp_chunks, 1):
            parts.append(f"[Blueprint Source {i}: {c['filename']}, Page {c['page']}]\n{c['text']}")

    if spec_chunks:
        parts.append("── SPECIFICATION (Written Spec) ──")
        for i, c in enumerate(spec_chunks, 1):
            parts.append(f"[Spec Source {i}: {c['filename']}, Page {c['page']}]\n{c['text']}")

    if other:
        parts.append("── OTHER DOCUMENTS ──")
        for i, c in enumerate(other, 1):
            parts.append(f"[Source {i}: {c['filename']}, Page {c['page']}]\n{c['text']}")

    return "\n\n".join(parts)


def _build_single_context(chunks: list[dict]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(f"[Source {i}: {c['filename']}, Page {c['page']}]\n{c['text']}")
    return "\n\n---\n\n".join(parts)


def _image_paths(chunks: list[dict]) -> list[str]:
    seen, paths = set(), []
    # Prioritise blueprint pages for images (drawings benefit most from vision)
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


# ── Public API ───────────────────────────────────────────────────────────────

def answer(
    question: str,
    doc_ids: list[str] | None,
    top_k: int = 5,
    visual: bool = False,
) -> QueryResponse:
    """
    Answer a question by searching across uploaded documents.

    When doc_ids contains both a blueprint and a spec, the prompt switches to
    cross-document mode: Gemini is told which chunks are from the drawing and
    which are from the written spec, and is asked to cross-reference them.
    The answer then reads like:
        "Slab thickness is 200mm.
         📐 Blueprint says: 200mm, Page 3
         📋 Specification says: 200mm per Clause 4.3, Page 8
         ✅ Status: Consistent"

    visual=True → blueprint page images are passed to Gemini so it can read
    dimensions annotated on the drawing directly, not just extracted text.
    """
    q_emb  = embedder.embed_query(question)
    chunks = vector_store.query(q_emb, doc_ids, n=top_k)

    if not chunks:
        return QueryResponse(
            question=question,
            answer="NOT FOUND IN DOCUMENTS — no documents uploaded yet.",
            citations=[],
        )

    # Decide which prompt mode to use
    has_blueprint = any(_is_blueprint(c) for c in chunks)
    has_spec      = any(_is_spec(c) for c in chunks)
    cross_mode    = has_blueprint and has_spec

    if cross_mode:
        context = _build_cross_context(chunks)
        system  = _CROSS_DOC_SYSTEM
        fmt     = _CROSS_DOC_FORMAT
        logger.info(f"[rag] Cross-document mode: blueprint + spec chunks both present")
    else:
        context = _build_single_context(chunks)
        system  = _SINGLE_DOC_SYSTEM
        fmt     = _SINGLE_DOC_FORMAT
        logger.info(f"[rag] Single-document mode")

    prompt = f"""{system}

DOCUMENT CONTEXT:
{context}

QUESTION: {question}

{fmt}"""

    if visual:
        img_paths = _image_paths(chunks)
        logger.info(f"[rag] Visual mode: {len(img_paths)} page image(s) attached")
        if img_paths:
            prompt += f"\n\n{len(img_paths)} blueprint page image(s) attached — read any dimensions or annotations you can see directly from the drawing."
        answer_text = generate_with_images(prompt, img_paths) if img_paths else generate(prompt)
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

    return QueryResponse(question=question, answer=answer_text, citations=citations)
 