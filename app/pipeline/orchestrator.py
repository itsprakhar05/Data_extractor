"""
app/pipeline/orchestrator.py
----------------------------
RagPipeline — wires all pipeline modules together.
Owns query_rag_stream() and delegates everything else to focused modules.

Flow for a query:
    cache.get() → rewrite_query() → embed() → retriever.search()
    → build_context() → build_prompt() → stream_answer() → db.log_query()
"""

import os
import time
import json
import logging
from pathlib import Path

from dotenv import load_dotenv

from app.pipeline.embedder  import embed, get_model
from app.pipeline.ingester  import ingest_pdf
from app.pipeline.rewriter  import rewrite_query
from app.pipeline.retriever import Retriever
from app.pipeline.cache     import SemanticCache
from app.pipeline.generator import build_context, build_prompt, stream_answer
from app.db.database        import log_query, init_db

load_dotenv()
log = logging.getLogger("RAG_Pipeline")


class RagPipeline:
    def __init__(self, config_path: str = "config/config.json"):
        with open(config_path, "r") as f:
            self.config = json.load(f)

        self.groq_api_key = os.getenv("GROQ_API_KEY")
        self.groq_model   = self.config["groq_model"]
        solr_url          = self.config["solr_url"]

        # Init sub-modules
        self.retriever = Retriever(solr_url)
        self.retriever.ensure_schema(solr_url)
        self.cache = SemanticCache(model=get_model())

        # Init DB
        init_db()

        # Ensure data dirs exist
        Path("data/uploads").mkdir(parents=True, exist_ok=True)
        Path("data/json_chunks").mkdir(parents=True, exist_ok=True)

        log.info("✅ RagPipeline initialized.")

    # ------------------------------------------------------------------
    # Ingestion — delegates to ingester.py
    # ------------------------------------------------------------------

    def process_and_ingest(self, pdf_path: Path) -> int:
        """Ingest a PDF. Returns number of chunks created."""
        return ingest_pdf(pdf_path, self.retriever)

    # ------------------------------------------------------------------
    # Deletion — delegates to retriever.py
    # ------------------------------------------------------------------

    def delete_document_by_name(self, filename: str) -> bool:
        return self.retriever.delete_by_filename(filename)

    # ------------------------------------------------------------------
    # Query — orchestrates the full RAG flow
    # ------------------------------------------------------------------

    def query_rag_stream(self, user_query: str):
        """
        Full RAG query flow. Yields str tokens for StreamingResponse.

        Steps:
            1. Check semantic cache
            2. Rewrite query for better retrieval
            3. Embed rewritten query
            4. Retrieve chunks from Solr
            5. Build prompt + stream Groq response
            6. Log query + answer to SQLite
        """
        start = time.time()

        # Step 1 — Cache check
        cached_response, similarity = self.cache.get(user_query)
        if cached_response:
            latency_ms = (time.time() - start) * 1000
            log_query(
                question=user_query,
                answer=cached_response,
                contexts=[],
                rewritten_question=None,
                cache_hit=True,
                latency_ms=latency_ms,
            )
            for word in cached_response.split(" "):
                yield word + " "
            return

        # Step 2 — Rewrite query
        rewritten = rewrite_query(user_query, self.groq_api_key, self.groq_model)

        # Step 3 — Embed + retrieve
        query_vec = embed(rewritten)
        docs      = self.retriever.search(query_vec, fallback_query=rewritten)

        # Step 4 — Build prompt
        context_str, context_list = build_context(docs)
        prompt = build_prompt(context_str, user_query)

        # Step 5 — Stream answer, collect full response via sentinel
        full_response = ""
        for token in stream_answer(prompt, self.groq_api_key, self.groq_model):
            if isinstance(token, dict) and "__full__" in token:
                full_response = token["__full__"]
            else:
                yield token

        # Step 6 — Log to DB + cache
        latency_ms = (time.time() - start) * 1000
        log_query(
            question=user_query,
            answer=full_response,
            contexts=context_list,
            rewritten_question=rewritten,
            cache_hit=False,
            latency_ms=latency_ms,
        )
        self.cache.set(user_query, full_response)