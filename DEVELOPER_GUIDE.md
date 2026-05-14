# Developer Guide

Everything an engineer taking over this codebase needs to know. Pair this
with [FLY_DEPLOY.md](FLY_DEPLOY.md) if you are also responsible for the
Fly.io deployment.

## Stack

- Python 3.12, FastAPI, Uvicorn
- SQLite (WAL mode) at `data/startup_intel.db` locally, `/data/startup_intel.db` on Fly.io
- `httpx` for outbound HTTP, `feedparser` for RSS, `beautifulsoup4` + `lxml` for HTML, `openpyxl` for Excel imports
- `apscheduler` for the optional periodic ingest job
- LLM via OpenAI-compatible API. Default provider is Groq's free tier (`llama-3.1-8b-instant`). OpenAI and a GitHub Copilot proxy are also supported - see [src/llm/provider.py](src/llm/provider.py)
- No frontend framework. Plain HTML + vanilla JS in [static/](static/)

## Repository layout

```
src/
  main.py                FastAPI app entry point + lifespan
  db/
    database.py          Single global SQLite connection (WAL)
    schema.sql           Schema
    migrate.py           Idempotent column-add migrations
    seed.py              CSV/Excel seed import
  ingestion/
    company_search.py    The main pipeline (Google News per-company + dedup + classify)
    monday_sync.py       Monday.com GraphQL sync
    rss_ingester.py      Generic RSS feed ingest
    html_scraper.py      Direct website scrape
    linkedin_ingester.py LinkedIn URL-first ingest (manual / CSV / best-effort discovery)
    newsletter_ingester.py  Substack RSS
    email_ingester.py    Gmail IMAP poll
    social_ingester.py   Twitter (currently disabled)
    scheduler.py         APScheduler wiring
    dedup.py             Content hashing helpers
  llm/
    provider.py          AsyncOpenAI client factory (openai / copilot / groq)
    classifier.py        Article -> {classification, sentiment, topics, summary, hired_count}
    summarizer.py        Weekly digest summarizer
  scoring/
    relevance.py         Founder-weighted relevance score (used to filter Google News matches)
  routes/
    startups.py          CRUD + Monday sync + CSV import
    content.py           List/get/delete content items
    search.py            FTS search
    summaries.py         Digest endpoints
    sources.py           Source CRUD
    social.py            LinkedIn + newsletter triggers
    health.py            /api/health, /api/ingest (background), /api/ingest/status, /api/ingest/logs, /api/classify, /api/analytics
static/                  HTML/JS/CSS dashboard
data/                    SQLite database (gitignored)
tests/                   pytest
```

## Local development

```bash
python -m venv .venv
source .venv/bin/activate          # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env
# Edit .env: at minimum set GROQ_API_KEY and MONDAY_API_TOKEN/MONDAY_BOARD_ID
python -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

Run tests:

```bash
pytest tests/ -v
```

## How ingestion actually works

This is the part that took the most rework, so it is worth understanding.

### The pipeline (per-company)

`src/ingestion/company_search.py::ingest_for_company(startup, fast=True)`:

1. Builds 1-3 Google News search queries (exact-phrase company name; legal
   name as fallback; for short/generic names it adds Forge-context terms
   like "McMaster", "incubator", and key terms from the description).
2. Fetches `https://news.google.com/rss/search?q=...` and parses the RSS.
3. For each entry: scores it with
   `src/scoring/relevance.py::score_relevance` (founder names weighted
   higher than company names because company names rename more often).
4. In **fast mode** (the default): items below confidence 0.45 are
   dropped. The LLM relevance verifier is skipped (it is slow and the
   scoring already does a decent job).
5. In **slow/precise mode**: items below confidence 0.8 OR from
   short-named companies also go through `verify_relevance_with_llm`
   which asks the LLM "is this article actually about this company".
6. Surviving items are written to `content_items` with
   `classification='unclassified'` and the score in `confidence_score`.
7. The function returns the list of new item IDs.

