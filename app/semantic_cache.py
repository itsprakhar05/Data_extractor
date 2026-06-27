"""
app/semantic_cache.py
---------------------
Semantic caching layer using Redis.
Before hitting Solr + Groq, checks if a semantically similar query
was already answered. Reduces latency and Groq API costs.

Requires: redis (pip install redis)
Redis container must be on rag-network (see docker-compose).
"""

import json
import logging
import numpy as np

log = logging.getLogger("RAG_Pipeline")

# Cosine similarity threshold — tune this:
# 0.95 = very strict (only near-identical queries hit cache)
# 0.90 = moderate (similar intent queries hit cache)
CACHE_THRESHOLD = 0.92
CACHE_TTL = 3600  # seconds — 1 hour


def _cosine_similarity(a: list, b: list) -> float:
    a, b = np.array(a), np.array(b)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


class SemanticCache:
    def __init__(self, embedder):
        """
        Args:
            embedder: The SentenceTransformer instance already loaded in RagPipeline.
                      We reuse it to avoid loading a second model.
        """
        self._embedder = embedder
        self._redis = None

    def _get_redis(self):
        """Lazy Redis connection — only connects when first used."""
        if self._redis is None:
            try:
                import redis
                self._redis = redis.Redis(
                    host="redis",   # service name in docker-compose
                    port=6379,
                    decode_responses=True,
                    socket_connect_timeout=2
                )
                self._redis.ping()
                log.info("✅ Redis semantic cache connected.")
            except Exception as e:
                log.warning(f"[SemanticCache] Redis unavailable, cache disabled: {e}")
                self._redis = None
        return self._redis

    def get(self, query: str):
        """
        Look for a cached response for this query.

        Returns:
            (cached_response: str, similarity: float) if cache hit
            (None, None) if miss or Redis unavailable
        """
        r = self._get_redis()
        if r is None:
            return None, None

        try:
            query_embedding = self._embedder.encode(query).tolist()
            keys = r.keys("semcache:*")

            for key in keys:
                raw = r.get(key)
                if not raw:
                    continue
                entry = json.loads(raw)
                similarity = _cosine_similarity(query_embedding, entry["embedding"])
                if similarity >= CACHE_THRESHOLD:
                    log.info(f"[SemanticCache] HIT (similarity={similarity:.3f}) for query: '{query}'")
                    return entry["response"], similarity

            log.info(f"[SemanticCache] MISS for query: '{query}'")
            return None, None

        except Exception as e:
            log.warning(f"[SemanticCache] get() failed: {e}")
            return None, None

    def set(self, query: str, response: str):
        """
        Store a query + response in Redis with TTL.
        Key is hash of query string — collisions are fine since
        we validate by cosine similarity on read.
        """
        r = self._get_redis()
        if r is None:
            return

        try:
            query_embedding = self._embedder.encode(query).tolist()
            cache_key = f"semcache:{abs(hash(query))}"
            payload = json.dumps({"embedding": query_embedding, "response": response})
            r.setex(cache_key, CACHE_TTL, payload)
            log.info(f"[SemanticCache] Stored response for query: '{query}'")
        except Exception as e:
            log.warning(f"[SemanticCache] set() failed: {e}")