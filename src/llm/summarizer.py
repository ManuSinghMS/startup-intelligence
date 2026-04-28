"""
LLM-powered summarizer — generates company-level and portfolio-level summaries.
Falls back to simple extraction if no API key is set.
"""
import os
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional

from src.db.database import get_db


def _get_content_for_period(startup_id: Optional[str], days: int) -> list:
    """Get content items for a startup within a time window."""
    db = get_db()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    if startup_id:
        items = db.execute(
            """SELECT title, summary, classification, source_name, published_at, url
            FROM content_items
            WHERE startup_id = ? AND published_at >= ? AND is_relevant = 1
            ORDER BY published_at DESC
            LIMIT 50""",
            (startup_id, cutoff)
        ).fetchall()
    else:
        items = db.execute(
            """SELECT ci.title, ci.summary, ci.classification, ci.source_name,
                      ci.published_at, ci.url, s.name as startup_name
            FROM content_items ci
            LEFT JOIN startups s ON ci.startup_id = s.id
            WHERE ci.published_at >= ? AND ci.is_relevant = 1
            ORDER BY ci.published_at DESC
            LIMIT 100""",
            (cutoff,)
        ).fetchall()

    return [dict(item) for item in items]


def simple_summary(items: list, context: str = "") -> str:
    """Generate a simple extractive summary (no LLM)."""
    if not items:
        return f"No recent activity found{' for ' + context if context else ''}."

    lines = [f"**{context} Activity Summary** ({len(items)} items)\n"] if context else []

    # Group by classification
    groups = {}
    for item in items:
        cat = item.get("classification", "general")
        if cat not in groups:
            groups[cat] = []
        groups[cat].append(item)

    category_labels = {
        "funding": "💰 Funding",
        "product_launch": "🚀 Product Launches",
        "milestone": "📈 Milestones",
        "hiring": "👥 Hiring",
        "partnership": "🤝 Partnerships",
        "customer_win": "🎯 Customer Wins",
        "general": "📰 General Updates",
        "unclassified": "📋 Other",
    }

    for cat, cat_items in groups.items():
        label = category_labels.get(cat, cat)
        lines.append(f"\n**{label}** ({len(cat_items)})")
        for item in cat_items[:5]:
            title = item.get("title", "Untitled")
            source = item.get("source_name", "Unknown")
            date = item.get("published_at", "")[:10]
            startup = item.get("startup_name", "")
            prefix = f"[{startup}] " if startup else ""
            lines.append(f"- {prefix}{title} — *{source}* ({date})")

    return "\n".join(lines)


async def generate_summary_llm(items: list, prompt_context: str) -> str:
    """Generate a summary using the configured LLM provider."""
    if not items:
        return "There were no new articles, updates, or mentions found during this time period."

    try:
        from src.llm.provider import get_llm_client, get_model_name, is_configured
        if not is_configured():
            return simple_summary(items, prompt_context)

        client = get_llm_client()
        if not client:
            return simple_summary(items, prompt_context)

        model = get_model_name()

        # Build content input
        content_text = "\n".join([
            f"- [{item.get('classification', 'general')}] {item.get('startup_name', 'Unknown Company')}: {item.get('title', '')} "
            f"({item.get('source_name', '')}, {item.get('published_at', '')[:10]}): "
            f"{item.get('summary', item.get('raw_content', ''))[:200]}"
            for item in items[:50]
        ])

        prompt = f"""You are producing a concise intelligence brief for a startup incubator.
Context: {prompt_context}

Here are the recent content items:
{content_text}

Write a professional, well-structured summary that:
1. Groups the updates by Company name as the primary section headers (display company first).
2. Under each company, list their specific info and updates grouped by category if there are multiple.
3. Uses bullet points and bold text for readability.
4. Keeps the tone professional but accessible.

Format using markdown. Be concise but comprehensive."""

        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1500,
        )

        return response.choices[0].message.content

    except Exception as e:
        print(f"LLM summary error: {e}")
        return simple_summary(items, prompt_context)


async def company_summary(startup_id: str, days: int = 7) -> dict:
    """Generate a summary for a specific startup."""
    db = get_db()
    startup = db.execute(
        "SELECT * FROM startups WHERE id = ?", (startup_id,)
    ).fetchone()

    if not startup:
        return {"error": "Startup not found"}

    startup = dict(startup)
    items = _get_content_for_period(startup_id, days)

    summary_type = f"company_{days}day"
    context = f"{startup['name']} — Last {days} Days"

    summary_text = await generate_summary_llm(items, context)

    # Cache the summary
    summary_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    db.execute(
        """INSERT INTO summaries (id, startup_id, summary_type, content, period_start, period_end)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (summary_id, startup_id, summary_type, summary_text, cutoff, now)
    )
    db.commit()

    return {
        "startup": startup["name"],
        "period_days": days,
        "items_count": len(items),
        "summary": summary_text
    }


async def weekly_digest(days: int = 7) -> dict:
    """Generate a weekly digest across all startups."""
    items = _get_content_for_period(None, days)

    context = f"Portfolio Digest ({days} Days)"
    summary_text = await generate_summary_llm(items, context)

    db = get_db()
    summary_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    db.execute(
        """INSERT INTO summaries (id, startup_id, summary_type, content, period_start, period_end)
        VALUES (?, NULL, ?, ?, ?, ?)""",
        (summary_id, "weekly_digest", summary_text, cutoff, now)
    )
    db.commit()

    return {
        "period": f"{days} days",
        "period_days": days,
        "items_count": len(items),
        "summary": summary_text
    }


async def market_snapshot(sector: Optional[str] = None) -> dict:
    """Generate a market-wide snapshot."""
    items = _get_content_for_period(None, 7)

    if sector:
        # Filter by sector/industry
        db = get_db()
        sector_startups = db.execute(
            "SELECT id FROM startups WHERE industry LIKE ? OR secondary_industry LIKE ?",
            (f"%{sector}%", f"%{sector}%")
        ).fetchall()
        sector_ids = {s["id"] for s in sector_startups}
        items = [i for i in items if i.get("startup_id") in sector_ids]

    context = f"Market Snapshot{' — ' + sector if sector else ''}"
    summary_text = await generate_summary_llm(items, context)

    return {
        "sector": sector or "all",
        "items_count": len(items),
        "summary": summary_text
    }
