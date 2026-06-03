from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models.schemas import (
    ConflictRequest, ConflictResponse,
    AllConflictsRequest, AllConflictsResponse,
    FactConflictResponse,
)
from services.conflict import (
    detect, detect_all_conflicts,
    detect_fact_conflicts, get_stored_conflicts,
)
from db import get_db

router = APIRouter()


@router.post("/detect", response_model=ConflictResponse)
async def detect_conflicts(req: ConflictRequest):
    """Legacy LLM-based conflict detection between two documents."""
    return detect(req.doc_id_a, req.doc_id_b, req.filename_a, req.filename_b)


@router.post("/detect-all", response_model=AllConflictsResponse)
async def detect_all(req: AllConflictsRequest):
    conflicts = detect_all_conflicts(req.doc_ids)
    return AllConflictsResponse(conflicts=conflicts, total=len(conflicts))


@router.post("/project/{project_id}/detect", response_model=FactConflictResponse)
async def detect_project_conflicts(project_id: str, db: Session = Depends(get_db)):
    """
    Deterministic fact-based conflict detection for a project.
    Requires fact extraction to have been run on at least one blueprint and one spec doc.
    """
    return detect_fact_conflicts(project_id, db)


@router.get("/project/{project_id}", response_model=FactConflictResponse)
async def get_project_conflicts(project_id: str, db: Session = Depends(get_db)):
    """Return previously-detected conflicts for a project."""
    return get_stored_conflicts(project_id, db)
