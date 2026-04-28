# 🚀 Startup Intelligence Platform

Real-time intelligence on portfolio companies — automated ingestion from news, LinkedIn, newsletters, and Monday.com.

## Features

- **News Ingestion** — Google News + DuckDuckGo, RSS feeds, HTML scraping
- **LinkedIn (URL-First)** — Manual/Monday/CSV post-URL ingestion as the
  primary path; Google News best-effort discovery as a secondary path. No
  scraping of LinkedIn or Sales Navigator. URL-only items are stored with
  `ingestion_status='url_only'` and shown as clickable cards.
- **Newsletter Monitoring** — Gmail IMAP polling + Substack RSS
- **Monday.com Sync** — Auto-sync startups + LinkedIn post URL columns
  (`Founder Posts`, `Co-Founder Posts`, `Company Posts`)
- **LLM Classification** — OpenAI / Copilot / Groq powered content categorization
- **Founder-Weighted Scoring** — Founder/co-founder names are the primary
  match signal (0.90/0.70) over company names (0.50/0.30) since names rename.
- **Weekly Digests** — AI-generated executive summaries
- **REST API** — Full FastAPI backend with Swagger docs

## Quick Start

```bash
# 1. Clone and install
git clone <your-repo-url>
cd startup-intel
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env with your API keys

# 3. Run
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000

# 4. Open
# Dashboard → http://localhost:8000
# API Docs  → http://localhost:8000/docs
```

## Architecture

```
src/
├── main.py                  # FastAPI app entry point
├── db/
│   ├── database.py          # SQLite connection (WAL mode)
│   ├── schema.sql           # Database schema
│   ├── migrate.py           # Schema migrations
│   └── seed.py              # CSV/Excel import
├── ingestion/
│   ├── company_search.py    # Google News + DuckDuckGo search
│   ├── linkedin_ingester.py # LinkedIn intelligence (free)
│   ├── email_ingester.py    # Gmail IMAP polling
│   ├── newsletter_ingester.py # Substack RSS
│   ├── rss_ingester.py      # RSS feed ingestion
│   ├── monday_sync.py       # Monday.com API sync
│   ├── scheduler.py         # APScheduler background jobs
│   └── dedup.py             # Deduplication
├── scoring/
│   └── relevance.py         # Founder-weighted relevance scoring
├── llm/
│   ├── provider.py          # LLM abstraction (OpenAI/Copilot/Groq)
│   ├── classifier.py        # Content classification
│   └── summarizer.py        # AI summary generation
├── routes/
│   ├── startups.py          # Startup CRUD + Monday.com sync
│   ├── content.py           # Content management
│   ├── social.py            # LinkedIn + newsletter triggers
│   ├── sources.py           # Source management
│   └── summaries.py         # AI summaries
└── static/                  # Dashboard HTML
```

## Ingestion Pipeline

The scheduler runs all ingestion automatically. Each source:

| Source | Method | Config Required |
|--------|--------|----------------|
| News | Google News RSS + DuckDuckGo | None |
| LinkedIn | Google News + DuckDuckGo search | None (free) |
| Newsletter | Gmail IMAP | `NEWSLETTER_EMAIL`, `NEWSLETTER_APP_PASSWORD` |
| Monday.com | GraphQL API v2 | `MONDAY_API_TOKEN`, `MONDAY_BOARD_ID` |
| RSS | Feed polling | Add sources via API |

### LinkedIn (URL-first, no scraping)

LinkedIn post URLs are gathered three ways, in priority order:

1. **Manual / Monday.com** (most reliable). Paste post URLs into the Monday
   columns `Founder Posts` / `Co-Founder Posts` / `Company Posts`, then run
   `python -m src.ingestion.monday_sync`.
2. **CSV** — for environments without Monday.com. Drop a CSV like
   [`data/manual_posts.sample.csv`](data/manual_posts.sample.csv) and run:
   ```bash
   python -m src.ingestion.linkedin_ingester --csv data/manual_posts.csv
   ```
3. **Auto-discovery** (best effort). Searches Google News for indexed
   `linkedin.com/posts/` URLs. Often returns 0 for small/early startups.
   ```bash
   python -m src.ingestion.linkedin_ingester --dry-run --limit 3 --batch-size 1 --sleep-seconds 5
   python -m src.ingestion.linkedin_ingester --demo            # zero-network fixture
   python -m src.ingestion.linkedin_ingester --company "CompanyName"
   ```

URL validation rules: `linkedin.com/posts/...`, `/feed/update/...`, and
`/pulse/...` are real post URLs. `/recent-activity/` and
`/company/<slug>/posts/` are activity pages (stored but flagged separately).
Bare profile/company pages update the startup row but are NOT stored as
content. Profile-directory pages, `/jobs/`, `/login`, etc. are rejected.

See [MONDAY_SETUP.md](MONDAY_SETUP.md) for the Sales-Navigator-assisted
human workflow.

### Monday.com

Syncs startups from a Monday.com board, including LinkedIn post-URL columns.

```bash
# Preview columns
python -m src.ingestion.monday_sync --preview-columns

# Dry run
python -m src.ingestion.monday_sync --dry-run

# Sync
python -m src.ingestion.monday_sync
```

Required env: `MONDAY_API_TOKEN`, `MONDAY_BOARD_ID`. Full setup in
[MONDAY_SETUP.md](MONDAY_SETUP.md).

## Scoring

Relevance scoring prioritizes **founder/co-founder names** over company names:

| Signal | Score |
|--------|-------|
| Founder name in title | 0.90 |
| Founder name in body | 0.70 |
| Company name in title | 0.50 |
| Company name in body | 0.30 |
| Both founder + company | 1.00 |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/startups` | List all startups |
| POST | `/api/startups` | Create startup |
| POST | `/api/startups/sync-monday` | Sync from Monday.com |
| POST | `/api/social/linkedin/ingest` | Run LinkedIn ingestion |
| GET | `/api/social/linkedin/status` | LinkedIn health check |
| POST | `/api/social/newsletter/ingest` | Poll newsletter inbox |
| GET | `/api/content` | List content items |
| GET | `/api/summaries/weekly` | Weekly digest |

Full API docs at `http://localhost:8000/docs`

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for Render, Railway, and VPS instructions.

Quick deploy to Render:
1. Push to GitHub
2. Connect repo on [render.com](https://render.com)
3. Click "Deploy" — `render.yaml` blueprint handles the rest

## Tests

```bash
pytest tests/ -v
```

## Environment Variables

See [.env.example](.env.example) for the complete list.
