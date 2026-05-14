"""
LLM-powered content classifier.
Uses OpenAI API to classify content into categories.
Falls back to keyword-based classification if no API key is set.
"""
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


def _keyword_fallback(title: str, content: str) -> dict:
    text = f"{title} {content}"
    return {
        "classification": classify_by_keywords(text),
        "sentiment": "neutral",
        "topics": [],
        "summary": content[:300] + "..." if len(content) > 300 else content,
        "hired_count": 0,
    }


def _extract_json(text: str) -> Optional[dict]:
    """Best-effort JSON extraction from an LLM response.

    LLMs sometimes return the JSON wrapped in prose, in a ```json block,
    or with trailing commentary. We try a strict json.loads first, then
    a substring slice between the first '{' and last '}'.
    """
    if not text:
        return None
    text = text.strip()
    # Strip code fences if present
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


async def classify_with_llm(title: str, content: str) -> dict:
    """
    Classify content using the configured LLM provider.
    Returns dict with classification, sentiment, topics, and summary.

    Falls back to keyword classification on any failure so items never
    get stuck as 'unclassified'.
    """
    try:
        from src.llm.provider import get_llm_client, get_model_name, is_configured, get_provider
        if not is_configured():
            return _keyword_fallback(title, content)

        client = get_llm_client()
        if not client:
            return _keyword_fallback(title, content)

        model = get_model_name()
        provider = get_provider()

        # Trim content harder than before — Groq's free TPM is the real
        # bottleneck, and the model classifies fine on 600 chars of body.
        snippet = (content or "")[:600]
        prompt = f"""Analyze this startup news article and return a JSON object with:
1. "classification": one of {json.dumps(CATEGORIES)}
2. "sentiment": one of ["positive", "neutral", "negative"]
3. "topics": array of 2-4 short topic tags (lowercase)
4. "summary": concise 1-2 sentence summary
5. "hired_count": integer (number of people hired/appointed/joined; 0 if none)

Title: {title}
Content: {snippet}

Return ONLY valid JSON, no other text."""

        from src.llm.provider import call_with_retry
        # Rough token estimate: prompt ~250 + snippet ~200 + output ~250.
        est_tokens = 500 + min(len(snippet), 600) // 3

        # Groq's JSON mode is finicky for some llama models — try with
        # response_format first, fall back without it on schema errors.
        kwargs = dict(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=300,
        )
        try:
            response = await call_with_retry(
                lambda: client.chat.completions.create(
                    **kwargs, response_format={"type": "json_object"}
                ),
                estimated_tokens=est_tokens,
            )
        except Exception as e:
            msg = str(e).lower()
            if "response_format" in msg or "unsupported" in msg or (
                "json" in msg and "rate" not in msg
            ):
                response = await call_with_retry(
                    lambda: client.chat.completions.create(**kwargs),
                    estimated_tokens=est_tokens,
                )
            else:
                raise

        raw = response.choices[0].message.content
        result = _extract_json(raw)
        if not result:
            print(f"LLM returned unparseable response: {raw[:200]!r}")
            return _keyword_fallback(title, content)

        # Validate classification
        if result.get("classification") not in CATEGORIES:
            result["classification"] = "general"
        if result.get("sentiment") not in ["positive", "neutral", "negative"]:
            result["sentiment"] = "neutral"
        if not isinstance(result.get("hired_count"), int):
            try:
                result["hired_count"] = int(result.get("hired_count", 0) or 0)
            except (TypeError, ValueError):
                result["hired_count"] = 0
        if not isinstance(result.get("topics"), list):
            result["topics"] = []
        if not isinstance(result.get("summary"), str):
            result["summary"] = ""

        return result

    except Exception as e:
        print(f"LLM classification error: {e}")
        return _keyword_fallback(title, content)


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
