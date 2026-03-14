import os
from google.cloud import storage

BUCKET_NAME = os.environ.get("GCS_BUCKET", "timelycal-pdfs")


def upload_file(file_bytes: bytes, destination: str) -> str:
    """Upload bytes to GCS and return the public gs:// URI."""
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(destination)
    blob.upload_from_string(file_bytes, content_type="application/pdf")
    return f"gs://{BUCKET_NAME}/{destination}"


def download_file(source: str) -> bytes:
    """Download a file from GCS and return its bytes."""
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(source)
    return blob.download_as_bytes()
