# """
# app/pipeline/solr.py
# ─────────────────────
# Manages Solr connections and schema synchronisation for two collections:

#   rag_chunks  — stores PDF chunks, vectors, NLP metadata
#   signals     — stores user interaction events for boost learning
# """

# from __future__ import annotations

# import logging
# import requests
# import pysolr

# from app.pipeline.config import AppConfig

# log = logging.getLogger("RAG.Solr")


# # ── Schema definitions ────────────────────────────────────────────────────────

# _CHUNKS_FIELD_TYPES = [
#     {
#         "name":               "knn_vector_384",
#         "class":              "solr.DenseVectorField",
#         "vectorDimension":    384,
#         "similarityFunction": "cosine",
#     }
# ]

# _CHUNKS_FIELDS = [
#     {"name": "doc_id",         "type": "string",           "stored": True,  "indexed": True},
#     {"name": "source_file",    "type": "string",           "stored": True,  "indexed": True},
#     {"name": "page_num",       "type": "pint",             "stored": True,  "indexed": True},
#     {"name": "chunk_index",    "type": "pint",             "stored": True,  "indexed": True},
#     {"name": "content",        "type": "text_general",     "stored": True,  "indexed": True},
#     {"name": "char_count",     "type": "plong",            "stored": True,  "indexed": True},
#     {"name": "metadata",       "type": "string",           "stored": True,  "indexed": False},
#     {"name": "content_vector", "type": "knn_vector_384",   "stored": True,  "indexed": True},
#     {"name": "keywords",       "type": "text_general",     "stored": True,  "indexed": True},
#     {
#         "name":         "entities",
#         "type":         "string",
#         "stored":       True,
#         "indexed":      True,
#         "multiValued":  True,
#     },
# ]

# _SIGNALS_FIELDS = [
#     {"name": "search_id", "type": "string",       "stored": True, "indexed": True},
#     {"name": "query",     "type": "text_general", "stored": True, "indexed": True},
#     {"name": "chunk_id",  "type": "string",       "stored": True, "indexed": True},
#     {"name": "route",     "type": "string",       "stored": True, "indexed": True},
#     {"name": "timestamp", "type": "string",       "stored": True, "indexed": False},
# ]


# # ── SolrManager ───────────────────────────────────────────────────────────────

# class SolrManager:
#     """
#     Owns both Solr connections and handles schema bootstrapping.

#     Attributes
#     ----------
#     chunks  : pysolr.Solr — main RAG chunks collection
#     signals : pysolr.Solr — user interaction signals collection
#     """

#     def __init__(self, config: AppConfig):
#         self.chunks  = pysolr.Solr(config.solr_url,         always_commit=True)
#         self.signals = pysolr.Solr(config.solr_signals_url, always_commit=True)
#         self._chunks_url  = config.solr_url
#         self._signals_url = config.solr_signals_url

#         self._sync_schema(
#             schema_url    = f"{self._chunks_url}/schema",
#             field_types   = _CHUNKS_FIELD_TYPES,
#             fields        = _CHUNKS_FIELDS,
#             label         = "chunks",
#         )
#         self._sync_schema(
#             schema_url    = f"{self._signals_url}/schema",
#             field_types   = [],
#             fields        = _SIGNALS_FIELDS,
#             label         = "signals",
#         )

#     # ── private ───────────────────────────────────────────────────────────────

#     @staticmethod
#     def _sync_schema(
#         schema_url:  str,
#         field_types: list[dict],
#         fields:      list[dict],
#         label:       str,
#     ) -> None:
#         log.info(f"Syncing '{label}' schema at {schema_url} ...")
#         try:
#             # 1 — field types
#             if field_types:
#                 type_resp      = requests.get(
#                     f"{schema_url}/fieldtypes",
#                     timeout=30        # ← changed from 5 to 30
#                 )
#                 existing_types = [
#                     t["name"]
#                     for t in type_resp.json().get("fieldTypes", [])
#                 ] if type_resp.ok else []
#                 to_add = [t for t in field_types if t["name"] not in existing_types]
#                 if to_add:
#                     requests.post(
#                         schema_url,
#                         json={"add-field-type": to_add},
#                         timeout=30    # ← changed from 5 to 30
#                     )
#                     log.info(f"  ✅ Added {len(to_add)} field type(s) to '{label}'.")

#             # 2 — fields
#             resp     = requests.get(
#                 f"{schema_url}/fields",
#                 timeout=30            # ← changed from 5 to 30
#             )
#             existing = [
#                 f["name"] for f in resp.json().get("fields", [])
#             ] if resp.ok else []
#             to_add   = [f for f in fields if f["name"] not in existing]
#             if to_add:
#                 requests.post(
#                     schema_url,
#                     json={"add-field": to_add},
#                     timeout=30        # ← changed from 5 to 30
#                 )
#                 log.info(f"  ✅ Added {len(to_add)} field(s) to '{label}'.")
#             else:
#                 log.info(f"  ✅ '{label}' schema up to date.")

