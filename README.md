# TimelyCal 🚆

RAG-powered Caltrain schedule assistant. Ask in plain English, get the next 3 trains in seconds.

[![Deploy](https://github.com/harrischew/timelycal/actions/workflows/deploy.yml/badge.svg)](https://github.com/harrischew/timelycal/actions/workflows/deploy.yml)

## How to use

Find the bot on Telegram: **@TimelyCal_bot**

**Commands:**
- `/next` — Next 3 trains from any station (both directions)
- `/schedule` — Full day timetable for a station
- `/mystation` — View or update your saved default station
- `/help` — Show all commands

Or just type a question in plain English:
> "When's the last train from Palo Alto to SF on weekends?"

## Stack
- **Backend**: FastAPI + python-telegram-bot (Google Cloud Run)
- **LLM**: Gemini 2.5 Flash (Google AI Studio)
- **Embeddings**: Vertex AI `text-embedding-004` (768-dim)
- **Vector DB**: Supabase pgvector
- **Storage**: Google Cloud Storage
- **Frontend**: Next.js — Phase 2

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
│   │   ├── rag.py            # Gemini 2.5 Flash RAG pipeline
│   │   ├── schedule.py       # Next/all trains query logic
│   │   └── user_prefs.py     # Saved station preferences
│   ├── Dockerfile
│   ├── requirements.txt
│   └── cloudbuild.yaml
├── web/                      # Phase 2 — Next.js
├── infra/                    # GCP infrastructure
├── tests/
│   ├── golden_queries.json
│   └── test_rag.py
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

## Deploy (manual)
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
  --min-instances 0 --max-instances 1 --memory 512Mi --timeout 300
```

After deploying: `curl https://telegram-bot-1077099046405.us-central1.run.app/webhook/set-webhook`

## CI/CD
Pushing to `main` automatically builds and deploys via GitHub Actions (`.github/workflows/deploy.yml`).

Required GitHub secrets: `GCP_SA_KEY`, `GCP_PROJECT`, `SERVICE_URL`
