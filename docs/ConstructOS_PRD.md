# ConstructOS — Product Requirements Document (v2)

**Status:** Draft for corrective release
**Owner:** Engineering
**Related doc:** ConstructOS_TDD.md (technical design for the fixes referenced here)

---

## 1. Overview

ConstructOS is an AI-powered document intelligence system for construction projects. It ingests blueprints and specification PDFs, makes them searchable in natural language with page-level citations, automatically detects contradictions between drawings and specs, and drafts RFI (Request for Information) letters for any conflict found.

This revision (v2) keeps the product scope from the current build but corrects the requirements that the current implementation silently violates — mainly around **ingestion not blocking the app**, **predictable per-document cost**, and **the shipped explainer matching shipped behavior**.

## 2. Problem Statement

Construction teams work from documents written by different parties at different times (architects, structural engineers, spec writers). Blueprints and specifications routinely disagree — a slab shown as 200mm on a drawing and specified as 150mm in the spec book — and these mismatches are usually caught late, on site, at real cost. Manually cross-checking hundred-page PDFs for this is slow and error-prone.

## 3. Goals

| ID | Goal |
|----|------|
| G1 | Ingest blueprint + specification PDFs, including scanned/drawing-heavy pages |
| G2 | Answer natural-language technical questions with exact values and page citations |
| G3 | Automatically detect blueprint-vs-spec contradictions with severity ratings |
| G4 | Generate a ready-to-send RFI letter for any detected conflict |
| G5 | **(new)** Uploading or processing one document must never degrade the app for other users or other in-flight requests |
| G6 | **(new)** Per-document processing cost (LLM calls) must be bounded and predictable, not proportional to `pages × categories` |
| G7 | **(new)** User-facing documentation/explainers must reflect actual system behavior — no undocumented fallback providers, no described-but-unbuilt features |

## 4. Non-Goals (v2)

- No support for non-PDF formats (CAD/DWG native files, images-only workflows)
- No multi-user auth/permissions model (single-tenant per deployment assumed)
- No real-time collaborative editing of RFIs
- No BIM/3D model ingestion

## 5. Users & Personas

- **Project/Site Engineer** — asks technical questions while on site, needs the exact number and its source fast.
- **QA/Compliance reviewer** — reviews the Conflict Dashboard, decides severity and whether to raise an RFI.
- **PM/Coordinator** — sends the generated RFI to the contractor or design team.

## 6. Functional Requirements (by pipeline stage)

### 6.1 Upload & Ingestion
- FR1.1: User uploads a PDF (blueprint or spec) to a project.
- FR1.2: System accepts the upload and **returns immediately** with a document ID and status `pending` — it does not make the user (or any other user) wait for parsing/embedding/fact-extraction to finish. *(corrects current blocking behavior)*
- FR1.3: User can see per-document processing status (`pending → parsing → embedding → extracting_facts → ready`, or `failed` with a reason).
- FR1.4: Re-uploading a file already in the project replaces the old version and its derived data (vectors, facts, images).

### 6.2 Parsing
- FR2.1: Every page is classified as text or drawing content.
- FR2.2: Drawing-heavy pages are rendered to images and enriched via vision extraction.
- FR2.3: Every page gets exactly one rendered image, regardless of whether it went through vision enrichment. *(corrects duplicate rendering)*

### 6.3 Search & Q&A
- FR3.1: User asks a question scoped to selected documents or a whole project.
- FR3.2: The system retrieves the most relevant chunks and answers **only** from that context, citing document + page for every value.
- FR3.3: If the answer isn't in the documents, the system says so explicitly rather than guessing.
- FR3.4: When both a blueprint and a spec are relevant, the answer states both values and flags agreement/disagreement.

### 6.4 Fact Extraction
- FR4.1: Structural, architectural, and MEP facts are extracted from every document automatically after ingestion.
- FR4.2: Extraction produces at most one LLM call per chunk (not one per category per chunk). *(corrects 3x call amplification)*
- FR4.3: Duplicate facts (same field + normalized value) are collapsed, keeping the earliest page reference.

### 6.5 Conflict Detection
- FR5.1: Facts are compared deterministically (no LLM) across blueprint vs spec documents in a project.
- FR5.2: Each conflict records both values, both sources (doc/page/sheet/section), and a severity.

### 6.6 RFI Generation
- FR6.1: User can generate a formal RFI letter from any detected conflict with one action.
- FR6.2: Generated RFIs persist and are retrievable per project.

## 7. Non-Functional Requirements

| Category | Requirement |
|---|---|
| **Latency (upload)** | Upload HTTP response returns in < 2s regardless of document size (work happens in the background) |
| **Latency (chat)** | P95 answer latency < 8s for a 5-chunk context on the configured primary provider |
| **Throughput/isolation** | A document processing in the background must not increase response time for concurrent `/query`, `/conflicts`, or other `/documents` requests by more than a small, bounded margin |
| **Cost** | LLM calls for fact extraction scale as O(chunks), not O(chunks × categories); embedding calls are batched, not one-per-chunk |
| **Reliability** | Transient provider errors (429/503) are retried with backoff; permanent failures mark the document `failed` with a visible reason, never fail silently |
| **Config correctness** | Every environment variable referenced in code appears in `.env.example` with the same name |
| **Security** | CORS restricted to known frontend origin(s) in any non-local deployment; file type/size validated on upload |
| **Documentation accuracy** | Any architecture explainer shipped to users/stakeholders reflects the current implementation, or is explicitly labeled as a future-state design |

## 8. Success Metrics

- **Time-to-ready**: median time from upload to `ready` status for a 50-page mixed document
- **Zero cross-blocking**: load test shows `/query` latency unaffected (within agreed margin) while a large upload is processing
- **Cost per document**: LLM calls per document tracked and reduced (target: ≥60% reduction vs current fact-extraction call count)
- **Conflict detection accuracy**: spot-checked precision/recall on a labeled test set of known blueprint/spec mismatches
- **Config drift**: zero env vars referenced in code but missing from `.env.example` (checked in CI)

## 9. Release Plan

1. **v2.1 — Correctness pass**: fix env/config mismatches, add missing `groq` dependency, correct/label the pipeline explainer. Low risk, no architecture change.
2. **v2.2 — Efficiency pass**: single-pass PDF rendering, true batch embeddings, merged fact-extraction prompt. Isolated, independently testable.
3. **v2.3 — Async ingestion**: background job model + status polling + frontend status UI. Highest impact, highest effort.
4. **v3 (future)**: durable job queue (Redis/RQ or Celery), Postgres migration if concurrent load requires it, real token-level streaming for chat.

## 10. Open Questions / Risks

- Do we need durable job persistence (survive server restart mid-processing) at current scale, or is in-process `BackgroundTasks` sufficient for v2.3?
- Merging fact-extraction categories into one prompt may reduce per-category prompt specificity — needs a quality spot-check before rollout.
- SQLite is acceptable for MVP single-instance deployment; revisit if concurrent multi-project usage grows.
