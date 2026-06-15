"""
app/pipeline/signals.py
────────────────────────
Tracks user interactions and learns which chunks are useful for which queries.

How it works
------------
1. Every query is logged as a "search" signal.
2. When a user clicks a source / marks a chunk helpful, an "opendocument"
   signal is logged.
3. At startup, all past "opendocument" signals are loaded into an in-memory
   boost cache: { query → { chunk_id → click_count } }.
4. At query time, SignalsManager.apply_boost() re-ranks chunks so previously
   clicked chunks float higher — without touching the vector or BM25 scores.

The system improves automatically the more it is used.
No retraining, no batch jobs — pure click-signal learning.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime

import pysolr

log = logging.getLogger("RAG.Signals")

# How much signals influence final ranking.
# 0.0 = ignore signals, 1.0 = signals dominate.  0.15 is a safe start.
_BOOST_WEIGHT = 0.15

# Small rank-position penalty so cross-encoder order is preserved as baseline.
_POSITION_PENALTY = 0.01


class SignalsManager:
    """
    Logs user signals to Solr and applies learned boosts at query time.
    """

    def __init__(self, solr_signals: pysolr.Solr):
        self._solr = solr_signals
        # { query_lower: { chunk_id: click_count } }
        self._cache: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._load_cache()

    # ── public ────────────────────────────────────────────────────────────────

    def log_search(self, search_id: str, query: str) -> None:
        """Log that a user submitted a query."""
        self._persist(search_id, query, chunk_id="", route="search")

    def log_click(self, search_id: str, query: str, chunk_id: str) -> None:
        """
        Log that a user found a chunk useful (clicked a source citation).
        Also updates the in-memory cache immediately so the next query
        benefits without waiting for a cache reload.
        """
        self._persist(search_id, query, chunk_id=chunk_id, route="opendocument")
        self._cache[query.lower().strip()][chunk_id] += 1
        log.info(f"✅ Click signal recorded — query='{query}' chunk='{chunk_id}'")

    def apply_boost(self, query: str, chunks: list[dict]) -> list[dict]:
        """
        Re-rank chunks using accumulated click signals for this query.
        Preserves the cross-encoder ranking as the baseline and uses
        signals as a tiebreaker / light nudge upward.

        Returns the same list if no signals exist for this query yet.
        """
        query_boosts = self._cache.get(query.lower().strip(), {})
        if not query_boosts:
            return chunks

        boosted = sorted(
            enumerate(chunks),
            key=lambda x: (
                query_boosts.get(x[1].get("id", ""), 0) * _BOOST_WEIGHT
                - x[0] * _POSITION_PENALTY
            ),
            reverse=True,
        )
        log.debug(f"Signals boost applied for query='{query}'")
        return [doc for _, doc in boosted]

    # ── private ───────────────────────────────────────────────────────────────

    def _persist(
        self, search_id: str, query: str, chunk_id: str, route: str
    ) -> None:
        signal = {
            "id":        str(uuid.uuid4()),
            "search_id": search_id,
            "query":     query.lower().strip(),
            "chunk_id":  chunk_id,
            "route":     route,
            "timestamp": datetime.utcnow().isoformat(),
        }
        try:
            self._solr.add([signal])
        except Exception as exc:
            log.warning(f"⚠️ Signal persist failed: {exc}")

    def _load_cache(self) -> None:
        """
        Replay all past click signals from Solr into the in-memory cache
        so boosts are active immediately on startup.
        """
        try:
            results = self._solr.search(
                'route:"opendocument"', rows=10_000, fl="query,chunk_id"
            )
            for doc in results:
                q   = doc.get("query", "").lower().strip()
                cid = doc.get("chunk_id", "")
                if q and cid:
                    self._cache[q][cid] += 1
            log.info(f"✅ Signals cache loaded: {len(self._cache)} distinct queries.")
        except Exception as exc:
            log.warning(f"⚠️ Signals cache load skipped: {exc}")