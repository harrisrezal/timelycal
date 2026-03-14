import os
import vertexai
from vertexai.language_models import TextEmbeddingModel

PROJECT_ID = os.environ.get("GCP_PROJECT", "my-telegram-bot-001")
REGION = os.environ.get("GCP_REGION", "us-central1")
MODEL = "text-embedding-004"


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a list of text chunks using Vertex AI. Returns list of 768-dim vectors."""
    vertexai.init(project=PROJECT_ID, location=REGION)
    model = TextEmbeddingModel.from_pretrained(MODEL)

    # Use small batches to stay within the 20k token limit per request
    all_embeddings = []
    for i in range(0, len(texts), 20):
        batch = texts[i:i + 20]
        results = model.get_embeddings(batch)
        all_embeddings.extend([r.values for r in results])

    return all_embeddings
