import json
import os
from datetime import datetime
from google import genai
from supabase import create_client, Client
import pytz

from services.embedder import embed
from services.schedule import STATIONS, get_travel_times, get_arrive_by, count_stops, _train_label

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

PACIFIC = pytz.timezone("America/Los_Angeles")

_INTENT_FALLBACK = {
    "station": None,
    "from_station": None,
    "to_station": None,
    "target_time": None,
    "direction": None,
    "day_type": None,
    "query_type": "general",
    "time_context": None,
}


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


def extract_intent(question: str) -> dict:
    """
    Use Gemini to parse the user's question into a structured intent dict.
    Returns _INTENT_FALLBACK on any failure so query() always has a safe value.
    """
    now = datetime.now(PACIFIC)
    day_of_week = now.strftime("%A")  # e.g. "Monday"
    current_time = now.strftime("%I:%M %p")  # e.g. "09:15 AM"
    stations_list = ", ".join(STATIONS)

    extraction_prompt = f"""You are a Caltrain query parser. Extract structured information from the user's question.

Known stations: {stations_list}

Today is {day_of_week}. Current time is {current_time} PT.

Detect these query patterns:
- "next train" / "when is the next" → query_type: "next_train"
- "first train" / "earliest" → query_type: "first_train"
- "last train" / "latest" → query_type: "last_train"
- "full schedule" / "all trains" / "timetable" → query_type: "full_schedule"
- "how many stops" / "how far" between two stations → query_type: "stops_count"
- "how long" / "travel time" / "how much time" between two stations → query_type: "travel_duration"
- "arrive by" / "need to arrive" / "get there by" / "be there by" / "need to be at" → query_type: "arrive_by", extract target_time
- Otherwise → query_type: "general"

Return JSON only, no explanation, no markdown:
{{
  "station": "<single station for next/first/last train queries, or null>",
  "from_station": "<origin station for stops_count/travel_duration/arrive_by queries, or null>",
  "to_station": "<destination station for stops_count/travel_duration/arrive_by queries, or null>",
  "target_time": "<target arrival time like '6:00pm', only for arrive_by queries, else null>",
  "direction": "<'sf' if heading toward San Francisco, 'sj' if toward San Jose, or null if unclear>",
  "day_type": "<'weekday' or 'weekend' based on today or what user specified>",
  "query_type": "<'next_train', 'first_train', 'last_train', 'full_schedule', 'stops_count', 'travel_duration', 'arrive_by', or 'general'>",
  "time_context": "<'morning', 'afternoon', 'evening', or null>"
}}

Question: {question}"""

    try:
        gemini = genai.Client(api_key=GEMINI_API_KEY)
        response = gemini.models.generate_content(
            model="gemini-2.5-flash",
            contents=extraction_prompt,
        )
        raw = response.text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        intent = json.loads(raw.strip())
        # Validate required keys are present
        for key in _INTENT_FALLBACK:
            if key not in intent:
                intent[key] = _INTENT_FALLBACK[key]
        return intent
    except Exception:
        return dict(_INTENT_FALLBACK)


