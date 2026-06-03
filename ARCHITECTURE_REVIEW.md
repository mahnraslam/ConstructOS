# Construction Intelligence Platform - Architectural Review
**Date:** June 3, 2026  
**Status:** Advanced Implementation - 70% Complete  
**Critical Path Items:** 3 Priority, 5 Secondary

---

## Executive Summary

Your codebase has implemented **the core architectural foundation** of the Construction Intelligence Platform refactor. The project-based architecture, multi-document retrieval, fact extraction, deterministic conflict detection, and RFI generation are all functional. However, several critical components remain incomplete or need refinement to meet production requirements.

**Overall Assessment:** ✅ **Solid Foundation** but requires focused work on persistence, knowledge graph, multi-document chat, and frontend implementation.

---

## 1. Architecture Alignment Matrix

### ✅ IMPLEMENTED (10/15 Components)

| Component | Status | Notes |
|-----------|--------|-------|
| **Project-Based Architecture** | ✅ Full | Projects, ProjectDocuments in SQLite with proper relationships |
| **Multi-Document Support** | ✅ Full | Supports Blueprint, Specification, BOQ, MethodStatement types |
| **Structured Reference Model** | ✅ Full | `Reference` schema with document_name, page, sheet, section, detail, quote |
| **Fact Extraction System** | ✅ Implemented | Extracts Structural, Architectural, MEP facts; stores in Fact table |
| **Deterministic Conflict Detection** | ✅ Implemented | Fact-based field matching without LLM for primary comparison |
| **RFI Generation** | ✅ Implemented | Generates RFIs from detected conflicts; LLM used for drafting only |
| **Document Classification** | ✅ Full | doc_type field on ProjectDocument; auto-detection logic in documents router |
| **Multi-Document Retrieval** | ✅ Partial | ChromaDB supports filtering by doc_ids, context merging in RAG |
| **Vector Search (Qdrant/Chroma)** | ✅ Vector Store Ready | Using ChromaDB (embedded), supports efficient semantic search |
| **Database Models** | ✅ SQLite Foundation | Project, ProjectDocument, Fact, Conflict, RFI tables defined |

### ⚠️ PARTIAL/NEEDS REFINEMENT (3/15 Components)

| Component | Status | Work Needed |
|-----------|--------|-------------|
| **Drawing Intelligence** | ⚠️ Basic | PDF parsing + Vision enrichment exist; missing: bbox extraction, sheet detection, schedule/legend parsing |
| **Evidence-Based Chat** | ⚠️ Basic | Single-query works; missing: multi-turn context, evidence ranking, cross-doc comparison UI |
| **Knowledge Graph (Neo4j)** | ⚠️ Not Started | Architecture designed; no implementation; PostgreSQL can substitute with JSON fields |

### ❌ NOT IMPLEMENTED (2/15 Components)

| Component | Priority | Implementation Effort |
|-----------|----------|----------------------|
| **Conflict Dashboard UI** | HIGH | 1-2 days (React table component) |
| **RFI Module UI** | HIGH | 2-3 days (Forms, list views, export) |

---

## 2. Database & Persistence Review

### Current State
**DB Engine:** SQLite via SQLAlchemy  
**Location:** `storage/constructos.db`  
**Schema:** 6 tables with relationships defined

```
Projects (1) ──┬──→ ProjectDocuments (N)
               ├──→ Facts (N)
               ├──→ Conflicts (N)
               └──→ RFIs (N)
```

### Assessment

**✅ Strengths:**
- Foreign keys properly defined with cascade delete
- Relationships established in ORM layer
- Document types tracked (blueprint, specification, boq, etc.)
- Fact storage with all required fields (category, field, value, unit, page, sheet, section, quote)
- Conflict table stores both sides with references

