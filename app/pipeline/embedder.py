"""
app/pipeline/embedder.py
------------------------
Loads and exposes the SentenceTransformer embedding model.
Singleton pattern — model is loaded once at import time.
"""

import logging
from sentence_transformers import SentenceTransformer

log = logging.getLogger("RAG_Pipeline")

MODEL_NAME = "all-MiniLM-L6-v2"

log.info("Loading embedding model: %s ...", MODEL_NAME)
_model = SentenceTransformer(MODEL_NAME)
log.info("✅ Embedding model loaded.")


def embed(text: str) -> list[float]:
    """Embed a single string. Returns a list of floats."""
    return _model.encode(text).tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a list of strings. More efficient than calling embed() in a loop."""
    return _model.encode(texts).tolist()


def get_model() -> SentenceTransformer:
    """Return the raw model (needed by SemanticCache)."""
    return _model