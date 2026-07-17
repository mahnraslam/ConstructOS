# ConstructOS

AI-powered construction document intelligence — upload blueprints and specifications, ask technical questions with cited answers, detect cross-document conflicts, and generate RFI drafts automatically.

---

## Features

- **Document Q&A** — ask questions in plain English; every answer cites the source document and page number
- **Blueprint Viewer** — click any citation to jump directly to the referenced page
- **Vision Enrichment** — drawing-heavy pages are automatically processed through Gemini Vision at ingestion
- **Fact Extraction** — structured construction facts extracted per document (slab thickness, rebar, concrete grade, etc.)
- **Conflict Detection** — blueprint facts compared against specification facts; conflicts classified by severity
- **RFI Generation** — one-click RFI draft for each detected conflict with both conflicting values pre-cited

---

## Prerequisites

- Python 3.11+
- Node.js 18+
- Poppler (for blueprint page rendering)
  - Ubuntu/WSL: `sudo apt install poppler-utils`
  - macOS: `brew install poppler`
  - Windows: download from [oschwartz10612/poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases) and add to PATH
---

## Setup & Run

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and add your key:

```env
GEMINI_API_KEY=your_key_here
```

Start the server:

```bash
uvicorn main:app --reload --port 8000
```

API runs at `http://localhost:8000` — docs at `http://localhost:8000/docs`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:5173`

### Docker (alternative)

```bash
docker-compose up --build
```

---

## Usage

1. Open `http://localhost:5173`
2. Create a new project from the workspace
3. Upload your construction PDFs (blueprints and specification documents)
4. Open the project — five tabs are available:
   - **Chat** — ask technical questions, get cited answers
   - **Blueprint** — view rendered pages; citations jump here automatically
   - **Facts** — structured facts extracted per document
   - **Conflicts** — contradictions detected between blueprint and spec values
   - **RFI** — drafted RFI letters generated from detected conflicts

---
## ERD 
                                ┌──────────────────────────┐
                                │         PROJECT          │
                                ├──────────────────────────┤
                                │ PK project_id : UUID     │
                                │ name                     │
                                │ created_at               │
                                └─────────────┬────────────┘
                                              │ 1
                                              │
                                              │
                                              │ *
                    ┌─────────────────────────▼────────────────────────┐
                    │              PROJECT_DOCUMENT                     │
                    ├───────────────────────────────────────────────────┤
                    │ PK doc_id : UUID                                 │
                    │ FK project_id                                    │
                    │ filename                                         │
                    │ document_type                                    │
                    │ page_count                                       │
                    │ chunk_count                                      │
                    │ status                                           │
                    │ status_detail                                    │
                    │ created_at                                       │
                    │ updated_at                                       │
                    └──────────────┬────────────────────────────────────┘
                                   │
                     ┌─────────────┴─────────────┐
                     │                           │
                     │                           │
                    1│                           │1
                     │                           │
                     │                           │
                    *│                           │*
        ┌────────────▼────────────┐      ┌───────▼─────────────────┐
        │         CHUNK           │      │          FACT           │
        ├─────────────────────────┤      ├─────────────────────────┤
        │ PK chunk_id             │      │ PK id                  │
        │ FK document_id          │      │ FK document_id         │
        │ page                    │      │ FK project_id          │
        │ chunk_text              │      │ category               │
        │ embedding_id            │      │ field                  │
        │ metadata                │      │ value                  │
        └─────────────────────────┘      │ unit                   │
                                         │ page                   │
                                         │ sheet                  │
                                         │ section                │
                                         │ quote                  │
                                         └─────────────┬──────────┘
                                                       │
                                                       │
                                         Used for Conflict Detection
                                                       │
                                                       ▼
                                  ┌──────────────────────────────────┐
                                  │      FACT COMPARISON ENGINE      │
                                  └──────────────────────────────────┘
## Project Structure

```
NLP-Course-Project/
├── .gitignore
├── docker-compose.yml
├── backend/
│   ├── .env
│   ├── .env.example
│   ├── Dockerfile
│   ├── db.py
│   ├── main.py
│   ├── pytest.ini
│   ├── requirements.txt
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── conflicts.py
│   │   ├── documents.py
│   │   ├── facts.py
│   │   ├── projects.py
│   │   ├── query.py
│   │   └── rfi.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── conflict.py
│   │   ├── embedder.py
│   │   ├── fact_extractor.py
│   │   ├── gemini.py
│   │   ├── pdf_parser.py
│   │   ├── rag.py
│   │   ├── rfi.py
│   │   └── vector_store.py
│   ├── storage/
│   │   ├── constructos.db
│   │   ├── chroma_db/
│   │   ├── pages/
│   │   └── uploads/
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py
│       ├── create_test_pdfs.py
│       ├── test_conflicts.py
│       ├── test_documents.py
│       ├── test_query.py
│       └── test_services.py
└── frontend/
    ├── .env.example
    ├── Dockerfile
    ├── index.html
    ├── package-lock.json
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── App.jsx
        ├── main.jsx
        ├── api/
        │   └── client.js
        ├── components/
        │   ├── BlueprintViewer.jsx
        │   ├── ChatPanel.jsx
        │   ├── CitationCard.jsx
        │   ├── ConflictDashboard.jsx
        │   ├── ConflictList.jsx
        │   ├── ErrorBoundary.jsx
        │   ├── FactViewer.jsx
        │   ├── Sidebar.jsx
        │   └── UploadZone.jsx
        └── pages/
            ├── Dashboard.jsx
            ├── ProjectView.jsx
            └── ProjectWorkspace.jsx
```

---

## Environment Variables

| Variable | Default | Required |
|---|---|---|
| `GEMINI_API_KEY` | — | Yes |
| `GEMINI_MODEL` | `gemini-2.0-flash` | No |
| `DB_PATH` | `storage/constructos.db` | No |
| `CHROMA_PATH` | `storage/chroma_db` | No |
| `PAGES_PATH` | `storage/pages` | No |
| `UPLOAD_PATH` | `storage/uploads` | No |

---

## Running Tests

```bash
cd backend
pytest
```

Tests use synthetic PDFs with seeded conflicts and run without a real API key. Tests marked `llm` or `slow` require a valid `GEMINI_API_KEY` and are skipped by default.
 
