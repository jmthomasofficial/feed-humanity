"""
plan_generator.py — Generate personalized Feed Humanity action plans.

Uses multi-provider LLM client (Gemini/NIM/OpenRouter) with automatic
fallback and round-robin key rotation. Zero vendor lock-in.

Input: zip_code, budget_usd, time_hours, tier (1-6), dietary_focus (optional)
Output: structured JSON plan with title, summary, steps[], resources[], hashtags[]
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from locator import find_food_banks

# Tier definitions aligned with Feed Humanity 6-tier system
TIER_LABELS = {
    1: "Individual",
    2: "Crew",
    3: "Organizer",
    4: "Small Business",
    5: "Corporation",
    6: "Tech Giant / CEO",
}

TIER_DESCRIPTIONS = {
    1: "A single person acting alone. Baby steps: buy one meal for a stranger, film it, post it, challenge 3 friends.",
    2: "A small group of 2-10 friends or colleagues coordinating together. Pool resources, amplify reach.",
    3: "A community organizer hosting a feeding event. Coordinate volunteers, venues, logistics, media.",
    4: "A local business sponsoring meals, running in-store campaigns, or donating surplus food.",
    5: "A corporation integrating Feed Humanity into CSR, employee programs, and supply chain.",
    6: "A tech company or CEO making an engineering commitment — dispatch AI, logistical infrastructure, or major funding.",
}

TIER_CHECKLISTS = {
    1: [
        "Buy a meal for a stranger (food truck, restaurant, grocery store)",
        "Film the act of giving (brief, genuine moment — not staged)",
        "Post with #FeedHumanity on Instagram/TikTok/X",
        "Challenge 3 specific friends by name in the caption",
        "Tag @FeedHumanity in the post",
        "Visit feedhumanity.org to log your act on the map",
    ],
    2: [
        "Coordinate with 2-9 others — assign roles (buyer, filmer, poster, challenger)",
        "Pool budget: each person contributes what they can",
        "Choose a target neighborhood or community",
        "Do a group feeding run — document the whole journey",
        "Each member posts their own angle with #FeedHumanity",
        "Challenge other crews",
        "Report total meals at feedhumanity.org",
    ],
    3: [
        "Pick a date and venue (park, community center, church parking lot)",
        "Partner with at least one local food bank for surplus food",
        "Recruit 5-20 volunteers (use the event kit at feedhumanity.org)",
        "Promote event 2 weeks ahead on social media",
        "Document the event: photos, video, testimonials",
        "Post event recap with #FeedHumanity",
        "Submit verified meal count to the global tracker",
        "Challenge 3 other organizers in other cities",
    ],
    4: [
        "Run a 'buy one, feed one' promotion in-store or online",
        "Partner with a local food bank for surplus/unsold inventory",
        "Offer a staff volunteer day for a feeding event",
        "Display #FeedHumanity materials (posters, counter cards)",
        "Post company participation on social media",
        "Report business contribution (meals, $, volunteer hours) to tracker",
        "Challenge 3 peer businesses",
    ],
    5: [
        "Designate a Feed Humanity internal champion (VP or C-suite sponsor)",
        "Launch employee matching: for every meal an employee buys, company matches",
        "Integrate surplus food policy (partner with Feeding America or local network)",
        "Run a company-wide challenge week with leaderboard",
        "Issue a press release announcing corporate commitment",
        "Report aggregate impact to the global tracker",
        "Challenge 3 peer corporations publicly",
    ],
    6: [
        "Make a public engineering commitment (open-source logistics tool, AI dispatch, etc.)",
        "Fund 1 million meals directly via verified food bank partnerships",
        "Issue an open letter to other tech CEOs",
        "Deploy an AI tool that helps Feed Humanity coordinators (dispatch, matching, routing)",
        "Host a live-streamed 'feeding summit' with other tech leaders",
        "Report tech contribution and meals to global tracker",
        "Challenge 3 other tech giants / CEOs by name, publicly",
    ],
}


@dataclass
class PlaybookInput:
    zip_code: str
    budget_usd: float
    time_hours: float
    tier: int
    dietary_focus: str = ""

    def validate(self):
        if not self.zip_code or not self.zip_code.strip():
            raise ValueError("zip_code is required")
        if self.budget_usd < 5.0 or self.budget_usd > 100000.0:
            raise ValueError("budget_usd must be between 5 and 100000")
        if self.time_hours < 0.25 or self.time_hours > 168.0:
            raise ValueError("time_hours must be between 0.25 and 168")
        if self.tier < 1 or self.tier > 6:
            raise ValueError("tier must be 1-6")


def _format_food_banks_for_prompt(food_banks: list) -> str:
    """Format food bank list into a readable prompt section."""
    if not food_banks:
        return "No food banks found via OpenStreetMap within search radius. Recommend searching FoodPantries.org or Feeding America's local network finder."

    lines = []
    for i, fb in enumerate(food_banks[:8], 1):  # Cap at 8 for prompt efficiency
        addr = fb.get("address", "Address not listed")
        dist = fb.get("distance_km", "?")
        lines.append(f"  {i}. {fb['name']} — {addr} ({dist} km away)")
    return "\n".join(lines)


def _build_prompt(inp: PlaybookInput, location: dict, food_banks: list) -> tuple[str, str]:
    """Build system prompt and user prompt for Claude."""
    tier_label = TIER_LABELS.get(inp.tier, "Individual")
    tier_desc = TIER_DESCRIPTIONS.get(inp.tier, "")
    checklist = TIER_CHECKLISTS.get(inp.tier, [])
    checklist_str = "\n".join(f"  - {item}" for item in checklist)
    food_banks_str = _format_food_banks_for_prompt(food_banks)
    city = location.get("city", "Unknown City")
    state = location.get("state", "Unknown State")

    dietary_note = ""
    if inp.dietary_focus:
        dietary_note = f"\nDietary focus: {inp.dietary_focus} — prioritize options that meet this requirement."

    system_prompt = """You are the Feed Humanity AI Playbook Generator. Your job is to create a specific, actionable, personalized action plan for someone who wants to participate in the Feed Humanity movement — proving that AI benefits humanity by organizing the largest feeding movement in history.

