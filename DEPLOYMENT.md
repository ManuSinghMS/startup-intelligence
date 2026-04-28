# Deployment Guide

This guide covers how to host the Startup Intelligence Platform for external
access. The recommended path is **Render** (free web service + small
persistent disk for SQLite).

---

## Option 1: Render (recommended)

### One-time setup

1. **Push to GitHub.** From this directory:
   ```bash
   git init                   # if not already a repo
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/<you>/startup-intel.git
   git push -u origin main
   ```

2. **Sign in at [render.com](https://render.com)** and click
   **New → Blueprint** (the repo already contains `render.yaml`). Point it
   at your GitHub repo. Render reads `render.yaml` and provisions:
   - A web service running `uvicorn src.main:app --host 0.0.0.0 --port $PORT`
   - A 1 GB persistent disk mounted at `/data`
   - `DATABASE_PATH=/data/startup_intel.db`
   - `PYTHON_VERSION=3.10`

3. **Add the secrets** the blueprint can't ship: Render dashboard →
   `startup-intel` → **Environment** → add as needed:
   ```
   MONDAY_API_TOKEN=...           # if using Monday.com sync
   MONDAY_BOARD_ID=...
   OPENAI_API_KEY=...             # optional, for LLM classification/summaries
   LLM_PROVIDER=openai            # or groq / copilot
   GROQ_API_KEY=...               # if using groq
   NEWSLETTER_EMAIL=...           # optional, Gmail IMAP polling
   NEWSLETTER_APP_PASSWORD=...
   ```

4. **First deploy.** Render will build and start the service automatically.
   On startup, the lifespan handler runs migrations (`src.db.migrate.migrate`)
   and `init_db`, so the schema is current — but the database starts empty.

### Seeding the database after first deploy

You have three options. Pick whichever matches your data flow:

**A. Sync from Monday.com (preferred if you already have a board):**
```bash
curl -X POST https://<your-render-url>/api/startups/sync-monday
```
Or wait for the scheduled job (`INGESTION_INTERVAL_MINUTES`, default 1440).

**B. Upload an Excel/CSV from your machine:**
```bash
curl -F "file=@FOR_MERGING_Companies.xlsx" \
     https://<your-render-url>/api/startups/import
```

**C. Use the Render shell** (Web → Shell tab in the dashboard) and run:
```bash
python -m src.db.seed
```

After seeding, populate LinkedIn post URLs either by editing Monday columns
and re-running the sync, or by uploading a CSV via:
```bash
# From your laptop, against the deployed URL — or via Render shell:
python -m src.ingestion.linkedin_ingester --csv data/manual_posts.csv
```

### Render notes

- Free tier spins down after 15 min idle (~30s cold start).
- Free tier has 750 hours/month — fine for one always-on service.
- The persistent disk is tied to the service. Don't delete the service or
  you'll lose the SQLite DB. Back up periodically:
  ```bash
  curl https://<your-render-url>/data/startup_intel.db -o backup.db
  ```
  (you'll need a `/health/db-download` route, or use the Render shell to
  `cp /data/startup_intel.db /tmp/` and download via the file browser).

---

## Option 2: Railway ($5/mo Hobby plan)

1. Sign up at [railway.app](https://railway.app).
2. **New Project → Deploy from GitHub.**
3. Railway auto-detects Python. Set the start command to
   `uvicorn src.main:app --host 0.0.0.0 --port $PORT`.
4. Add the same env vars as listed for Render.
5. Add a 1 GB volume mounted somewhere persistent and set
   `DATABASE_PATH=/<mount>/startup_intel.db`.

Railway has no cold starts and an always-on plan, but costs ~$5/month.

---

## Option 3: Self-host (VPS)

For a small DigitalOcean/Linode/Hetzner droplet:

```bash
# On the server
git clone https://github.com/<you>/startup-intel.git
cd startup-intel
python3.10 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env

# Migrate + seed
python -m src.db.migrate
python -m src.db.seed   # or: python -m src.ingestion.monday_sync

# Run with systemd
sudo tee /etc/systemd/system/startup-intel.service <<'EOF'
[Unit]
Description=Startup Intel Platform
After=network.target

[Service]
WorkingDirectory=/home/ubuntu/startup-intel
ExecStart=/home/ubuntu/startup-intel/venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000
Restart=always
EnvironmentFile=/home/ubuntu/startup-intel/.env
User=ubuntu

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now startup-intel
```

Front it with nginx + Let's Encrypt for HTTPS.

---

## Important notes

- SQLite is fine for this scale (~150 startups, a few thousand content items).
- The `.db` file MUST be on a persistent volume — ephemeral container disks
  will lose data on every restart.
- `Netlify` / `Vercel` will NOT work — this is a long-running Python
  server, not a static site or serverless function.
- For scheduled ingestion, the service must stay running. On Render free
  tier, cold starts will delay the first request after a quiet period —
  that's fine, just don't expect minute-precision schedules.