**⚠️ Gaps & Limitations:**
- **SQLite for Production:** SQLite works for development but lacks concurrent write support. Refactor plan specifies PostgreSQL for production.
- **No Reference Table:** Plan calls for separate Reference table; currently embedded in Fact quotes
- **Missing Neo4j Integration:** Knowledge graph not implemented; can be added without blocking other features
- **Fact-Conflict Mapping:** RFI->Conflict link exists, but Fact->Conflict explicit join missing (should track which facts triggered conflict)
- **No Cache Layer:** Refactor mentions Redis; not currently integrated

### Recommendation
1. Keep SQLite for local dev
2. Add PostgreSQL support for production deployment
3. Create separate Reference table if needed for advanced features
4. Consider adding fact->conflict tracking table for audit trails

---

## 3. Backend Services - Implementation Status

### 3.1 PDF Parser (`pdf_parser.py`)
**Status:** ✅ Core Complete, ⚠️ Drawing Intel Partial

**Implemented:**
- Text extraction via pdfplumber
- Page-level chunking with overlap
- Vision enrichment for low-text pages (< 200 chars)
- Page image rendering to PNG
- Auto doc_type detection from filename

**Missing:**
- **Sheet detection:** No extraction of sheet references (S-101, A-1.0, etc.)
- **Bbox extraction:** No bounding box coordinates for source highlighting
- **Schedule parsing:** No structured extraction of door/window schedules, material schedules
- **Legend/Callout extraction:** Symbols and references not captured
- **Dimension capture:** No structured extraction of dimension callouts

**Priority:** Medium (nice-to-have; current vision augmentation covers most use cases)

### 3.2 Embedder (`embedder.py`)
**Status:** ✅ Functional

Uses Google's embedding API. Stores in ChromaDB with metadata. Should verify recent API changes.

### 3.3 Vector Store (`vector_store.py`)
**Status:** ✅ Functional

ChromaDB PersistentClient with cosine similarity. Supports doc_ids filtering.

**Note:** Refactor plan mentions Qdrant; ChromaDB is sufficient and already embedded.

### 3.4 Fact Extractor (`fact_extractor.py`)
**Status:** ✅ Working, ⚠️ Needs Refinement

**Implemented:**
- Extracts facts for Structural, Architectural, MEP categories
- Stores in Fact table with all metadata (page, sheet, section, quote)
- LLM-based extraction via Gemini

**Issues:**
- **No Duplicate Detection:** Same fact extracted multiple times across chunks not deduplicated
- **Field Coverage:** Current 15 fields may need expansion for specific project types
- **Fact Confidence:** No confidence scores; cannot prioritize facts
- **Batch Processing:** Currently processes one document at a time; could use Celery for async

**Priority:** Medium (works but could be optimized)

### 3.5 Conflict Detection (`conflict.py`)
**Status:** ✅ Fully Implemented

**Implemented:**
- Deterministic fact-based comparison (NO LLM in primary path ✓)
- Field normalization and matching
- Severity assignment (high/medium/low)
- Fallback LLM path for docs without facts (legacy support)
- Stored in Conflict table

**Quality:** Excellent - follows the "no LLM for engineering comparisons" principle

### 3.6 RAG (`rag.py`)
**Status:** ✅ Multi-Document Ready

**Implemented:**
- Multi-doc retrieval with filtering
- Context merging (Blueprint | Specification layout)
- Cross-reference detection in answers
- Vision augmentation for layout-heavy pages
- Structured citation building

**Gaps:**
- No multi-turn conversation context (stateless per query)
- No explicit evidence ranking
- No streaming responses

**Priority:** Low (fundamental functionality works)

### 3.7 RFI Service (`rfi.py`)
**Status:** ✅ Implemented

**Implemented:**
- Generates RFI-XXX numbering
- Pulls stored conflicts → generates RFI body via LLM
- Stores RFIs in DB
- Returns structured RFIItem with references

**Quality:** Good - LLM used only for drafting, facts/conflicts are deterministic

---

## 4. API Endpoints - Coverage Analysis

