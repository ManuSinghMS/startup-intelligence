# Deploying to Fly.io

End-to-end instructions for the team taking over: how to fork the repo
into your own GitHub, deploy to your own Fly.io account, configure
secrets, and make changes after that.

If you are deploying somewhere other than Fly.io, see
[DEPLOYMENT.md](DEPLOYMENT.md) (covers Render, Railway, VPS).

## What "handing this off" means

The current deploy lives in the original developer's Fly.io account. To
take ownership, you have two choices:

| Option | What it gets you | Effort |
|---|---|---|
| A. Transfer the existing Fly app | Keeps the same URL and database | Requires the original owner to invite you as an org member |
| B. Deploy fresh in your own account | A clean Fly app under your billing, fresh database | The path described below |

Option B is what the rest of this document walks through. The database
gets re-seeded by re-importing from Monday.com on the first ingestion
run, so nothing is lost.

## Prerequisites

You need:

- A GitHub account.
- A Fly.io account: https://fly.io/app/sign-up (free).
- The Fly.io CLI installed: https://fly.io/docs/flyctl/install/
  - On Windows: `iwr https://fly.io/install.ps1 -useb | iex`
  - On macOS: `brew install flyctl`
  - On Linux: `curl -L https://fly.io/install.sh | sh`
- A credit card on the Fly.io account if you want to lift the 5-minute
  trial timeout. The free allowance is plenty for this app; the card
  is required to opt-in to long-running machines, not because it costs
  money.
- A Groq API key (free, for the LLM): sign up at
  https://console.groq.com and create an API key.
- A Monday.com API token + board ID (see [MONDAY_SETUP.md](MONDAY_SETUP.md)).

## Step 1: Fork the repo

1. Go to the GitHub repo (the original developer will send you the URL).
2. Click **Fork** -> choose your team's GitHub account/org.
3. Clone your fork locally:

   ```bash
   git clone https://github.com/YOUR_ORG/startup-intelligence.git
   cd startup-intelligence
   ```

## Step 2: Sign in to Fly

```bash
flyctl auth login
```

This opens a browser; log in to your Fly.io account.

## Step 3: Create a new Fly app

```bash
flyctl apps create startup-intel-mcmaster
```

Pick any name you want - it becomes part of your URL
(`https://startup-intel-mcmaster.fly.dev`). The name must be globally
unique on Fly.io. If it is already taken, pick a different one.

Edit [fly.toml](fly.toml) and change the `app = ...` line at the top to
match the name you chose:

```toml
app = 'startup-intel-mcmaster'
primary_region = 'iad'   # 'iad' = US East. Change to 'yyz' for Toronto if you prefer Canadian region.
```

## Step 4: Create the persistent volume

The SQLite database needs to survive deploys. Fly.io has volumes for that.

```bash
flyctl volumes create startup_intel_data --region iad --size 1
```

Region must match `primary_region` in `fly.toml`. The name
`startup_intel_data` must match the `[[mounts]]` block at the bottom of
`fly.toml` (it already does - just leave it alone).

## Step 5: Set secrets

These are the API keys / tokens. Do **not** put them in `.env` or commit
them - put them on Fly:

```bash
flyctl secrets set LLM_PROVIDER=groq
flyctl secrets set GROQ_API_KEY=gsk_yourGroqKeyHere
flyctl secrets set MONDAY_API_TOKEN=eyJ...yourMondayTokenHere
flyctl secrets set MONDAY_BOARD_ID=18407911760
```

Optional, if you want newsletter ingestion (see
[NEWSLETTER_SETUP.md](NEWSLETTER_SETUP.md)):

```bash
flyctl secrets set NEWSLETTER_EMAIL=your-team-inbox@gmail.com
flyctl secrets set NEWSLETTER_APP_PASSWORD=xxxxxxxxxxxxxxxx
```

Verify:

```bash
flyctl secrets list
```

## Step 6: Deploy

```bash
flyctl deploy
```

This builds the Docker image (using the included [Dockerfile](Dockerfile)),
pushes it to Fly's registry, and starts a machine. First deploy takes
3-5 minutes. Subsequent deploys are faster (~1-2 minutes).

When it is done, open the URL it prints (something like
`https://startup-intel-mcmaster.fly.dev`).

## Step 7: First-run setup (in the dashboard)

