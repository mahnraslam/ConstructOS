"""
Document ingestion pipeline.

This module is the single place that coordinates the full ingestion
workflow (parse → embed → store → extract facts) and owns document status
transitions. Routers should call into this module rather than calling
pdf_parser / embedder / vector_store / fact_extractor directly — that keeps
routers thin (validate request, save file, create/update the DB record,
kick off processing, return a response) and keeps orchestration, retries,
and status handling in one testable place.
"""
import logging
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from db import SessionLocal, ProjectDocument
from services.pdf_parser import parse
from services.embedder import embed_and_store
from services.fact_extractor import extract_facts_for_document

logger = logging.getLogger(__name__)

# Status constants
STATUS_PENDING = "pending"
STATUS_PARSING = "parsing"
STATUS_EMBEDDING = "embedding"
STATUS_EXTRACTING_FACTS = "extracting_facts"
STATUS_READY = "ready"
STATUS_FAILED = "failed"


class PipelineError(Exception):
    """Base class for ingestion pipeline failures."""


class DocumentParsingError(PipelineError):
    """PDF parsing raised an exception."""


class EmptyDocumentError(PipelineError):
    """PDF parsed successfully but produced no usable chunks."""


class EmbeddingError(PipelineError):
    """Embedding generation or vector storage failed."""


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
        # Note: updated_at has onupdate=func.now() at the model/DB level
        # (see db.py), so it's refreshed automatically on this commit — no
        # need to set it here. (A previous version of this function tried
        # to set it manually with an unimported `func`, which raised
        # NameError on every single status update.)
        db.commit()
        logger.info(f"[pipeline] doc_id={doc_id} status → {status}" + (f" ({detail})" if detail else ""))
    else:
        logger.warning(f"[pipeline] Document {doc_id} not found when updating status to {status}")


def process_document(
    doc_id: str,
    file_path: str,
    filename: str,
    doc_type: str,
    project_id: str,
) -> None:
    """
    Process a document through the full pipeline: parse, embed, extract facts.
    Designed to run as a FastAPI BackgroundTask — owns its own DB session and
    persists status transitions (including failures) so callers can poll
    GET /{doc_id}/status instead of waiting on this to return.
    """
    # Create a new database session for this background task
    db = SessionLocal()
    try:
        logger.info(f"[pipeline] Starting ingestion for doc_id={doc_id} file={filename}")

        # ── Stage 1: parse ────────────────────────────────────────────────
        _update_document_status(db, doc_id, STATUS_PARSING, "Starting PDF parsing")
        try:
            chunks, page_count = parse(file_path, doc_id)
        except Exception as e:
            logger.error(f"[pipeline] Parsing failed for {doc_id}: {e}")
            _update_document_status(db, doc_id, STATUS_FAILED, f"PDF parsing failed: {e}")
            return

        if not chunks:
            logger.error(f"[pipeline] No readable content found in document {doc_id}")
            _update_document_status(db, doc_id, STATUS_FAILED, "No readable content found in PDF")
            return

        logger.info(f"[pipeline] Parsed doc_id={doc_id}: {page_count} pages, {len(chunks)} chunks")

        doc = db.query(ProjectDocument).filter(ProjectDocument.id == doc_id).first()
        if doc:
            doc.page_count = page_count
            doc.chunk_count = len(chunks)
            db.commit()

        # ── Stage 2: embed + store ────────────────────────────────────────
        _update_document_status(db, doc_id, STATUS_EMBEDDING, "Starting embedding generation")
        try:
            embed_and_store(chunks, doc_id, filename, doc_type)
        except Exception as e:
            logger.error(f"[pipeline] Embedding failed for {doc_id}: {e}")
            _update_document_status(db, doc_id, STATUS_FAILED, f"Embedding failed: {e}")
            return
        logger.info(f"[pipeline] Embedding + vector storage complete for doc_id={doc_id}")

        # ── Stage 3: fact extraction ───────────────────────────────────────
        _update_document_status(db, doc_id, STATUS_EXTRACTING_FACTS, "Starting fact extraction")
        try:
            fact_count = extract_facts_for_document(
                doc_id=doc_id,
                project_id=project_id,
                filename=filename,
                doc_type=doc_type,
                db=db,
            )
            logger.info(f"[pipeline] Extracted {fact_count} facts from document {doc_id}")
        except Exception as e:
            logger.error(f"[pipeline] Fact extraction failed for {doc_id}: {e}")
            _update_document_status(db, doc_id, STATUS_FAILED, f"Fact extraction failed: {e}")
            return

        # ── Done ───────────────────────────────────────────────────────────
        _update_document_status(db, doc_id, STATUS_READY, "Document processing completed")
        logger.info(f"[pipeline] Document {doc_id} processed successfully")

    except Exception as e:
        # Catch any unexpected error so a bug in one stage can't leave the
        # document stuck in an in-progress status forever.
        logger.error(f"[pipeline] Unexpected error processing document {doc_id}: {e}", exc_info=True)
        _update_document_status(db, doc_id, STATUS_FAILED, f"Unexpected error: {str(e)}")
    finally:
        db.close()


def process_document_sync(
    doc_id: str,
    file_path: str,
    filename: str,
    doc_type: str,
    project_id: str = "",
    db: Optional[Session] = None,
) -> dict:
    """
    Process a document synchronously and return a result dict, for callers
    that need an immediate response instead of polling status (this backs
    the router's no-project_id / anonymous upload path).

    Raises DocumentParsingError / EmptyDocumentError on unrecoverable
    failures so the router can translate them into the right HTTP status
    without needing to know anything about parsing or embedding internals.
    Fact extraction failures are non-fatal here (matching prior behavior):
    they're reported back in the result dict rather than raised, since a
    document can still be usable for search/QA even if fact extraction
    failed.
    """
    logger.info(f"[pipeline] Starting synchronous ingestion for doc_id={doc_id} file={filename}")

    # ── Stage 1: parse ────────────────────────────────────────────────────
    try:
        chunks, page_count = parse(file_path, doc_id)
    except Exception as e:
        logger.error(f"[pipeline] Parsing failed for {doc_id}: {e}")
        raise DocumentParsingError(str(e)) from e

    if not chunks:
        logger.error(f"[pipeline] No readable content found in document {doc_id}")
        raise EmptyDocumentError("No readable content found in PDF.")

    logger.info(f"[pipeline] Parsed doc_id={doc_id}: {page_count} pages, {len(chunks)} chunks")

    # ── Stage 2: embed + store ────────────────────────────────────────────
    try:
        embed_and_store(chunks, doc_id, filename, doc_type)
    except Exception as e:
        logger.error(f"[pipeline] Embedding failed for {doc_id}: {e}")
        raise EmbeddingError(str(e)) from e
    logger.info(f"[pipeline] Embedding + vector storage complete for doc_id={doc_id}")

    # ── Stage 3: fact extraction (only when we have a project + DB row) ───
    fact_count = None
    fact_error = None
    if project_id and db is not None:
        _update_document_status(db, doc_id, STATUS_EXTRACTING_FACTS, "Starting fact extraction")
        try:
            fact_count = extract_facts_for_document(
                doc_id=doc_id,
                project_id=project_id,
                filename=filename,
                doc_type=doc_type,
                db=db,
            )
            logger.info(f"[pipeline] Extracted {fact_count} facts from document {doc_id}")
        except Exception as e:
            fact_error = str(e)
            logger.error(f"[pipeline] Fact extraction failed for {doc_id}: {e}")

    return {
        "page_count": page_count,
        "chunk_count": len(chunks),
        "fact_count": fact_count,
        "fact_extraction_error": fact_error,
    }