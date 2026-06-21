# """
# pipeline_run.py
# Run as: python pipeline_run.py <stage>
# Stages: extract | chunk | embed | ingest
# """
# import sys
# import json
# import logging
# import uuid
# import time
# import requests
# import pysolr
# from pathlib import Path

# logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
# log = logging.getLogger("pipeline")

# cfg = json.load(open("config/config.json"))


# def extract():
#     import opendataloader_pdf
#     temp_dir = Path("data/temp_extraction")
#     uploads  = Path("data/uploads")
#     temp_dir.mkdir(parents=True, exist_ok=True)

#     pdfs = list(uploads.glob("*.pdf"))
#     if not pdfs:
#         log.warning("No PDFs found in data/uploads/")
#         return

#     for pdf in pdfs:
#         out_md = temp_dir / (pdf.stem + ".md")
#         if out_md.exists():
#             log.info(f"Skip {pdf.name} (already extracted)")
#             continue
#         log.info(f"Extracting {pdf.name}")
#         opendataloader_pdf.convert(
#             input_path=[str(pdf.resolve())],
#             output_dir=str(temp_dir.resolve()),
#             format="markdown"
#         )
#     log.info(f"Extract done. {len(pdfs)} file(s).")


# def chunk():
#     target_words = 300
#     temp_dir = Path("data/temp_extraction")
#     out_dir  = Path("data/json_chunks")
#     out_dir.mkdir(parents=True, exist_ok=True)

#     def is_table(block):
#         return any("|" in l for l in block.splitlines())

#     def chunk_md(text):
#         chunks, cur, cw = [], [], 0
#         for block in text.split("\n\n"):
#             if not block.strip():
#                 continue
#             bw = len(block.split())
#             if is_table(block):
#                 if cur:
#                     chunks.append("\n\n".join(cur))
#                     cur, cw = [], 0
#                 chunks.append(block)
#                 continue
#             if cw + bw > target_words and cur:
#                 chunks.append("\n\n".join(cur))
#                 cur, cw = [block], bw
#             else:
#                 cur.append(block)
#                 cw += bw
#         if cur:
#             chunks.append("\n\n".join(cur))
#         return chunks

#     total = 0
#     for md in temp_dir.glob("*.md"):
#         text   = md.read_text(encoding="utf-8")
#         chunks = chunk_md(text)
#         docs   = [
#             {
#                 "id":          f"{md.stem}_c{i}",
#                 "doc_id":      str(uuid.uuid4()),
#                 "chunk_index": i,
#                 "source_file": md.stem + ".pdf",
#                 "page_num":    0,
#                 "content":     c,
#                 "char_count":  len(c),
#                 "is_table":    is_table(c),
#             }
#             for i, c in enumerate(chunks) if c.strip()
#         ]
#         out = out_dir / f"{md.stem}_chunks.json"
#         out.write_text(json.dumps(docs, indent=2, ensure_ascii=False), encoding="utf-8")
#         log.info(f"{md.name} -> {len(docs)} chunks")
#         total += len(docs)

#     log.info(f"Chunk done. {total} total chunks.")


# def embed():
#     from sentence_transformers import SentenceTransformer

#     in_dir  = Path("data/json_chunks")
#     out_dir = Path("data/embedded_chunks")
#     out_dir.mkdir(parents=True, exist_ok=True)

#     log.info("Loading all-MiniLM-L6-v2 ...")
#     model = SentenceTransformer("all-MiniLM-L6-v2")

#     total = 0
#     for cf in in_dir.glob("*_chunks.json"):
#         chunks  = json.loads(cf.read_text(encoding="utf-8"))
#         texts   = [c["content"] for c in chunks]
#         vectors = model.encode(texts, show_progress_bar=True, batch_size=32).tolist()
#         for c, v in zip(chunks, vectors):
#             c["content_vector"] = v
#         out = out_dir / cf.name.replace("_chunks", "_embedded")
#         out.write_text(json.dumps(chunks, indent=2, ensure_ascii=False), encoding="utf-8")
#         log.info(f"{cf.name} -> {len(chunks)} embedded")
#         total += len(chunks)

