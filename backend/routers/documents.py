"""
Documents router.

Responsibilities ONLY:
  - Validate the incoming request
  - Save the uploaded file to disk
  - Create/update the database record
  - Kick off processing (background task or inline call)
  - Translate results/failures into an HTTP response

All actual ingestion work (parsing, embedding, vector storage, fact
extraction, status transitions) lives in services/pipeline.py and the
modules it coordinates. This router does not import pdf_parser, embedder,
or fact_extractor directly.
"""
import os
import uuid
import shutil
import glob
import logging
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from services import vector_store
from services.pipeline import (
    process_document, process_document_sync,
    DocumentParsingError, EmptyDocumentError, EmbeddingError,
)
from models.schemas import DocumentMeta, DeleteResponse
from db import get_db, ProjectDocument
from dotenv import load_dotenv

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
load_dotenv(_ENV_PATH, override=True)

logger     = logging.getLogger(__name__)
router     = APIRouter()
UPLOAD_DIR = os.getenv("UPLOAD_PATH", "storage/uploads")
PAGES_DIR  = os.getenv("PAGES_PATH", "storage/pages")
os.makedirs(UPLOAD_DIR, exist_ok=True)

DOC_TYPES = {"blueprint", "specification", "boq", "method_statement", "submittal", "rfi", "om_manual", "other"}


def detect_doc_type(filename: str) -> str:
    name = filename.lower()
    if any(x in name for x in ["dwg", "drawing", "blueprint", "plan", "sheet"]):
        return "blueprint"
    if any(x in name for x in ["spec", "specification", "csi"]):
        return "specification"
    if any(x in name for x in ["boq", "bill of quantities", "bill_of_quantities"]):
        return "boq"
    if any(x in name for x in ["method", "statement", "ms_"]):
        return "method_statement"
    if any(x in name for x in ["submittal", "approval", "shop drawing"]):
        return "submittal"
    if any(x in name for x in ["rfi", "request for information"]):
        return "rfi"
    if any(x in name for x in ["o&m", "manual", "maintenance"]):
        return "om_manual"
    return "other"


def _remove_existing_document(db: Session, project_id: str, filename: str) -> None:
    """If a document with this filename already exists in the project, tear
    down its vectors/files/DB row so the re-upload replaces it cleanly."""
    existing = db.query(ProjectDocument).filter(
        ProjectDocument.project_id == project_id,
        ProjectDocument.filename == filename,
    ).first()
    if existing:
        logger.info(f"[documents] Re-upload detected for {filename}, cleaning old doc_id={existing.id}")
        vector_store.delete_document(existing.id)
        _cleanup_files(existing.id)
        db.delete(existing)
        db.commit()


@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file:       UploadFile = File(...),
    doc_type:   str        = Form(default=""),
    project_id: str        = Form(default=""),
    db:         Session    = Depends(get_db),
):
    # ── Validate request ───────────────────────────────────────────────────
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files supported.")
    resolved_type = doc_type if doc_type in DOC_TYPES else detect_doc_type(file.filename)
    doc_id = str(uuid.uuid4())

    # ── Save uploaded file ──────────────────────────────────────────────────
    dest = os.path.join(UPLOAD_DIR, f"{doc_id}_{file.filename}")
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    logger.info(f"[documents] Saved upload doc_id={doc_id} filename={file.filename}")

    if project_id:
        # ── Create database record, start background processing ───────────
        _remove_existing_document(db, project_id, file.filename)

        doc = ProjectDocument(
            id=doc_id,
            project_id=project_id,
            filename=file.filename,
            document_type=resolved_type,
            page_count=0,
            chunk_count=0,
            status="pending",
        )
        db.add(doc)
        db.commit()

        background_tasks.add_task(
            process_document,
            doc_id=doc_id,
            file_path=dest,
            filename=file.filename,
            doc_type=resolved_type,
            project_id=project_id,
        )

        # Return immediately; the pipeline updates the record asynchronously
        # and the client polls GET /{doc_id}/status.
        return DocumentMeta(
            doc_id=doc_id,
            filename=file.filename,
            page_count=0,
            chunk_count=0,
            doc_type=resolved_type,
            fact_count=None,
            fact_extraction_error=None,
        )

    # ── No project_id: process inline and return full metadata (existing,
    #    backward-compatible synchronous behavior) ───────────────────────────
    try:
        result = process_document_sync(
            doc_id=doc_id,
            file_path=dest,
            filename=file.filename,
            doc_type=resolved_type,
            project_id="",
            db=None,
        )
    except DocumentParsingError as e:
        os.remove(dest)
        raise HTTPException(500, f"PDF parsing failed: {e}")
    except EmptyDocumentError as e:
        os.remove(dest)
        raise HTTPException(422, str(e))
    except EmbeddingError as e:
        os.remove(dest)
        raise HTTPException(500, f"Embedding failed: {e}")

    return DocumentMeta(
        doc_id=doc_id,
        filename=file.filename,
        page_count=result["page_count"],
        chunk_count=result["chunk_count"],
        doc_type=resolved_type,
        fact_count=result["fact_count"],
        fact_extraction_error=result["fact_extraction_error"],
    )


@router.get("/", response_model=list[DocumentMeta])
def list_documents():
    return vector_store.list_documents()


@router.delete("/{doc_id}", response_model=DeleteResponse)
def delete_document(doc_id: str, db: Session = Depends(get_db)):
    vector_store.delete_document(doc_id)
    _cleanup_files(doc_id)
    pd = db.query(ProjectDocument).filter(ProjectDocument.id == doc_id).first()
    if pd:
        db.delete(pd)
        db.commit()
    return DeleteResponse(doc_id=doc_id, deleted=True)


@router.get("/{doc_id}/status")
def get_document_status(doc_id: str, db: Session = Depends(get_db)):
    """Get the processing status of a document."""
    doc = db.query(ProjectDocument).filter(ProjectDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "doc_id": doc.id,
        "status": doc.status,
        "detail": doc.status_detail,
    }


@router.get("/{doc_id}/page-url/{page_num}")
def page_url(doc_id: str, page_num: int):
    pages_path = os.getenv("PAGES_PATH", "storage/pages")
    path = os.path.join(pages_path, f"{doc_id}_page_{page_num}.png")
    return {"exists": os.path.isfile(path),
            "url": f"/pages/{doc_id}_page_{page_num}.png"}


def _cleanup_files(doc_id: str):
    """Remove uploaded PDF and rendered page images for a document."""
    for f in glob.glob(os.path.join(UPLOAD_DIR, f"{doc_id}_*")):
        try:
            os.remove(f)
            logger.info(f"[documents] Removed upload: {f}")
        except OSError as e:
            logger.warning(f"[documents] Could not remove {f}: {e}")
    for f in glob.glob(os.path.join(PAGES_DIR, f"{doc_id}_page_*.png")):
        try:
            os.remove(f)
            logger.info(f"[documents] Removed page image: {f}")
        except OSError as e:
            logger.warning(f"[documents] Could not remove {f}: {e}")