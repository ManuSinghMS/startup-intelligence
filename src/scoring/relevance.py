"""
Relevance scoring module — founder-weighted relevance matching.

The core insight: company names change, but founders don't. When matching
content to startups, founder/co-founder names are the primary signal.

Scoring weights:
  - Founder name in title  → 0.90 (highest confidence)
  - Founder name in body   → 0.70
  - Company name in title  → 0.50 (moderate — names change)
  - Company name in body   → 0.30 (low)
  - Legal name match       → same as company name
  - Multiple signal bonus  → cumulative (capped at 1.0)

Fuzzy matching:
  - Case-insensitive
  - Strips common suffixes (Inc., Corp., LLC, etc.)
  - Handles "J. Smith" vs "John Smith" via last-name matching
  - Filters out very short names that cause false positives
"""
from typing import List, Optional


# ---------------------------------------------------------------------------
# Name normalization helpers
# ---------------------------------------------------------------------------

_COMPANY_SUFFIXES = [
    " inc.", " inc", " corp.", " corp", " ltd.", " ltd",
    " llc", " group inc.", " group", " co.", " co",
    " technologies", " technology", " solutions", " labs",
]


def _normalize_company(name: str) -> List[str]:
    """
    Return a list of normalized company name variants to match against.
    E.g. "FooBar Inc." → ["foobar inc.", "foobar"]
    """
    if not name:
        return []
    lower = name.strip().lower()
    variants = [lower]
    for suffix in _COMPANY_SUFFIXES:
        if lower.endswith(suffix):
            base = lower[: -len(suffix)].strip()
            if len(base) > 2:
                variants.append(base)
    return variants


def _parse_person_names(raw: Optional[str]) -> List[str]:
    """
    Parse one or more person names from a raw string.
    Handles comma, semicolon, ampersand, and 'and' separators.
    Returns a list of individual name strings.
    """
    if not raw:
        return []
    raw = raw.strip()
    if not raw:
        return []

    # Try multi-person separators
    for sep in [";", ",", "&", " and "]:
        if sep in raw:
            parts = [p.strip() for p in raw.split(sep) if p.strip()]
            return [p for p in parts if len(p) > 2]

    return [raw] if len(raw) > 2 else []


def _name_variants(full_name: str) -> List[str]:
    """
    Generate matching variants for a person name.
    "John Smith" → ["john smith", "smith", "j. smith", "j smith"]
    """
    lower = full_name.strip().lower()
    if not lower:
        return []

    variants = [lower]
    parts = lower.split()
    if len(parts) >= 2:
        last = parts[-1]
        first_initial = parts[0][0]
        # Last name only (if long enough to avoid false positives)
        if len(last) > 4:
            variants.append(last)
        # "J. Smith" and "J Smith"
        variants.append(f"{first_initial}. {last}")
        variants.append(f"{first_initial} {last}")

    return variants


# ---------------------------------------------------------------------------
# Core scoring function
# ---------------------------------------------------------------------------

def score_relevance(
    title: str,
    content: str,
    company_name: str,
    legal_name: Optional[str] = None,
    founder_names: Optional[str] = None,
    cofounder_names: Optional[str] = None,
    contact_name: Optional[str] = None,
) -> tuple:
    """
    Score how relevant an article is to a startup.

    Returns (is_relevant, confidence) where confidence is 0.0–1.0.

    Founder/co-founder names are the PRIMARY signal.
    Company name is a secondary signal (companies rename).

    Args:
        title:           Article title
        content:         Article body text
        company_name:    Startup's display name
        legal_name:      Optional legal/registered name
        founder_names:   Comma-separated founder name(s)
        cofounder_names: Comma-separated co-founder name(s)
        contact_name:    Fallback contact name (used if no founder fields)
    """
    check_title = title.lower() if title else ""
    check_body = content.lower() if content else ""

    score = 0.0

    # --- Founder / co-founder matching (PRIMARY signal) ---
    all_people = []
    for raw in [founder_names, cofounder_names]:
        all_people.extend(_parse_person_names(raw))

    # Fallback to contact_name if no founder fields populated
    if not all_people:
        all_people.extend(_parse_person_names(contact_name))

    for person in all_people:
        variants = _name_variants(person)
        for variant in variants:
            if len(variant) < 4:
                continue  # Skip very short to avoid false positives
            if variant in check_title:
                score = max(score, 0.90)
                break  # Found in title — highest person score
            elif variant in check_body:
                score = max(score, 0.70)
                # Don't break — might find in title from another variant

    # --- Company name matching (SECONDARY signal) ---
    company_score = 0.0
    for name_source in [company_name, legal_name]:
        if not name_source:
            continue
        for variant in _normalize_company(name_source):
            if len(variant) < 3:
                continue
            if variant in check_title:
                company_score = max(company_score, 0.50)
            elif variant in check_body:
                company_score = max(company_score, 0.30)

    # Combine: if both founder AND company match, boost confidence
    if score > 0 and company_score > 0:
        score = min(1.0, score + 0.10)  # Bonus for cross-match
    elif company_score > 0 and score == 0:
        score = company_score  # Company-only match (lower confidence)

    is_relevant = score >= 0.25  # Minimum threshold
    return is_relevant, round(score, 2)