#     log.info(f"Embed done. {total} chunks embedded.")


# def ingest():
#     solr_url   = cfg["solr_url"]
#     solr       = pysolr.Solr(solr_url, always_commit=True)
#     in_dir     = Path("data/embedded_chunks")
#     metrics_path = Path("data/metrics/ingest_metrics.json")
#     metrics_path.parent.mkdir(parents=True, exist_ok=True)

#     schema_url = f"{solr_url}/schema"
#     try:
#         existing_types = [
#             t["name"]
#             for t in requests.get(f"{schema_url}/fieldtypes", timeout=5)
#                               .json().get("fieldTypes", [])
#         ]
#         if "knn_vector_384" not in existing_types:
#             requests.post(schema_url, json={"add-field-type": [{
#                 "name": "knn_vector_384",
#                 "class": "solr.DenseVectorField",
#                 "vectorDimension": 384,
#                 "similarityFunction": "cosine"
#             }]}, timeout=5)
#             log.info("Created knn_vector_384 field type")

#         existing = [
#             f["name"]
#             for f in requests.get(f"{schema_url}/fields", timeout=5)
#                               .json().get("fields", [])
#         ]
#         needed = [
#             f for f in [
#                 {"name": "doc_id",         "type": "string",         "stored": True,  "indexed": True},
#                 {"name": "source_file",    "type": "string",         "stored": True,  "indexed": True},
#                 {"name": "page_num",       "type": "pint",           "stored": True,  "indexed": True},
#                 {"name": "chunk_index",    "type": "pint",           "stored": True,  "indexed": True},
#                 {"name": "content",        "type": "text_general",   "stored": True,  "indexed": True},
#                 {"name": "char_count",     "type": "plong",          "stored": True,  "indexed": True},
#                 {"name": "metadata",       "type": "string",         "stored": True,  "indexed": False},
#                 {"name": "content_vector", "type": "knn_vector_384", "stored": True,  "indexed": True},
#             ]
#             if f["name"] not in existing
#         ]
#         if needed:
#             requests.post(schema_url, json={"add-field": needed}, timeout=5)
#             log.info(f"Added {len(needed)} fields")
#         else:
#             log.info("Schema up to date")
#     except Exception as e:
#         log.error(f"Schema sync failed: {e}")

#     result = {"files": [], "total_chunks": 0, "total_errors": 0}
#     t0 = time.time()

#     for ef in in_dir.glob("*_embedded.json"):
#         chunks = json.loads(ef.read_text(encoding="utf-8"))
#         docs   = [
#             {
#                 "id":             c["id"],
#                 "doc_id":         c["doc_id"],
#                 "source_file":    c.get("source_file", "unknown.pdf"),
#                 "page_num":       c.get("page_num", 0),
#                 "chunk_index":    c["chunk_index"],
#                 "content":        c["content"],
#                 "content_vector": c["content_vector"],
#                 "char_count":     c["char_count"],
#                 "metadata":       json.dumps({"is_table": c.get("is_table", False)}),
#             }
#             for c in chunks
#         ]
#         try:
#             solr.add(docs)
#             log.info(f"Ingested {len(docs)} docs from {ef.name}")
#             result["files"].append({"file": ef.name, "chunks": len(docs), "status": "ok"})
#             result["total_chunks"] += len(docs)
#         except Exception as e:
#             log.error(f"Failed {ef.name}: {e}")
#             result["files"].append({"file": ef.name, "chunks": 0, "status": "error", "error": str(e)})
#             result["total_errors"] += 1

#     result["elapsed_seconds"] = round(time.time() - t0, 2)
#     metrics_path.write_text(json.dumps(result, indent=2))
#     log.info(f"Ingest done. {result['total_chunks']} chunks in {result['elapsed_seconds']}s")


# stages = {"extract": extract, "chunk": chunk, "embed": embed, "ingest": ingest}

# if len(sys.argv) < 2 or sys.argv[1] not in stages:
#     print(f"Usage: python pipeline_run.py <stage>")
#     print(f"Stages: {', '.join(stages)}")
#     sys.exit(1)

# stages[sys.argv[1]]()