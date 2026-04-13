# TimelyCal

RAG-powered Caltrain schedule assistant. FastAPI + Telegram bot on Cloud Run.

## Project Structure
```
timelycal/
├── backend/
│   ├── main.py               # FastAPI entry point, includes routers
│   ├── bot.py                # Telegram bot handlers + Application builder
│   ├── db.py                 # Supabase user tracking (save_user, get_user_count)
│   ├── routes/
│   │   ├── telegram.py       # /webhook/telegram, /webhook/set-webhook, /webhook/info
│   │   ├── query.py          # POST /api/query (RAG) — LIVE
│   │   └── upload.py         # POST /admin/upload (PDF) — LIVE
│   ├── services/
│   │   ├── pdf_parser.py     # Table-aware PDF parser (pdfplumber extract_tables)
│   │   ├── embedder.py       # Vertex AI text-embedding-004 (768-dim), batch=20
│   │   ├── gcs.py            # GCS upload/download (bucket: timelycal-pdfs)
│   │   ├── rag.py            # Intent extraction + Supabase pgvector search + Gemini 2.5 Flash answer
│   │   ├── schedule.py       # Direct schedule queries (get_next_trains, get_travel_times)
│   │   └── user_prefs.py     # Per-user saved station preference
│   ├── Dockerfile
│   ├── requirements.txt
│   └── cloudbuild.yaml
├── web/                      # Phase 2 — Next.js
├── infra/                    # GCP infrastructure
├── tests/
│   ├── requirements-test.txt # pytest, pytest-mock, pytest-cov, freezegun
│   └── test_intent_extraction.py
├── pytest.ini
├── .github/
│   └── workflows/
│       └── deploy.yml        # CI: test job (all PRs) + deploy job (main only)
├── CLAUDE.md
├── README.md
└── .gitignore
```

## Git Workflow

**Every change must follow this process — no direct commits to `main`:**

1. Always branch from `main` (or from a feature branch if the fix depends on unreleased code):
   ```bash
   git checkout main && git checkout -b feat/your-feature-name
   git checkout main && git checkout -b fix/your-fix-name
   git checkout main && git checkout -b docs/your-doc-name
   git checkout main && git checkout -b chore/your-chore-name
   ```
2. One concern per branch — do not bundle unrelated fixes into the same branch
3. Commit to the branch, then push and open a PR:
   ```bash
   git push origin feat/your-feature-name
   gh pr create --title "type: short description" --body "..."
   ```
4. PR body must include: **Summary** (bullet points), **Test plan** (checklist)
5. After creating the PR, immediately switch back to `main`:
   ```bash
   git checkout main
   ```
6. Wait for the owner (harrischew) to review and approve before merging to `main`
7. CI/CD pipeline runs automatically on merge to `main`

**Branch naming:**
| Prefix | When to use |
|---|---|
| `feat/` | New user-facing feature |
| `fix/` | Bug fix |
| `docs/` | Documentation only |
| `chore/` | Tooling, config, CI changes |
| `refactor/` | Code restructure with no behaviour change |

**Do not:**
- Push directly to `main`
- Force-push a branch that has an open PR (resets reviewer context)
- Commit unrelated changes on the same branch

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
- `ADMIN_API_KEY` — protects `/admin/upload`, `/webhook/set-webhook`, `/webhook/info` (pass as `x-api-key` header)
- `WEBHOOK_SECRET` — Telegram signs every webhook request with this; verified via `X-Telegram-Bot-API-Secret-Token` header

## Supabase
- **Region:** West US (Oregon)
- **Table:** `documents` — columns: `id`, `content` (text), `embedding` (vector(768)), `metadata` (jsonb)
- **Table:** `users` — columns: `chat_id` (bigint PK), `username` (text), `first_seen` (timestamptz), `last_seen` (timestamptz)
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
  --set-secrets "BOT_TOKEN=BOT_TOKEN:latest,SUPABASE_URL=SUPABASE_URL:latest,SUPABASE_KEY=SUPABASE_KEY:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest,ADMIN_API_KEY=ADMIN_API_KEY:latest,WEBHOOK_SECRET=WEBHOOK_SECRET:latest" \
  --set-env-vars "GCS_BUCKET=timelycal-pdfs,GCP_PROJECT=my-telegram-bot-001,GCP_REGION=us-central1" \
  --min-instances 0 \
  --max-instances 1 \
  --memory 512Mi \
  --timeout 300
```

After deploying: `curl -H "x-api-key: YOUR_ADMIN_API_KEY" https://telegram-bot-1077099046405.us-central1.run.app/webhook/set-webhook`

## Re-uploading PDFs
```bash
# 1. Clear Supabase: run "delete from documents;" in SQL Editor
# 2. Re-upload:
curl -X POST https://telegram-bot-1077099046405.us-central1.run.app/admin/upload \
  -H "x-api-key: YOUR_ADMIN_API_KEY" \
  -F "file=@/Users/harrischew/Downloads/WeekendCaltrain-schedule.pdf"
curl -X POST https://telegram-bot-1077099046405.us-central1.run.app/admin/upload \
  -H "x-api-key: YOUR_ADMIN_API_KEY" \
  -F "file=@/Users/harrischew/Downloads/WeekdayCaltrain-schedule.pdf"
curl -X POST https://telegram-bot-1077099046405.us-central1.run.app/admin/upload \
  -H "x-api-key: <ADMIN_API_KEY>" \
  -F "file=@/Users/harrischew/Downloads/WeekendCaltrain-schedule.pdf"
```

