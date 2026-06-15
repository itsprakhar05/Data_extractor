"""
app/pipeline/retrieval.py
──────────────────────────
Handles chunk retrieval from Solr using Hybrid Search.

Strategy
--------
  1. Vector search  (KNN)  — semantic similarity via embedded query vector.
  2. Keyword search (BM25)  — exact / fuzzy term matching via Solr text index.
  3. Reciprocal Rank Fusion — merges both ranked lists into a single list
                              without needing to normalise incompatible scores.

Why RRF?
--------
Vector scores and BM25 scores live on completely different scales and cannot
be added directly.  RRF converts each result's rank position into a score
(1 / (rank + k), k=60 by convention) and sums them.  Documents that rank
highly in both lists win; documents that rank highly in only one list still
benefit.  This consistently outperforms either search alone.

Fallback
--------
If both searches return zero results (e.g. the collection is empty or the
query is very unusual), the module falls back to a plain BM25 search on the
raw query text.
"""

from __future__ import annotations

import logging

import pysolr
from sentence_transformers import SentenceTransformer

log = logging.getLogger("RAG.Retrieval")

# RRF constant — 60 is the standard from the original paper
_RRF_K = 60


class RetrievalManager:
    """
    Executes hybrid search against the Solr chunks collection.
    """

    def __init__(
        self,
        solr_chunks: pysolr.Solr,
        embedder:    SentenceTransformer,
        top_k:       int = 10,
    ):
        self._solr    = solr_chunks
        self._embedder = embedder
        self._top_k   = top_k

    # ── public ────────────────────────────────────────────────────────────────

    def search(self, query: str) -> list[dict]:
        """
        Run hybrid search and return up to top_k merged, deduplicated chunks.

        Parameters
        ----------
        query : str
            The (already spell-corrected) user query.

        Returns
        -------
        list[dict]
            Solr documents sorted by RRF score, highest first.
        """
        query_vector   = self._embed(query)
        vector_results = self._vector_search(query_vector)
        keyword_results= self._keyword_search(query)

        merged = self._reciprocal_rank_fusion(vector_results, keyword_results)

        if not merged:
            log.warning("Hybrid search returned nothing — falling back to BM25.")
            merged = self._keyword_search(query, rows=self._top_k)

        log.info(f"Retrieval complete: {len(merged)} chunks returned.")
        return merged

    # ── private ───────────────────────────────────────────────────────────────

    def _embed(self, query: str) -> str:
        """Encode query and return it as a Solr KNN vector string."""
        vector = self._embedder.encode(query).tolist()
        return "[" + ",".join(map(str, vector)) + "]"

    def _vector_search(self, vector_str: str) -> list[dict]:
        try:
            results = self._solr.search(
                f"{{!knn f=content_vector topK={self._top_k}}}{vector_str}",
                rows=self._top_k,
            )
            return list(results)
        except Exception as exc:
            log.warning(f"Vector search failed: {exc}")
            return []

    def _keyword_search(self, query: str, rows: int | None = None) -> list[dict]:
        try:
            results = self._solr.search(
                f"content:({query})",
                rows=rows or self._top_k,
            )
            return list(results)
        except Exception as exc:
            log.warning(f"Keyword search failed: {exc}")
            return []

    def _reciprocal_rank_fusion(
        self, *ranked_lists: list[dict]
    ) -> list[dict]:
        """
        Merge multiple ranked result lists via Reciprocal Rank Fusion.
        Returns a deduplicated list sorted by descending RRF score.
        """
        scores: dict[str, float] = {}
        docs:   dict[str, dict]  = {}

        for ranked_list in ranked_lists:
            for rank, doc in enumerate(ranked_list):
                did              = doc["id"]
                scores[did]      = scores.get(did, 0.0) + 1.0 / (rank + _RRF_K)
                docs[did]        = doc

        sorted_ids = sorted(scores, key=scores.__getitem__, reverse=True)
        return [docs[did] for did in sorted_ids[: self._top_k]]