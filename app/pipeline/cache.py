"""
app/pipeline/cache.py
---------------------
Semantic caching layer using Redis.
Before hitting Solr + Groq, checks if a semantically similar query
was already answered. Silently disabled if Redis is unavailable.
"""

import json
import logging
import numpy as np
from sentence_transformers import SentenceTransformer

log = logging.getLogger("RAG_Pipeline")

CACHE_THRESHOLD = 0.92  # cosine similarity — tune between 0.90–0.95
CACHE_TTL = 3600        # 1 hour


def _cosine_similarity(a: list, b: list) -> float:
    a, b = np.array(a), np.array(b)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0


class SemanticCache:
    def __init__(self, model: SentenceTransformer):
        """
        Args:
            model: Shared SentenceTransformer instance from embedder.py
                   Reused to avoid loading a second model into memory.
        """
        self._model = model
        self._redis = None

    def _get_redis(self):
        if self._redis is not None:
            return self._redis
        try:
            import redis
            r = redis.Redis(host="redis", port=6379, decode_responses=True, socket_connect_timeout=2)
            r.ping()
            self._redis = r
            log.info("✅ Redis semantic cache connected.")
        except Exception as e:
            log.warning("[Cache] Redis unavailable, caching disabled: %s", e)
            self._redis = None
        return self._redis

    def get(self, query: str) -> tuple[str | None, float | None]:
        """
        Check Redis for a semantically similar cached response.

        Returns:
            (response, similarity) on HIT
            (None, None) on MISS or Redis unavailable
        """
        r = self._get_redis()
        if r is None:
            return None, None
        try:
            query_vec = self._model.encode(query).tolist()
            for key in r.keys("semcache:*"):
                raw = r.get(key)
                if not raw:
                    continue
                entry = json.loads(raw)
                sim = _cosine_similarity(query_vec, entry["embedding"])
                if sim >= CACHE_THRESHOLD:
                    log.info("[Cache] HIT (sim=%.3f) for: '%s'", sim, query)
                    return entry["response"], sim
            log.info("[Cache] MISS for: '%s'", query)
            return None, None
        except Exception as e:
            log.warning("[Cache] get() error: %s", e)
            return None, None

    def set(self, query: str, response: str):
        """Store a query+response embedding in Redis with TTL."""
        r = self._get_redis()
        if r is None:
            return
        try:
            query_vec = self._model.encode(query).tolist()
            key = f"semcache:{abs(hash(query))}"
            r.setex(key, CACHE_TTL, json.dumps({"embedding": query_vec, "response": response}))
            log.info("[Cache] Stored response for: '%s'", query)
        except Exception as e:
            log.warning("[Cache] set() error: %s", e)