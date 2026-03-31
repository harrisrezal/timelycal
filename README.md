# TimelyCal

A conversational Caltrain schedule assistant powered by a RAG pipeline. Ask in plain English — TimelyCal extracts your intent, searches the live timetable, and answers in seconds.

## How to use

Find the bot on Telegram: **@TimelyCal_bot**

**Commands:**
- `/schedule` — Guided menu: pick day, station, and direction to see the next 3 trains
- `/traveltime` — Pick an origin and destination to see travel time by train type (Normal / Limited / Express)
- `/ask` — Ask anything in plain English
- `/mystation` — Save, view, or clear your default station
- `/stats` — Total unique users
- `/help` — Show all commands

Or just type a question directly:
> "When's the last train from Palo Alto to SF on weekends?"
> "What time does the first express leave Mountain View?"

## How it works

TimelyCal uses a two-stage Retrieval-Augmented Generation (RAG) pipeline to answer freeform questions about the Caltrain schedule.

### 1. PDF ingestion and chunking
Caltrain publishes separate weekday and weekend timetables as PDFs. TimelyCal parses these with `pdfplumber` using table-aware extraction — each row in the timetable becomes one chunk that captures every station's departure time for a given train:

```
San Francisco: 7:02am | 22nd Street: 7:08am | Bayshore: 7:14am | ... | San Jose Diridon: 8:40am
```

Times are normalised to unambiguous `am`/`pm` format at parse time. Each chunk is stored alongside its vector embedding and schedule metadata (weekday vs weekend) in Supabase.

### 2. Embeddings
Each chunk is embedded using Vertex AI `text-embedding-004`, which produces 768-dimensional dense vectors. Embeddings are generated in batches of 20 to stay within Vertex AI's token limits, then stored in Supabase's pgvector column for fast cosine similarity search.

### 3. Intent extraction
When a user sends a freeform question, the first of two Gemini 2.5 Flash calls parses it into a structured intent:

```json
{
  "station": "Palo Alto",
  "direction": "sf",
  "day_type": "weekend",
  "query_type": "last_train",
  "time_context": "evening"
}
```

The model is given the current day and Pacific time as context, so questions like "trains tomorrow morning" resolve correctly. If the JSON parse fails, the pipeline falls back gracefully to stopword-filtered keyword search.

### 4. Retrieval
Two searches run in parallel and are merged:
- **Vector search** — pgvector cosine similarity finds the top 10 most semantically relevant chunks (20 for first/last-train queries)
- **Keyword search** — `ilike` filter on the extracted station name to ensure exact station matches aren't missed by the vector search

Results are sorted by database insertion order (which mirrors timetable order), so Gemini sees trains in chronological sequence — critical for accurate first/last-train answers.

### 5. Answer synthesis
The second Gemini 2.5 Flash call receives the retrieved chunks and an enriched prompt that includes the current Pacific time, the resolved direction label, and a chain-of-thought instruction to reason step by step before answering. Extended thinking is disabled (`thinking_budget: 0`) so responses return in under 5 seconds.

### 6. Direct schedule queries
`/schedule` and `/traveltime` bypass the RAG pipeline entirely. They query Supabase directly, extract train numbers and departure times from chunks using a regex, compare parsed `time` objects against the current Pacific time, and return structured results. This makes guided commands fast and deterministic.

## Stack
| Layer | Technology |
|---|---|
| Backend | FastAPI + python-telegram-bot on Google Cloud Run |
| LLM | Gemini 2.5 Flash (Google AI Studio) |
| Embeddings | Vertex AI `text-embedding-004` (768-dim) |
| Vector DB | Supabase pgvector |
| Storage | Google Cloud Storage |
| Frontend | Next.js — Phase 2 |

## Project Structure
```
timelycal/
├── backend/
│   ├── main.py               # FastAPI entry point
│   ├── bot.py                # Telegram bot handlers
│   ├── routes/
│   │   ├── telegram.py       # /webhook/telegram
│   │   ├── query.py          # /api/query (RAG)
│   │   └── upload.py         # /admin/upload (PDF)
│   ├── services/
│   │   ├── pdf_parser.py     # Table-aware pdfplumber extractor
│   │   ├── embedder.py       # Vertex AI embeddings
│   │   ├── gcs.py            # Cloud Storage helper
│   │   ├── rag.py            # Intent extraction + RAG pipeline
│   │   ├── schedule.py       # Direct next/all trains query logic
│   │   └── user_prefs.py     # Saved station preferences
│   ├── Dockerfile
│   ├── requirements.txt
│   └── cloudbuild.yaml
├── web/                      # Phase 2 — Next.js
├── infra/                    # GCP infrastructure
├── tests/
│   └── test_intent_extraction.py
└── .gitignore
```

## Phase Build Plan
| Phase | What | Status |
|---|---|---|
| 0 | Project structure + Telegram bot deployed | ✅ Done |
| 1a | Supabase setup + PDF parser | ✅ Done |
| 1b | Embedder + RAG pipeline + Gemini Flash | ✅ Done |
| 1c | Wire bot.py to RAG, redeploy | ✅ Done |
| V1 | GitHub + CI/CD pipeline | ✅ Done |
| 2 | Next.js web portal | ⏳ |
| 3 | WhatsApp integration | ⏳ |
