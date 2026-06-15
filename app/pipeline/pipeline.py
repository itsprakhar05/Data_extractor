# import os
# import json
# import uuid
# import logging
# import requests
# import pysolr
# from pathlib import Path
# from sentence_transformers import SentenceTransformer
# import opendataloader_pdf

# log = logging.getLogger("RAG_Pipeline")

# class RagPipeline:
#     def __init__(self, config_path="config/config.json"):
#         with open(config_path, "r") as f:
#             self.config = json.load(f)
        
#         self.solr_url = self.config["solr_url"]
#         self.solr = pysolr.Solr(self.solr_url, always_commit=True)
#         self.ollama_url = self.config["ollama_url"]
#         self.model_name = self.config["ollama_model"]
        
#         # ✅ Load embedding model once at startup
#         log.info("Loading embedding model...")
#         self.embedder = SentenceTransformer('all-MiniLM-L6-v2')
#         log.info("✅ Embedding model loaded.")

#         Path("data/uploads").mkdir(parents=True, exist_ok=True)
#         Path("data/json_chunks").mkdir(parents=True, exist_ok=True)
        
#         self.ensure_solr_schema()

#     def ensure_solr_schema(self):
#         schema_url = f"{self.solr_url}/schema"
#         log.info(f"Synchronizing Solr core schema variables at {schema_url}...")
        
#         required_fields = [
#             {"name": "doc_id",          "type": "string",       "stored": True,  "indexed": True},
#             {"name": "source_file",     "type": "string",       "stored": True,  "indexed": True},
#             {"name": "page_num",        "type": "pint",         "stored": True,  "indexed": True},
#             {"name": "chunk_index",     "type": "pint",         "stored": True,  "indexed": True},
#             {"name": "content",         "type": "text_general", "stored": True,  "indexed": True},
#             {"name": "char_count",      "type": "plong",        "stored": True,  "indexed": True},
#             {"name": "metadata",        "type": "string",       "stored": True,  "indexed": False},
#             {"name": "content_vector",  "type": "knn_vector_384", "stored": True, "indexed": True}
#         ]

#         required_field_types = [
#             {
#                 "name": "knn_vector_384",
#                 "class": "solr.DenseVectorField",
#                 "vectorDimension": 384,
#                 "similarityFunction": "cosine"
#             }
#         ]

#         try:
#             # Step 1 — Add vector field type if missing
#             type_response = requests.get(f"{schema_url}/fieldtypes", timeout=5)
#             existing_types = [t["name"] for t in type_response.json().get("fieldTypes", [])] if type_response.status_code == 200 else []
            
#             types_to_add = [t for t in required_field_types if t["name"] not in existing_types]
#             if types_to_add:
#                 type_payload = {"add-field-type": types_to_add}
#                 requests.post(schema_url, json=type_payload, timeout=5)
#                 log.info("✅ Created vector field type: knn_vector_384")

#             # Step 2 — Add fields if missing
#             response = requests.get(f"{schema_url}/fields", timeout=5)
#             existing_fields = [f["name"] for f in response.json().get("fields", [])] if response.status_code == 200 else []
#             fields_to_add = [f for f in required_fields if f["name"] not in existing_fields]

#             if not fields_to_add:
#                 log.info("✅ All core data fields matched. Schema up to date.")
#                 return

#             payload = {"add-field": fields_to_add}
#             schema_response = requests.post(schema_url, json=payload, timeout=5)
#             if schema_response.status_code == 200:
#                 log.info(f"✅ Created {len(fields_to_add)} missing fields inside Solr core index.")

#         except Exception as e:
#             log.error(f"❌ Failed field initialization: {e}")


#     def process_and_ingest(self, pdf_path: Path):
#         doc_id = str(uuid.uuid4())
#         file_stem = pdf_path.stem
#         temp_dir = Path("data/temp_extraction")
#         temp_dir.mkdir(parents=True, exist_ok=True)
        
#         extracted_md = temp_dir / f"{file_stem}.md"
        
#         log.info(f"[Layer 1] Extracting structured layout grid as Markdown: {pdf_path.name}")
        
#         try:
#             opendataloader_pdf.convert(
#                 input_path=[str(pdf_path.resolve())],
#                 output_dir=str(temp_dir.resolve()),
#                 format="markdown"
#             )
#         except Exception as e:
#             log.error(f"❌ OpenDataLoader conversion failed internally: {str(e)}")
#             if temp_dir.exists() and not os.listdir(temp_dir):
#                 os.rmdir(temp_dir)
#             raise RuntimeError(f"OpenDataLoader extraction crash: {str(e)}")

