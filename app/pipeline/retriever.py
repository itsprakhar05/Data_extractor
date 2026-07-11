"""
app/pipeline/retriever.py
-------------------------
Solr retrieval logic.
Handles vector (KNN) search with keyword fallback.
"""

import logging
import pysolr

log = logging.getLogger("RAG_Pipeline")


class Retriever:
    def __init__(self, solr_url: str):
        self.solr = pysolr.Solr(solr_url, always_commit=True)
        log.info("✅ Retriever connected to Solr: %s", solr_url)

    def search(self, query_embedding: list[float], fallback_query: str, top_k: int = 5) -> list[dict]:
        """
        Run KNN vector search. Falls back to keyword search if no results.

        Args:
            query_embedding:  Embedding of the (rewritten) query
            fallback_query:   Raw text query used if vector search returns nothing
            top_k:            Number of chunks to retrieve

        Returns:
            List of Solr doc dicts with at least 'content', 'source_file', 'chunk_index'
        """
        vector_str = "[" + ",".join(map(str, query_embedding)) + "]"

        results = self.solr.search(
            f'{{!knn f=content_vector topK={top_k}}}{vector_str}',
            rows=top_k
        )

        if len(results) == 0:
            log.warning("[Retriever] Vector search returned nothing, falling back to keyword search.")
            results = self.solr.search(f'content:({fallback_query})', rows=top_k)

        docs = list(results)
        log.info("[Retriever] Retrieved %d chunks.", len(docs))
        return docs

    def ensure_schema(self, solr_url: str):
        """Synchronize Solr schema fields. Called once at startup."""
        import requests

        schema_url = f"{solr_url}/schema"
        log.info("Synchronizing Solr schema at %s ...", schema_url)

        required_field_types = [
            {
                "name": "knn_vector_384",
                "class": "solr.DenseVectorField",
                "vectorDimension": 384,
                "similarityFunction": "cosine"
            }
        ]

        required_fields = [
            {"name": "doc_id",         "type": "string",         "stored": True,  "indexed": True},
            {"name": "source_file",    "type": "string",         "stored": True,  "indexed": True},
            {"name": "page_num",       "type": "pint",           "stored": True,  "indexed": True},
            {"name": "chunk_index",    "type": "pint",           "stored": True,  "indexed": True},
            {"name": "content",        "type": "text_general",   "stored": True,  "indexed": True},
            {"name": "char_count",     "type": "plong",          "stored": True,  "indexed": True},
            {"name": "metadata",       "type": "string",         "stored": True,  "indexed": False},
            {"name": "content_vector", "type": "knn_vector_384", "stored": True,  "indexed": True},
        ]

        try:
            type_resp = requests.get(f"{schema_url}/fieldtypes", timeout=5)
            existing_types = [t["name"] for t in type_resp.json().get("fieldTypes", [])] if type_resp.ok else []
            types_to_add = [t for t in required_field_types if t["name"] not in existing_types]
            if types_to_add:
                requests.post(schema_url, json={"add-field-type": types_to_add}, timeout=5)
                log.info("✅ Added field type: knn_vector_384")

            field_resp = requests.get(f"{schema_url}/fields", timeout=5)
            existing_fields = [f["name"] for f in field_resp.json().get("fields", [])] if field_resp.ok else []
            fields_to_add = [f for f in required_fields if f["name"] not in existing_fields]

            if fields_to_add:
                requests.post(schema_url, json={"add-field": fields_to_add}, timeout=5)
                log.info("✅ Added %d missing Solr fields.", len(fields_to_add))
            else:
                log.info("✅ Solr schema up to date.")

        except Exception as e:
            log.error("❌ Schema sync failed: %s", e)

    def add_docs(self, docs: list[dict]):
        self.solr.add(docs)

    def delete_by_filename(self, filename: str) -> bool:
        try:
            self.solr.delete(q=f'source_file:"{filename}"')
            log.info("✅ Deleted chunks for file: %s", filename)
            return True
        except Exception as e:
            log.error("❌ Delete failed for %s: %s", filename, e)
            return False