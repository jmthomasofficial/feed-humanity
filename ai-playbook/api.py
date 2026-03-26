"""
api.py — FastAPI REST endpoint for the Feed Humanity AI Playbook Generator.

Uses multi-provider LLM system (Gemini/NIM/OpenRouter) with automatic fallback.
No vendor lock-in. No Anthropic dependency.

Endpoints:
  POST /playbook       — Generate a personalized action plan
  GET  /playbook/tiers — List tier descriptions
  GET  /health         — Health check including LLM provider status
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from plan_generator import generate_playbook, PlaybookInput, TIER_LABELS, TIER_DESCRIPTIONS  # type: ignore[import]

app = FastAPI(
    title="Feed Humanity AI Playbook Generator",
    description="Generates personalized Feed Humanity action plans based on location, budget, time, and participation tier.",
    version="2.0.0",
)


# --- Request / Response Models ---

class PlaybookRequest(BaseModel):
    zip_code: str = Field(..., description="US zip code")
    budget_usd: float = Field(..., ge=5.0, le=100000.0, description="Budget in USD")
    time_hours: float = Field(..., ge=0.25, le=168.0, description="Hours available")
    tier: int = Field(..., ge=1, le=6, description="Participation tier (1-6)")
    dietary_focus: Optional[str] = Field(default="", description="Optional dietary requirement")


class PlaybookResponse(BaseModel):
    plan: dict
    food_banks_found: int
    city: str
    state: str
    lat: float
    lng: float
    search_radius_km: int
    generated_at: str
    provider: str
    model_used: str


class TierInfo(BaseModel):
    tier: int
    label: str
    description: str


class HealthResponse(BaseModel):
    status: str
    llm_providers: list[dict]
    timestamp: str


# --- Endpoints ---

@app.post("/playbook", response_model=PlaybookResponse, summary="Generate personalized action plan")
async def create_playbook(request: PlaybookRequest):
    """
    Generate a personalized Feed Humanity action plan.

    - Geocodes the zip code to find real location data
    - Queries OpenStreetMap Overpass API for real food banks near the location
    - Calls LLM (Gemini/NIM/OpenRouter) to generate a structured, personalized action plan
    - Returns the plan with food bank data, location info, and metadata
    """
    inp = PlaybookInput(
        zip_code=request.zip_code,
        budget_usd=request.budget_usd,
        time_hours=request.time_hours,
        tier=request.tier,
        dietary_focus=request.dietary_focus or "",
    )

    try:
        result = generate_playbook(inp)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        error_msg = str(e)
        if "No API keys found" in error_msg:
            raise HTTPException(status_code=503, detail="No LLM provider keys configured. Add keys to d:\\JM\\env\\.")
        raise HTTPException(status_code=502, detail=f"Upstream service error: {error_msg}")

    return PlaybookResponse(**result)


@app.get("/playbook/tiers", response_model=list[TierInfo], summary="List all participation tiers")
async def get_tiers():
    """Return descriptions for all 6 Feed Humanity participation tiers."""
    return [
        TierInfo(tier=tier, label=TIER_LABELS[tier], description=TIER_DESCRIPTIONS[tier])
        for tier in range(1, 7)
    ]


@app.get("/health", response_model=HealthResponse, summary="Service health check")
async def health_check():
    """
    Check service health and LLM provider availability.
    Returns list of available providers with key counts.
    """
    try:
        from llm_client import list_available_providers  # type: ignore[import]
        providers = list_available_providers()
    except Exception:
        providers = []

    return HealthResponse(
        status="ok" if any(p.get("available") for p in providers) else "no_providers",
        llm_providers=providers,
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


# --- Run directly ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
