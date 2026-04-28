# Monday.com Integration Setup

This document explains how to wire a Monday.com board to the Startup
Intelligence Platform, including the LinkedIn post-URL columns that drive
the **manual / Monday-as-source-of-truth** ingestion path.

---

## 1. Required environment variables

In your `.env` (or your hosting provider's env panel):

```ini
MONDAY_API_TOKEN=...        # Avatar → Admin → API → Generate
MONDAY_BOARD_ID=1234567890  # Visible in the board URL
# Optional — only set if your column titles differ from defaults below.
# MONDAY_COLUMN_MAP={"Founder Name":"founder_name", ...}
```

Get the token: Monday.com → click your avatar → **Admin** → **API** → generate
a **Personal API token** (v2). Keep it secret — it grants access to every
board you can see.

Get the board ID: open the board, look at the URL — `monday.com/boards/<ID>`.

---

## 2. Default column-title → DB-field mapping

The sync matches Monday columns by **column title**, case-sensitive. Either
rename your columns to match these titles, OR override the mapping via
`MONDAY_COLUMN_MAP` (a JSON object in env).

| Monday column title    | DB field                   | Notes                                            |
|------------------------|----------------------------|--------------------------------------------------|
| `Name`                 | `name`                     | The board item name. Always populated by Monday. |
| `Legal Name`           | `legal_name`               | Optional                                         |
| `Email`                | `contact_email`            |                                                  |
| `Contact`              | `contact_name`             | Used as fallback if no founder/co-founder names  |
| `Founder`              | `founder_name`             | **Primary scoring signal**                       |
| `Co-Founder`           | `cofounder_name`           |                                                  |
| `Founder LinkedIn`     | `founder_linkedin_url`     | Profile URL                                      |
| `Co-Founder LinkedIn`  | `cofounder_linkedin_url`   |                                                  |
| `LinkedIn`             | `linkedin_url`             | Company LinkedIn page                            |
| `Website`              | `website`                  |                                                  |
| `Twitter`              | `twitter_handle`           |                                                  |
| `Instagram`            | `instagram_handle`         |                                                  |
| `Industry`             | `industry`                 |                                                  |
| `Secondary Industry`   | `secondary_industry`       |                                                  |
| `Stage`                | `stage`                    |                                                  |
| `Status`               | `status`                   |                                                  |
| `Program Stream`       | `program_stream`           |                                                  |
| `Description`          | `description`              |                                                  |
| **`Founder Posts`**    | LinkedIn post URLs         | One or many URLs (see below)                     |
| **`Co-Founder Posts`** | LinkedIn post URLs         | One or many URLs                                 |
| **`Company Posts`**    | LinkedIn post URLs         | One or many URLs                                 |

---

## 3. The post-URL columns — bulletproof manual path

The three "Posts" columns are how a human researcher feeds **real LinkedIn
post URLs** into the platform. Each cell can hold multiple URLs.

**Accepted separators** (mix freely): newline, comma, semicolon, pipe.

**Accepted URL shapes** (validated by `classify_linkedin_url`):

| URL shape                                    | What it becomes        |
|----------------------------------------------|------------------------|
| `linkedin.com/posts/<slug>_<id>`             | Real post URL          |
| `linkedin.com/feed/update/urn:li:activity:…` | Real post URL          |
| `linkedin.com/pulse/<article-slug>`          | LinkedIn Pulse article |
| `linkedin.com/in/<slug>/recent-activity/…`   | Activity page (link only — not a single post) |
| `linkedin.com/company/<slug>/posts/…`        | Company activity page  |

**Rejected** (will NOT be stored as content): bare profile pages
(`linkedin.com/in/<slug>`), bare company pages (`linkedin.com/company/<slug>`),
`/jobs/`, `/login`, search results, profile directory pages.

**Author attribution** is set automatically by the column the URL came from
— `Founder Posts` → role `founder`, `Co-Founder Posts` → role `cofounder`,
`Company Posts` → role `company`.

---

## 4. Recommended workflow (no scraping required)

The product DOES NOT scrape Sales Navigator or LinkedIn directly. The intended
human-in-the-loop flow is:

1. Researcher uses Sales Navigator (or just LinkedIn directly) to find a
   relevant founder / co-founder / company post.
2. They copy the post URL (right-click on the timestamp → "Copy link").
3. They paste it into the right column (`Founder Posts` / `Company Posts`)
   on the Monday board for that startup. Multiple URLs in one cell are fine.
4. The next sync — manual or scheduled — pulls all rows and stores those
   URLs as `content_items` with `ingestion_status = 'url_only'`.
5. The dashboard renders each as a clickable card with an "Open LinkedIn
   Post" button. **Post text is not stored locally.**

---

## 5. Running the sync

```bash
# Preview the columns + current mapping (helpful before first sync)
python -m src.ingestion.monday_sync --preview-columns

# Dry run — log only, no DB writes
python -m src.ingestion.monday_sync --dry-run

# Live sync
python -m src.ingestion.monday_sync
```

Or via API:

```bash
curl -X POST http://localhost:8000/api/startups/sync-monday
```

The sync is **upsert by name** (case-insensitive). It creates new rows for
new startups and updates existing rows in place.

---

## 6. Custom column mapping

If your board uses different column titles, set:

```ini
MONDAY_COLUMN_MAP={"Founder Name":"founder_name","Cofounder Name":"cofounder_name","LinkedIn URL":"linkedin_url","Founder LinkedIn URL":"founder_linkedin_url","Founder Post URLs":"founder_posts","Company Post URLs":"company_posts"}
```

Keys = your Monday column titles. Values = the DB fields listed in the
table above. Anything not listed is ignored.

---

## 7. Avoiding CSV/Excel breakage

The historical CSV/Excel import path (`src.db.seed`) still works and is
unchanged by Monday integration. You can run them in either order:

- CSV/Excel first, then Monday sync → existing rows are matched by name and
  updated in place. Monday columns overwrite where they have non-empty values.
- Monday first, then CSV/Excel → CSV's seed logic only fills in NULL fields,
  so it won't clobber Monday-managed values.

---

## 8. Manual import without Monday — CSV path

If you don't have Monday yet, you can drop a CSV at `data/manual_posts.csv`
with columns:

```
startup_name,founder_post_urls,cofounder_post_urls,company_post_urls,linkedin_post_notes,linkedin_post_date,sales_nav_status
```

and run:

```bash
python -m src.ingestion.linkedin_ingester --csv data/manual_posts.csv --dry-run
python -m src.ingestion.linkedin_ingester --csv data/manual_posts.csv
```

A sample is provided at [`data/manual_posts.sample.csv`](data/manual_posts.sample.csv).
