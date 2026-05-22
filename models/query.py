"""
models/query.py
---------------
Request and response shapes for the query API.
"""

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, description="Natural language question")
    top_k: int = Field(5, ge=1, le=20, description="Number of chunks to retrieve from Solr")
    doc_id: str | None = Field(None, description="Restrict search to a specific document")


class RetrievedChunk(BaseModel):
    chunk_id: str
    doc_id: str
    filename: str
    page_number: int
    text: str
    score: float = 0.0


class QueryResponse(BaseModel):
    question: str
    answer: str
    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)
    model_used: str
    total_chunks_retrieved: int = 0


class IngestResponse(BaseModel):
    doc_id: str
    filename: str
    total_pages: int
    total_chunks: int
    json_cache_path: str
    message: str = "Ingestion successful"