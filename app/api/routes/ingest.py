from fastapi import APIRouter, UploadFile, File, HTTPException
from pathlib import Path
from app.pipeline import pipeline
import shutil

router = APIRouter(prefix="/api/v1", tags=["Ingestion"])

@router.post("/ingest")
async def ingest_pdf(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
        
    saved_file_path = Path("data/uploads") / file.filename
    try:
        with saved_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        num_chunks = pipeline.process_and_ingest(saved_file_path)
        return {"status": "success", "filename": file.filename, "chunks_created": num_chunks}
    except Exception as e:
        if saved_file_path.exists():
            saved_file_path.unlink()
        raise HTTPException(status_code=500, detail=str(e))
