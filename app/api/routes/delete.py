from fastapi import APIRouter, HTTPException
from app.pipeline import pipeline
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["Deletion"])

class DeleteDocRequest(BaseModel):
    filename: str

@router.delete("/delete")
async def delete_file(payload: DeleteDocRequest):
    file_name = payload.filename.strip()
    if not file_name:
        raise HTTPException(status_code=400, detail="Filename cannot be empty.")

    success = pipeline.delete_document_by_name(file_name)

    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to delete document '{file_name}' from Solr.")
    
    
    return {
        "status": "success",
        "message": f"Successfully deleted all text chunks for file: '{file_name}' from Solr."
    }