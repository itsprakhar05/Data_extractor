# from fastapi import APIRouter, HTTPException
# from pydantic import BaseModel
# from fastapi.responses import StreamingResponse
# from app.pipeline import pipeline

# router = APIRouter(prefix="/api/v1", tags=["Query"])

# class QueryRequest(BaseModel):
#     question: str

# @router.post("/query")
# async def query_knowledge_base(payload: QueryRequest):
#     if not payload.question.strip():
#         raise HTTPException(status_code=400, detail="Question string cannot be empty.")
#     try:
#         # We call a modified streaming method inside your pipeline
#         return StreamingResponse(
#             pipeline.query_rag_stream(payload.question), 
#             media_type="text/event-stream"
#         )
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))



from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.pipeline import pipeline

router = APIRouter(prefix="/api/v1", tags=["Query"])


class QueryRequest(BaseModel):
    question: str


@router.post("/query")
async def query_knowledge_base(payload: QueryRequest):
    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="Question string cannot be empty.")
    try:
        return StreamingResponse(
            pipeline.query_rag_stream(payload.question),
            media_type="text/event-stream",
            headers={
                # Frontend can read this header to show a "⚡ Cached" badge
                "X-Cache": "UNKNOWN"  # pipeline will log HIT/MISS internally
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))