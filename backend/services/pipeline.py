"""
Asynchronous document processing pipeline.
"""
import logging
from typing import Optional
from sqlalchemy.orm import Session
from db import SessionLocal
from services.pdf_parser import parse
from services.embedder import embed_and_store
from services.fact_extractor import extract_facts_for_document
from db import ProjectDocument

logger = logging.getLogger(__name__)

# Status constants
STATUS_PENDING = "pending"
STATUS_PARSING = "parsing"
STATUS_EMBEDDING = "embedding"
STATUS_EXTRACTING_FACTS = "extracting_facts"
STATUS_READY = "ready"
STATUS_FAILED = "failed"


def _update_document_status(
    db: Session,
    doc_id: str,
    status: str,
    detail: Optional[str] = None,
) -> None:
    """Update the status and detail of a document."""
    doc = db.query(ProjectDocument).filter(ProjectDocument.id == doc_id).first()
    if doc:
        doc.status = status
        if detail is not None:
            doc.status_detail = detail
        doc.updated_at = func.now()  # This will be set by the database on update if we use onupdate
        # However, we don't have an updated_at column yet. We'll add it in the model.
        # For now, we'll just commit and let the database handle it if we have the column.
        # We'll need to add the column to the model.
        db.commit()
    else:
        logger.warning(f"Document {doc_id} not found when updating status to {status}")


def process_document(
    doc_id: str,
    file_path: str,
    filename: str,
    doc_type: str,
    project_id: str,
) -> None:
    """
    Process a document through the pipeline: parse, embed, extract facts.
    This function is designed to run in the background.
    """
    # Create a new database session for this background task
    db = SessionLocal()
    try:
        # Update status to parsing
        _update_document_status(db, doc_id, STATUS_PARSING, "Starting PDF parsing")

        # Parse the PDF
        try:
            chunks, page_count = parse(file_path, doc_id)
        except Exception as e:
            logger.error(f"Failed to parse document {doc_id}: {e}")
            _update_document_status(db, doc_id, STATUS_FAILED, f"PDF parsing failed: {e}")
            return

        if not chunks:
            logger.error(f"No readable content found in document {doc_id}")
            _update_document_status(db, doc_id, STATUS_FAILED, "No readable content found in PDF")
            return

        # Update page count in the document record
        doc = db.query(ProjectDocument).filter(ProjectDocument.id == doc_id).first()
        if doc:
            doc.page_count = page_count
            doc.chunk_count = len(chunks)
            db.commit()

        # Update status to embedding
        _update_document_status(db, doc_id, STATUS_EMBEDDING, "Starting embedding generation")

        # Generate embeddings and store in vector database
        try:
            embed_and_store(chunks, doc_id, filename, doc_type)
        except Exception as e:
            logger.error(f"Failed to embed and store document {doc_id}: {e}")
            _update_document_status(db, doc_id, STATUS_FAILED, f"Embedding failed: {e}")
            return

        # Update status to extracting facts
        _update_document_status(db, doc_id, STATUS_EXTRACTING_FACTS, "Starting fact extraction")

        # Extract facts
        try:
            fact_count = extract_facts_for_document(
                doc_id=doc_id,
                project_id=project_id,
                filename=filename,
                doc_type=doc_type,
                db=db,
            )
            logger.info(f"Extracted {fact_count} facts from document {doc_id}")
        except Exception as e:
            logger.error(f"Failed to extract facts from document {doc_id}: {e}")
            _update_document_status(db, doc_id, STATUS_FAILED, f"Fact extraction failed: {e}")
            return

        # Update status to ready
        _update_document_status(db, doc_id, STATUS_READY, "Document processing completed")
        logger.info(f"Document {doc_id} processed successfully")

    except Exception as e:
        # Catch any unexpected error
        logger.error(f"Unexpected error processing document {doc_id}: {e}", exc_info=True)
        _update_document_status(db, doc_id, STATUS_FAILED, f"Unexpected error: {str(e)}")
    finally:
        db.close()