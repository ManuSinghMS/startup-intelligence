"""
Scheduler — automated periodic ingestion using APScheduler.
Runs company news search, LinkedIn, and newsletter ingestion.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import os

from src.ingestion.company_search import ingest_all_companies

scheduler = AsyncIOScheduler()
_is_running = False


async def run_ingestion_job():
    """Run the full ingestion pipeline: news + LinkedIn + newsletter."""
    global _is_running
    if _is_running:
        print("Ingestion already running, skipping...")
        return

    _is_running = True
    try:
        print("\n[Scheduler] Starting automated ingestion...")

        # 0. Monday.com sync (if configured — pulls latest company data)
        try:
            from src.ingestion.monday_sync import is_configured as monday_configured, sync_from_monday
            if monday_configured():
                monday_result = await sync_from_monday()
                print(f"[Scheduler] Monday.com: {monday_result.get('created', 0)} new, "
                      f"{monday_result.get('updated', 0)} updated")
        except Exception as e:
            print(f"[Scheduler] Monday.com sync skipped: {e}")

        # 1. Company-specific news search (Google News)
        results = await ingest_all_companies()
        total_new = sum(r.get("new", 0) for r in results)
        print(f"[Scheduler] News: {total_new} new items")

        # 2. LinkedIn via free search engines (Google News + DuckDuckGo)
        try:
            from src.ingestion.linkedin_ingester import ingest_all_companies as li_ingest
            li_results = await li_ingest()
            li_new = sum(r.get("new", 0) for r in li_results if "new" in r)
            print(f"[Scheduler] LinkedIn: {li_new} new items")
        except Exception as e:
            print(f"[Scheduler] LinkedIn ingestion skipped: {e}")

        # 3. Newsletter via Gmail IMAP (if configured)
        try:
            from src.ingestion.email_ingester import is_configured as email_configured, ingest_newsletters
            if email_configured():
                nl_stats = ingest_newsletters()
                print(f"[Scheduler] Newsletters: {nl_stats.get('new', 0)} new items")
        except Exception as e:
            print(f"[Scheduler] Newsletter ingestion skipped: {e}")

        print("[Scheduler] Ingestion cycle complete")

    except Exception as e:
        print(f"[Scheduler] Ingestion error: {e}")
    finally:
        _is_running = False


def start_scheduler():
    """Start the periodic ingestion scheduler."""
    interval_minutes = int(os.getenv("INGESTION_INTERVAL_MINUTES", "1440"))

    scheduler.add_job(
        run_ingestion_job,
        "interval",
        minutes=interval_minutes,
        id="full_ingestion",
        replace_existing=True,
        max_instances=1
    )
    scheduler.start()
    print(f"[Scheduler] Started — ingesting every {interval_minutes} minutes")


def stop_scheduler():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        print("[Scheduler] Stopped")

