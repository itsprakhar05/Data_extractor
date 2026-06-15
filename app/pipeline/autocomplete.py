"""
app/pipeline/autocomplete.py
─────────────────────────────
Trie-based autocomplete for search-as-you-type suggestions.

How it works
------------
1. At startup, AutocompleteManager fetches all stored keywords from Solr
   and inserts them into the Trie, weighted by frequency.
2. At ingest time, newly extracted YAKE keywords are inserted so the
   Trie always reflects what's in the knowledge base.
3. At query time, get_suggestions(prefix) returns top-N completions
   sorted by frequency.

Example
-------
    ac = AutocompleteManager(solr_chunks)
    ac.get_suggestions("sol")  → ["solr", "solar energy", "solution"]
"""

from __future__ import annotations

import logging
from collections import defaultdict

import pysolr

log = logging.getLogger("RAG.Autocomplete")


# ── Trie ──────────────────────────────────────────────────────────────────────

class _TrieNode:
    __slots__ = ("children", "is_end", "frequency")

    def __init__(self):
        self.children:  dict[str, "_TrieNode"] = {}
        self.is_end:    bool = False
        self.frequency: int  = 0


class Trie:
    """
    Prefix tree for fast autocomplete lookups.
    Thread-safe for reads; inserts should happen before serving traffic.
    """

    def __init__(self):
        self._root = _TrieNode()

    def insert(self, word: str, freq: int = 1) -> None:
        node = self._root
        for ch in word.lower():
            if ch not in node.children:
                node.children[ch] = _TrieNode()
            node = node.children[ch]
        node.is_end     =  True
        node.frequency  += freq

    def search(self, prefix: str, top_n: int = 10) -> list[str]:
        """Return up to top_n completions for the given prefix."""
        node = self._root
        for ch in prefix.lower():
            if ch not in node.children:
                return []
            node = node.children[ch]
        matches = self._collect(node, prefix.lower())
        return [w for w, _ in sorted(matches, key=lambda x: -x[1])][:top_n]

    def _collect(self, node: _TrieNode, prefix: str) -> list[tuple[str, int]]:
        results: list[tuple[str, int]] = []
        if node.is_end:
            results.append((prefix, node.frequency))
        for ch, child in node.children.items():
            results.extend(self._collect(child, prefix + ch))
        return results

    @property
    def size(self) -> int:
        """Number of distinct words inserted."""
        return self._count(self._root)

    def _count(self, node: _TrieNode) -> int:
        total = 1 if node.is_end else 0
        for child in node.children.values():
            total += self._count(child)
        return total


# ── AutocompleteManager ───────────────────────────────────────────────────────

class AutocompleteManager:
    """
    Wraps the Trie and handles seeding it from Solr at startup
    and updating it as new documents are ingested.
    """

    _MIN_WORD_LENGTH = 3

    def __init__(self, solr_chunks: pysolr.Solr):
        self._trie = Trie()
        self._seed_from_solr(solr_chunks)

    # ── public ────────────────────────────────────────────────────────────────

    def get_suggestions(self, prefix: str, top_n: int = 10) -> list[str]:
        """Return autocomplete suggestions for a search prefix."""
        return self._trie.search(prefix.strip(), top_n=top_n)

    def add_keywords(self, keywords: list[str]) -> None:
        """Insert newly extracted keywords after a document is ingested."""
        for kw in keywords:
            word = kw.strip().lower()
            if len(word) >= self._MIN_WORD_LENGTH:
                self._trie.insert(word)
        log.debug(f"Trie updated with {len(keywords)} new keywords.")

    # ── private ───────────────────────────────────────────────────────────────

    def _seed_from_solr(self, solr: pysolr.Solr) -> None:
        """
        Fetch all stored keywords from the chunks collection and
        populate the Trie so suggestions work immediately on startup.
        """
        try:
            results    = solr.search("*:*", fl="keywords", rows=5_000)
            word_freq: dict[str, int] = defaultdict(int)

            for doc in results:
                for kw in doc.get("keywords", "").split(","):
                    word = kw.strip().lower()
                    if len(word) >= self._MIN_WORD_LENGTH:
                        word_freq[word] += 1

            for word, freq in word_freq.items():
                self._trie.insert(word, freq)

            log.info(f"✅ Autocomplete Trie seeded with {self._trie.size} terms.")
        except Exception as exc:
            log.warning(f"⚠️ Trie seeding skipped (Solr may be empty): {exc}")