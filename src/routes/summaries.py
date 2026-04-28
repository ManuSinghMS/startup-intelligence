"""
Summary and digest routes.
"""
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


@router.get("/digest")
async def get_weekly_digest(
    days: int = Query(7, ge=1, le=90, description="Number of days for digest")
):
    """Generate a weekly digest across all portfolio companies."""
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
