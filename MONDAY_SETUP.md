# Monday.com Integration Setup

This app automatically syncs company data from a Monday.com board instead of requiring manual CSV exports.

## Quick Start

### 1. Get API Credentials

1. Go to [monday.com](https://monday.com) → click your **avatar** → **Admin** → **API**
2. Create a new API token and copy it
3. Find your **Board ID** in the URL: `monday.com/boards/123456789` → `123456789`

### 2. Configure Environment

Add to `.env`:

```env
MONDAY_API_TOKEN=your_token_here
MONDAY_BOARD_ID=your_board_id_here
```

### 3. Inspect Your Board

See what columns exist and how they map to the database:

```bash
python -m src.ingestion.monday_board_inspect
```

Output shows:
- All column titles, types, and IDs
- Current mapping (which Monday columns → database fields)
- Sample item structure

### 4. Sync Companies

**Dry run** (preview what would happen):

```bash
python -m src.ingestion.monday_sync --dry-run
```

**Live sync** (create/update companies):

```bash
python -m src.ingestion.monday_sync
```

**API endpoint:**

```bash
curl -X POST http://localhost:8000/api/startups/sync-monday
```

Response:
```json
{
  "status": "completed",
  "created": 328,
  "updated": 20,
  "skipped": 0,
  "errors": 0,
  "total": 348,
  "dry_run": false
}
```

## Column Mapping

By default, recognizes these Monday column titles and maps them to the database:

| Monday Column | Database Field |
| --- | --- |
| Name | name |
| Legal Name | legal_name |
| Email | contact_email |
| Contact | contact_name |
| Founder | founder_name |
| Co-Founder | cofounder_name |
| Founder LinkedIn | founder_linkedin_url |
| Co-Founder LinkedIn | cofounder_linkedin_url |
| Website | website |
| LinkedIn | linkedin_url |
| Twitter | twitter_handle |
| Instagram | instagram_handle |
| Industry | industry |
| Secondary Industry | secondary_industry |
| Stage | stage |
| Status | status |
| Program Stream | program_stream |
| Description | description |
| Founder Posts | founder_posts |
| Company Posts | company_posts |
| Co-Founder Posts | cofounder_posts |

### Custom Mapping

If your board uses different column names, customize in `.env`:

```env
MONDAY_COLUMN_MAP={"My Company Name":"name","My Founder":"founder_name","My Website":"website"}
```

Only listed columns are synced; unmapped columns are ignored.

## How It Works

1. Fetch board items and columns via GraphQL API
2. Map each Monday item → normalized row object (same format as CSV import)
3. Upsert by company name (case-insensitive):
   - If exists → update non-empty fields
   - If new → create with available fields
4. LinkedIn URLs in "Founder Posts", "Company Posts", etc. are imported as manual posts

## Existing CSV Flow Still Works

CSV uploads remain unchanged. You can:
- Use **only Monday.com sync**
- Use **only CSV uploads**
- Use **both** (they complement each other)

## CLI Commands

```bash
# Inspect board structure
python -m src.ingestion.monday_board_inspect

# Preview what would sync
python -m src.ingestion.monday_sync --dry-run

# Live sync
python -m src.ingestion.monday_sync

# Show column mapping
python -m src.ingestion.monday_sync --preview-columns
```

## Periodic Syncs

To sync automatically on schedule (e.g., every 6 hours with cron):

```bash
0 */6 * * * cd /path/to/app && python -m src.ingestion.monday_sync
```

Or add to your scheduler (systemd timer, Docker, etc.).

## API Endpoints

### POST /api/startups/sync-monday

Trigger sync via API.

**Optional params:**
- `dry_run=true` — preview without writing

**Response:**
```json
{
  "status": "completed",
  "created": 328,
  "updated": 20,
  "skipped": 0,
  "errors": 0,
  "total": 348,
  "dry_run": false
}
```

### GET /api/startups/columns-preview

View board structure and current column mapping.

## Troubleshooting

**"not_configured"** → Check MONDAY_API_TOKEN and MONDAY_BOARD_ID in .env

**API token errors** → Regenerate token at monday.com Admin > API

**Column shows "(unmapped)"** → Either:
1. Add to MONDAY_COLUMN_MAP in .env
2. Rename column in Monday.com to match default names
3. Leave unmapped (it's skipped)

**Sync creates duplicates** → Shouldn't happen — matches by company name. If it does, check company name spelling in Monday.com.

## FAQ

**Q: Does it delete companies?**
No — sync only creates or updates. Removed companies stay in the database.

**Q: What if a field is empty?**
Empty values are skipped. Existing database values aren't overwritten with blanks.

**Q: How often should I sync?**
Depends on your needs. Hourly is common for active boards. Dry-run shows what would change.

**Q: Can I sync only certain companies?**
Currently syncs the entire board. Filter by status in Monday.com if needed.

## For Developers

The integration is split across:

- `src/ingestion/monday_sync.py` — Core sync logic, GraphQL queries, upsert
- `src/ingestion/monday_board_inspect.py` — CLI to view board structure
- `src/routes/startups.py` — API endpoints

GraphQL queries handle pagination (up to 100 items per request). Column IDs are mapped to titles to enrich the returned data.

The upsert logic reuses the same pattern as CSV import — just feed normalized rows to the existing company ingestion layer.