## Key Endpoints
| Endpoint | Description |
|---|---|
| `GET /` | Health check |
| `POST /webhook/telegram` | Telegram webhook |
| `GET /webhook/set-webhook` | Register webhook with Telegram |
| `POST /api/query` | RAG query `{"question": "..."}` |
| `POST /admin/upload` | PDF upload (multipart, field: `file`) |

## Bot Commands
| Command | Description |
|---|---|
| `/start` | Welcome message for new users with command overview |
| `/schedule` | Guided menu: pick day → station → direction → see next 3 trains |
| `/traveltime` | Pick origin → destination → see travel time per train type (Normal/Limited/Express) |
| `/ask` | Freeform natural language query via RAG pipeline |
| `/help` | List all commands |
| `/mystation` | Save / view / clear your default station |
| `/stats` | Show total unique users (admin info) |

## Architecture Decisions
- **Embeddings:** Vertex AI `text-embedding-004` (768-dim), batch=20 (to stay under 20k token limit per request)
- **LLM:** Google AI Studio `gemini-2.5-flash` via `google-genai` SDK — project has NO Vertex AI Gemini access, do not use Vertex AI for LLM calls. Thinking is disabled (`thinking_budget: 0`) on both Gemini calls to keep latency under 5s
- **PDF parsing:** `pdfplumber.extract_tables()` (table-aware) — each train row = one chunk: `"Station: 7:15am | Station: 8:01am | ..."`. Times are normalised to `am`/`pm` at parse time. Falls back to line-based if no tables
- **RAG pipeline (2-call flow):** (1) `extract_intent()` — Gemini parses freeform question into structured JSON `{station, from_station, to_station, target_time, direction, day_type, query_type, time_context}`; (2) `query()` — similarity search with enriched prompt (current time PT, direction label, chain-of-thought instruction)
- **Short-circuit query types:** `stops_count`, `travel_duration`, `arrive_by` resolve before embedding — no vector search or Gemini synthesis needed
- **Intent extraction fallback:** returns `{"station": null, ...}` on invalid JSON — query falls back to keyword search
- **Recurring timetable rule:** the RAG answer prompt explicitly states the schedule is recurring weekly — "tomorrow" = weekday/weekend type, not a calendar date
- **Similarity search:** match_count=10 (20 for first/last train queries)
- **Train type classification:** 400–499 = Limited, 500–599 = Express, others = Normal (by train number)
- **Travel time calculation:** match train numbers across two station DB chunks, diff departure times — direction inferred from `STATIONS` list geographic order (SF→SJ)
- **User tracking:** every incoming message runs `_track_user` (group=-1, runs before all handlers) — upserts `chat_id` and `last_seen` in Supabase `users` table
- **bot_app:** stored on `app.state.bot_app` via FastAPI lifespan, accessed in routes via `request.app.state.bot_app`
- **CI:** GitHub Actions `test` job runs on every PR and push to main; `deploy` job has `needs: test` and only runs on push to main

## What's In Progress (Next Session Start Here)
**Open PRs (pending review + merge):**
- PR #22 `fix/disable-gemini-thinking` — disables Gemini 2.5 Flash thinking to fix /ask latency
- PR #23 `docs/update-readme` — updated README with current commands and AI pipeline detail
- PR #24 `fix/debug-lawrence-rag-query` — fixes "tomorrow" queries returning no results
- PR #25 `feat/natural-language-query-expansion` — adds stops_count, travel_duration, arrive_by query types + smart redirects
- PR open `fix/travel-duration-label-format` — fixes travel_duration showing clean labels and single duration

**After merging all PRs:**
- Clear Supabase `documents` table and re-upload both PDFs (old `7:15a` format rows still exist alongside new `7:15am` rows from re-upload without prior clear)
- Phase 2: Next.js web portal

## Known Errors & Fixes
| Error | Fix |
|---|---|
| `uvicorn not found` | Add to requirements.txt |
| `Bad webhook: https required` | `.replace("http://","https://")` on base_url |
| `gemini-X.X not found (Vertex AI)` | Project has no Vertex AI Gemini — use Google AI Studio + `google-genai` pkg |
| `input token count > 20000` | Vertex AI embedding batch too large — use batch=20 in embedder.py |
| Secret Manager permission denied | `gcloud projects add-iam-policy-binding my-telegram-bot-001 --member="serviceAccount:1077099046405-compute@developer.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"` |
| Poor RAG results | Was using char-based chunking — fixed with table-aware `extract_tables()` parser |
| `/help` and `/ask` silent crash | Both called `_is_cold_start()` which was deleted — removed stale calls (PR #5) |
| `/start` fires twice on button tap | Telegram sends both a callback and `/start` text when tapping Start — fixed with `allow_reentry=True` and deduplication (PR #8, #10) |
| MarkdownV2 parse error on `/start` | Reverted `/start` to plain text formatting (PR #10) |
| `/ask "tomorrow from X"` returns "I don't have that information" | Gemini treated "tomorrow" as a calendar date — fixed by adding recurring timetable rule to answer prompt (PR #24) |
| `/ask` 30-40s latency / timeout | Gemini 2.5 Flash thinking enabled by default — fixed with `thinking_budget: 0` on both generate_content calls (PR #22) |
| Duplicate rows in Supabase after re-upload | Always run `delete from documents;` in Supabase SQL Editor before re-uploading PDFs |
| Admin upload returns 403 Forbidden | Trailing `%` from zsh shell included in API key — copy key without the trailing `%` |