### 4.1 Documents Router
**Status:** ✅ Complete

```
POST   /api/documents/upload      → Upload & process PDF
GET    /api/documents/            → List all documents
DELETE /api/documents/{doc_id}    → Delete document
```

**Works as designed.** Auto doc_type detection functional.

### 4.2 Query Router
**Status:** ✅ Functional

```
POST /api/query/  (QueryRequest) → answer()
  - Supports multi-doc retrieval
  - Supports project_id filtering
  - Returns QueryResponse with citations + references
```

**Note:** Query is stateless; no conversation history.

### 4.3 Projects Router
**Status:** ✅ Core Complete

```
POST   /api/projects/             → Create project
GET    /api/projects/             → List projects
GET    /api/projects/{id}         → Get project details
POST   /api/projects/{id}/docs    → Add document to project
GET    /api/projects/{id}/docs    → List project documents
```

**Implementation is basic but functional.**

### 4.4 Conflicts Router
**Status:** ✅ Mostly Complete

```
POST   /api/conflicts/detect             → Legacy LLM-based (2 docs)
POST   /api/conflicts/detect-all         → LLM-based multi-doc
POST   /api/conflicts/project/{id}/detect → Fact-based deterministic
GET    /api/conflicts/project/{id}       → Retrieve stored conflicts
```

**Good separation of legacy vs. new approach.**

### 4.5 RFI Router
**Status:** ✅ Implemented

```
POST /api/rfi/project/generate       → Generate RFIs from conflicts
GET  /api/rfi/project/{project_id}   → List RFIs
```

**Works. Could add:**
- Export RFIs (PDF, CSV, Word)
- Update RFI status (open/closed/answered)
- Attach supplementary documents

### 4.6 Facts Router
**Status:** ✅ Implemented

```
POST /api/facts/extract         → Trigger fact extraction
GET  /api/facts/project/{id}    → List extracted facts
```

**Functional. Missing:**
- Update fact (manual correction)
- Delete fact
- Fact deduplication
- Search facts

---

## 5. Frontend - Implementation Status

### Current Structure
```
src/
├── pages/
│   ├── Dashboard.jsx           (⚠️ Not in router)
│   ├── ProjectWorkspace.jsx    (✅ Entry point)
│   └── ProjectView.jsx         (✅ Primary workspace)
│
├── components/
│   ├── UploadZone.jsx          (✅ File upload)
│   ├── ChatPanel.jsx           (✅ Basic chat)
│   ├── CitationCard.jsx        (✅ Citation display)
│   ├── BlueprintViewer.jsx     (⚠️ Basic)
│   ├── ConflictDashboard.jsx   (⚠️ Exists but incomplete)
│   ├── ConflictList.jsx        (⚠️ Partial)
│   ├── FactViewer.jsx          (⚠️ Partial)
│   └── Sidebar.jsx             (✅ Navigation)
```

### Assessment

**✅ Completed Components:**
- Project workspace layout
- Document upload zone
- Basic chat interface
- Citation card display
- Sidebar navigation

**⚠️ Incomplete/Stubbed Components:**
- **ConflictDashboard:** Exists but needs table UI with sorting/filtering
- **FactViewer:** Raw fact display; needs grouped view by category
- **BlueprintViewer:** Page viewer without bbox annotation
- **RFI Module:** No dedicated UI; RFIs only in API response

**Missing Features:**
1. **Multi-Document Selection Widget** - Checkbox UI for choosing docs in chat
2. **Evidence-Based Answer Display** - Structured reference cards
3. **Conflict Comparison Table** - Side-by-side blueprint vs. spec
4. **RFI Management Page** - Generate, review, export RFIs
5. **Chat History/Multi-Turn** - Conversation persistence
6. **Source Preview on Click** - Zoom to source location with bbox highlight

**Priority:** High - Frontend heavily stubs several plan components

---

