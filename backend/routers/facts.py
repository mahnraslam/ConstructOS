from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List
from db import get_db, ProjectDocument
from services.fact_extractor import extract_facts_for_document, get_facts_for_project
from models.schemas import FactOut

router = APIRouter()


class ExtractRequest(BaseModel):
    project_id: str
    doc_id: str


@router.post("/extract")
def extract_facts(body: ExtractRequest, db: Session = Depends(get_db)):
    """Trigger fact extraction for a document in a project."""
    pd = db.query(ProjectDocument).filter(
        ProjectDocument.id == body.doc_id,
        ProjectDocument.project_id == body.project_id,
    ).first()
    if not pd:
        raise HTTPException(404, "Document not found in project")
    count = extract_facts_for_document(
        doc_id     = body.doc_id,
        project_id = body.project_id,
        filename   = pd.filename,
        doc_type   = pd.document_type,
        db         = db,
    )
    return {"extracted": count}


@router.get("/project/{project_id}")
def list_project_facts(project_id: str, db: Session = Depends(get_db)):
    """List all extracted facts for a project."""
    return get_facts_for_project(project_id, db)
