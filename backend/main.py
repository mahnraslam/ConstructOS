from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from routers import documents, query, conflicts, rfi
import os

app = FastAPI(title="ConstructOS API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(query.router,     prefix="/api/query",     tags=["query"])
app.include_router(conflicts.router, prefix="/api/conflicts", tags=["conflicts"])
app.include_router(rfi.router,       prefix="/api/rfi",       tags=["rfi"])

os.makedirs("storage/pages", exist_ok=True)
app.mount("/pages", StaticFiles(directory="storage/pages"), name="pages")

@app.get("/")
def health():
    return {"status": "ConstructOS API running"}