from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List
from db import get_db
from services.rfi import generate_project_rfis, get_stored_rfis
from models.schemas import RFIItem

router = APIRouter()


class GenerateRequest(BaseModel):
    project_id: str


class RFIListResponse(BaseModel):
    project_id: str
    rfis: List[RFIItem]
    total: int


@router.post("/project/generate", response_model=RFIListResponse)
def generate_rfis(body: GenerateRequest, db: Session = Depends(get_db)):
    """
    Generate RFIs from previously-detected fact conflicts for a project.
    Run /conflicts/project/{id}/detect first to populate conflicts.
    """
    rfis = generate_project_rfis(body.project_id, db)
    return RFIListResponse(project_id=body.project_id, rfis=rfis, total=len(rfis))


@router.get("/project/{project_id}", response_model=RFIListResponse)
def get_rfis(project_id: str, db: Session = Depends(get_db)):
    """Return stored RFIs for a project."""
    rfis = get_stored_rfis(project_id, db)
    return RFIListResponse(project_id=project_id, rfis=rfis, total=len(rfis))
