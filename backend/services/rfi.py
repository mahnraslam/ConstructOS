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
from models.schemas import RFIItem, RFIResponse, Reference

logger = logging.getLogger(__name__)


def _build_rfi_body(
    field: str,
    blueprint_doc: str, bp_page: int, bp_sheet: str, blueprint_value: str,
    spec_doc: str, sp_page: int, sp_section: str, spec_value: str,
) -> str:
    """
    Generate a professional RFI body deterministically — no LLM, no API calls.
    Produces consistent, readable output from the conflict data alone.
    """
    field_label = field.replace("_", " ").title()
    bp_ref = f"Page {bp_page}" + (f", Sheet {bp_sheet}" if bp_sheet else "")
    sp_ref = f"Page {sp_page}" + (f", {sp_section}" if sp_section else "")

    return (
        f"The construction drawings ({blueprint_doc}, {bp_ref}) indicate "
        f"{field_label} as {blueprint_value}. "
        f"However, the project specification ({spec_doc}, {sp_ref}) requires "
        f"{field_label} to be {spec_value}. "
        f"These two documents are in conflict and cannot both be satisfied as currently issued. "
        f"Please clarify which value governs and issue a revised document or written directive "
        f"so that construction may proceed accordingly."
    )


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
        body = _build_rfi_body(
            field           = conflict.field,
            blueprint_doc   = bp_doc,
            bp_page         = conflict.blueprint_page or 0,
            bp_sheet        = conflict.blueprint_sheet or "",
            blueprint_value = conflict.blueprint_value,
            spec_doc        = sp_doc,
            sp_page         = conflict.spec_page or 0,
            sp_section      = conflict.spec_section or "",
            spec_value      = conflict.spec_value,
        )
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

        # Persist (Bug 3 fix: serialize references to JSON)
        refs_data = [ref.model_dump() for ref in references]
        db.add(RFIRow(
            project_id      = project_id,
            conflict_id     = conflict.id,
            number          = number,
            subject         = subject,
            body            = body,
            priority        = conflict.severity,
            status          = "open",
            references_json = refs_data,
        ))

        rfis.append(RFIItem(number=number, subject=subject, body=body,
                            priority=conflict.severity, references=references))

    db.commit()
    logger.info(f"[rfi] Generated {len(rfis)} RFIs for project {project_id}")
    return rfis


def get_stored_rfis(project_id: str, db: Session) -> list[RFIItem]:
    """Return stored RFIs for a project (Bug 3 fix: restore persisted references)."""
    rows = db.query(RFIRow).filter(RFIRow.project_id == project_id).all()
    result = []
    for r in rows:
        refs = []
        if r.references_json:
            refs = [Reference(**ref_data) for ref_data in r.references_json]
        result.append(RFIItem(
            number=r.number, subject=r.subject, body=r.body,
            priority=r.priority, references=refs,
        ))
    return result