#         except requests.exceptions.Timeout:
#             log.warning(
#                 f"  ⚠️ Schema sync timed out for '{label}'. "
#                 f"Solr may be slow to start — pipeline will retry on next request."
#             )
#         except Exception as exc:
#             log.error(f"  ❌ Schema sync failed for '{label}': {exc}")






"""
app/pipeline/solr.py
"""

from __future__ import annotations

import logging
import threading

import requests
import pysolr

from app.pipeline.config import AppConfig

log = logging.getLogger("RAG.Solr")


_CHUNKS_FIELD_TYPES = [
    {
        "name":               "knn_vector_384",
        "class":              "solr.DenseVectorField",
        "vectorDimension":    384,
        "similarityFunction": "cosine",
    }
]

_CHUNKS_FIELDS = [
    {"name": "doc_id",         "type": "string",           "stored": True,  "indexed": True},
    {"name": "source_file",    "type": "string",           "stored": True,  "indexed": True},
    {"name": "page_num",       "type": "pint",             "stored": True,  "indexed": True},
    {"name": "chunk_index",    "type": "pint",             "stored": True,  "indexed": True},
    {"name": "content",        "type": "text_general",     "stored": True,  "indexed": True},
    {"name": "char_count",     "type": "plong",            "stored": True,  "indexed": True},
    {"name": "metadata",       "type": "string",           "stored": True,  "indexed": False},
    {"name": "content_vector", "type": "knn_vector_384",   "stored": True,  "indexed": True},
    {"name": "keywords",       "type": "text_general",     "stored": True,  "indexed": True},
    {
        "name":        "entities",
        "type":        "string",
        "stored":      True,
        "indexed":     True,
        "multiValued": True,
    },
]

_SIGNALS_FIELDS = [
    {"name": "search_id", "type": "string",       "stored": True, "indexed": True},
    {"name": "query",     "type": "text_general", "stored": True, "indexed": True},
    {"name": "chunk_id",  "type": "string",       "stored": True, "indexed": True},
    {"name": "route",     "type": "string",       "stored": True, "indexed": True},
    {"name": "timestamp", "type": "string",       "stored": True, "indexed": False},
]


class SolrManager:

    def __init__(self, config: AppConfig):
        self.chunks  = pysolr.Solr(config.solr_url,         always_commit=True)
        self.signals = pysolr.Solr(config.solr_signals_url, always_commit=True)
        self._chunks_url  = config.solr_url
        self._signals_url = config.solr_signals_url

        # ── Run schema sync in background so startup never blocks ──────────
        thread = threading.Thread(
            target=self._sync_all_schemas,
            daemon=True    # daemon=True means thread dies if app exits
        )
        thread.start()
        log.info("✅ Solr connections established. Schema sync running in background.")

    def _sync_all_schemas(self):
        """Runs in a background thread — never blocks app startup."""
        self._sync_schema(
            schema_url  = f"{self._chunks_url}/schema",
            field_types = _CHUNKS_FIELD_TYPES,
            fields      = _CHUNKS_FIELDS,
            label       = "chunks",
        )
        self._sync_schema(
            schema_url  = f"{self._signals_url}/schema",
            field_types = [],
            fields      = _SIGNALS_FIELDS,
            label       = "signals",
        )

    @staticmethod
    def _sync_schema(
        schema_url:  str,
        field_types: list[dict],
        fields:      list[dict],
        label:       str,
    ) -> None:
        log.info(f"Syncing '{label}' schema at {schema_url} ...")
        try:
            # 1 — field types
            if field_types:
                type_resp = requests.get(
                    f"{schema_url}/fieldtypes",
                    timeout=30
                )
                existing_types = [
                    t["name"]
                    for t in type_resp.json().get("fieldTypes", [])
                ] if type_resp.ok else []

                to_add = [
                    t for t in field_types
                    if t["name"] not in existing_types
                ]
                if to_add:
                    requests.post(
                        schema_url,
                        json={"add-field-type": to_add},
                        timeout=30
                    )
                    log.info(f"  ✅ Added {len(to_add)} field type(s) to '{label}'.")

            # 2 — fields
            resp     = requests.get(f"{schema_url}/fields", timeout=30)
            existing = [
                f["name"] for f in resp.json().get("fields", [])
            ] if resp.ok else []

            to_add = [f for f in fields if f["name"] not in existing]
            if to_add:
                requests.post(
                    schema_url,
                    json={"add-field": to_add},
                    timeout=30
                )
                log.info(f"  ✅ Added {len(to_add)} field(s) to '{label}'.")
            else:
                log.info(f"  ✅ '{label}' schema up to date.")

        except requests.exceptions.Timeout:
            log.warning(
                f"  ⚠️ Schema sync timed out for '{label}'. "
                f"Will work fine — schema sync will retry on next startup."
            )
        except requests.exceptions.ConnectionError:
            log.warning(
                f"  ⚠️ Could not connect to Solr for '{label}' schema sync. "
                f"Is Solr running at {schema_url}?"
            )
        except Exception as exc:
            log.warning(f"  ⚠️ Schema sync failed for '{label}': {exc}")