"""
FastAPI + Google Cloud Storage
File upload and download service
"""
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from google.cloud import storage
from typing import List
import os
import io

app = FastAPI(title="GCS File Service")

# Initialize GCS client
# TODO: use workload identity instead of service account file
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/app/secrets/gcp-service-account.json"

storage_client = storage.Client()
BUCKET_NAME = "my-app-uploads-prod"

# Get or create bucket
try:
    bucket = storage_client.get_bucket(BUCKET_NAME)
except:
    # TODO: handle bucket creation more gracefully
    bucket = storage_client.create_bucket(BUCKET_NAME)

@app.get("/")
async def root():
    return {
        "message": "GCS File Service API",
        "bucket": BUCKET_NAME,
        "project": storage_client.project
    }

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), folder: str = "uploads"):
    """
    Upload a file to Google Cloud Storage
    """
    # TODO: add file size limit
    # TODO: add file type validation
    # TODO: sanitize filename to prevent path traversal

    try:
        # Read file content
        contents = await file.read()

        # Create blob path
        blob_path = f"{folder}/{file.filename}"
        blob = bucket.blob(blob_path)

        # Upload to GCS
        blob.upload_from_string(
            contents,
            content_type=file.content_type
        )

        # Make it publicly accessible (TODO: add access control)
        blob.make_public()

        return {
            "filename": file.filename,
            "path": blob_path,
            "size": len(contents),
            "public_url": blob.public_url,
            "message": "File uploaded successfully"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

@app.post("/upload/batch")
async def upload_multiple_files(files: List[UploadFile] = File(...)):
    """
    Upload multiple files at once
    """
    results = []

    for file in files:
        try:
            contents = await file.read()
            blob_path = f"uploads/{file.filename}"
            blob = bucket.blob(blob_path)

            blob.upload_from_string(contents, content_type=file.content_type)

            results.append({
                "filename": file.filename,
                "status": "success",
                "path": blob_path
            })
        except Exception as e:
            results.append({
                "filename": file.filename,
                "status": "failed",
                "error": str(e)
            })

    return {"results": results, "total": len(files)}

@app.get("/download/{folder}/{filename}")
async def download_file(folder: str, filename: str):
    """
    Download a file from GCS
    """
    try:
        blob_path = f"{folder}/{filename}"
        blob = bucket.blob(blob_path)

        if not blob.exists():
            raise HTTPException(status_code=404, detail="File not found")

        # Download as bytes
        content = blob.download_as_bytes()

        # Return as streaming response
        return StreamingResponse(
            io.BytesIO(content),
            media_type=blob.content_type or "application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

@app.get("/list")
async def list_files(folder: str = "uploads", limit: int = 100):
    """
    List files in a folder
    """
    try:
        blobs = bucket.list_blobs(prefix=folder, max_results=limit)

        files = []
        for blob in blobs:
            files.append({
                "name": blob.name,
                "size": blob.size,
                "created": blob.time_created.isoformat() if blob.time_created else None,
                "content_type": blob.content_type,
                "public_url": blob.public_url if blob.public_url else None
            })

        return {
            "folder": folder,
            "count": len(files),
            "files": files
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/delete/{folder}/{filename}")
async def delete_file(folder: str, filename: str):
    """
    Delete a file from GCS
    """
    # TODO: add authentication before enabling in production
    try:
        blob_path = f"{folder}/{filename}"
        blob = bucket.blob(blob_path)

        if not blob.exists():
            raise HTTPException(status_code=404, detail="File not found")

        blob.delete()

        return {"message": "File deleted successfully", "path": blob_path}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Check if we can access the bucket
        bucket.exists()
        return {
            "status": "ok",
            "bucket": BUCKET_NAME,
            "project": storage_client.project
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
