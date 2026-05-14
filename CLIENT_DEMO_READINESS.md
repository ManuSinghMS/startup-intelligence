# Client Demo Readiness

## Status: READY (URL-First, Demo-Safe)

The platform is intentionally **honest** about LinkedIn: it does not scrape
LinkedIn or Sales Navigator, does not use paid APIs, and does not pretend
to have post text it doesn't have. It captures real LinkedIn **URLs** and
presents them as clickable links, plus a Google News fallback for general
web mentions.

---

## What's actually working

| Component                         | Status        | Notes                                                                 |
|-----------------------------------|---------------|-----------------------------------------------------------------------|
| FastAPI server                    | Ready         | Starts on `$PORT`, runs migrations on startup                         |
| Database migrations               | Ready         | Idempotent; rebuilds `content_items` to drop legacy CHECK constraint  |
| News ingestion (Google News)      | Ready         | Per-startup search; founder-weighted scoring                          |
| LinkedIn URL ingestion (manual)   | Ready         | Bulletproof — Monday.com columns OR CSV (sample at `data/manual_posts.sample.csv`) |
| LinkedIn URL ingestion (auto)     | Best-effort   | Google News indexing of `site:linkedin.com/posts/`. Often returns 0 for small startups. |
| Newsletter (Gmail IMAP)           | Needs config  | Requires `NEWSLETTER_EMAIL` / `NEWSLETTER_APP_PASSWORD`               |
| Monday.com sync                   | Ready, needs token | Requires `MONDAY_API_TOKEN` + `MONDAY_BOARD_ID`                  |
| Founder-weighted scoring          | Ready         | 0.90/0.70 founder vs 0.50/0.30 company; cross-match bonus +0.10       |
| LLM classification (optional)     | Needs config  | OpenAI / Copilot / Groq                                                |
| Dashboard                         | Ready         | Renders URL-only LinkedIn cards distinct from news/blog cards         |

---

## Source-type and classification taxonomy

`content_items.source_type` is one of `news / newsletter / social / press / blog`.

`content_items.classification` carries either a news category (for scraped
articles) **or** a LinkedIn URL kind (for URL-only LinkedIn items):

| URL kind                  | What it is                                                  | Stored as content? |
|---------------------------|-------------------------------------------------------------|--------------------|
| `founder_post_url`        | `linkedin.com/posts/...`, `/feed/update/...`, `/pulse/...` |  yes              |
| `cofounder_post_url`      | same, attributed to a co-founder                            |  yes              |
| `company_post_url`        | same, on a company page                                     |  yes              |
| `founder_activity_page`   | `linkedin.com/in/<slug>/recent-activity/`                   |  yes (separate)   |
| `cofounder_activity_page` | same, co-founder                                            |  yes              |
| `company_activity_page`   | `linkedin.com/company/<slug>/posts/`                        |  yes              |
| `founder_profile_url`     | `linkedin.com/in/<slug>` (bare profile)                     |  no — updates `founder_linkedin_url` instead |
| `cofounder_profile_url`   | same, co-founder                                            |  no — updates startup row |
| `company_page_url`        | `linkedin.com/company/<slug>` (bare page)                   |  no — updates startup row |
| `news_mention`            | News article that explicitly references a LinkedIn post     |  yes              |
| `web_mention`             | Other web reference (reserved)                              |  yes              |

URL-only items have `ingestion_status='url_only'`. The dashboard renders them
with a clear "Open LinkedIn Post" button and never claims the post text was
scraped.

---

## Recommended demo workflow

### 1. Make sure the DB has data

If first run, seed from the supplied Excel/CSV:
```bash
python -m src.db.seed
```
Or sync from a Monday board:
```bash
python -m src.ingestion.monday_sync --dry-run   # preview
python -m src.ingestion.monday_sync             # commit
```

### 2. Walk through the URL-first LinkedIn path

