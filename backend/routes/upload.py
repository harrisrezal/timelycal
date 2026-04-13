import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from routes.telegram import verify_admin
from services.pdf_parser import parse_pdf
from services.gcs import upload_file
from services.embedder import embed
from services.rag import store_chunks

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5MB


@router.post("/upload")
async def upload_pdf(file: UploadFile = File(...), _: None = Depends(verify_admin)):
    """
    Upload a Caltrain schedule PDF.
    Parses, stores in GCS, embeds with Vertex AI, and saves to Supabase.
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    file_bytes = await file.read()

    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 5MB limit.")

    filename = file.filename

    # 1. Upload raw PDF to GCS
    gcs_uri = upload_file(file_bytes, destination=f"schedules/{filename}")
    logger.info(f"Uploaded to GCS: {gcs_uri}")

    # 2. Parse PDF into text chunks
    chunks = parse_pdf(file_bytes)
    logger.info(f"Parsed {len(chunks)} chunks from {filename}")

    if not chunks:
        raise HTTPException(status_code=422, detail="Could not extract text from PDF.")

    # 3. Embed chunks with Vertex AI
    embeddings = embed(chunks)
    logger.info(f"Generated {len(embeddings)} embeddings")

    # 4. Store in Supabase
    metadata = {"source": filename, "gcs_uri": gcs_uri}
    count = store_chunks(chunks, embeddings, metadata)
    logger.info(f"Stored {count} rows in Supabase")

    return {
        "status": "ok",
        "filename": filename,
        "chunks": len(chunks),
        "gcs_uri": gcs_uri,
    }