1. Open the dashboard URL.
2. Go to **Companies** -> click **Sync from Monday.com** (or upload an
   Excel export with **Import CSV / Excel**). This populates the company
   list.
3. Click **Run Ingestion** -> **Ingest Next Batch**. Watch the progress
   bar. The first batch of ~25 companies will fetch news and classify
   each article.
4. Click again to process the next batch. Repeat until you have cycled
   through everyone (the modal shows "Cycle so far: X of 347" - keep
   clicking until X = 347).

## Step 8 (recommended): Lift the trial timeout

Without this step, Fly.io will kill the machine after 5 minutes of
activity every time. The pipeline copes (each click finishes a partial
batch in <5 min), but production deployments should not be on a trial.

1. https://fly.io/dashboard/your-org/billing
2. Add a credit card. There is no charge for normal usage; this just
   unlocks long-running machines.
3. Once added, you can raise the batch size:

   ```bash
   flyctl secrets set INGEST_BATCH_LIMIT=75
   flyctl deploy   # apply the change
   ```

   And you can let the scheduler run automatic daily ingests:

   ```bash
   flyctl secrets set INGESTION_INTERVAL_MINUTES=1440
   ```

## Making code changes after that

```bash
# edit files locally
git add -p
git commit -m "your change"
git push origin main
flyctl deploy
```

That is the whole loop. You can also wire up GitHub Actions to auto-deploy
on push to `main`:

```yaml
# .github/workflows/deploy.yml
name: Deploy to Fly
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - run: flyctl deploy --remote-only
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

Get the `FLY_API_TOKEN` via `flyctl tokens create deploy -x 999999h` and
add it as a GitHub Actions secret.

## Operating the deploy

### Viewing logs

```bash
flyctl logs              # live tail
flyctl logs --no-tail    # recent only
```

### Restarting

```bash
flyctl machine restart
```

### SSH into the machine

```bash
flyctl ssh console
```

Useful for poking around the SQLite database directly.

### Pulling the production database to your laptop

```bash
flyctl ssh sftp get /data/startup_intel.db ./prod.db
sqlite3 prod.db
```

### Scaling memory or CPU

`fly.toml` has a `[[vm]]` block. Bump `memory = '2gb'` and
`flyctl deploy` if the app starts running out of RAM (probably will not
for 347 companies, but might if you grow past ~5,000).

### Rolling back a bad deploy

```bash
flyctl releases                   # list recent deploys
flyctl deploy --image registry.fly.io/your-app:deployment-XXX
```

Or revert the offending commit on GitHub and push - `flyctl deploy`
rebuilds from `main`.

## Costs

Fly's free tier covers:

- 3 shared-cpu-1x machines with 256MB RAM (you can run this on one).
- 3GB persistent volume storage (the DB is well under 100MB for this scale).
- 160GB outbound bandwidth.

This app fits comfortably inside the free tier even after adding a card.
The card unlocks longer machine runtime; it does not start billing until
you exceed the free allowance.

## Troubleshooting

### `flyctl deploy` says "no machine"

```bash
flyctl machine list
```

If empty, the deploy failed to create one. Run `flyctl deploy` again -
sometimes a transient Fly.io API hiccup.

### `502 Bad Gateway` when opening the URL

Machine is starting up. Wait 10-15 seconds and refresh. If it persists,
check `flyctl logs` for crashes.

### Ingestion stops at ~10 companies

The trial timeout is still active. Add a credit card (Step 8) or accept
that each click only does part of the portfolio.

### News articles classify as "general" only

The LLM credentials are wrong. Check:

```bash
flyctl secrets list                          # are LLM_PROVIDER and GROQ_API_KEY present?
flyctl ssh console -C "printenv | grep -i llm"
flyctl logs | grep -i "LLM classification"
```

If `GROQ_API_KEY` is missing, re-run Step 5.

### "Database is locked" errors

SQLite WAL mode allows concurrent reads + one writer. If you see this,
likely another process is connected (e.g. you left `sqlite3` open in an
SSH session). Close it, or restart the machine.

### After a deploy, the dashboard is empty

The volume was probably not mounted. Check `fly.toml` still has the
`[[mounts]]` block pointing to `/data` and that the volume exists:
`flyctl volumes list`. If the volume got destroyed, re-create it (Step 4)
and re-seed (Step 7).