#         if not extracted_md.exists():
#             raise FileNotFoundError(f"OpenDataLoader did not output expected markdown file at: {extracted_md}")

#         with open(extracted_md, "r", encoding="utf-8") as f:
#             full_markdown = f.read()

#         log.info("[Layer 2] Splitting markdown chunks with table protection...")

#         # ✅ Helper to detect markdown table rows
#         def is_table_block(block: str) -> bool:
#             return any("|" in line for line in block.splitlines())

#         raw_blocks = full_markdown.split("\n\n")
#         chunks = []
#         current_chunk = []
#         current_word_count = 0
#         target_chunk_words = 300

#         for block in raw_blocks:
#             if not block.strip():
#                 continue

#             block_words = len(block.split())
#             is_table = is_table_block(block)

#             # ✅ Tables always go as their own isolated chunk — never split
#             if is_table:
#                 if current_chunk:
#                     chunks.append("\n\n".join(current_chunk))
#                     current_chunk = []
#                     current_word_count = 0
#                 chunks.append(block)
#                 continue

#             if current_word_count + block_words > target_chunk_words and current_chunk:
#                 chunks.append("\n\n".join(current_chunk))
#                 current_chunk = [block]
#                 current_word_count = block_words
#             else:
#                 current_chunk.append(block)
#                 current_word_count += block_words

#         if current_chunk:
#             chunks.append("\n\n".join(current_chunk))

#         log.info(f"[Layer 2] Total chunks created: {len(chunks)}")

#         # ✅ Build Solr docs with vectors
#         solr_docs = []
#         for idx, chunk_text in enumerate(chunks):
#             if chunk_text.strip():
#                 vector = self.embedder.encode(chunk_text).tolist()

#                 solr_docs.append({
#                     "id":           f"{file_stem}_p0_c{idx}",
#                     "doc_id":       doc_id,
#                     "source_file":  pdf_path.name,
#                     "page_num":     0,
#                     "chunk_index":  idx,
#                     "content":      chunk_text,
#                     "content_vector": vector,
#                     "char_count":   len(chunk_text),
#                     "metadata":     json.dumps({
#                         "file_type": "pdf",
#                         "parser": "native-opendataloader-markdown",
#                         "is_table": is_table_block(chunk_text)  # ✅ Tag table chunks
#                     }, ensure_ascii=False)
#                 })

#         # Save backup
#         final_json_path = Path("data/json_chunks") / f"{file_stem}_chunks.json"
#         with open(final_json_path, "w", encoding="utf-8") as f:
#             json.dump(solr_docs, f, indent=2, ensure_ascii=False)

#         log.info(f"[Layer 3] Uploading {len(solr_docs)} chunks to Solr Core...")
#         self.solr.add(solr_docs)
        
#         # Housekeeping
#         if extracted_md.exists():
#             os.remove(extracted_md)
#         if temp_dir.exists() and not os.listdir(temp_dir):
#             os.rmdir(temp_dir)
            
#         return len(solr_docs)


#     def delete_document_by_name(self, filename: str):
#         try:
#             delete_query = f'source_file:"{filename}"'
#             self.solr.delete(q=delete_query)
#             log.info(f"✅ Successfully deleted all chunks for file: {filename} from Solr.")
#             return True
#         except Exception as e:
#             log.error(f"❌ Failed to delete document '{filename}': {e}")
#             return False


#     def query_rag_stream(self, user_query: str):
#         # ✅ Step 1 — Convert query to vector
#         query_vector = self.embedder.encode(user_query).tolist()
#         vector_str = "[" + ",".join(map(str, query_vector)) + "]"

#         # ✅ Step 2 — Vector search (semantic)
#         search_results = self.solr.search(
#             f'{{!knn f=content_vector topK=5}}{vector_str}',
#             rows=5
#         )

#         # ✅ Step 3 — Fallback to keyword search if vector returns nothing
#         if len(search_results) == 0:
#             log.warning("Vector search returned nothing, falling back to keyword search...")
#             search_results = self.solr.search(f'content:({user_query})', rows=5)

#         # ✅ Step 4 — Debug log what Solr returned
#         log.info(f"Chunks retrieved: {len(search_results)}")
#         for doc in search_results:
#             log.debug(f"--- CHUNK ---\n{doc.get('content', '')[:300]}\n")

#         # ✅ Step 5 — Build context
#         context_blocks = []
#         for doc in search_results:
#             source_info = f"[Source: {doc.get('source_file', 'Unknown')} | Chunk: {doc.get('chunk_index', 0)}]"
#             context_blocks.append(f"{source_info}\n{doc.get('content', '')}")
            