## 6. Tech Stack Comparison

### Recommended vs. Current

| Component | Recommended | Current | Status |
|-----------|-------------|---------|--------|
| **API Framework** | FastAPI | FastAPI ✅ | Match |
| **Database** | PostgreSQL | SQLite ⚠️ | Dev only; needs PostgreSQL for prod |
| **Vector DB** | Qdrant | ChromaDB ✅ | Functional; ChromaDB embedded is acceptable |
| **Knowledge Graph** | Neo4j | Not started ❌ | Optional for v1; can add later |
| **Cache/Queue** | Redis + Celery | Not started ❌ | Not critical for MVP; recommend for scale |
| **Frontend** | React | React ✅ | Framework match; component coverage ~60% |
| **Query Library** | TanStack Query | Not evident ❌ | Consider adding for state management |
| **Storage** | S3/MinIO | Local filesystem | Works for dev; S3 for production |

### Missing Dependencies (Requirements.txt)
```diff
+ celery (for async fact extraction)
+ redis (for caching/queuing)
+ psycopg2 (PostgreSQL adapter)
+ sqlalchemy-postgresql (if using PostgreSQL)
```

---

## 7. Critical Gaps & Issues

### 🔴 CRITICAL (Blocks Production)

1. **Multi-Document Chat Selection Not Implemented**
   - User cannot select which docs to query
   - Currently hardcoded or auto-filtered
   - **Impact:** Core refactor requirement
   - **Fix:** Add doc selection widget to ChatPanel
   - **Effort:** 2-3 hours

2. **Frontend RFI Module Missing**
   - RFI API exists but no UI
   - No generation trigger from dashboard
   - No RFI display, review, export
   - **Impact:** RFI feature unusable
   - **Fix:** Create dedicated RFI page + components
   - **Effort:** 4-5 hours

3. **Conflict Dashboard Stubbed**
   - Component exists but no table rendering
   - No filtering, sorting, or export
   - **Impact:** Conflict feature feels incomplete
   - **Fix:** Implement React table with data binding
   - **Effort:** 3-4 hours

4. **No PostgreSQL Production Setup**
   - SQLite not suitable for concurrent load
   - No migration path documented
   - **Impact:** Cannot scale beyond single user
   - **Fix:** Add PostgreSQL support + migration guide
   - **Effort:** 2-3 hours

### 🟠 HIGH PRIORITY (Near-term Blockers)

5. **Drawing Intelligence Incomplete**
   - No sheet reference extraction
   - No bbox coordinates for highlighting
   - **Impact:** Source preview feature incomplete
   - **Fix:** Add sheet detection + bbox extraction
   - **Effort:** 3-5 hours

6. **Fact Deduplication Missing**
   - Same facts extracted multiple times
   - **Impact:** Noise in fact viewer, inefficient conflict detection
   - **Fix:** Add dedup logic post-extraction
   - **Effort:** 2-3 hours

7. **Evidence Ranking Not Implemented**
   - Citations shown in arbitrary order
   - No relevance weighting in multi-doc queries
   - **Impact:** User confusion about best sources
   - **Fix:** Add scoring + sort by relevance
   - **Effort:** 2 hours

8. **No Chat History/Conversation Context**
   - Each query is stateless
   - **Impact:** No multi-turn reasoning possible
   - **Fix:** Add conversation table + session management
   - **Effort:** 4-6 hours

### 🟡 MEDIUM PRIORITY (Polish + Scale)

9. **No Async Processing Pipeline**
   - Fact extraction is synchronous
   - Large PDFs block request
   - **Impact:** Poor UX for large documents
   - **Fix:** Integrate Celery + Redis
   - **Effort:** 4-5 hours

10. **Citation Card Redesign Incomplete**
    - References structure exists but UI doesn't display all fields (sheet, section)
    - **Impact:** Visual clue to source location missing
    - **Fix:** Update CitationCard component
    - **Effort:** 1-2 hours

