"""
app/pipeline/
─────────────
Modular RAG pipeline package.

Modules
-------
config          — loads and validates config.json
solr            — Solr connections + schema management
nlp             — spell correction, intent, NER, keywords, QA, re-ranking
autocomplete    — Trie-based prefix suggestion
signals         — user interaction logging + boost cache
ingest          — PDF → chunks → Solr
retrieval       — hybrid search (KNN + BM25 + RRF)
generator       — Ollama streaming
pipeline        — RagPipeline: assembles all modules

Usage
-----
    from app.pipeline import pipeline          # singleton
    from app.pipeline.pipeline import RagPipeline  # class
"""

from app.pipeline.pipeline import RagPipeline

pipeline = RagPipeline()