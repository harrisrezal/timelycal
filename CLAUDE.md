# TimelyCal

RAG-powered Caltrain schedule assistant. FastAPI + Telegram bot on Cloud Run.

## Project Structure
```
timelycal/
├── backend/
│   ├── main.py               # FastAPI entry point, includes routers
│   ├── bot.py                # Telegram bot handlers + Application builder
│   ├── routes/
│   │   ├── telegram.py       # /webhook/telegram, /webhook/set-webhook, /webhook/info
│   │   ├── query.py          # POST /api/query (RAG) — LIVE
│   │   └── upload.py         # POST /admin/upload (PDF) — LIVE
│   ├── services/
│   │   ├── pdf_parser.py     # Table-aware PDF parser (pdfplumber extract_tables)
│   │   ├── embedder.py       # Vertex AI text-embedding-004 (768-dim), batch=20
│   │   ├── gcs.py            # GCS upload/download (bucket: timelycal-pdfs)
│   │   └── rag.py            # Supabase pgvector search + Gemini 2.5 Flash answer
│   ├── Dockerfile
│   ├── requirements.txt
│   └── cloudbuild.yaml
├── web/                      # Phase 2 — Next.js
├── infra/                    # GCP infrastructure
├── tests/
├── CLAUDE.md
├── README.md
└── .gitignore
```

## Infrastructure
- **GCP Project:** `my-telegram-bot-001`
- **Cloud Run service:** `telegram-bot` (region: `us-central1`)
- **Container image:** `gcr.io/my-telegram-bot-001/telegram-bot`
- **Service URL:** `https://telegram-bot-1077099046405.us-central1.run.app`
- **GCS Bucket:** `timelycal-pdfs` (raw PDFs stored at `schedules/`)
- **Cloud Run timeout:** 300s (increased from 60s for large PDF uploads)

## GCP Secrets (all in Secret Manager)
- `BOT_TOKEN` — Telegram bot token
- `SUPABASE_URL` — `https://egjgppunsrickvkmnhib.supabase.co/`
- `SUPABASE_KEY` — Supabase secret key
- `GEMINI_API_KEY` — Google AI Studio API key (NOT Vertex AI Gemini)

## Supabase
- **Region:** West US (Oregon)
- **Table:** `documents` — columns: `id`, `content` (text), `embedding` (vector(768)), `metadata` (jsonb)
- **Required SQL function:**
```sql
create or replace function match_documents(
  query_embedding vector(768),
  match_count int default 5)
returns table (id bigint, content text, metadata jsonb, similarity float)
language sql stable as $$
  select id, content, metadata,
    1 - (embedding <=> query_embedding) as similarity
  from documents
  order by embedding <=> query_embedding
  limit match_count;
$$;
```

## Deployment Workflow
Always run from `backend/` directory:
```bash
cd backend
gcloud builds submit --tag gcr.io/my-telegram-bot-001/telegram-bot --project my-telegram-bot-001

gcloud run deploy telegram-bot \
  --image gcr.io/my-telegram-bot-001/telegram-bot \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-secrets "BOT_TOKEN=BOT_TOKEN:latest,SUPABASE_URL=SUPABASE_URL:latest,SUPABASE_KEY=SUPABASE_KEY:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest" \
  --set-env-vars "GCS_BUCKET=timelycal-pdfs,GCP_PROJECT=my-telegram-bot-001,GCP_REGION=us-central1" \
  --min-instances 0 \
  --max-instances 1 \
  --memory 512Mi \
  --timeout 300
```

After deploying: `curl https://telegram-bot-1077099046405.us-central1.run.app/webhook/set-webhook`

## Re-uploading PDFs
```bash
# 1. Clear Supabase: run "delete from documents;" in SQL Editor
# 2. Re-upload:
curl -X POST https://telegram-bot-1077099046405.us-central1.run.app/admin/upload \
  -F "file=@/Users/harrischew/Downloads/WeekendCaltrain-schedule.pdf"
curl -X POST https://telegram-bot-1077099046405.us-central1.run.app/admin/upload \
  -F "file=@/Users/harrischew/Downloads/WeekdayCaltrain-schedule.pdf"
```

## Key Endpoints
| Endpoint | Description |
|---|---|
| `GET /` | Health check |
| `POST /webhook/telegram` | Telegram webhook |
| `GET /webhook/set-webhook` | Register webhook with Telegram |
| `POST /api/query` | RAG query `{"question": "..."}` |
| `POST /admin/upload` | PDF upload (multipart, field: `file`) |

## Architecture Decisions
- **Embeddings:** Vertex AI `text-embedding-004` (768-dim), batch=20 (to stay under 20k token limit per request)
- **LLM:** Google AI Studio `gemini-2.5-flash` via `google-genai` SDK — project has NO Vertex AI Gemini access, do not use Vertex AI for LLM calls
- **PDF parsing:** `pdfplumber.extract_tables()` (table-aware) — each train row = one chunk: `"Station: time | Station: time | ..."`. Falls back to line-based if no tables
- **Similarity search:** match_count=10
- **bot_app:** stored on `app.state.bot_app` via FastAPI lifespan, accessed in routes via `request.app.state.bot_app`

## What's In Progress (Next Session Start Here)
1. **Weekday PDF needs re-uploading** — Supabase was cleared, weekend re-uploaded (96 chunks), weekday upload failed mid-session. Next session: clear Supabase again and re-upload BOTH PDFs fresh using the commands above.
2. **Test queries after re-upload** to verify table-aware chunking works correctly
3. Phase 2: Next.js web portal

## Known Errors & Fixes
| Error | Fix |
|---|---|
| `uvicorn not found` | Add to requirements.txt |
| `Bad webhook: https required` | `.replace("http://","https://")` on base_url |
| `gemini-X.X not found (Vertex AI)` | Project has no Vertex AI Gemini — use Google AI Studio + `google-genai` pkg |
| `input token count > 20000` | Vertex AI embedding batch too large — use batch=20 in embedder.py |
| Secret Manager permission denied | `gcloud projects add-iam-policy-binding my-telegram-bot-001 --member="serviceAccount:1077099046405-compute@developer.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"` |
| Poor RAG results | Was using char-based chunking — fixed with table-aware `extract_tables()` parser |
