# Handoff

Start here. This page tells the team taking over what to do, in what
order, and which document answers which question.

## What this project is

A small FastAPI web app that tracks news, social posts, and newsletter
mentions for the ~347 companies in The Forge incubator. It searches
Google News for each company, filters out irrelevant matches, classifies
each article with an LLM (Groq's free tier), and shows the result in a
dashboard. There is also a weekly digest view and a Gmail-IMAP path for
newsletter ingestion.

Live demo:           https://startup-intelligence.fly.dev (will stay up
                     until you are comfortable on your own deploy).

## Recommended handoff path: fork and deploy fresh

The clean break: you own your GitHub fork, your Fly.io account, your
billing, your credentials. No shared accounts.

1. Click **Fork** on the GitHub repo into your team's GitHub org.
2. Sign up for free accounts you will need:
   - Fly.io: https://fly.io/app/sign-up
   - Groq: https://console.groq.com (free tier, for the LLM)
3. Get a Monday.com API token from your existing board. See
   [MONDAY_SETUP.md](MONDAY_SETUP.md).
4. Follow [FLY_DEPLOY.md](FLY_DEPLOY.md) step-by-step. ~30 minutes from
   "flyctl install" to a live URL like
   `https://startup-intel-mcmaster.fly.dev`.
5. Open the new URL, click **Sync from Monday.com**, then click
   **Ingest Next Batch** a few times to populate news for your
   companies.

The original developer's deploy at `startup-intelligence.fly.dev` will
stay up until you say otherwise, so you have a fallback.

## Other handoff options (if Option A does not fit)

- **Transfer the existing Fly app.** Keeps the same URL + database. The
  original developer goes to Fly dashboard -> app -> Settings -> Transfer
  ownership and enters your Fly org. Faster, but you inherit their
  infrastructure setup rather than building your own.
- **Run side-by-side during a transition.** You deploy fresh (Option A)
  while the original developer's deploy keeps running for 2-4 weeks as a
  safety net. Then it gets torn down once you are confident.

## Read these in order

| When | Read |
|---|---|
| Right now (5 min overview) | [README.md](README.md) |
| When you are ready to deploy (~30 min) | [FLY_DEPLOY.md](FLY_DEPLOY.md) |
| Before non-technical staff start using the dashboard | [USER_GUIDE.md](USER_GUIDE.md) |
| When something breaks, or you need to change behavior | [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) |
| If you want to wire up newsletter ingestion from a Gmail inbox | [NEWSLETTER_SETUP.md](NEWSLETTER_SETUP.md) |
| If you change anything about the Monday.com board structure | [MONDAY_SETUP.md](MONDAY_SETUP.md) |

## Credentials you need to get yourself

| Credential | Where | Purpose |
|---|---|---|
| Groq API key | https://console.groq.com -> API Keys -> Create | LLM (free tier; classifier + relevance filter + digest) |
| Monday.com API token | monday.com -> Profile -> Admin -> API | Sync the company list |
| Monday.com Board ID | The board URL contains it | Same |
| (Optional) Gmail address + App Password | https://myaccount.google.com/apppasswords | Newsletter ingestion. Walkthrough in NEWSLETTER_SETUP.md |

Once you have them, set them on your Fly app (replace placeholder values):

```bash
flyctl secrets set LLM_PROVIDER=groq
flyctl secrets set GROQ_API_KEY=gsk_yourKeyHere
flyctl secrets set MONDAY_API_TOKEN=eyJ...yourTokenHere
flyctl secrets set MONDAY_BOARD_ID=18407911760
```

Never put these in `.env` and commit them - `.env` is gitignored for a
reason. Fly secrets are the durable home for production credentials.

## One thing to know about Fly's free tier

Fly.io's free trial caps each machine at 5 minutes of activity. Inside
that window the pipeline reliably handles ~25 companies per click; a
full pass over 347 companies takes ~14 clicks. To lift the cap, add a
credit card to your Fly.io account at
https://fly.io/dashboard/<your-org>/billing. There is no charge for
normal usage of this app - the card just unlocks long-running machines.

Once the cap is lifted you can raise the batch size and let the
scheduler run automatic ingests:

```bash
flyctl secrets set INGEST_BATCH_LIMIT=75
flyctl secrets set INGESTION_INTERVAL_MINUTES=1440
flyctl deploy
```

## After deploy - sanity check

1. Open your live URL. The dashboard should load and show 0 content
   items (clean DB).
2. Click **Sync from Monday.com** (under Companies). You should see
   ~347 companies imported.
3. Click **Run Ingestion** -> **Ingest Next Batch**. Watch the live
   progress modal. After ~3-5 minutes you should see ~25 companies
   processed, some new articles classified.
4. Click around: Dashboard, Analytics, Companies, Weekly Digest. All
   four should render.

If any of those steps misbehaves, the troubleshooting section of
[FLY_DEPLOY.md](FLY_DEPLOY.md) covers the common failure modes.

## Questions

- Operating the dashboard: [USER_GUIDE.md](USER_GUIDE.md)
- Deploying / DevOps: [FLY_DEPLOY.md](FLY_DEPLOY.md)
- Modifying the code: [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md)
- Anything else: open a GitHub issue on your fork.