```bash
# (a) Demo fixture — zero network calls, perfect for a hostile demo network
python -m src.ingestion.linkedin_ingester --demo

# (b) Manual URL import from a CSV — the bulletproof path
python -m src.ingestion.linkedin_ingester --csv data/manual_posts.sample.csv --dry-run
python -m src.ingestion.linkedin_ingester --csv data/manual_posts.sample.csv

# (c) Auto-discovery dry run — small batch, gentle on Google
python -m src.ingestion.linkedin_ingester --dry-run --limit 3 --batch-size 1 --sleep-seconds 5
```

### 3. Show the dashboard

```bash
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
# open http://localhost:8000
```

URL-only LinkedIn items appear with a blue left border, a clear " Open
LinkedIn Post" CTA, and the role attribution (`founder` / `cofounder` /
`company`).

---

## What the dry-run output looks like

```
[LinkedIn] Processing HYGN Energy Inc.
[LinkedIn] Checking manual/Monday post URLs (handled by Monday sync / API)...
[LinkedIn] Founder URL missing for Thomas Ross. Running discovery only.
[LinkedIn] Discovery found possible founder profile: https://www.linkedin.com/in/thomas-ross
[LinkedIn] Not storing discovery result as content item.
[LinkedIn] Searching for recent LinkedIn post URLs for Thomas Ross
[LinkedIn] Searching for recent LinkedIn post URLs for company HYGN Energy Inc.
[LinkedIn] Found 3 candidate result(s)
[LinkedIn] DRY-RUN would store founder_post_url: https://www.linkedin.com/posts/...
[LinkedIn] Valid post URLs: 1
[LinkedIn] Activity pages: 0
[LinkedIn] Invalid/profile-only URLs skipped: 2
```

---

## Constraints we honor (deliberately)

-  No paid LinkedIn APIs, Phantombuster, Clay, Sales Navigator exporters,
  or paid proxies.
-  No aggressive scraping, IP rotation, or "stay-under-the-radar" tactics.
-  No scraping Sales Navigator pages — Sales Navigator is treated as a
  human-assisted research console; URLs are pasted into Monday.
-  No storing generic profile pages or search-result pages as posts.
-  No labeling of Google News results as LinkedIn posts unless the URL
  itself is a LinkedIn post URL.

---

## Known limitations

1. **Auto-discovery coverage is limited.** Google indexes only a fraction of
   LinkedIn posts, especially for small/early-stage startups. Plan on
   `--demo` or manual/Monday/CSV ingestion for guaranteed content.
2. **Post text is not stored** for URL-only items. The card shows the title
   (or URL) and a click-out to LinkedIn.
3. **Render free tier** has cold starts (~30s after 15 min idle).
4. **DDGS / generic web search** still exists in `company_search.py` for
   news enrichment, but is rate-limit-prone. Use Google News as the primary
   feed for live runs.

---

## Pre-demo checklist

- [ ] `.env` exists and `DATABASE_PATH` is set
- [ ] `python -m src.db.migrate` runs cleanly (no errors)
- [ ] `pytest tests/` passes (65 tests)
- [ ] `python -m src.ingestion.linkedin_ingester --demo` shows 3 fixtures
- [ ] Dashboard loads at `/` and shows existing news content
- [ ] Manual / Monday post URL ingestion dry-run shows the role attribution
- [ ] If using Monday: `python -m src.ingestion.monday_sync --preview-columns` lists every expected column

---

## Sales Navigator workflow (human-in-the-loop)

If the team has Sales Navigator, the intended use is:

1. Use Sales Navigator search/saved-leads/alerts to find relevant founder /
   company posts.
2. Copy the post URL (right-click on the post timestamp → "Copy link").
3. Paste it into the matching `Founder Posts` / `Co-Founder Posts` /
   `Company Posts` column on the Monday board for that startup.
4. Run the Monday sync. The platform stores those URLs as content, dedupes
   by canonical URL, and renders them as clickable LinkedIn cards.

The platform NEVER scrapes Sales Navigator pages directly.