Then `_run_ingestion` immediately calls
`src/llm/classifier.py::classify_content_item` on each new item. This is
deliberate: doing classification per-company instead of in one big batch
at the end means that if the Fly.io trial machine dies mid-run, every
already-processed company is fully classified, not stuck in 'unclassified'
limbo.

### Rolling batch order

`ingest_all_companies(limit=25)` selects the next batch with:

```sql
SELECT * FROM startups
WHERE tag IS NULL OR tag != 'not_active'
ORDER BY last_ingested_at ASC NULLS FIRST
LIMIT ?
```

So companies that have never been ingested go first, then the
longest-ago-ingested ones. Each click advances the cursor; with 25 per
click and 347 companies, the full portfolio cycles in ~14 clicks. The
`last_ingested_at` timestamp is stamped after each company.

`DEFAULT_BATCH_LIMIT` is configurable via the `INGEST_BATCH_LIMIT`
environment variable.

### Background task + progress

`POST /api/ingest` returns immediately with `status: "started"`. It uses
`asyncio.create_task(_run_ingestion_job(...))` to drive the work without
holding the HTTP connection open (otherwise Fly.io's proxy would close it
at 60s anyway). A module-level `_ingestion_state` dict is updated as the
worker progresses. `GET /api/ingest/status` exposes that dict; the frontend
polls it every 2.5 seconds.

`GET /api/ingest/logs` returns the last ~200 server log lines so the
dashboard can show them without anyone needing flyctl access. The buffer
is purely in-memory and resets when the machine restarts.

### Fly.io trial timeout

Fly's free trial kills any machine after 5 minutes of activity. This is
the single biggest constraint on the pipeline. Per-company budget at the
moment:

| Step | Time |
|---|---|
| Google News fetch | ~1-3s |
| Score & insert (no LLM verify in fast mode) | ~0.1s |
| Per-item classification (one LLM call per new article) | ~1-2s |
| Loop sleep | 0.5s |

With an average ~3-5 new items per company, this lands around 8-12 seconds
per company - 25 companies fits inside 5 minutes with margin. If you bump
`max_items` or re-enable LLM relevance verification, recheck the budget.

When the team adds a credit card to Fly the 5-minute cap is lifted; you
can then set `INGEST_BATCH_LIMIT` higher and/or call `fast=False` inside
`ingest_all_companies` for more accurate filtering.

## LLM classification

`src/llm/classifier.py::classify_with_llm`:

1. Build a JSON-mode prompt asking for `classification`, `sentiment`,
   `topics`, `summary`, `hired_count`.
2. Try with `response_format={"type": "json_object"}` first. If the
   provider rejects that (Groq is finicky on some models), retry without.
3. Parse the response with `_extract_json`, which tolerates code-fenced
   replies and prose wrapping.
4. Validate fields (classification within the allowed set; sentiment one
   of pos/neut/neg; `hired_count` coerced to int).
5. On any failure - whether HTTP error, rate limit, or parse error -
   fall back to `classify_by_keywords`. The point is that items never
   stay in the literal string `'unclassified'`; the worst case is they
   get classified as `'general'` by the keyword heuristic.

If classification looks broken on Fly.io, check:

```bash
flyctl secrets list                         # are GROQ_API_KEY and LLM_PROVIDER set?
flyctl ssh console -C "env | grep GROQ"     # are they actually in the container?
flyctl logs                                 # look for "LLM classification error:"
```

## Database

SQLite, single file, WAL mode. The schema lives in
[src/db/schema.sql](src/db/schema.sql). Migrations are idempotent
column-adds in [src/db/migrate.py](src/db/migrate.py) that run on every
startup - safe to re-run.

The full-text-search virtual table `content_fts` mirrors `content_items`
via triggers. Search hits `/api/search`.

The DB file lives at:

- Local: `data/startup_intel.db` (gitignored)
- Fly.io: `/data/startup_intel.db` on the mounted volume `startup_intel_data`

To grab a copy of production for debugging:

```bash
flyctl ssh sftp get /data/startup_intel.db ./prod.db
sqlite3 prod.db
```

## Environment variables

See [.env.example](.env.example) for the full list. The ones you actually
need to set:

