"""
Summary and digest routes.
"""
import json as _json
from datetime import datetime, timedelta

from fastapi import APIRouter, Query, HTTPException
from typing import Optional

from src.db.database import get_db
from src.llm.summarizer import company_summary, weekly_digest, market_snapshot

router = APIRouter(prefix="/api/summaries", tags=["summaries"])


@router.get("/company/{startup_id}")
async def get_company_summary(
    startup_id: str,
    days: int = Query(7, ge=1, le=90, description="Number of days to summarize")
):
    """Generate an AI summary for a specific startup."""
    result = await company_summary(startup_id, days)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/digest/current")
def get_current_digest(days: int = Query(7, ge=1, le=90)):
    """Return the most recently stored digest (no generation)."""
    db = get_db()
    now = datetime.utcnow()
    period_start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    period_end = now.strftime("%Y-%m-%d")

    # Prefer exact-period match; fall back to latest of any period
    row = db.execute(
        """SELECT * FROM summaries
           WHERE summary_type = 'weekly_digest' AND period_start = ? AND period_end = ?
           LIMIT 1""",
        (period_start, period_end)
    ).fetchone()

    if not row:
        row = db.execute(
            """SELECT * FROM summaries
               WHERE summary_type = 'weekly_digest'
               ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()

    if not row:
        return {"digest": None}

    row = dict(row)
    try:
        parsed = _json.loads(row["content"])
        if isinstance(parsed, dict) and "companies" in parsed:
            row["companies"] = parsed["companies"]
            row["period_days"] = parsed.get("period_days", days)
        elif isinstance(parsed, list):
            row["companies"] = parsed
            row["period_days"] = days
        else:
            row["companies"] = []
            row["legacy"] = True
    except Exception:
        row["companies"] = []
        row["legacy"] = True

    return {"digest": row}


@router.get("/digest")
async def get_weekly_digest(
    days: int = Query(7, ge=1, le=90, description="Number of days for digest")
):
    """Generate (or replace) a weekly digest across all portfolio companies."""
    return await weekly_digest(days)


@router.get("/market")
async def get_market_snapshot(
    sector: Optional[str] = Query(None, description="Filter by industry sector")
):
    """Generate a market-wide snapshot."""
    return await market_snapshot(sector)


@router.get("/history")
def get_summary_history(
    startup_id: Optional[str] = Query(None),
    summary_type: Optional[str] = Query(None),
    limit: int = Query(20, le=100)
):
    """Get previously generated summaries."""
    db = get_db()
    conditions = []
    params = []

    if startup_id:
        conditions.append("startup_id = ?")
        params.append(startup_id)
    if summary_type:
        conditions.append("summary_type = ?")
        params.append(summary_type)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    summaries = db.execute(f"""
        SELECT sm.*, s.name as startup_name
        FROM summaries sm
        LEFT JOIN startups s ON sm.startup_id = s.id
        {where}
        ORDER BY sm.created_at DESC
        LIMIT ?
    """, params + [limit]).fetchall()

    return {"summaries": [dict(s) for s in summaries]}
