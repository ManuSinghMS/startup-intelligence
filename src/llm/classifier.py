"""
LLM-powered content classifier.
Uses OpenAI API to classify content into categories.
Falls back to keyword-based classification if no API key is set.
"""
import os
import json
from typing import Optional

from src.db.database import get_db


CATEGORIES = [
    "funding",          # Funding rounds, investments, grants
    "product_launch",   # New products, features, releases
    "milestone",        # Traction, metrics, achievements
    "hiring",           # New hires, job openings, team growth
    "partnership",      # Partnerships, integrations, collaborations
    "customer_win",     # New customers, contracts, deals
    "general",          # General news / updates
]

KEYWORD_MAP = {
    "funding": ["funding", "raised", "investment", "series a", "series b", "seed round",
                "venture", "capital", "investor", "valuation", "fundraise", "grant"],
    "product_launch": ["launch", "released", "new product", "new feature", "beta",
                       "announce", "unveil", "debut", "rollout", "available now"],
    "milestone": ["milestone", "achievement", "growth", "revenue", "users",
                  "customers", "reached", "surpassed", "record", "award"],
    "hiring": ["hire", "hiring", "join", "appointed", "ceo", "cto", "cfo",
               "vp of", "team", "recruit", "talent", "position", "role"],
    "partnership": ["partner", "partnership", "collaborate", "integration",
                    "alliance", "joint venture", "teamed up", "strategic"],
    "customer_win": ["customer", "client", "deal", "contract", "signed",
                     "onboard", "enterprise", "adoption"],
}


def classify_by_keywords(text: str) -> str:
    """Simple keyword-based classification fallback."""
    text_lower = text.lower()
    scores = {}
    for category, keywords in KEYWORD_MAP.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[category] = score

    if scores:
        return max(scores, key=scores.get)
    return "general"


async def classify_with_llm(title: str, content: str) -> dict:
    """
    Classify content using the configured LLM provider.
    Returns dict with classification, sentiment, topics, and summary.
    """
    try:
        from src.llm.provider import get_llm_client, get_model_name, is_configured
        if not is_configured():
            text = f"{title} {content}"
            return {
                "classification": classify_by_keywords(text),
                "sentiment": "neutral",
                "topics": [],
                "summary": content[:300] + "..." if len(content) > 300 else content,
                "hired_count": 0
            }

        client = get_llm_client()
        if not client:
            text = f"{title} {content}"
            return {
                "classification": classify_by_keywords(text),
                "sentiment": "neutral",
                "topics": [],
                "summary": content[:300] + "..." if len(content) > 300 else content,
                "hired_count": 0
            }

        model = get_model_name()



        prompt = f"""Analyze this startup news article and return a JSON object with:
1. "classification": one of {json.dumps(CATEGORIES)}
2. "sentiment": one of ["positive", "neutral", "negative"]
3. "topics": array of 2-5 relevant topic tags (lowercase)
4. "summary": a concise 2-3 sentence summary of the key points
5. "hired_count": integer representing the number of people hired, appointed, or joined (0 if none mentioned)

Title: {title}
Content: {content[:1000]}

Return ONLY valid JSON, no other text."""

        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=500,
            response_format={"type": "json_object"}
        )

        result = json.loads(response.choices[0].message.content)

        # Validate classification
        if result.get("classification") not in CATEGORIES:
            result["classification"] = "general"
        if result.get("sentiment") not in ["positive", "neutral", "negative"]:
            result["sentiment"] = "neutral"
        if not isinstance(result.get("hired_count"), int):
            result["hired_count"] = 0

        return result

    except Exception as e:
        print(f"LLM classification error: {e}")
        text = f"{title} {content}"
        return {
            "classification": classify_by_keywords(text),
            "sentiment": "neutral",
            "topics": [],
            "summary": content[:300] + "..." if len(content) > 300 else content,
            "hired_count": 0
        }


async def classify_content_item(content_id: str) -> dict:
    """Classify a single content item and update the database."""
    db = get_db()
    item = db.execute(
        "SELECT * FROM content_items WHERE id = ?", (content_id,)
    ).fetchone()

    if not item:
        return {"error": "Content item not found"}

    item = dict(item)
    result = await classify_with_llm(item.get("title", ""), item.get("raw_content", ""))

    db.execute(
        """UPDATE content_items
        SET classification = ?, sentiment = ?, topics = ?, summary = ?, hired_count = ?
        WHERE id = ?""",
        (result["classification"], result["sentiment"],
         json.dumps(result.get("topics", [])),
         result.get("summary", ""), result.get("hired_count", 0), content_id)
    )
    db.commit()
    return result


async def classify_unclassified(limit: int = 50) -> dict:
    """Classify all unclassified content items."""
    db = get_db()
    items = db.execute(
        "SELECT id FROM content_items WHERE classification = 'unclassified' LIMIT ?",
        (limit,)
    ).fetchall()

    stats = {"classified": 0, "errors": 0}
    for item in items:
        try:
            await classify_content_item(item["id"])
            stats["classified"] += 1
        except Exception as e:
            print(f"Classification error for {item['id']}: {e}")
            stats["errors"] += 1

    return stats