#         context = "\n---\n".join(context_blocks)
#         if not context.strip():
#             context = "No specific relevant documentation found."

#         # ✅ Step 6 — Table-aware prompt
#         prompt = f"""You are a precise assistant. Answer ONLY using the context below.
# The context may contain markdown tables with | symbols — read them carefully.
# If the answer is in a table, extract and present the relevant rows clearly.
# If the answer is not in the context, say "I don't have enough information."
# Do not make up answers.

# CONTEXT:
# {context}

# QUESTION:
# {user_query}

# ANSWER (if data is in a table, present it clearly):"""

#         # ✅ Step 7 — Ollama payload with increased limits for table output
#         payload = {
#             "model": self.model_name,
#             "prompt": prompt,
#             "stream": True,
#             "options": {
#                 "num_ctx": 512,
#                 "num_predict": 200,
#                 "num_gpu": 99,
#                 "num_thread": 4,
#                 "temperature": 0.1,
#                 "low_vram": True
#             }
#         }

#         # ✅ Step 8 — Stream response
#         try:
#             response = requests.post(self.ollama_url, json=payload, timeout=300, stream=True)
#             response.raise_for_status()
            
#             for line in response.iter_lines():
#                 if line:
#                     chunk = json.loads(line.decode('utf-8'))
#                     yield chunk.get("response", "")
#                     if chunk.get("done", False):
#                         break
                        
#         except Exception as e:
#             log.error(f"Streaming failed: {e}")
#             yield f"Error generating response: {str(e)}"


# pipeline = RagPipeline()




















