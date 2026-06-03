import os, uuid, shutil
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from sqlalchemy.orm import Session
from services.pdf_parser import parse
from services.embedder import embed_and_store
from services import vector_store
from services.fact_extractor import extract_facts_for_document
from models.schemas import DocumentMeta, DeleteResponse
from db import get_db, ProjectDocument, SessionLocal
from dotenv import load_dotenv

load_dotenv()
router     = APIRouter()
UPLOAD_DIR = os.getenv("UPLOAD_PATH", "storage/uploads")
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
    try:
        chunks, page_count = parse(dest, doc_id)
    except Exception as e:
        os.remove(dest)
        raise HTTPException(500, f"PDF parsing failed: {e}")
    if not chunks:
        raise HTTPException(422, "No readable content found in PDF.")
    embed_and_store(chunks, doc_id, file.filename, resolved_type)

    # Persist to DB if project_id given
    if project_id:
        pd = ProjectDocument(
            id=doc_id, project_id=project_id, filename=file.filename,
            document_type=resolved_type, page_count=page_count,
            chunk_count=len(chunks),
        )
        db.merge(pd)   # merge = insert-or-update
        db.commit()
        # Auto-trigger fact extraction for pipeline activation
        try:
            extract_facts_for_document(
                doc_id=doc_id,
                project_id=project_id,
                filename=file.filename,
                doc_type=resolved_type,
                db=db,
            )
        except Exception as e:
            # Log but don't block upload
            import logging
            logging.error(f"[documents] Fact extraction failed for {doc_id}: {e}")

    return DocumentMeta(doc_id=doc_id, filename=file.filename,
                        page_count=page_count, chunk_count=len(chunks),
                        doc_type=resolved_type)


@router.get("/", response_model=list[DocumentMeta])
def list_documents():
    return vector_store.list_documents()


@router.delete("/{doc_id}", response_model=DeleteResponse)
def delete_document(doc_id: str, db: Session = Depends(get_db)):
    vector_store.delete_document(doc_id)
    # Remove DB entry if exists
    pd = db.query(ProjectDocument).filter(ProjectDocument.id == doc_id).first()
    if pd:
        db.delete(pd)
        db.commit()
    return DeleteResponse(doc_id=doc_id, deleted=True)


@router.get("/{doc_id}/page-url/{page_num}")
def page_url(doc_id: str, page_num: int):
    pages_path = os.getenv("PAGES_PATH", "storage/pages")
    path = os.path.join(pages_path, f"{doc_id}_page_{page_num}.png")
    return {"exists": os.path.isfile(path),
            "url": f"/pages/{doc_id}_page_{page_num}.png"}
