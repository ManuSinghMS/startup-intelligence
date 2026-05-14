"""
LLM-powered summarizer — generates company-level and portfolio-level summaries.
Falls back to simple extraction if no API key is set.
"""
import os
import json
import uuid
from collections import defaultdict
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


def _simple_digest(company_items: dict) -> list:
    """Fallback: build simple per-company digest without LLM."""
    result = []
    for company, items in company_items.items():
        key_updates = [i.get("title", "") for i in items[:3] if i.get("title")]
        result.append({
            "company": company,
            "key_updates": key_updates,
            "linkedin_activity": [],
            "news_mentions": [],
            "risks": [],
            "opportunities": [],
            "next_action": None,
        })
    return result


async def generate_digest_llm(company_items: dict, days: int) -> list:
    """Generate structured per-company digest via a single LLM call."""
    if not company_items:
        return []

    try:
        from src.llm.provider import get_llm_client, get_model_name, is_configured
        if not is_configured():
            return _simple_digest(company_items)

        client = get_llm_client()
        if not client:
            return _simple_digest(company_items)

        model = get_model_name()

        real_company_names = list(company_items.keys())
        # Build a name -> canonical-name map for validation (lower, stripped).
        canonical = {n.strip().lower(): n for n in real_company_names}

        companies_text = ""
        for company, items in company_items.items():
            companies_text += f"\n### {company}\n"
            for item in items[:10]:
                companies_text += (
                    f"- [{item.get('classification', 'general')}] {item.get('title', '')}"
                    f" ({item.get('source_name', '')}, {(item.get('published_at') or '')[:10]})"
                    f": {(item.get('summary') or '')[:150]}\n"
                )

        prompt = f"""You are producing a startup portfolio intelligence digest for the past {days} days.

Return a JSON array with EXACTLY {len(real_company_names)} objects — one per
company in the list below, in the same order, using the EXACT company name
strings shown. Do NOT invent placeholder entries like "Company 2",
"Company 3", or any company name that is not in the list.

Each object must have these keys:
- "company": company name string (must match one of: {json.dumps(real_company_names)})
- "key_updates": array of 1-3 concise strings for the most important updates (empty array if none)
- "linkedin_activity": array of strings about LinkedIn or founder/co-founder posts (empty array if none)
- "news_mentions": array of strings about external news or web coverage (empty array if none)
- "risks": array of strings about concerns or warning signs (empty array if none)
- "opportunities": array of strings about growth or partnership opportunities (empty array if none)
- "next_action": single recommended action string for the portfolio manager (null if nothing urgent)

Return ONLY a valid JSON array — no markdown fences, no extra text.

Companies and recent content:
{companies_text}"""

        from src.llm.provider import call_with_retry
        # Rough estimate: prompt ~600 + content body ~500 per company + output ~400 per company
        est_tokens = 1000 + len(real_company_names) * 800
        response = await call_with_retry(
            lambda: client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=3000,
            ),
            estimated_tokens=est_tokens,
        )

        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return _simple_digest(company_items)

        # Drop hallucinated placeholders. Only keep entries whose "company"
        # matches an actual portfolio company name (case-insensitive).
        # Canonicalize the name so downstream renders show the exact string.
        cleaned = []
        seen = set()
        for obj in parsed:
            if not isinstance(obj, dict):
                continue
            name = (obj.get("company") or "").strip()
            real = canonical.get(name.lower())
            if not real or real in seen:
                continue
            obj["company"] = real
            cleaned.append(obj)
            seen.add(real)

        dropped = len(parsed) - len(cleaned)
        if dropped > 0:
            print(f"[Digest] Dropped {dropped} hallucinated/duplicate entries from LLM output")
        print(f"[Digest] LLM generated summaries for {len(cleaned)} real companies")
        return cleaned

    except Exception as e:
        print(f"[Digest] LLM digest error: {e}")
        return _simple_digest(company_items)


async def weekly_digest(days: int = 7) -> dict:
    """Generate (or replace) a portfolio digest for the given calendar period."""
    db = get_db()
    now = datetime.utcnow()
    cutoff_dt = now - timedelta(days=days)
    period_start = cutoff_dt.strftime("%Y-%m-%d")
    period_end = now.strftime("%Y-%m-%d")

    print(f"[Digest] Generating {days}-day digest: {period_start} → {period_end}")

    # Fetch content for all active portfolio companies
    rows = db.execute("""
        SELECT ci.title, ci.summary, ci.classification, ci.source_name,
               ci.published_at, ci.url, ci.source_type,
               s.name as startup_name, s.id as startup_id
        FROM content_items ci
        JOIN startups s ON ci.startup_id = s.id
        WHERE ci.published_at >= ? AND ci.is_relevant = 1
          AND (s.tag IS NULL OR (s.tag != 'not_active' AND s.tag != 'forge'))
        ORDER BY s.name, ci.published_at DESC
        LIMIT 300
    """, (cutoff_dt.isoformat(),)).fetchall()

    items = [dict(r) for r in rows]
    print(f"[Digest] Found {len(items)} content items across portfolio")

    # Group by company
    company_items: dict = defaultdict(list)
    for item in items:
        company_items[item["startup_name"]].append(item)

    # Generate per-company summaries via LLM
    companies = await generate_digest_llm(company_items, days)

    # Store as JSON with metadata
    content_obj = {"period_days": days, "companies": companies}
    content_json = json.dumps(content_obj)

    # Upsert: replace existing digest for the same calendar period
    existing = db.execute(
        """SELECT id FROM summaries
           WHERE summary_type = 'weekly_digest' AND period_start = ? AND period_end = ?""",
        (period_start, period_end)
    ).fetchone()

    now_iso = now.isoformat()
    updated_existing = False
    if existing:
        db.execute(
            "UPDATE summaries SET content = ?, created_at = ? WHERE id = ?",
            (content_json, now_iso, existing["id"])
        )
        updated_existing = True
        print(f"[Digest] Updated existing digest for {period_start} → {period_end}")
    else:
        summary_id = str(uuid.uuid4())
        db.execute(
            """INSERT INTO summaries (id, startup_id, summary_type, content, period_start, period_end)
               VALUES (?, NULL, 'weekly_digest', ?, ?, ?)""",
            (summary_id, content_json, period_start, period_end)
        )
        print(f"[Digest] Created new digest for {period_start} → {period_end}")

    db.commit()

    return {
        "period_days": days,
        "period_start": period_start,
        "period_end": period_end,
        "items_count": len(items),
        "companies_count": len(companies),
        "companies": companies,
        "updated_existing": updated_existing,
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