"""
app/pipeline/pipeline.py
─────────────────────────
RagPipeline — the top-level orchestrator.

This class owns no business logic itself.  It wires together the six
specialist modules and exposes the three public methods that the API
routes call:

  query_rag_stream(user_query, search_id)
      Full query pipeline — spell correct → intent → retrieve → rerank →
      signals boost → extractive QA → stream Ollama answer.

  process_and_ingest(pdf_path)
      PDF → chunks → NLP enrichment → Solr upload.

  mark_chunk_useful(search_id, query, chunk_id)
      Records user feedback that trains the signals boost system.

All other helpers (list_documents, get_chunks_for_file,
get_autocomplete_suggestions) are thin pass-throughs to the relevant module.

Module dependency graph
-----------------------
    AppConfig
        │
        ├── SolrManager ──────────┐
        │   ├── .chunks           │
        │   └── .signals          │
        │                         │
        ├── NLPProcessor          │
        │   ├── SpellCorrector    │
        │   ├── IntentClassifier  │
        │   ├── EntityExtractor   │
        │   ├── KeywordExtractor  │
        │   ├── Reranker          │
        │   └── ExtractiveQA      │
        │                         │
        ├── AutocompleteManager ──┤ (uses SolrManager.chunks)
        │                         │
        ├── SignalsManager ───────┤ (uses SolrManager.signals)
        │                         │
        ├── IngestManager ────────┤ (uses SolrManager.chunks + NLP + Autocomplete)
        │                         │
        ├── RetrievalManager ─────┤ (uses SolrManager.chunks + embedder)
        │                         │
        └── OllamaGenerator / PromptBuilder
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from sentence_transformers import SentenceTransformer

from app.pipeline.config      import AppConfig
from app.pipeline.solr        import SolrManager
from app.pipeline.nlp         import NLPProcessor
from app.pipeline.autocomplete import AutocompleteManager
from app.pipeline.signals     import SignalsManager
from app.pipeline.ingest      import IngestManager
from app.pipeline.retrieval   import RetrievalManager
from app.pipeline.generator   import OllamaGenerator, PromptBuilder

log = logging.getLogger("RAG.Pipeline")


class RagPipeline:
    """
    Assembles and orchestrates all pipeline modules.
    Instantiated once at application startup (singleton via __init__.py).
    """

    def __init__(self, config_path: str = "config/config.json"):
        log.info("Initialising RAG Pipeline...")

        # ── 1. Config ──────────────────────────────────────────────────────────
        self._config = AppConfig.load(config_path)

        # ── 2. Solr connections + schema ───────────────────────────────────────
        self._solr = SolrManager(self._config)

        # ── 3. Shared embedding model (used by ingest AND retrieval) ───────────
        log.info("Loading embedding model (all-MiniLM-L6-v2)...")
        self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
        log.info("✅ Embedding model loaded.")

        # ── 4. NLP processor (spell, intent, NER, keywords, rerank, QA) ───────
        self._nlp = NLPProcessor()

        # ── 5. Autocomplete ────────────────────────────────────────────────────
        self._autocomplete = AutocompleteManager(self._solr.chunks)

        # ── 6. Signals boosting ────────────────────────────────────────────────
        self._signals = SignalsManager(self._solr.signals)

        # ── 7. Ingest manager ──────────────────────────────────────────────────
        self._ingest = IngestManager(
            solr_chunks   = self._solr.chunks,
            embedder      = self._embedder,
            nlp           = self._nlp,
            autocomplete  = self._autocomplete,
            target_words  = self._config.chunk_target_words,
        )

        # ── 8. Retrieval manager ───────────────────────────────────────────────
        self._retrieval = RetrievalManager(
            solr_chunks = self._solr.chunks,
            embedder    = self._embedder,
        )

        # ── 9. Generator (prompt builder + Ollama streamer) ────────────────────
        self._prompt_builder = PromptBuilder()
        self._generator      = OllamaGenerator(
            ollama_url  = self._config.ollama_url,
            model_name  = self._config.ollama_model,
            options     = self._config.ollama_options,
        )

        log.info("✅ RAG Pipeline ready.")

    # ══════════════════════════════════════════════════════════════════════════
    #  PUBLIC API
    # ══════════════════════════════════════════════════════════════════════════

    def query_rag_stream(self, user_query: str, search_id: str | None = None):
        """
        Full query pipeline — yields a metadata JSON line then streams the answer.

        Step 1  Spell correction
        Step 2  Intent classification
        Step 3  Hybrid retrieval  (KNN + BM25 + RRF)
        Step 4  Cross-encoder re-ranking
        Step 5  Signals boost
        Step 6  Extractive QA span  (exact answer highlight)
        Step 7  Prompt assembly + Ollama streaming
        Step 8  Log search signal
        """
        search_id = search_id or str(uuid.uuid4())

        # Step 1 — spell correction
        query = self._nlp.correct_query(user_query)

        # Step 2 — intent
        intent      = self._nlp.classify_intent(query)
        instruction = self._nlp.intent_prompt(intent)
        log.info(f"Intent: {intent} | Query: '{query}'")

        # Step 3 — hybrid retrieval
        chunks = self._retrieval.search(query)

        # Step 4 — cross-encoder re-ranking
        chunks = self._nlp.rerank_chunks(query, chunks)

        # Step 5 — signals boost
        chunks = self._signals.apply_boost(query, chunks)

        # Take top 5 for the LLM (balance context vs speed)
        top_chunks = chunks[:5]

        # Step 6 — extractive QA
        top_context  = top_chunks[0].get("content", "") if top_chunks else ""
        exact_answer = self._nlp.extract_answer_span(query, top_context)

        # Step 7 — yield metadata then stream answer
        yield self._prompt_builder.build_meta(
            corrected_query = query,
            intent          = intent,
            exact_answer    = exact_answer,
            chunks          = top_chunks,
        ) + "\n"

        prompt = self._prompt_builder.build(
            question     = query,
            intent       = intent,
            instruction  = instruction,
            chunks       = top_chunks,
            exact_answer = exact_answer,
        )

        yield from self._generator.stream(prompt)

        # Step 8 — log search signal (after streaming so latency is unaffected)
        self._signals.log_search(search_id, query)

    def process_and_ingest(self, pdf_path: Path) -> int:
        """Ingest a PDF file. Returns the number of chunks created."""
        return self._ingest.ingest(pdf_path)

    def delete_document_by_name(self, filename: str) -> bool:
        """Delete all chunks for the given filename from Solr."""
        return self._ingest.delete(filename)

    def mark_chunk_useful(
        self, search_id: str, query: str, chunk_id: str
    ) -> None:
        """
        Record that the user found a chunk helpful.
        Trains the signals boost system over time.
        """
        self._signals.log_click(search_id, query, chunk_id)

    def get_autocomplete_suggestions(
        self, prefix: str, top_n: int = 10
    ) -> list[str]:
        """Return autocomplete suggestions for a search prefix."""
        return self._autocomplete.get_suggestions(prefix, top_n=top_n)

    def list_documents(self) -> list[dict]:
        """Return all distinct ingested documents."""
        return self._ingest.list_documents()

    def get_chunks_for_file(self, filename: str) -> list[dict]:
        """Return all stored chunks for a given file (chunk inspector)."""
        return self._ingest.get_chunks_for_file(filename)