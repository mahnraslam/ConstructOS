"""
RFI Generation Service
-----------------------
Generates RFIs from detected fact-level conflicts stored in the DB.
LLM is used only to draft the RFI body — the conflict data (field, values,
references) is deterministic and comes from the conflict detection step.
"""
import logging
from sqlalchemy.orm import Session
from db import Conflict, ProjectDocument, RFI as RFIRow
from services.gemini import generate
from models.schemas import RFIItem, RFIResponse, Reference

logger = logging.getLogger(__name__)

_RFI_PROMPT = """You are a construction RFI drafter. Write a professional Request for Information.

Conflict:
- Field: {field}
- Blueprint ({blueprint_doc}, Page {bp_page}{bp_sheet}): {blueprint_value}
- Specification ({spec_doc}, Page {sp_page}{sp_section}): {spec_value}

Write a concise RFI body (3–5 sentences):
1. State what the blueprint shows
2. State what the specification requires
3. Ask for clarification on which value is correct
4. Optionally suggest a resolution

Be professional and precise. Do not add a subject line or RFI number — just the body text."""


def generate_project_rfis(project_id: str, db: Session) -> list[RFIItem]:
    """
    Generate RFIs for all stored conflicts in a project.
    Persists RFIs to DB and returns them.
    """
    conflicts = db.query(Conflict).filter(Conflict.project_id == project_id).all()
    if not conflicts:
        logger.info(f"[rfi] No conflicts found for project {project_id}")
        return []

    # Build filename lookup
    doc_names: dict[str, str] = {}
    for c in conflicts:
        for did in [c.blueprint_doc_id, c.spec_doc_id]:
            if did and did not in doc_names:
                pd = db.query(ProjectDocument).filter(ProjectDocument.id == did).first()
                doc_names[did] = pd.filename if pd else did

    # Remove previous RFIs for this project
    db.query(RFIRow).filter(RFIRow.project_id == project_id).delete()
    db.commit()

    rfis: list[RFIItem] = []
    for i, conflict in enumerate(conflicts, 1):
        bp_doc  = doc_names.get(conflict.blueprint_doc_id or "", "Blueprint")
        sp_doc  = doc_names.get(conflict.spec_doc_id or "", "Specification")
        bp_sheet  = f", Sheet {conflict.blueprint_sheet}" if conflict.blueprint_sheet else ""
        sp_section = f", {conflict.spec_section}" if conflict.spec_section else ""

        prompt = _RFI_PROMPT.format(
            field           = conflict.field.replace("_", " ").title(),
            blueprint_doc   = bp_doc,
            bp_page         = conflict.blueprint_page,
            bp_sheet        = bp_sheet,
            blueprint_value = conflict.blueprint_value,
            spec_doc        = sp_doc,
            sp_page         = conflict.spec_page,
            sp_section      = sp_section,
            spec_value      = conflict.spec_value,
        )

        body = generate(prompt)
        number = f"RFI-{i:03d}"
        subject = f"{conflict.field.replace('_', ' ').title()} Discrepancy"

        references = []
        if conflict.blueprint_doc_id:
            references.append(Reference(
                document_name = bp_doc,
                document_type = "blueprint",
                page          = conflict.blueprint_page,
                sheet         = conflict.blueprint_sheet or "",
                quote         = conflict.blueprint_value,
            ))
        if conflict.spec_doc_id:
            references.append(Reference(
                document_name = sp_doc,
                document_type = "specification",
                page          = conflict.spec_page,
                section       = conflict.spec_section or "",
                quote         = conflict.spec_value,
            ))

        # Persist
        db.add(RFIRow(
            project_id  = project_id,
            conflict_id = conflict.id,
            number      = number,
            subject     = subject,
            body        = body,
            priority    = conflict.severity,
            status      = "open",
        ))

        rfis.append(RFIItem(number=number, subject=subject, body=body,
                            priority=conflict.severity, references=references))

    db.commit()
    logger.info(f"[rfi] Generated {len(rfis)} RFIs for project {project_id}")
    return rfis


def get_stored_rfis(project_id: str, db: Session) -> list[RFIItem]:
    """Return stored RFIs for a project."""
    rows = db.query(RFIRow).filter(RFIRow.project_id == project_id).all()
    return [
        RFIItem(number=r.number, subject=r.subject, body=r.body,
                priority=r.priority, references=[])
        for r in rows
    ]
