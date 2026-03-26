"""
api.py — FastAPI REST endpoints for the Feed Humanity AI Impact Tracker.

Parses social media posts for meal counts and city geolocation,
tracks global impact stats, and serves live data for the frontend widget.

Endpoints:
  POST /impact            — Submit a social media post for parsing
  GET  /impact/stats      — Global stats (total meals, posts, cities)
  GET  /impact/map-data   — GeoJSON for Leaflet.js city map
  GET  /impact/leaderboard — Top cities by meal count
  GET  /health            — Service health check
"""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from database import (
    DEFAULT_DB_PATH,
    init_db,
    insert_impact,
    get_stats,
    get_map_data,
    get_leaderboard,
)
from parser import parse_post
from geocoder import geocode_city

# ─── App Init ──────────────────────────────────────────────────

DB_PATH = os.getenv("IMPACT_DB_PATH", DEFAULT_DB_PATH)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure database tables exist at startup."""
    init_db(DB_PATH)
    yield


app = FastAPI(
    title="Feed Humanity AI Impact Tracker",
    description="Tracks #FeedHumanity social media posts, parses meal counts, "
                "and serves live impact data for the global counter and map.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow frontend to call from any origin (static site hosting)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ─── Pydantic Models ──────────────────────────────────────────

class ImpactSubmission(BaseModel):
    post_url: str = Field(..., description="URL of the social media post")
    raw_text: str = Field(..., min_length=1, description="Full text of the post")


class ImpactResult(BaseModel):
    id: int
    meals_count: int
    city: str
    state: str
    platform: str
    poster_handle: str
    extraction_method: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    message: str


class StatsResponse(BaseModel):
    total_meals: int
    total_posts: int
    cities_active: int
    top_cities: list
    timestamp: str


class MapDataResponse(BaseModel):
    type: str
    features: list


class LeaderboardEntry(BaseModel):
    city: str
    state: str
    country: str
    meals_total: int
    post_count: int
    last_active: str


class HealthResponse(BaseModel):
    status: str
    database: str
    timestamp: str


# ─── Endpoints ─────────────────────────────────────────────────

@app.post("/impact", response_model=ImpactResult, status_code=201,
          summary="Submit a social media post for impact tracking")
async def submit_impact(submission: ImpactSubmission):
    """
    Parse a social media post for meal count and city, store the result,
    and update the global impact counter.

    The parser uses regex first for speed, falling back to the multi-provider
    LLM (Gemini/NIM/OpenRouter) for ambiguous posts.
    """
    # Parse the post
    parsed = parse_post(submission.raw_text, submission.post_url)

    # Geocode the city if found
    lat, lng, state = None, None, ""
    city = parsed["city"]
    if city:
        geo = geocode_city(city, db_path=DB_PATH)
        if geo:
            lat = geo["lat"]
            lng = geo["lng"]
            # Try to extract state from display_name (e.g., "Nashville, Tennessee, US")
            parts = geo.get("display_name", "").split(",")
            if len(parts) >= 2:
                state = parts[-2].strip()

    # Store the event
    event = {
        "post_url":      submission.post_url,
        "platform":      parsed["platform"],
        "raw_text":      submission.raw_text,
        "meals_count":   parsed["meals"],
        "city":          city,
        "state":         state,
        "lat":           lat,
        "lng":           lng,
        "poster_handle": parsed["poster_handle"],
    }

    row_id = insert_impact(DB_PATH, event)

    return ImpactResult(
        id=row_id,
        meals_count=parsed["meals"],
        city=city,
        state=state,
        platform=parsed["platform"],
        poster_handle=parsed["poster_handle"],
        extraction_method=parsed["extraction_method"],
        lat=lat,
        lng=lng,
        message=f"Tracked: {parsed['meals']} meal(s) in {city or 'unknown location'}",
    )


@app.get("/impact/stats", response_model=StatsResponse,
         summary="Get global impact statistics")
async def impact_stats():
    """Return total meals, posts, active cities, and top city rankings."""
    stats = get_stats(DB_PATH)
    return StatsResponse(
        **stats,
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


@app.get("/impact/map-data", response_model=MapDataResponse,
         summary="Get GeoJSON map data for Leaflet.js")
async def impact_map_data():
    """Return GeoJSON FeatureCollection of all participating cities."""
    return get_map_data(DB_PATH)


@app.get("/impact/leaderboard", response_model=list[LeaderboardEntry],
         summary="Get city leaderboard")
async def impact_leaderboard(limit: int = 20):
    """Return top cities ranked by total meals contributed."""
    return get_leaderboard(DB_PATH, limit=limit)


@app.get("/health", response_model=HealthResponse, summary="Service health check")
async def health_check():
    """Check service health and database connectivity."""
    try:
        stats = get_stats(DB_PATH)
        db_status = "connected"
    except Exception:
        db_status = "error"

    return HealthResponse(
        status="ok" if db_status == "connected" else "degraded",
        database=db_status,
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


# ─── Run directly ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002, reload=False)
