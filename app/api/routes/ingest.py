# from fastapi import APIRouter, UploadFile, File, HTTPException
# from pathlib import Path
# from app.pipeline import pipeline
# import shutil

# router = APIRouter(prefix="/api/v1", tags=["Ingestion"])

# @router.post("/ingest")
# async def ingest_pdf(file: UploadFile = File(...)):
#     if not file.filename.endswith(".pdf"):
#         raise HTTPException(status_code=400, detail="Only PDF files are supported.")

#     saved_path = Path("data/uploads") / file.filename
#     try:
#         with saved_path.open("wb") as buffer:
#             shutil.copyfileobj(file.file, buffer)

#         num_chunks = pipeline.process_and_ingest(saved_path)
#         return {"status": "success", "filename": file.filename, "chunks_created": num_chunks}
#     except Exception as e:
#         if saved_path.exists():
#             saved_path.unlink()
#         raise HTTPException(status_code=500, detail=str(e))




"""
app/api/routes/ingest.py
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from pathlib import Path
import shutil

from app.pipeline.orchestrator import RagPipeline
from app.core.dependency import get_pipeline

router = APIRouter(prefix="/api/v1", tags=["Ingestion"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/ingest")
@limiter.limit("5/minute")
async def ingest_pdf(
    request: Request,
    file: UploadFile = File(...),
    pipeline: RagPipeline = Depends(get_pipeline),   # injected singleton
):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    saved_path = Path("data/uploads") / file.filename
    try:
        with saved_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        num_chunks = pipeline.process_and_ingest(saved_path)
        return {"status": "success", "filename": file.filename, "chunks_created": num_chunks}
    except Exception as e:
        if saved_path.exists():
            saved_path.unlink()
        raise HTTPException(status_code=500, detail=str(e))