def query(question: str) -> str:
    """Embed question → intent extraction → similarity + text search → Gemini answer."""
    # 1. Extract intent from the question
    intent = extract_intent(question)

    # 2. Short-circuit for query types that don't need RAG
    q_type = intent.get("query_type")
    from_st = intent.get("from_station")
    to_st = intent.get("to_station")
    now = datetime.now(PACIFIC)
    day = intent.get("day_type") or ("weekday" if now.weekday() < 5 else "weekend")

    if q_type == "stops_count" and from_st and to_st:
        n = count_stops(from_st, to_st)
        if n is not None:
            return f"There are {n} stop(s) between {from_st} and {to_st}."

    elif q_type == "travel_duration" and from_st and to_st:
        trains = get_travel_times(from_st, to_st, day)
        if trains:
            # Clean label: "" → "Normal", " [Limited]" → "Limited", " [Express]" → "Express"
            by_label: dict[str, int] = {}
            for t in trains:
                label = t["label"].strip().strip("[]") or "Normal"
                if label not in by_label:
                    by_label[label] = t["duration_mins"]
            lines = [f"{lbl}: {mins} mins" for lbl, mins in by_label.items()]
            return f"Travel time from {from_st} to {to_st}:\n" + "\n".join(lines)

    elif q_type == "arrive_by" and from_st and to_st and intent.get("target_time"):
        train = get_arrive_by(from_st, to_st, intent["target_time"], day)
        if train:
            return (
                f"To arrive at {to_st} by {intent['target_time']}, take "
                f"Train {train['train']}{_train_label(train['train'])} departing {from_st} "
                f"at {train['depart_str']} (arrives {train['arrive_str']})."
            )
        return (
            f"No trains from {from_st} to {to_st} arrive by {intent['target_time']}. "
            f"Try an earlier target time or check /traveltime for all options."
        )

    # 3. Embed the question
    question_embedding = embed([question])[0]

    # 3a. Vector similarity search — increase match_count for first/last queries
    match_count = 20 if intent["query_type"] in ("first_train", "last_train") else 10
    vector_chunks = similarity_search(question_embedding, match_count=match_count)

    # 3b. Text search: use extracted station if available, else fall back to stopword filtering
    if intent["station"]:
        keywords = [intent["station"]]
    else:
        words = [w.strip("?.,!").lower() for w in question.split()]
        keywords = [w for w in words if len(w) > 4 and w not in _STOPWORDS]
    db = _client()
    text_chunks = _text_search(db, keywords) if keywords else []

    # 3c. Merge and sort chronologically by DB insertion order (id) so Gemini
    # sees trains in timetable order — makes first/last train queries accurate.
    seen_ids = {c["id"] for c in vector_chunks}
    extra_chunks = [c for c in text_chunks if c["id"] not in seen_ids]
    chunks = sorted(vector_chunks + extra_chunks, key=lambda c: c["id"])

    if not chunks:
        return (
            "I couldn't find schedule data for that. Here are some things I can help with:\n"
            "• /schedule — next trains from any station\n"
            "• /traveltime — travel time between two stations\n"
            "• /ask How many stops from Lawrence to San Mateo?\n"
            "• /ask When's the last train from Palo Alto to SF on weekends?\n"
            "• /ask If I need to arrive at SF by 6pm from Lawrence, which train should I take?"
        )

    # 4. Build context from retrieved chunks, labelled by schedule type
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

    # 5. Build enriched prompt using extracted intent
    day_of_week = now.strftime("%A")
    date_str = now.strftime("%B %d, %Y")
    current_time = now.strftime("%I:%M %p")

    direction_label = (
        "towards San Francisco (northbound)"
        if intent["direction"] == "sf"
        else "towards San Jose (southbound)"
        if intent["direction"] == "sj"
        else "not specified"
    )
    day_type_label = intent["day_type"] or "unknown"
    station_label = intent["station"] or "not specified"

    prompt = f"""You are TimelyCal, a Caltrain schedule assistant. Answer the user's question using ONLY the schedule data provided below.

Rules:
- Always include the train number and exact departure time in your answer
- If asked for the next train, list up to 3 upcoming trains with their times
- If asked for first/last train, scan ALL provided chunks and find the earliest/latest time
- If the schedule data does not contain the answer, say: "I'm not sure about that — try /schedule for a station timetable, /traveltime for journey times, or /ask with a specific question like 'next train from Lawrence to SF'."
- Do not make up times or train numbers

Context:
- Today is {day_of_week}, {date_str}
- Current time: {current_time} PT
- Station asked about: {station_label}
- Direction: {direction_label}
- Schedule type: {day_type_label}

Schedule Data:
{context}

Question: {question}

Think step by step:
1. Identify which schedule chunks are relevant to the question
2. Find the specific train(s) that match the request
3. Give a clear, direct answer with train number(s) and time(s)

Answer:"""

    # 6. Call Gemini Flash via Google AI Studio
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return response.text
