from fastapi import APIRouter, UploadFile, File, HTTPException
from pathlib import Path
from app.pipeline import pipeline
import shutil

router = APIRouter(prefix="/api/v1", tags=["Ingestion"])

@router.post("/ingest")
async def ingest_pdf(file: UploadFile = File(...)):
    filename = file.filename

    # ── Fix: remove double .pdf extension ──
    if filename.lower().endswith(".pdf.pdf"):
        filename = filename[:-4]   # remove the extra .pdf

    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    saved_file_path = Path("data/uploads") / filename
    try:
        with saved_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        num_chunks = pipeline.process_and_ingest(saved_file_path)
        return {
            "status":         "success",
            "filename":       filename,
            "chunks_created": num_chunks
        }
    except Exception as e:
        if saved_file_path.exists():
            saved_file_path.unlink()
        raise HTTPException(status_code=500, detail=str(e))
