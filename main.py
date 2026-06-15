# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware
# from app.api.routes import ingest, query, delete
# import logging

# logging.basicConfig(level=logging.INFO)

# app = FastAPI(title="OpenDataLoader Solr RAG Engine", version="1.0.0")

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# app.include_router(ingest.router)
# app.include_router(query.router)
# app.include_router(delete.router)

# @app.get("/")
# async def root_healthcheck():
#     return {"status": "online"}




"""
app/main.py
────────────
FastAPI application entry point.

Routers registered
------------------
  ingest  → POST   /api/v1/ingest
  query   → POST   /api/v1/query
  delete  → DELETE /api/v1/delete
  extras  → GET    /api/v1/autocomplete
            POST   /api/v1/feedback
            GET    /api/v1/documents
            GET    /api/v1/chunks
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import ingest, query, delete
from app.api.routes.extras import router as extras_router

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("RAG.Main")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title       = "OpenDataLoader Solr RAG Engine",
    version     = "2.0.0",
    description = """
A fully local, private RAG system — no OpenAI, no cloud.

## How it works
1. **Ingest** a PDF → extracted, chunked, NLP-enriched, stored in Solr
2. **Query** in natural language → hybrid search, re-ranked, streamed answer
3. **Feedback** on useful sources → signals boost improves ranking over time

## NLP layers
Spell correction · Intent classification · NER · Keyword extraction ·
Hybrid search (BM25 + KNN + RRF) · Cross-encoder re-ranking ·
Signals boosting · Extractive QA span highlighting · Autocomplete
""",
)


# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # tighten this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(ingest.router)
app.include_router(query.router)
app.include_router(delete.router)
app.include_router(extras_router)   # autocomplete, feedback, documents, chunks


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def root_healthcheck():
    """
    Confirms the server is running.
    Also lists every available endpoint so you can verify all routers
    registered correctly without opening the /docs page.
    """
    return {
        "status":  "online",
        "version": "2.0.0",
        "endpoints": {
            "ingest":       "POST   /api/v1/ingest",
            "query":        "POST   /api/v1/query",
            "delete":       "DELETE /api/v1/delete",
            "autocomplete": "GET    /api/v1/autocomplete?q=<prefix>",
            "feedback":     "POST   /api/v1/feedback",
            "documents":    "GET    /api/v1/documents",
            "chunks":       "GET    /api/v1/chunks?filename=<name>",
            "docs":         "GET    /docs",
            "redoc":        "GET    /redoc",
        }
    }


# ── Startup / shutdown events ─────────────────────────────────────────────────
@app.on_event("startup")
async def on_startup():
    log.info("=" * 60)
    log.info("  RAG Engine v2.0.0 starting up")
    log.info("  Docs available at http://localhost:8000/docs")
    log.info("=" * 60)


@app.on_event("shutdown")
async def on_shutdown():
    log.info("RAG Engine shutting down.")
