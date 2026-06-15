"""
app/api/routes/extras.py
─────────────────────────
Four supplementary endpoints that extend the core RAG API.

Endpoints
---------
GET  /api/v1/autocomplete?q=<prefix>
    Returns live search suggestions as the user types.
    Powered by the Trie built from YAKE keywords extracted at ingest time.

POST /api/v1/feedback
    Called when a user clicks a source citation or marks an answer helpful.
    Logs an "opendocument" signal that trains the signals boost system.
    The more this is called, the smarter the ranking becomes over time.

GET  /api/v1/documents
    Returns a list of all PDFs currently ingested into the knowledge base.
    Used by the UI to show what is available and allow per-document filtering.

GET  /api/v1/chunks?filename=<name>
    Returns all stored chunks for a given filename.
    Used by the Chunk Inspector panel — shows content, keywords, entities
    per chunk so you can debug what the pipeline extracted from a PDF.
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.pipeline import pipeline

log = logging.getLogger("RAG.Routes.Extras")

router = APIRouter(prefix="/api/v1", tags=["Extras"])


# ══════════════════════════════════════════════════════════════════════════════
#  REQUEST / RESPONSE MODELS
# ══════════════════════════════════════════════════════════════════════════════

class FeedbackRequest(BaseModel):
    """
    Payload for the /feedback endpoint.

    Fields
    ------
    search_id : str
        The search_id returned in the meta JSON line from /query.
        Links this click back to the original search session.

    query : str
        The original user query that produced the result.
        Used as the key in the signals boost cache.

    chunk_id : str
        The Solr document id of the chunk the user found useful.
        Format: "<file_stem>_p<page>_c<chunk_index>"
        e.g.  "annual_report_p0_c3"
        This is returned in the sources list of the /query meta response.
    """
    search_id: str
    query:     str
    chunk_id:  str


class AutocompleteResponse(BaseModel):
    prefix:      str
    suggestions: list[str]


class DocumentItem(BaseModel):
    filename: str
    doc_id:   str


class DocumentsResponse(BaseModel):
    total:     int
    documents: list[DocumentItem]


class ChunkItem(BaseModel):
    id:          str
    chunk_index: int
    content:     str
    keywords:    str
    entities:    list[str]
    char_count:  int


class ChunksResponse(BaseModel):
    filename:     str
    total_chunks: int
    chunks:       list[dict]


# ══════════════════════════════════════════════════════════════════════════════
#  ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

# ── 1. Autocomplete ───────────────────────────────────────────────────────────

@router.get(
    "/autocomplete",
    response_model=AutocompleteResponse,
    summary="Get search suggestions for a prefix",
    description="""
    Returns up to 10 autocomplete suggestions for the given prefix string.

    Suggestions come from the Trie which is built from YAKE keywords
    extracted across all ingested documents at ingest time.
    Suggestions are ranked by keyword frequency — terms that appear
    across many chunks surface first.

    Example
    -------
    GET /api/v1/autocomplete?q=sol

    {
        "prefix": "sol",
        "suggestions": ["solr", "solar energy", "solution architecture"]
    }
    """,
)
async def autocomplete(
    q: str = Query(
        ...,
        min_length=1,
        description="Search prefix to autocomplete"
    )
):
    try:
        suggestions = pipeline.get_autocomplete_suggestions(
            prefix=q.strip(),
            top_n=10
        )
        log.debug(f"Autocomplete '{q}' → {len(suggestions)} suggestions")
        return AutocompleteResponse(prefix=q, suggestions=suggestions)

    except Exception as exc:
        log.error(f"Autocomplete failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── 2. Feedback ───────────────────────────────────────────────────────────────

@router.post(
    "/feedback",
    summary="Record that a user found a chunk useful",
    description="""
    Call this endpoint when a user clicks a source citation or
    explicitly marks an answer as helpful.

    What happens internally
    -----------------------
    1. An "opendocument" signal is persisted to the Solr signals collection.
    2. The in-memory boost cache is updated immediately.
    3. The next time the same query is run, the clicked chunk will rank
       higher — without any retraining or batch jobs.

    How to get the required fields
    ------------------------------
    The /query endpoint returns a meta JSON line as its first streamed chunk:

    {
        "type":            "meta",
        "corrected_query": "what is RAG?",
        "intent":          "definition",
        "exact_answer":    "Retrieval Augmented Generation",
        "sources": [
            { "file": "report.pdf", "chunk": 3, "id": "report_p0_c3" },
            ...
        ]
    }

    Pass "corrected_query" as query, the session search_id your client
    generated, and the "id" of the source the user clicked as chunk_id.

    Example
    -------
    POST /api/v1/feedback
    {
        "search_id": "a1b2c3d4-...",
        "query":     "what is RAG?",
        "chunk_id":  "report_p0_c3"
    }
    """,
)
async def log_feedback(payload: FeedbackRequest):
    # Validate fields
    if not payload.search_id.strip():
        raise HTTPException(
            status_code=400,
            detail="search_id cannot be empty."
        )
    if not payload.query.strip():
        raise HTTPException(
            status_code=400,
            detail="query cannot be empty."
        )
    if not payload.chunk_id.strip():
        raise HTTPException(
            status_code=400,
            detail="chunk_id cannot be empty."
        )

    try:
        pipeline.mark_chunk_useful(
            search_id=payload.search_id,
            query=payload.query,
            chunk_id=payload.chunk_id,
        )
        log.info(
            f"Feedback recorded — "
            f"query='{payload.query}' chunk='{payload.chunk_id}'"
        )
        return {
            "status":  "ok",
            "message": f"Feedback recorded for chunk '{payload.chunk_id}'."
                       f" Ranking will improve for query '{payload.query}'."
        }

    except Exception as exc:
        log.error(f"Feedback logging failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── 3. Documents ──────────────────────────────────────────────────────────────

@router.get(
    "/documents",
    response_model=DocumentsResponse,
    summary="List all ingested documents",
    description="""
    Returns one record per distinct PDF currently stored in the
    knowledge base.

    Use this endpoint to:
    - Show the user what documents are available to query
    - Build a document selector UI
    - Check if a specific file has been ingested

    Example
    -------
    GET /api/v1/documents

    {
        "total": 3,
        "documents": [
            { "filename": "annual_report.pdf", "doc_id": "a1b2c3..." },
            { "filename": "user_manual.pdf",   "doc_id": "d4e5f6..." },
            { "filename": "policy.pdf",        "doc_id": "g7h8i9..." }
        ]
    }
    """,
)
async def list_documents():
    try:
        docs = pipeline.list_documents()
        log.info(f"Documents listed: {len(docs)} found")
        return DocumentsResponse(
            total=len(docs),
            documents=[
                DocumentItem(filename=d["filename"], doc_id=d["doc_id"])
                for d in docs
            ]
        )

    except Exception as exc:
        log.error(f"list_documents failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── 4. Chunk Inspector ────────────────────────────────────────────────────────

@router.get(
    "/chunks",
    response_model=ChunksResponse,
    summary="Inspect all chunks for a specific file",
    description="""
    Returns every chunk stored in Solr for the given filename,
    including the extracted content, YAKE keywords, spaCy entities,
    and character count.

    Use this endpoint to:
    - Debug what the pipeline extracted from a PDF
    - Verify NLP enrichment (keywords and entities) is working
    - Build a chunk browser in your UI
    - Check how a document was split

    Example
    -------
    GET /api/v1/chunks?filename=annual_report.pdf

    {
        "filename": "annual_report.pdf",
        "total_chunks": 42,
        "chunks": [
            {
                "id":          "annual_report_p0_c0",
                "chunk_index": 0,
                "content":     "This report covers fiscal year 2024...",
                "keywords":    "fiscal year, annual revenue, net profit",
                "entities":    ["DATES:2024", "ORG:Acme Corp"],
                "char_count":  843
            },
            ...
        ]
    }
    """,
)
async def get_chunks(
    filename: str = Query(
        ...,
        min_length=1,
        description="Exact filename as stored in Solr e.g. annual_report.pdf"
    )
):
    if not filename.strip():
        raise HTTPException(
            status_code=400,
            detail="filename cannot be empty."
        )

    try:
        chunks = pipeline.get_chunks_for_file(filename.strip())

        if not chunks:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No chunks found for '{filename}'. "
                    f"Has this file been ingested? "
                    f"Check GET /api/v1/documents for available files."
                )
            )

        log.info(f"Chunks retrieved for '{filename}': {len(chunks)}")
        return ChunksResponse(
            filename=filename,
            total_chunks=len(chunks),
            chunks=chunks,
        )

    except HTTPException:
        raise   # re-raise 404 as-is

    except Exception as exc:
        log.error(f"get_chunks failed for '{filename}': {exc}")
        raise HTTPException(status_code=500, detail=str(exc))