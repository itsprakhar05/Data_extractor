# """
# app/api/routes/query.py
# -----------------------
# Query endpoint. Streams RAG answer via SSE.
# Logging to DB happens inside pipeline.query_rag_stream().
# """

# from fastapi import APIRouter, HTTPException
# from fastapi.responses import StreamingResponse
# from pydantic import BaseModel

# from slowapi import Limiter
# from slowapi.util import get_remote_address
# from fastapi import Request

# from app.pipeline.orchestrator import RagPipeline
# limiter = Limiter(key_func=get_remote_address)


# router = APIRouter(prefix="/api/v1", tags=["Query"])


# class QueryRequest(BaseModel):
#     question: str


# @router.post("/query")
# @limiter.limit("10/minute")
# async def query_knowledge_base(payload: QueryRequest):
#     if not payload.question.strip():
#         raise HTTPException(status_code=400, detail="Question cannot be empty.")
#     try:
#         return StreamingResponse(
#             RagPipeline.query_rag_stream(payload.question),
#             media_type="text/event-stream",
#         )
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))



"""
app/api/routes/query.py
-----------------------
Query endpoint. Streams RAG answer via SSE.
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.pipeline.orchestrator import RagPipeline
from app.core.dependency import get_pipeline

router = APIRouter(prefix="/api/v1", tags=["Query"])
limiter = Limiter(key_func=get_remote_address)


class QueryRequest(BaseModel):
    question: str


@router.post("/query")
@limiter.limit("10/minute")
async def query_knowledge_base(
    request: Request,
    payload: QueryRequest,
    pipeline: RagPipeline = Depends(get_pipeline),   # injected singleton
):
    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    try:
        return StreamingResponse(
            pipeline.query_rag_stream(payload.question),
            media_type="text/event-stream",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))