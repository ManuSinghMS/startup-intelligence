# User Guide

For Forge staff and program managers operating the Startup Intelligence
dashboard day-to-day. No coding knowledge needed.

## What is this thing?

It is a website that watches the news for every company in your portfolio.
Every day (or whenever you click "Run Ingestion") it goes out to Google News,
finds articles that mention each of your companies, and groups them by
company on the dashboard. It then uses AI to tag each article with what kind
of story it is - funding, hiring, product launch, milestone, partnership,
customer win, or general news.

The goal: instead of you Googling 347 companies one by one each week, the
dashboard does it for you and shows you what is new.

## Opening the dashboard

The live dashboard is hosted on Fly.io. The URL is in your handoff email
(something like `https://startup-intelligence.fly.dev`). Open it in any
browser. There is no login.

## The five main sections (top nav)

1. **Dashboard** - the main feed. Recent articles grouped by company.
   Filter on the left by source type, category, or date.
2. **Analytics** - charts. How many funding stories this month, which
   companies were in the news most, etc.
3. **Companies** - the master list of every company being tracked. You
   can click into one to see its full history.
4. **Weekly Digest** - an AI-generated executive summary of the week.
5. **Sources** - the RSS feeds and news sites the platform monitors.
   Most people will not touch this.

## How to add or remove companies

The list of companies the platform tracks comes from your Monday.com board.
Whenever you add a new company on Monday.com, click **Run Ingestion ->
Ingest Next Batch** on the dashboard (or wait for the next scheduled run)
and it will pick the new company up automatically.

If you do not use Monday.com for some reason, you can also bulk-import
companies from an Excel or CSV file:

1. Go to **Companies**.
2. Click **Import CSV / Excel**.
3. Upload an exported Monday.com Excel file. Duplicates are skipped
   automatically.

To deactivate a company so it stops being ingested, open the company page
and click **Deactivate** (a "not_active" tag is added; the company is not
deleted, just skipped from now on).

## How to fetch fresh news ("Run Ingestion")

This is the button you will use most.

1. Click **Run Ingestion** in the top right.
2. A modal opens. It tells you how many companies have been processed in
   the last 24 hours (e.g. "Cycle so far: 73 of 347 companies").
3. Click **Ingest Next Batch**. The platform processes the next ~25
   companies in rolling order (always the ones whose news has not been
   refreshed for the longest time, so over many clicks it cycles through
   the whole portfolio).
4. A live progress bar shows you which company is currently being
   processed and how many new articles have been found so far. Each
   article is also automatically classified (tagged as funding / hiring /
   etc.) as it is added.
5. When the run finishes, the dashboard refreshes automatically.

### Why only 25 at a time?

Two reasons:

- Google News and the AI service we use have free-tier rate limits. If we
  hammered them with 347 companies at once we would get throttled.
- The Fly.io free trial cuts off any work that runs longer than 5 minutes.
  25 companies is the most we can reliably finish inside that window. The
  team can lift this limit by adding a credit card to the Fly.io account
  (no charge for the included allowance; see
  [FLY_DEPLOY.md](FLY_DEPLOY.md)).

If you want news for one specific company immediately, use **Select
Specific** inside the modal instead of "Ingest Next Batch".

## How to read the dashboard

Each company shows up as a card with its 5 most recent articles. The colored
tags ("funding", "hiring", etc.) come from the AI classifier. The dot
on each card indicates sentiment: green = positive, gray = neutral, red =
negative.

The left-side filters narrow the feed:

- **Source Type** - news, newsletter, social, press, blog
- **Category** - funding, product, milestones, hiring, partnership, customers
- **Time Period** - last 7 / 30 / 90 days, or all-time

Click any article to open the original source in a new tab.

## How to read the weekly digest

Click **Weekly Digest**. The dashboard generates (or loads the cached version
of) an AI-written summary of what happened across all companies in the past
7 days. You can copy it into a Slack post or email.

## Troubleshooting

### "I clicked Run Ingestion but nothing seems to be happening"

Open the modal again. If the live progress bar shows percentages going up,
it is working - it just runs in the background, so you can close the modal
and come back later. If the progress bar is stuck at 0% for more than a
minute, click the **Server logs (debug)** disclosure in the modal and copy
the last few lines to the developer.

### "All my articles say 'general' - the AI never tags them properly"

This means either the AI service is rate-limited (Groq's free tier) or the
API key is unset. Forward the URL of the dashboard and the message to your
developer; they can check the Fly.io secrets.

### "The dashboard is empty / says 'Failed to load'"

The server might have auto-stopped (Fly.io stops idle machines to save
money; it boots back up on the first request, which takes ~10 seconds).
Refresh the page once and wait. If still broken after 30 seconds, contact
the developer.

### "I imported companies but the count did not go up"

The importer skips duplicates by name. If a company already existed (even
spelled slightly differently), it will not be re-added. Check the
**Companies** list to see if it is already there under a slightly different
name.

## Who to contact

- Operational issues (a button does not work, data looks wrong): your
  developer / McMaster team.
- New feature requests, removing a noisy news source: same.
- The Forge program decisions on what should be tracked: Forge leadership.
