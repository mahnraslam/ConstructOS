import os
import chromadb
from models.schemas import DocumentMeta
from dotenv import load_dotenv

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
load_dotenv(_ENV_PATH, override=True)

_CHROMA_PATH = os.getenv("CHROMA_PATH", "storage/chroma_db")
_client = chromadb.PersistentClient(path=_CHROMA_PATH)
_col    = _client.get_or_create_collection("documents", metadata={"hnsw:space": "cosine"})


def add(chunks: list[dict], embeddings: list[list[float]], doc_id: str, filename: str, doc_type: str = "other"):
    """
    Store chunks in ChromaDB.
    Chunk IDs use index suffix to avoid collision when multiple chunks share a page.
    """
    ids       = [f"{doc_id}_p{c['page']}_c{i}" for i, c in enumerate(chunks)]
    documents = [c["text"] for c in chunks]
    metadatas = [
        {"doc_id": doc_id, "filename": filename, "page": c["page"], "doc_type": doc_type}
        for c in chunks
    ]
    _col.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)


def query(
    embedding: list[float],
    doc_ids: list[str] | None = None,
    n: int = 5,
) -> list[dict]:
    """Retrieve top-n chunks closest to the query embedding."""
    count = _col.count()
    if count == 0:
        return []
    actual_n = min(n, count)
    where = {"doc_id": {"$in": doc_ids}} if doc_ids else None
    results = _col.query(
        query_embeddings=[embedding],
        n_results=actual_n,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    items = []
    for i in range(len(results["documents"][0])):
        meta  = results["metadatas"][0][i]
        dist  = results["distances"][0][i]
        score = max(0.0, round(1.0 - dist, 4))   # cosine similarity
        items.append({
            "text":             results["documents"][0][i],
            "doc_id":           meta["doc_id"],
            "filename":         meta["filename"],
            "page":             meta["page"],
            "doc_type":         meta.get("doc_type", "other"),
            "relevance_score":  score,
        })
    return items


def get_all_by_doc_id(doc_id: str) -> list[dict]:
    """Retrieve ALL chunks for a document deterministically (no semantic search)."""
    results = _col.get(
        where={"doc_id": doc_id},
        include=["documents", "metadatas"],
    )
    if not results["ids"]:
        return []
    items = []
    for i in range(len(results["ids"])):
        meta = results["metadatas"][i]
        items.append({
            "text":     results["documents"][i],
            "doc_id":   meta["doc_id"],
            "filename": meta["filename"],
            "page":     meta["page"],
            "doc_type": meta.get("doc_type", "other"),
        })
    # Sort by page number for consistent processing order
    items.sort(key=lambda x: x["page"])
    return items


def list_documents() -> list[DocumentMeta]:
    """List all unique documents with correct page_count and chunk_count."""
    all_meta = (_col.get(include=["metadatas"])["metadatas"]) or []
    # Aggregate per doc_id
    doc_map: dict[str, dict] = {}
    for m in all_meta:
        did = m["doc_id"]
        if did not in doc_map:
            doc_map[did] = {"filename": m["filename"], "pages": set(), "chunks": 0, "doc_type": m.get("doc_type", "other")}
        doc_map[did]["pages"].add(m["page"])
        doc_map[did]["chunks"] += 1

    return [
        DocumentMeta(
            doc_id      = did,
            filename    = info["filename"],
            page_count  = len(info["pages"]),
            chunk_count = info["chunks"],
            doc_type    = info["doc_type"],
        )
        for did, info in doc_map.items()
    ]


def delete_document(doc_id: str):
    """Delete all chunks belonging to a document."""
    ids = _col.get(where={"doc_id": doc_id})["ids"]
    if ids:
        _col.delete(ids=ids)
        print(f"[vector_store] Deleted {len(ids)} chunks for doc_id={doc_id}")
