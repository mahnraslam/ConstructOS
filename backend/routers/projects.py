import uuid, os, glob, logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from db import get_db, Project, ProjectDocument
from services import vector_store

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Schemas ──────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    description: str = ""

class ProjectOut(BaseModel):
    id: str
    name: str
    description: str
    document_count: int = 0

    class Config:
        from_attributes = True

class DocAddRequest(BaseModel):
    doc_id: str
    filename: str
    document_type: str = "other"
    page_count: int = 0
    chunk_count: int = 0

class ProjectDocOut(BaseModel):
    id: str
    filename: str
    document_type: str
    page_count: int
    chunk_count: int

    class Config:
        from_attributes = True

# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/", response_model=ProjectOut)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    proj = Project(id=str(uuid.uuid4()), name=body.name, description=body.description)
    db.add(proj)
    db.commit()
    db.refresh(proj)
    return ProjectOut(id=proj.id, name=proj.name, description=proj.description or "",
                      document_count=0)


@router.get("/", response_model=List[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    projs = db.query(Project).all()
    return [
        ProjectOut(id=p.id, name=p.name, description=p.description or "",
                   document_count=len(p.documents))
        for p in projs
    ]


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404, "Project not found")
    return ProjectOut(id=p.id, name=p.name, description=p.description or "",
                      document_count=len(p.documents))


@router.delete("/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404, "Project not found")

    # Bug 2 fix: clean up ChromaDB vectors and disk files BEFORE deleting DB rows
    upload_dir = os.getenv("UPLOAD_PATH", "storage/uploads")
    pages_dir  = os.getenv("PAGES_PATH", "storage/pages")
    docs = db.query(ProjectDocument).filter(ProjectDocument.project_id == project_id).all()
    for doc in docs:
        # Remove vectors from ChromaDB
        try:
            vector_store.delete_document(doc.id)
        except Exception as e:
            logger.warning(f"[projects] Failed to delete vectors for doc {doc.id}: {e}")
        # Remove uploaded PDF files
        for f in glob.glob(os.path.join(upload_dir, f"{doc.id}_*")):
            try:
                os.remove(f)
            except OSError:
                pass
        # Remove page images
        for f in glob.glob(os.path.join(pages_dir, f"{doc.id}_page_*.png")):
            try:
                os.remove(f)
            except OSError:
                pass

    logger.info(f"[projects] Cleaned up {len(docs)} documents for project {project_id}")

    # Cascade delete handles ProjectDocuments, Facts, Conflicts, RFIs in SQLite
    db.delete(p)
    db.commit()
    return {"deleted": True}


@router.post("/{project_id}/documents", response_model=ProjectDocOut)
def add_document_to_project(project_id: str, body: DocAddRequest, db: Session = Depends(get_db)):
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(404, "Project not found")
    # Upsert — if same doc_id already in project, update fields
    existing = db.query(ProjectDocument).filter(
        ProjectDocument.id == body.doc_id,
        ProjectDocument.project_id == project_id,
    ).first()
    if existing:
        existing.document_type = body.document_type
        existing.page_count    = body.page_count
        existing.chunk_count   = body.chunk_count
        db.commit()
        db.refresh(existing)
        return existing
    doc = ProjectDocument(
        id=body.doc_id, project_id=project_id, filename=body.filename,
        document_type=body.document_type, page_count=body.page_count,
        chunk_count=body.chunk_count,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/{project_id}/documents", response_model=List[ProjectDocOut])
def list_project_documents(project_id: str, db: Session = Depends(get_db)):
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(404, "Project not found")
    docs = db.query(ProjectDocument).filter(ProjectDocument.project_id == project_id).all()
    return docs


@router.delete("/{project_id}/documents/{doc_id}")
def remove_document_from_project(project_id: str, doc_id: str, db: Session = Depends(get_db)):
    doc = db.query(ProjectDocument).filter(
        ProjectDocument.id == doc_id,
        ProjectDocument.project_id == project_id,
    ).first()
    if not doc:
        raise HTTPException(404, "Document not in project")
    db.delete(doc)
    db.commit()
    return {"deleted": True}
