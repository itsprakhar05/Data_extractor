"""
app/api/routes/query.py
-----------------------
Query endpoint. Streams RAG answer via SSE, scoped to the caller's own docs.
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.pipeline.orchestrator import RagPipeline
from app.core.dependency import get_pipeline
from app.core.security import get_current_user_id

router = APIRouter(prefix="/api/v1", tags=["Query"])
limiter = Limiter(key_func=get_remote_address)


class QueryRequest(BaseModel):
    question: str


@router.post("/query")
@limiter.limit("10/minute")
async def query_knowledge_base(
    request: Request,
    payload: QueryRequest,
    pipeline: RagPipeline = Depends(get_pipeline),      # injected singleton
    user_id: str = Depends(get_current_user_id),        # requires a valid JWT
):
    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    try:
        return StreamingResponse(
            pipeline.query_rag_stream(payload.question, user_id),
            media_type="text/event-stream",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))