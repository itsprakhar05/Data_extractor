# # from fastapi import APIRouter, UploadFile, File, HTTPException
# # from pathlib import Path
# # from app.pipeline import pipeline
# # import shutil

# # router = APIRouter(prefix="/api/v1", tags=["Ingestion"])

# # @router.post("/ingest")
# # async def ingest_pdf(file: UploadFile = File(...)):
# #     if not file.filename.endswith(".pdf"):
# #         raise HTTPException(status_code=400, detail="Only PDF files are supported.")

# #     saved_path = Path("data/uploads") / file.filename
# #     try:
# #         with saved_path.open("wb") as buffer:
# #             shutil.copyfileobj(file.file, buffer)

# #         num_chunks = pipeline.process_and_ingest(saved_path)
# #         return {"status": "success", "filename": file.filename, "chunks_created": num_chunks}
# #     except Exception as e:
# #         if saved_path.exists():
# #             saved_path.unlink()
# #         raise HTTPException(status_code=500, detail=str(e))




# """
# app/api/routes/ingest.py
# """

# from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
# from slowapi import Limiter
# from slowapi.util import get_remote_address
# from pathlib import Path
# import shutil

# from app.pipeline.orchestrator import RagPipeline
# from app.core.dependency import get_pipeline

# router = APIRouter(prefix="/api/v1", tags=["Ingestion"])
# limiter = Limiter(key_func=get_remote_address)


# @router.post("/ingest")
# @limiter.limit("5/minute")
# async def ingest_pdf(
#     request: Request,
#     file: UploadFile = File(...),
#     pipeline: RagPipeline = Depends(get_pipeline),   # injected singleton
# ):
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
from app.core.security import get_current_user_id

router = APIRouter(prefix="/api/v1", tags=["Ingestion"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/ingest")
@limiter.limit("5/minute")
async def ingest_pdf(
    request: Request,
    file: UploadFile = File(...),
    pipeline: RagPipeline = Depends(get_pipeline),      # injected singleton
    user_id: str = Depends(get_current_user_id),        # requires a valid JWT
):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    # Path(...).name strips any directory components — closes the
    # path-traversal gap where file.filename like "../../.env" could
    # write outside data/uploads/.
    safe_name = Path(file.filename).name
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    # Namespace uploads per-user on disk, not just in Solr.
    user_upload_dir = Path("data/uploads") / user_id
    user_upload_dir.mkdir(parents=True, exist_ok=True)
    saved_path = user_upload_dir / safe_name

    try:
        with saved_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        num_chunks = pipeline.process_and_ingest(saved_path, user_id)
        return {"status": "success", "filename": safe_name, "chunks_created": num_chunks}
    except Exception as e:
        if saved_path.exists():
            saved_path.unlink()
        raise HTTPException(status_code=500, detail=str(e))