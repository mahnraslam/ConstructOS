import os, uuid, shutil, glob, logging
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from services.pdf_parser import parse
from services.embedder import embed_and_store
from services import vector_store
from services.fact_extractor import extract_facts_for_document
from services.pipeline import process_document
from models.schemas import DocumentMeta, DeleteResponse
from db import get_db, ProjectDocument, SessionLocal
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


@router.post("/upload", response_model=DocumentMeta)
async def upload_document(
    background_tasks: BackgroundTasks,
    file:       UploadFile = File(...),
    doc_type:   str        = Form(default=""),
    project_id: str        = Form(default=""),
    db:         Session    = Depends(get_db),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files supported.")
    resolved_type = doc_type if doc_type in DOC_TYPES else detect_doc_type(file.filename)
    doc_id = str(uuid.uuid4())
    dest   = os.path.join(UPLOAD_DIR, f"{doc_id}_{file.filename}")
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    if project_id:
        # Check for existing document with same filename in the same project and remove it
        existing = db.query(ProjectDocument).filter(
            ProjectDocument.project_id == project_id,
            ProjectDocument.filename == file.filename,
        ).first()
        if existing:
            logger.info(f"[documents] Re-upload detected for {file.filename}, cleaning old doc_id={existing.id}")
            vector_store.delete_document(existing.id)
            _cleanup_files(existing.id)
            db.delete(existing)
            db.commit()

        # Create new document record with pending status
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

        # Add background task for processing
        background_tasks.add_task(
            process_document,
            doc_id=doc_id,
            file_path=dest,
            filename=file.filename,
            doc_type=resolved_type,
            project_id=project_id,
        )

        # Return immediate response with minimal info (processing will update the record)
        return DocumentMeta(
            doc_id=doc_id,
            filename=file.filename,
            page_count=0,
            chunk_count=0,
            doc_type=resolved_type,
            fact_count=None,
            fact_extraction_error=None,
        )
    else:
        # No project_id provided: process synchronously (existing behavior)
        try:
            chunks, page_count = parse(dest, doc_id)
        except Exception as e:
            os.remove(dest)
            raise HTTPException(500, f"PDF parsing failed: {e}")
        if not chunks:
            raise HTTPException(422, "No readable content found in PDF.")

        # Bug 9 fix: clean up old vectors if re-uploading same file to same project
        # (Not applicable when no project_id, but we keep the check for safety)
        if project_id:  # This will be false, so skip
            existing = db.query(ProjectDocument).filter(
                ProjectDocument.project_id == project_id,
                ProjectDocument.filename == file.filename,
            ).first()
            if existing:
                logger.info(f"[documents] Re-upload detected for {file.filename}, cleaning old doc_id={existing.id}")
                vector_store.delete_document(existing.id)
                _cleanup_files(existing.id)
                db.delete(existing)
                db.commit()

        embed_and_store(chunks, doc_id, file.filename, resolved_type)

        # Track fact extraction result for response (Bug 1 fix)
        fact_count = None
        fact_error = None

        # Persist to DB if project_id given (not in this branch)
        if project_id:  # This will be false, so skip
            pd = ProjectDocument(
                id=doc_id, project_id=project_id, filename=file.filename,
                document_type=resolved_type, page_count=page_count,
                chunk_count=len(chunks),
            )
            db.merge(pd)   # merge = insert-or-update
            db.commit()
            # Auto-trigger fact extraction for pipeline activation
            try:
                fact_count = extract_facts_for_document(
                    doc_id=doc_id,
                    project_id=project_id,
                    filename=file.filename,
                    doc_type=resolved_type,
                    db=db,
                )
            except Exception as e:
                # Bug 1 fix: capture error message instead of silently swallowing
                fact_error = str(e)
                logger.error(f"[documents] Fact extraction failed for {doc_id}: {e}")

        return DocumentMeta(
            doc_id=doc_id, filename=file.filename,
            page_count=page_count, chunk_count=len(chunks),
            doc_type=resolved_type,
            fact_count=fact_count,
            fact_extraction_error=fact_error,
        )


@router.get("/", response_model=list[DocumentMeta])
def list_documents():
    return vector_store.list_documents()


@router.delete("/{doc_id}", response_model=DeleteResponse)
def delete_document(doc_id: str, db: Session = Depends(get_db)):
    vector_store.delete_document(doc_id)
    # Bug 5 fix: clean up uploaded PDF and page images from disk
    _cleanup_files(doc_id)
    # Remove DB entry if exists
    pd = db.query(ProjectDocument).filter(ProjectDocument.id == doc_id).first()
    if pd:
        db.delete(pd)
        db.commit()
    return DeleteResponse(doc_id=doc_id, deleted=True)


@router.get("/{doc_id}/status")
def get_document_status(doc_id: str, db: Session = Depends(get_db)):
    """
    Get the processing status of a document.
    """
    doc = db.query(ProjectDocument).filter(ProjectDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "doc_id": doc.id,
        "status": doc.status,
        "detail": doc.status_detail
    }


@router.get("/{doc_id}/page-url/{page_num}")
def page_url(doc_id: str, page_num: int):
    pages_path = os.getenv("PAGES_PATH", "storage/pages")
    path = os.path.join(pages_path, f"{doc_id}_page_{page_num}.png")
    return {"exists": os.path.isfile(path),
            "url": f"/pages/{doc_id}_page_{page_num}.png"}


def _cleanup_files(doc_id: str):
    """Remove uploaded PDF and rendered page images for a document."""
    # Remove uploaded PDF
    for f in glob.glob(os.path.join(UPLOAD_DIR, f"{doc_id}_*")):
        try:
            os.remove(f)
            logger.info(f"[documents] Removed upload: {f}")
        except OSError as e:
            logger.warning(f"[documents] Could not remove {f}: {e}")
    # Remove page images
    for f in glob.glob(os.path.join(PAGES_DIR, f"{doc_id}_page_*.png")):
        try:
            os.remove(f)
            logger.info(f"[documents] Removed page image: {f}")
        except OSError as e:
            logger.warning(f"[documents] Could not remove {f}: {e}")