| Var | Purpose |
|---|---|
| `LLM_PROVIDER` | `groq` (default, free) / `openai` / `copilot` |
| `GROQ_API_KEY` | Sign up at console.groq.com - free tier is generous |
| `GROQ_MODEL` | Optional; defaults to `llama-3.1-8b-instant` |
| `OPENAI_API_KEY` | Only if `LLM_PROVIDER=openai` |
| `MONDAY_API_TOKEN` | From monday.com -> Profile -> Admin -> API |
| `MONDAY_BOARD_ID` | The board's URL contains it |
| `MONDAY_COLUMN_MAP` | JSON override of the default column mapping. See [MONDAY_SETUP.md](MONDAY_SETUP.md). |
| `NEWSLETTER_EMAIL`, `NEWSLETTER_APP_PASSWORD` | Gmail IMAP. See [NEWSLETTER_SETUP.md](NEWSLETTER_SETUP.md). |
| `INGEST_BATCH_LIMIT` | Default 25; raise once Fly trial is lifted |
| `INGESTION_INTERVAL_MINUTES` | Scheduler period (default 1440 = once a day) |
| `DATABASE_PATH` | Override SQLite path |

`.env` is gitignored but does get copied into the Docker image during
local builds. On Fly.io, secrets are set via `flyctl secrets set` and
never live in the image - see [FLY_DEPLOY.md](FLY_DEPLOY.md).

## API surface (high level)

| Method | Path | Notes |
|---|---|---|
| GET | `/` | Dashboard |
| GET | `/api/health` | DB ok + row counts |
| POST | `/api/ingest` | Background ingestion. Body: `{}` for next-batch, `{"startup_ids":[...]}` for specific |
| GET | `/api/ingest/status` | Live job progress + cycle summary |
| GET | `/api/ingest/logs` | Last ~200 server log lines |
| POST | `/api/ingest/forge-feed` | One-off Forge RSS pull (separate so it does not eat the 5-min budget) |
| POST | `/api/classify` | Classify remaining unclassified items |
| POST | `/api/reclassify` | Reclassify last 500 items from scratch |
| GET | `/api/analytics` | Aggregated dashboard counts |
| GET/POST/PUT/DELETE | `/api/startups[...]` | CRUD + bulk-tag + CSV import + Monday sync |
| GET | `/api/content[...]` | Content list / detail / delete |
| GET | `/api/search?q=` | FTS5 search |
| GET | `/api/summaries/digest/current` | Weekly digest |

Full OpenAPI / Swagger docs at `/docs`.

## Scheduler

`src/ingestion/scheduler.py` is started at app boot. By default it runs the
full ingestion every `INGESTION_INTERVAL_MINUTES` (default 1440 = daily).
It is disabled when `INGESTION_INTERVAL_MINUTES <= 0`. On Fly.io with the
trial timeout the scheduler will only run while the machine is awake, so
in practice the dashboard's "Run Ingestion" button is the primary trigger.

## Tests

```bash
pytest tests/ -v
```

The top-level `test_*.py` scripts (`test_ddgs.py`, `test_gn.py`, etc.) are
scratch scripts left over from initial development - gitignored, not real
tests.

## Common changes

### Bump the batch size

If the Fly.io trial limit has been lifted:

1. `flyctl secrets set INGEST_BATCH_LIMIT=75`
2. Optionally set `INGESTION_INTERVAL_MINUTES` lower for more frequent runs.

### Swap LLM provider

The classifier and the relevance LLM verifier both use
`src/llm/provider.py`. Set `LLM_PROVIDER=openai` and `OPENAI_API_KEY=...`
and they switch automatically. No code changes.

### Add a new news source

Sources are rows in the `sources` table. Add via the dashboard's
**Sources** tab or `POST /api/sources` (see `/docs`). Generic RSS sources
are picked up by `src/ingestion/rss_ingester.py` on the next scheduled
run.

### Remove a noisy story or false-positive match

Click the trash icon on the article card in the dashboard, or
`DELETE /api/content/{id}`. To mark it irrelevant without deleting,
`POST /api/content/{id}/irrelevant`.
