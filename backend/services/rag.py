import os
from google import genai
from supabase import create_client, Client

from services.embedder import embed

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


def _client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def store_chunks(chunks: list[str], embeddings: list[list[float]], metadata: dict) -> int:
    """Store text chunks and their embeddings in Supabase. Returns number of rows inserted."""
    client = _client()
    rows = [
        {"content": chunk, "embedding": embedding, "metadata": metadata}
        for chunk, embedding in zip(chunks, embeddings)
    ]
    result = client.table("documents").insert(rows).execute()
    return len(result.data)


def similarity_search(query_embedding: list[float], match_count: int = 5) -> list[dict]:
    """Find the most similar chunks to a query embedding via pgvector."""
    client = _client()
    result = client.rpc(
        "match_documents",
        {"query_embedding": query_embedding, "match_count": match_count},
    ).execute()
    return result.data


_STOPWORDS = {
    "what", "when", "where", "which", "who", "how", "does", "do", "did",
    "the", "a", "an", "is", "are", "was", "were", "will", "would", "can",
    "could", "from", "to", "at", "on", "in", "of", "for", "and", "or",
    "that", "this", "it", "its", "time", "train", "trains", "leave",
    "depart", "arrive", "next", "first", "last", "caltrain", "station",
}


def _text_search(client: "Client", keywords: list[str]) -> list[dict]:
    """Fetch all chunks whose content contains any of the given keywords."""
    seen_ids: set = set()
    results = []
    for kw in keywords:
        rows = (
            client.table("documents")
            .select("id, content, metadata")
            .ilike("content", f"%{kw}%")
            .execute()
        ).data
        for row in rows:
            if row["id"] not in seen_ids:
                seen_ids.add(row["id"])
                results.append(row)
    return results


def query(question: str) -> str:
    """Embed question → similarity search + text search → Gemini Flash answer."""
    # 1. Embed the question
    question_embedding = embed([question])[0]

    # 2a. Vector similarity search
    vector_chunks = similarity_search(question_embedding, match_count=10)

    # 2b. Text search: find ALL chunks containing significant words from the question
    words = [w.strip("?.,!").lower() for w in question.split()]
    keywords = [w for w in words if len(w) > 4 and w not in _STOPWORDS]
    db = _client()
    text_chunks = _text_search(db, keywords) if keywords else []

    # 2c. Merge and sort chronologically by DB insertion order (id) so Gemini
    # sees trains in timetable order — makes first/last train queries accurate.
    seen_ids = {c["id"] for c in vector_chunks}
    extra_chunks = [c for c in text_chunks if c["id"] not in seen_ids]
    chunks = sorted(vector_chunks + extra_chunks, key=lambda c: c["id"])

    if not chunks:
        return "I couldn't find relevant schedule information. Please try rephrasing your question."

    # 3. Build context from retrieved chunks, labelled by schedule type
    def _schedule_label(source: str) -> str:
        if "weekend" in source.lower():
            return "[Weekend Schedule]"
        if "weekday" in source.lower():
            return "[Weekday Schedule]"
        return "[Schedule]"

    context = "\n\n".join(
        f"{_schedule_label(c['metadata'].get('source', ''))}\n{c['content']}"
        for c in chunks
    )

    # 4. Call Gemini Flash via Google AI Studio
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""You are TimelyCal, a helpful Caltrain schedule assistant.
Answer the user's question using only the schedule information provided below.
Be concise and specific. Include train numbers and exact times when available.
If the answer isn't in the schedule data, say so honestly.

Schedule Data:
{context}

Question: {question}
Answer:"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return response.text
