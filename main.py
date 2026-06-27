from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import ingest, query, delete, evaluate
import logging

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="OpenDataLoader Solr RAG Engine", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router)
app.include_router(query.router)
app.include_router(delete.router)
app.include_router(evaluate.router)  # Include the evaluation router

@app.get("/")
async def root_healthcheck():
    return {"status": "online"}
