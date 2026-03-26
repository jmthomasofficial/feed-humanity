"""
parser.py — NLP extraction engine for Feed Humanity social media posts.

Two-stage pipeline:
  1. Regex stage: Fast pattern matching for meal counts, city hashtags, platform.
  2. LLM fallback: When regex finds no meal count, uses multi-provider LLM
     (via llm_client.py) with a structured extraction prompt.

Supported patterns:
  - "fed 5 people", "bought 10 meals", "3 plates", "gave food to 2 families"
  - "#FeedHumanityNashville" → city = "Nashville"
  - URL domain → platform (tiktok, instagram, twitter/x, youtube)
"""

import re
import sys
import os
from typing import Optional
from urllib.parse import urlparse

# Allow importing llm_client from sibling ai-playbook directory
_PLAYBOOK_DIR = os.path.join(os.path.dirname(__file__), "..", "ai-playbook")
if _PLAYBOOK_DIR not in sys.path:
    sys.path.insert(0, _PLAYBOOK_DIR)


# ─── Platform Detection ───────────────────────────────────────

PLATFORM_PATTERNS = {
    "tiktok":    ["tiktok.com"],
    "instagram": ["instagram.com", "instagr.am"],
    "twitter":   ["twitter.com", "x.com"],
    "youtube":   ["youtube.com", "youtu.be"],
    "facebook":  ["facebook.com", "fb.com"],
    "threads":   ["threads.net"],
}


def detect_platform(post_url: str) -> str:
    """Detect social media platform from URL domain."""
    if not post_url:
        return "unknown"
    try:
        domain = urlparse(post_url).netloc.lower().lstrip("www.")
        for platform, domains in PLATFORM_PATTERNS.items():
            if any(d in domain for d in domains):
                return platform
    except Exception:
        pass
    return "unknown"


# ─── Meal Count Extraction (Regex) ─────────────────────────────

# Number words for text-based counts
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
    "a dozen": 12, "a couple": 2, "a few": 3,
}

# Food-related words that appear near meal counts
FOOD_WORDS = r"(?:meals?|plates?|people|families|persons?|folks|neighbors?|strangers?|bags?|boxes?|servings?|portions?)"

# Patterns: "fed 5 people", "bought 10 meals", "gave 3 plates", etc.
MEAL_PATTERNS = [
    # "fed 5 people", "served 10 meals", "gave 3 plates"
    re.compile(rf"(?:fed|served|gave|delivered|donated|distributed|handed\s+out|provided)\s+(\d+)\s+{FOOD_WORDS}", re.IGNORECASE),
    # "bought 5 meals", "prepared 10 plates"
    re.compile(rf"(?:bought|prepared|made|cooked|packed|assembled)\s+(\d+)\s+{FOOD_WORDS}", re.IGNORECASE),
    # "5 meals served", "10 plates given"
    re.compile(rf"(\d+)\s+{FOOD_WORDS}\s+(?:served|given|donated|delivered|distributed|handed)", re.IGNORECASE),
    # "fed five people" (word-based numbers)
    re.compile(rf"(?:fed|served|gave|delivered)\s+({"|".join(NUMBER_WORDS.keys())})\s+{FOOD_WORDS}", re.IGNORECASE),
    # Standalone number near food words: "10 meals"
    re.compile(rf"(\d+)\s+{FOOD_WORDS}", re.IGNORECASE),
]


def extract_meal_count_regex(text: str) -> Optional[int]:
    """
    Try to extract a meal count from text using regex patterns.
    Returns the first match found, or None if no pattern matches.
    """
    for pattern in MEAL_PATTERNS:
        match = pattern.search(text)
        if match:
            raw = match.group(1).strip().lower()
            # Try numeric
            try:
                return int(raw)
            except ValueError:
                pass
            # Try word-based
            if raw in NUMBER_WORDS:
                return NUMBER_WORDS[raw]
    return None


# ─── City Extraction ──────────────────────────────────────────

# Pattern: #FeedHumanityNashville, #FeedHumanityLosAngeles, etc.
CITY_HASHTAG_PATTERN = re.compile(
    r"#FeedHumanity([A-Z][a-zA-Z]+(?:[A-Z][a-zA-Z]+)*)",
    re.UNICODE
)


def extract_city_from_hashtag(text: str) -> Optional[str]:
    """
    Extract city name from #FeedHumanity{City} hashtag.
    Handles CamelCase: #FeedHumanityLosAngeles → "Los Angeles"
    """
    match = CITY_HASHTAG_PATTERN.search(text)
    if match:
        raw_city = match.group(1)
        # Split CamelCase into words: "LosAngeles" → "Los Angeles"
        city = re.sub(r"([a-z])([A-Z])", r"\1 \2", raw_city)
        return city.strip()
    return None


# ─── Handle Extraction ────────────────────────────────────────

def extract_handle(text: str) -> str:
    """Extract the first @handle from text."""
    match = re.search(r"@(\w+)", text)
    return match.group(1) if match else ""


# ─── LLM Fallback ─────────────────────────────────────────────

LLM_EXTRACTION_PROMPT = """You are a data extraction engine. Extract the following from this social media post:
1. Number of meals/plates/servings mentioned (integer, default to 1 if food is given but no number specified)
2. City name if mentioned (empty string if not found)

Respond with ONLY a JSON object, no markdown, no explanation:
{"meals": <integer>, "city": "<string>"}

Post text:
"""


def extract_via_llm(text: str) -> dict:
    """
    Use the multi-provider LLM to extract meal count and city from ambiguous text.
    Returns {"meals": int, "city": str}
    """
    try:
        from llm_client import chat  # type: ignore[import]
        result = chat(
            system_prompt="You are a precise data extraction engine. Return only valid JSON. No markdown.",
            user_prompt=LLM_EXTRACTION_PROMPT + text,
        )
        import json
        # Strip any markdown code fences
        response_text = result["text"].strip()
        if response_text.startswith("```"):
            response_text = re.sub(r"^```(?:json)?\s*", "", response_text)
            response_text = re.sub(r"\s*```$", "", response_text)
        parsed = json.loads(response_text)
        return {
            "meals": int(parsed.get("meals", 1)),
            "city":  str(parsed.get("city", "")),
        }
    except Exception as e:
        # LLM failed — fall back to default
        return {"meals": 1, "city": ""}


# ─── Main Entry Point ─────────────────────────────────────────

def parse_post(raw_text: str, post_url: str = "") -> dict:
    """
    Parse a social media post for impact data.

    Returns:
        {
            "meals": int,           # Number of meals (>= 1)
            "city": str,            # City name (may be empty)
            "platform": str,        # Social platform (tiktok, instagram, etc.)
            "poster_handle": str,   # @handle if found
            "extraction_method": str,  # "regex" or "llm"
        }
    """
    platform = detect_platform(post_url)
    poster_handle = extract_handle(raw_text)
    city = extract_city_from_hashtag(raw_text)
    meals = extract_meal_count_regex(raw_text)
    extraction_method = "regex"

    # If regex found nothing, try LLM
    if meals is None:
        llm_result = extract_via_llm(raw_text)
        meals = llm_result["meals"]
        extraction_method = "llm"
        if not city:
            city = llm_result["city"]

    # Ensure meals is at least 1 (if someone posted, they gave at least 1 meal)
    if meals is None or meals < 1:
        meals = 1

    return {
        "meals":             meals,
        "city":              city or "",
        "platform":          platform,
        "poster_handle":     poster_handle,
        "extraction_method": extraction_method,
    }
