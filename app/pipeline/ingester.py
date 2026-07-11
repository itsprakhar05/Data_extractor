"""
app/pipeline/ingester.py
------------------------
Handles the full PDF ingestion pipeline:
    PDF → OpenDataLoader → Markdown → Chunks → Embeddings → Solr
"""

import os
import json
import uuid
import logging
from pathlib import Path

import opendataloader_pdf

from app.pipeline.embedder  import embed_batch
from app.pipeline.retriever import Retriever

log = logging.getLogger("RAG_Pipeline")

TARGET_CHUNK_WORDS = 300


def _is_table_block(block: str) -> bool:
    return any("|" in line for line in block.splitlines())


def _chunk_markdown(markdown: str) -> list[dict]:
    """
    Split markdown text into chunks, keeping table blocks intact.

    Returns:
        List of dicts: {"text": str, "is_table": bool}
    """
    raw_blocks    = markdown.split("\n\n")
    chunks        = []
    current_chunk = []
    current_words = 0

    for block in raw_blocks:
        if not block.strip():
            continue
        block_words = len(block.split())

        if _is_table_block(block):
            if current_chunk:
                chunks.append({"text": "\n\n".join(current_chunk), "is_table": False})
                current_chunk, current_words = [], 0
            chunks.append({"text": block, "is_table": True})
            continue

        if current_words + block_words > TARGET_CHUNK_WORDS and current_chunk:
            chunks.append({"text": "\n\n".join(current_chunk), "is_table": False})
            current_chunk, current_words = [block], block_words
        else:
            current_chunk.append(block)
            current_words += block_words

    if current_chunk:
        chunks.append({"text": "\n\n".join(current_chunk), "is_table": False})

    return chunks


def ingest_pdf(pdf_path: Path, retriever: Retriever) -> int:
    """
    Full ingestion pipeline for a single PDF.

    Args:
        pdf_path:  Path to the uploaded PDF file
        retriever: Retriever instance (for uploading docs to Solr)

    Returns:
        Number of chunks ingested
    """
    doc_id    = str(uuid.uuid4())
    file_stem = pdf_path.stem
    temp_dir  = Path("data/temp_extraction")
    temp_dir.mkdir(parents=True, exist_ok=True)
    extracted_md = temp_dir / f"{file_stem}.md"

    # Step 1 — Extract PDF to Markdown
    log.info("[Ingester] Extracting: %s", pdf_path.name)
    try:
        opendataloader_pdf.convert(
            input_path=[str(pdf_path.resolve())],
            output_dir=str(temp_dir.resolve()),
            format="markdown"
        )
    except Exception as e:
        log.error("❌ OpenDataLoader failed: %s", e)
        raise RuntimeError(f"PDF extraction failed: {e}")

    if not extracted_md.exists():
        raise FileNotFoundError(f"Expected markdown not found: {extracted_md}")

    # Step 2 — Chunk markdown
    full_markdown = extracted_md.read_text(encoding="utf-8")
    chunks        = _chunk_markdown(full_markdown)
    log.info("[Ingester] %d chunks created.", len(chunks))

    # Step 3 — Batch embed all chunks
    texts   = [c["text"] for c in chunks]
    vectors = embed_batch(texts)

    # Step 4 — Build Solr docs
    solr_docs = []
    for idx, (chunk, vector) in enumerate(zip(chunks, vectors)):
        solr_docs.append({
            "id":             f"{file_stem}_p0_c{idx}",
            "doc_id":         doc_id,
            "source_file":    pdf_path.name,
            "page_num":       0,
            "chunk_index":    idx,
            "content":        chunk["text"],
            "content_vector": vector,
            "char_count":     len(chunk["text"]),
            "metadata":       json.dumps({
                "file_type": "pdf",
                "parser":    "native-opendataloader-markdown",
                "is_table":  chunk["is_table"],
            }, ensure_ascii=False),
        })

    # Step 5 — Save JSON backup
    cache_path = Path("data/json_chunks") / f"{file_stem}_chunks.json"
    cache_path.write_text(
        json.dumps(solr_docs, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Step 6 — Upload to Solr
    log.info("[Ingester] Uploading %d chunks to Solr...", len(solr_docs))
    retriever.add_docs(solr_docs)

    # Cleanup temp file
    if extracted_md.exists():
        extracted_md.unlink()

    return len(solr_docs)