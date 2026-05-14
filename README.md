# Startup Intelligence Platform

A small FastAPI application that tracks news, social posts, and newsletter
mentions for portfolio companies (built for The Forge incubator at McMaster
University). Ingests from Google News, RSS, Monday.com, and Gmail; uses an
LLM to classify and summarize content; serves a dashboard.

## Documentation

The README is intentionally short. Pick the doc that matches your role:

| If you are... | Read |
|---|---|
| A non-technical user opening the dashboard for the first time | [USER_GUIDE.md](USER_GUIDE.md) |
| A developer who needs to run, modify, or understand the code | [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) |
| Deploying this to Fly.io from scratch (your own account) | [FLY_DEPLOY.md](FLY_DEPLOY.md) |
| Connecting a Gmail inbox for newsletter ingestion | [NEWSLETTER_SETUP.md](NEWSLETTER_SETUP.md) |
| Connecting Monday.com as a source of truth for companies | [MONDAY_SETUP.md](MONDAY_SETUP.md) |

## What it does in one paragraph

The team imports a list of companies (from Monday.com, CSV, or Excel). On a
schedule (or on-demand from the dashboard), the platform searches Google News
for each company, filters out irrelevant matches with a relevance score, and
classifies each remaining article as funding / hiring / product launch /
milestone / partnership / customer win / general using an LLM (Groq's free
tier by default). The dashboard groups recent items by company and offers a
weekly digest summary.

## Quick local run

```bash
pip install -r requirements.txt
cp .env.example .env       # fill in MONDAY_API_TOKEN and GROQ_API_KEY
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

Dashboard: http://localhost:8000 - API docs: http://localhost:8000/docs

## Production

The currently-deployed instance lives on Fly.io. See
[FLY_DEPLOY.md](FLY_DEPLOY.md) for the full deploy story (forking the repo
into the team's own GitHub, creating a Fly app, setting secrets, etc.).

## Important operational note

Fly.io's free trial machines auto-stop after 5 minutes of activity. To make
this deploy production-ready the team needs to add a credit card to the
Fly.io account (no charge for the free allowance, but the timeout is lifted).
The ingestion pipeline has been tuned to make as much progress as possible
within a 5-minute window in case the trial limit is still in place - see
[DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) for the details.
