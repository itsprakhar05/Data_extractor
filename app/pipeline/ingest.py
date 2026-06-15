"""
app/pipeline/ingest.py
───────────────────────
Handles the full PDF → Solr ingestion pipeline in three layers:

  Layer 1 — PDF extraction
      OpenDataLoader converts the PDF to Markdown, preserving tables,
      headings, and layout structure better than raw text extraction.

  Layer 2 — Chunking
      Splits the Markdown into ~300-word chunks.
      Tables are always kept as isolated chunks (never split mid-row).

  Layer 3 — NLP enrichment + Solr upload
      Each chunk is:
        • embedded  (SentenceTransformer → 384-dim vector)
        • enriched  (YAKE keywords + spaCy NER entities)
        • uploaded  to Solr with all fields populated
      Keywords are also fed back to the AutocompleteManager Trie.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path

import opendataloader_pdf
from sentence_transformers import SentenceTransformer

from app.pipeline.nlp import NLPProcessor
from app.pipeline.autocomplete import AutocompleteManager

import pysolr

log = logging.getLogger("RAG.Ingest")


class IngestManager:
    """
    Converts a PDF file into enriched chunks and stores them in Solr.
    """

    _TEMP_DIR       = Path("data/temp_extraction")
    _CHUNKS_DIR     = Path("data/json_chunks")
    _UPLOADS_DIR    = Path("data/uploads")

    def __init__(
        self,
        solr_chunks:    pysolr.Solr,
        embedder:       SentenceTransformer,
        nlp:            NLPProcessor,
        autocomplete:   AutocompleteManager,
        target_words:   int = 300,
    ):
        self._solr          = solr_chunks
        self._embedder      = embedder
        self._nlp           = nlp
        self._autocomplete  = autocomplete
        self._target_words  = target_words

        # Ensure working directories exist
        for d in (self._temp_dir, self._chunks_dir, self._uploads_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ── directory properties (class-level defaults, overridable) ─────────────
    @property
    def _temp_dir(self):    return self._TEMP_DIR
    @property
    def _chunks_dir(self):  return self._CHUNKS_DIR
    @property
    def _uploads_dir(self): return self._UPLOADS_DIR

    # ── public ────────────────────────────────────────────────────────────────

    def ingest(self, pdf_path: Path) -> int:
        """
        Full ingestion pipeline for one PDF file.
        Returns the number of chunks successfully uploaded to Solr.
        """
        doc_id    = str(uuid.uuid4())
        file_stem = pdf_path.stem

        markdown      = self._extract_markdown(pdf_path, file_stem)
        chunks        = self._chunk_markdown(markdown)
        solr_docs     = self._build_solr_docs(chunks, pdf_path, file_stem, doc_id)

        self._save_json_backup(solr_docs, file_stem)
        self._upload_to_solr(solr_docs)

        # Feed keywords back to autocomplete Trie
        all_keywords = [
            kw
            for doc in solr_docs
            for kw in doc.get("keywords", "").split(", ")
            if kw.strip()
        ]
        self._autocomplete.add_keywords(all_keywords)

        log.info(f"✅ Ingestion complete: {len(solr_docs)} chunks for '{pdf_path.name}'")
        return len(solr_docs)

    def delete(self, filename: str) -> bool:
        """Remove all Solr chunks belonging to a given source file."""
        try:
            self._solr.delete(q=f'source_file:"{filename}"')
            log.info(f"✅ Deleted all chunks for '{filename}'")
            return True
        except Exception as exc:
            log.error(f"❌ Delete failed for '{filename}': {exc}")
            return False

    def list_documents(self) -> list[dict]:
        """Return one record per distinct ingested file."""
        try:
            results = self._solr.search("*:*", fl="source_file,doc_id", rows=10_000)
            seen: dict[str, str] = {}
            for doc in results:
                sf = doc.get("source_file", "")
                if sf and sf not in seen:
                    seen[sf] = doc.get("doc_id", "")
            return [{"filename": k, "doc_id": v} for k, v in seen.items()]
        except Exception as exc:
            log.error(f"list_documents failed: {exc}")
            return []

    def get_chunks_for_file(self, filename: str) -> list[dict]:
        """Return all stored chunks for a given filename."""
        try:
            results = self._solr.search(
                f'source_file:"{filename}"',
                fl="id,chunk_index,content,keywords,entities,char_count",
                rows=1_000,
            )
            return list(results)
        except Exception as exc:
            log.error(f"get_chunks_for_file failed: {exc}")
            return []

    # ── Layer 1 — PDF extraction ──────────────────────────────────────────────

    def _extract_markdown(self, pdf_path: Path, file_stem: str) -> str:
        extracted_md = self._temp_dir / f"{file_stem}.md"
        log.info(f"[Layer 1] Extracting Markdown from '{pdf_path.name}'...")

        try:
            opendataloader_pdf.convert(
                input_path=[str(pdf_path.resolve())],
                output_dir=str(self._temp_dir.resolve()),
                format="markdown",
            )
        except Exception as exc:
            self._cleanup_temp(self._temp_dir)
            raise RuntimeError(f"OpenDataLoader extraction failed: {exc}") from exc

        if not extracted_md.exists():
            raise FileNotFoundError(
                f"OpenDataLoader did not produce expected file: {extracted_md}"
            )

        text = extracted_md.read_text(encoding="utf-8")
        extracted_md.unlink()                          # remove temp file
        self._cleanup_temp(self._temp_dir)
        return text

    # ── Layer 2 — Chunking ────────────────────────────────────────────────────

    def _chunk_markdown(self, markdown: str) -> list[str]:
        """
        Split Markdown into chunks of ~target_words words.
        Tables (blocks containing '|') are always isolated as their own chunk.
        """
        log.info("[Layer 2] Chunking Markdown...")

        raw_blocks      = markdown.split("\n\n")
        chunks:         list[str] = []
        current_chunk:  list[str] = []
        current_words:  int       = 0

        for block in raw_blocks:
            if not block.strip():
                continue

            block_words = len(block.split())

            if self._is_table(block):
                # Flush current chunk first, then add table as its own chunk
                if current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk, current_words = [], 0
                chunks.append(block)
                continue

            if current_words + block_words > self._target_words and current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk, current_words = [block], block_words
            else:
                current_chunk.append(block)
                current_words += block_words

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        log.info(f"[Layer 2] {len(chunks)} chunks created.")
        return chunks

    @staticmethod
    def _is_table(block: str) -> bool:
        return any("|" in line for line in block.splitlines())

    # ── Layer 3 — NLP enrichment + Solr doc building ─────────────────────────

    def _build_solr_docs(
        self,
        chunks:     list[str],
        pdf_path:   Path,
        file_stem:  str,
        doc_id:     str,
    ) -> list[dict]:
        log.info(f"[Layer 3] Enriching {len(chunks)} chunks (embed + NLP)...")
        solr_docs: list[dict] = []

        for idx, chunk_text in enumerate(chunks):
            if not chunk_text.strip():
                continue

            vector    = self._embedder.encode(chunk_text).tolist()
            keywords  = self._nlp.extract_keywords(chunk_text)
            entities  = self._nlp.extract_entities(chunk_text)
            tags      = self._nlp.entities_to_tags(entities)
            is_table  = self._is_table(chunk_text)

            solr_docs.append({
                "id":             f"{file_stem}_p0_c{idx}",
                "doc_id":         doc_id,
                "source_file":    pdf_path.name,
                "page_num":       0,
                "chunk_index":    idx,
                "content":        chunk_text,
                "content_vector": vector,
                "char_count":     len(chunk_text),
                "keywords":       ", ".join(keywords),
                "entities":       tags,
                "metadata": json.dumps({
                    "file_type": "pdf",
                    "parser":    "opendataloader-markdown",
                    "is_table":  is_table,
                    "entities":  entities,
                }, ensure_ascii=False),
            })

        return solr_docs

    # ── helpers ───────────────────────────────────────────────────────────────

    def _save_json_backup(self, solr_docs: list[dict], file_stem: str) -> None:
        out = self._chunks_dir / f"{file_stem}_chunks.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(solr_docs, f, indent=2, ensure_ascii=False)
        log.debug(f"JSON backup saved: {out}")

    def _upload_to_solr(self, solr_docs: list[dict]) -> None:
        log.info(f"[Layer 3] Uploading {len(solr_docs)} chunks to Solr...")
        self._solr.add(solr_docs)

    @staticmethod
    def _cleanup_temp(temp_dir: Path) -> None:
        if temp_dir.exists() and not os.listdir(temp_dir):
            os.rmdir(temp_dir)