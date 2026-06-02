from fastapi import APIRouter, HTTPException
from models.schemas import RFIRequest, RFIResponse
from services.rfi import generate_rfis
from services import vector_store

router = APIRouter()


@router.post("/generate", response_model=RFIResponse)
async def generate_rfi(req: RFIRequest):
    """
    Compare a blueprint document against a specification and generate RFIs
    for every discrepancy found.

    How it works:
    1. 12 construction topics are probed (slab, rebar, columns, etc.)
    2. For each topic, the most relevant chunks from each document are retrieved.
    3. With visual=true (default), the blueprint page images are sent to Gemini
       Vision so it can read dimensions and annotations directly off the drawing —
       not just rely on extracted text.
    4. Gemini returns structured discrepancy data per topic.
    5. Each discrepancy becomes a numbered RFI with priority, references,
       exact quotes, a clarification question, and a suggested resolution.

    Returns RFIResponse with a list of RFIItem objects ready to display or export.
    """
    # Resolve filenames from the vector store if not provided
    blueprint_filename = req.blueprint_filename
    spec_filename      = req.spec_filename

    if not blueprint_filename or not spec_filename:
        docs = {d.doc_id: d.filename for d in vector_store.list_documents()}
        blueprint_filename = blueprint_filename or docs.get(req.blueprint_doc_id, req.blueprint_doc_id)
        spec_filename      = spec_filename      or docs.get(req.spec_doc_id,       req.spec_doc_id)

    try:
        return generate_rfis(
            blueprint_doc_id   = req.blueprint_doc_id,
            spec_doc_id        = req.spec_doc_id,
            blueprint_filename = blueprint_filename,
            spec_filename      = spec_filename,
            visual             = req.visual,
            top_k_per_topic    = req.top_k_per_topic,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RFI generation failed: {e}")