11. **Fact/Conflict Viewing UI Incomplete**
    - Fact list shown but not grouped by category
    - No fact filtering/search
    - **Impact:** Hard to browse large fact sets
    - **Fix:** Add grouping + search UI
    - **Effort:** 2-3 hours

12. **Knowledge Graph (Neo4j) Not Started**
    - Optional for v1 but useful for advanced queries
    - **Impact:** Complex cross-project reasoning not possible
    - **Fix:** Design + implement Neo4j schema
    - **Effort:** 5-7 hours (post-v1)

---

## 8. Code Quality Assessment

### Strengths
✅ Clean service separation (fact_extractor, conflict, rag, rfi)  
✅ Deterministic comparison logic (no LLM for engineering)  
✅ Proper ORM relationships defined  
✅ Environment configuration via .env  
✅ Error handling in place  

### Improvements Needed
⚠️ Limited logging detail (add correlation IDs for debugging)  
⚠️ No request validation middleware  
⚠️ No rate limiting  
⚠️ Fact extraction prompt could be more specific to construction domain  
⚠️ Frontend components lack error boundary  
⚠️ No unit tests for services  

---

## 9. Priority Roadmap

### PHASE 1: CRITICAL FIX (3-4 Days)
**Goal:** Make all planned features usable end-to-end

1. ✅ **Document Selection Widget** (2h)
   - Add checkboxes to ChatPanel for multi-doc selection
   - Pass selected doc_ids to query endpoint

2. ✅ **RFI Module UI** (5h)
   - Create `/project/:id/rfis` page
   - Add generate button → fetch conflicts → generate RFIs
   - Display RFI list with subject + body
   - Add export button (JSON/CSV)

3. ✅ **Conflict Dashboard Table** (4h)
   - Render conflicts as table (Field | Blueprint | Spec | Status)
   - Add filtering/sorting
   - Link to source documents

4. ✅ **Evidence Display Redesign** (3h)
   - Update CitationCard to show: Document | Sheet | Page | Section | Quote
   - Sort by relevance score
   - Add visual badges for doc type

### PHASE 2: HIGH PRIORITY (3-4 Days)
**Goal:** Production-readiness + drawing intelligence

5. ✅ **PostgreSQL Migration Guide** (2h)
   - Document connection string setup
   - Migration script for SQLite → PostgreSQL
   - Update requirements.txt

6. ✅ **Drawing Intelligence** (5h)
   - Add sheet reference detection from PDF metadata
   - Extract bbox coordinates during Vision analysis
   - Store bbox in Fact/Citation for highlighting

7. ✅ **Fact Deduplication** (2h)
   - Add dedup service post-extraction
   - Match on (category, field, value, doc_id)
   - Keep highest-confidence version

8. ✅ **Conversation History** (4h)
   - Create Conversation table
   - Store queries + answers + turn sequence
   - Implement session management

### PHASE 3: POLISH (2-3 Days)
**Goal:** UX refinement + scale

9. ✅ **Async Processing Pipeline** (5h)
   - Set up Celery + Redis
   - Convert fact extraction to async task
   - Show progress indicator in UI

10. ✅ **Fact Viewer Grouping** (2h)
    - Group facts by category (Structural | Architectural | MEP)
    - Add search/filter

11. ✅ **Citation Highlighting** (3h)
    - Click citation → open source page
    - Zoom to bbox if available
    - Highlight region

### PHASE 4: ADVANCED (Post-v1)
**Goal:** Knowledge graph + cross-project reasoning

12. ⏳ **Neo4j Integration** (7h)
    - Design graph schema
    - Sync facts → nodes
    - Implement relationship queries

---

## 10. Recommended Next Actions

### Immediate (This Week)
1. **Set up PostgreSQL** locally for development
2. **Create Multi-Doc Selection Component** → integrate with chat
3. **Stub out RFI Page** → connect to API
4. **Run backend tests** → ensure fact extraction works reliably