The plan must be:
- Hyper-specific to their location, budget, and time
- Grounded in the real food banks and resources available near them
- Achievable within their stated constraints
- Motivating and mission-aligned with #FeedHumanity

Output ONLY valid JSON — no markdown, no code fences, no explanations outside the JSON. The JSON must match this exact structure:

{
  "title": "string — compelling plan title, personalized to their tier and city",
  "summary": "string — 2-3 sentences: what they'll do, why it matters, what impact they'll have",
  "steps": [
    {
      "step_number": 1,
      "action": "string — the specific action verb + what to do",
      "detail": "string — specific details: exact locations, amounts, how-to, tips",
      "time_estimate": "string — e.g. '30 minutes', '2 hours'",
      "cost_estimate": "string — e.g. '$10-15', 'Free', '$0-5'"
    }
  ],
  "resources": [
    {
      "name": "string — resource name",
      "type": "string — 'food_bank' | 'website' | 'app' | 'tool'",
      "url": "string — URL if available, else empty string",
      "note": "string — how this resource helps them"
    }
  ],
  "hashtags": ["#FeedHumanity", "...additional relevant hashtags..."],
  "estimated_meals_impact": "string — realistic estimate of meals this plan could generate",
  "viral_challenge": "string — the specific challenge text to post on social media"
}

Generate at minimum 4 steps and at minimum 3 resources. Steps must be numbered sequentially."""

    user_prompt = f"""Generate a personalized Feed Humanity action plan for:

LOCATION: {city}, {state} (ZIP: {inp.zip_code})
TIER: {inp.tier} — {tier_label}
TIER DESCRIPTION: {tier_desc}
BUDGET: ${inp.budget_usd:.2f}
TIME AVAILABLE: {inp.time_hours} hours{dietary_note}

REAL FOOD BANKS NEAR THEM (from OpenStreetMap / Overpass API):
{food_banks_str}

TIER {inp.tier} CHECKLIST (incorporate these into the steps):
{checklist_str}

Create a plan that uses their actual budget of ${inp.budget_usd:.2f} and {inp.time_hours} hours effectively. Reference real local food banks by name where relevant. Make the social media challenge compelling and shareable."""

    return system_prompt, user_prompt


def generate_playbook(inp: PlaybookInput) -> dict:
    """
    Generate a personalized Feed Humanity action plan.

    Returns:
        {
            "plan": {...},          # Claude-generated structured plan
            "food_banks_found": int,
            "city": str,
            "state": str,
            "lat": float,
            "lng": float,
            "search_radius_km": int,
            "generated_at": str,   # ISO timestamp
            "model_used": str
        }

    Raises:
        ValueError: on invalid input
        RuntimeError: on API or geocoding failure
    """
    inp.validate()

    # Step 1: Get real location + food banks
    location_data = find_food_banks(inp.zip_code)
    food_banks = location_data.get("food_banks", [])
    city = location_data.get("city", "Unknown")
    state = location_data.get("state", "Unknown")

    # Step 2: Build prompts
    system_prompt, user_prompt = _build_prompt(inp, location_data, food_banks)

    # Step 3: Call LLM via multi-provider client (Gemini → NIM → OpenRouter)
    try:
        from llm_client import chat
        llm_result = chat(system_prompt, user_prompt)
        raw_response = llm_result["text"]
        provider_name = llm_result["provider"]
        model_name = llm_result["model"]
    except Exception as e:
        raise RuntimeError(f"LLM API call failed: {e}")

    # Step 4: Parse JSON response
    # Strip any accidental markdown fences
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first and last fence lines
        inner = []
        in_block = False
        for line in lines:
            if line.startswith("```") and not in_block:
                in_block = True
                continue
            elif line.startswith("```") and in_block:
                break
            elif in_block:
                inner.append(line)
        cleaned = "\n".join(inner)

    try:
        plan = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Last-resort: try to find JSON object in the response
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                plan = json.loads(cleaned[start:end])
            except json.JSONDecodeError:
                raise RuntimeError(
                    f"Claude returned unparseable JSON. Parse error: {e}\n"
                    f"Raw response (first 500 chars): {raw_response[:500]}"
                )
        else:
            raise RuntimeError(
                f"Claude returned no valid JSON. Parse error: {e}\n"
                f"Raw response (first 500 chars): {raw_response[:500]}"
            )

    return {
        "plan": plan,
        "food_banks_found": len(food_banks),
        "city": city,
        "state": state,
        "lat": location_data.get("lat"),
        "lng": location_data.get("lng"),
        "search_radius_km": location_data.get("search_radius_km", 25),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "provider": provider_name,
        "model_used": model_name,
    }
