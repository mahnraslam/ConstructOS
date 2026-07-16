 ## Context

The current document ingestion pipeline is **synchronous**.

The `POST /api/documents/upload` endpoint currently performs:

```
Save uploaded file
↓
Parse PDF
↓
Vision analysis
↓
Chunk text
↓
Generate embeddings
↓
Store vectors
↓
Extract facts
↓
Store facts
↓
Return HTTP response
```

This causes uploads to take a long time, blocks the request, and prevents the frontend from tracking progress.

I want to refactor this architecture without changing the existing parsing, embedding, or fact extraction logic.

---

# Goal

Implement an asynchronous ingestion workflow.

The upload endpoint should only:

1. Save uploaded file
2. Create ProjectDocument database record
3. Set status = pending
4. Start a background processing task
5. Return HTTP 202 immediately

Heavy processing must run in a separate pipeline.

---

# Required Changes

## 1. Create a new file

Create

```
backend/app/services/pipeline.py
```

This file should contain a single orchestration function:

```
process_document(...)
```

Its responsibility is ONLY orchestration.

It should NOT duplicate parser or embedding code.

Instead it should call the existing services.

Workflow:

```
set_status(PARSING)

↓

parse()

↓

set_status(EMBEDDING)

↓

embed_and_store()

↓

set_status(EXTRACTING_FACTS)

↓

extract_facts()

↓

set_status(READY)
```

If any exception occurs:

```
status = FAILED
status_detail = error message
```

---

## 2. Modify upload endpoint

Locate

```
backend/app/routers/documents.py
```

Refactor

```
POST /upload
```

Current behavior:

```
save

↓

parse

↓

embed

↓

extract

↓

return
```

Replace with:

```
save file

↓

create ProjectDocument

↓

status = pending

↓

BackgroundTasks.add_task(
    process_document(...)
)

↓

return HTTP 202
```

The upload endpoint must NOT call parser, embedding or fact extraction directly anymore.

---

## 3. Database Schema

Locate the SQLAlchemy model

```
ProjectDocument
```

Add:

```
status

status_detail

updated_at
```

Status values:

```
pending

parsing

embedding

extracting_facts

ready

failed
```

Prefer using an Enum or constants rather than hardcoded strings.

---

## 4. Status Endpoint

Create

```
GET /documents/{doc_id}/status
```

Return

```json
{
  "doc_id": "...",
  "status": "...",
  "detail": "..."
}
```

The frontend will poll this endpoint.

---

## 5. Reuse Existing Logic

Do NOT rewrite:

* PDF parser
* Vision analysis
* Chunking
* Embedding
* Fact extraction
* Vector storage

Simply call the existing functions from `pipeline.py`.

---

## 6. Error Handling

Whenever a stage begins:

```
update status
commit
```

Whenever a stage finishes:

```
update status
commit
```

On exception:

```
status = failed
status_detail = str(exception)
commit
```

Always close database sessions properly.

---

## 7. Maintain Existing Functionality

The following functionality must remain unchanged:

* PDF parsing
* Chunk generation
* Embedding quality
* Fact extraction logic
* Chroma storage
* Existing APIs (except upload behavior)

Only the workflow should change.

---

## 8. Deliverables

Produce:

1. New `pipeline.py`
2. Updated `documents.py`
3. Updated `ProjectDocument` model
4. Required database migration (Alembic or equivalent)
5. New status endpoint
6. List of imports changed
7. Explanation of every change made

Do not introduce unnecessary architectural changes or new frameworks. Use FastAPI's built-in `BackgroundTasks` for now. Keep the implementation clean, modular, and consistent with the existing codebase.