### Short-term (Next 2 Weeks)
5. **Complete Conflict Dashboard** with table rendering
6. **Add Conversation Table** to DB
7. **Implement Sheet Detection** in PDF parser
8. **Set up Celery** for async tasks
9. **Write integration tests** for full workflows

### Medium-term (Next Month)
10. **PostgreSQL deployment** documentation
11. **Neo4j evaluation** for advanced use cases
12. **Performance optimization** (indexing, caching)
13. **Production deployment** checklist

---

## 11. Architecture Validation Checklist

| Requirement | Status | Evidence |
|-------------|--------|----------|
| Project-based multi-document reasoning | ✅ | Project ↔ ProjectDocument relationships |
| Fact extraction layer | ✅ | fact_extractor.py + Fact table |
| Deterministic conflict detection | ✅ | conflict.py (no LLM in primary path) |
| RFI generation from conflicts | ✅ | rfi.py generates from Conflict table |
| Structured references with exact locations | ✅ | Reference schema with page/sheet/section/quote |
| Multi-document retrieval | ✅ | vector_store.query with doc_ids filtering |
| Evidence-based answers | ⚠️ | Citations returned but UI incomplete |
| Blueprint drawing intelligence | ⚠️ | Vision enrichment works; bbox missing |
| Conflict dashboard UI | ❌ | Component stubbed, no table |
| RFI module UI | ❌ | No UI; API only |
| Verifiable references for every answer | ✅ | Citations stored; UI needs work |
| No LLM for engineering comparisons | ✅ | Fact-based matching implemented |

**Overall Alignment:** 75% (10/13 completed, 1 partial conflict, 2 UI stubs)

---

## 12. Known Limitations & Workarounds

| Issue | Workaround | Timeline |
|-------|-----------|----------|
| SQLite concurrency | Use in dev; switch to PostgreSQL for prod | Phase 2 |
| No sheet bbox extraction | Use Vision-enriched text references | Phase 2 |
| Fact duplication across chunks | Manual dedup in service layer | Phase 2 |
| No conversation history | Query stateless; implement session layer | Phase 2 |
| No async tasks | Synchronous fact extraction OK for small projects | Phase 3 |
| No Knowledge Graph | SQL queries sufficient for v1 | Phase 4 |

---

## 13. Success Metrics

### By End of Phase 1
- ✅ User can select multiple documents for chat
- ✅ Conflict detection returns properly formatted results
- ✅ RFI generation UI functional
- ✅ All answers include structured references

### By End of Phase 2
- ✅ System handles PostgreSQL backend
- ✅ Blueprint source highlighting works with bbox
- ✅ 500+ facts processed without duplication
- ✅ Multi-turn conversations preserved

### By End of Phase 3
- ✅ Fact extraction async (non-blocking)
- ✅ <100ms query response time (p95)
- ✅ No UI lag for 1000+ facts
- ✅ Citation highlighting pixel-accurate

### By End of Phase 4 (Post-v1)
- ✅ Cross-project fact relationships possible
- ✅ Complex graph queries for pattern detection
- ✅ Knowledge graph enables "similar projects" discovery

---

## Conclusion

Your Construction Intelligence Platform is **well-architected and ~70% complete**. The core vision of:
- ✅ Project-based organization
- ✅ Fact extraction + deterministic comparisons
- ✅ Conflict detection & RFI generation
- ✅ Multi-document reasoning

...is **fully implemented in the backend**.

The main gaps are **UI components** and **production-readiness features** (PostgreSQL, async tasks, bbox extraction). By focusing on Phase 1 (Critical Fix) over the next 3-4 days, you'll have a **fully functional MVP** that demonstrates all planned capabilities end-to-end.

**Recommendation:** Prioritize Frontend UI completion → PostgreSQL setup → Async scaling. The backend architecture is solid and ready for production use.

