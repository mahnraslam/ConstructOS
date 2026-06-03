from fastapi import APIRouter
from models.schemas import QueryRequest, QueryResponse
from services.rag import answer

router = APIRouter()

@router.post("/", response_model=QueryResponse)
async def query(req: QueryRequest):
    return answer(req.question, req.doc_ids, req.project_id, req.top_k, req.visual)

   