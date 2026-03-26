"""
api.py — FastAPI REST layer for the HELIOS AI Dispatch System.

Endpoints:
  POST /supply                    — Register a surplus food listing
  POST /demand                    — Register a food need
  GET  /matches/{demand_id}       — Ranked matches for a demand
  POST /matches/{match_id}/confirm — Confirm a pending match
  GET  /supply/available          — List all active supply listings
  GET  /demand/open               — List all open demand listings
  GET  /stats                     — Live stats

Run with: uvicorn api:app --reload
"""

import json
import os
from contextlib import asynccontextmanager
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from database import (
    DEFAULT_DB_PATH,
    init_db,
    insert_supply,
    insert_demand,
    get_available_supply,
    get_open_demand,
    get_matches_for_demand,
    confirm_match,
    get_stats,
)
from matching_engine import run_matching

# ─── App init ─────────────────────────────────────────────────────────────────

# Allow overriding DB path via environment variable (useful in tests)
DB_PATH = os.getenv("DISPATCH_DB_PATH", DEFAULT_DB_PATH)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure database tables exist at startup."""
    init_db(DB_PATH)
    yield


app = FastAPI(
    title="HELIOS AI Dispatch System",
    description="Surplus food ↔ deficit matching engine for the Feed Humanity campaign.",
    version="1.0.0",
    lifespan=lifespan,
)


# ─── Pydantic Models ───────────────────────────────────────────────────────────

class DietaryFlags(BaseModel):
    vegan:       bool = False
    halal:       bool = False
    kosher:      bool = False
    gluten_free: bool = False


class SupplyCreate(BaseModel):
    supplier_name:  str = Field(..., description="Name of the supplier")
    supplier_type:  str = Field(..., description="restaurant | farm | grocer | caterer")
    address:        str = Field(..., description="Full street address")
    lat:            float = Field(..., description="Latitude (decimal degrees)")
    lng:            float = Field(..., description="Longitude (decimal degrees)")
    food_type:      str = Field(..., description="Description of the food (e.g. 'mixed entrees')")
    quantity_meals: int = Field(..., gt=0, description="Estimated number of meals")
    dietary_flags:  DietaryFlags = Field(default_factory=DietaryFlags)
    available_from: str = Field(..., description="ISO datetime when food becomes available")
    expires_at:     str = Field(..., description="ISO datetime when food expires")
    contact_phone:  Optional[str] = None
    contact_email:  Optional[str] = None

    @field_validator("supplier_type", mode="before")
    @classmethod
    def validate_supplier_type(cls, v):
        allowed = {"restaurant", "farm", "grocer", "caterer"}
        if v not in allowed:
            raise ValueError(f"supplier_type must be one of {allowed}")
        return v


class SupplyResponse(BaseModel):
    id: int
    message: str


class DemandCreate(BaseModel):
    org_name:             str = Field(..., description="Name of the requesting organisation")
    org_type:             str = Field(..., description="food_bank | shelter | soup_kitchen | event")
    address:              str
    lat:                  float
    lng:                  float
    meals_needed:         int = Field(..., gt=0)
    dietary_requirements: DietaryFlags = Field(default_factory=DietaryFlags)
    needed_by:            str = Field(..., description="ISO datetime when food is needed by")
    contact_phone:        Optional[str] = None
    contact_email:        Optional[str] = None

    @field_validator("org_type", mode="before")
    @classmethod
    def validate_org_type(cls, v):
        allowed = {"food_bank", "shelter", "soup_kitchen", "event"}
        if v not in allowed:
            raise ValueError(f"org_type must be one of {allowed}")
        return v


class DemandResponse(BaseModel):
    id: int
    message: str


class MatchResult(BaseModel):
    match_id:       int
    supply_id:      int
    demand_id:      int
    supplier_name:  str
    food_type:      str
    org_name:       str
    distance_km:    float
    score:          float
    status:         str


class ConfirmResponse(BaseModel):
    match_id: int
    confirmed: bool
    message:  str


class StatsResponse(BaseModel):
    total_meals_available: int
    total_meals_needed:    int
    total_matches_made:    int
    confirmed_matches:     int


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/supply", response_model=SupplyResponse, status_code=201)
def register_supply(payload: SupplyCreate):
    """Register a new surplus food listing in the dispatch system."""
    data = payload.model_dump()
    data["dietary_flags"] = json.dumps(data["dietary_flags"])
    row_id = insert_supply(DB_PATH, data)
    return SupplyResponse(id=row_id, message="Supply listing registered successfully.")


@app.post("/demand", response_model=DemandResponse, status_code=201)
def register_demand(payload: DemandCreate):
    """Register a new food-need listing in the dispatch system."""
    data = payload.model_dump()
    data["dietary_requirements"] = json.dumps(data["dietary_requirements"])
    row_id = insert_demand(DB_PATH, data)
    return DemandResponse(id=row_id, message="Demand listing registered successfully.")


@app.get("/matches/{demand_id}", response_model=List[MatchResult])
def get_matches(demand_id: int, run_engine: bool = Query(False)):
    """
    Return ranked matches for a given demand listing.
    Pass ?run_engine=true to trigger a fresh matching pass before returning results.
    """
    if run_engine:
        run_matching(DB_PATH, top_n=5, write_to_db=True)

    rows = get_matches_for_demand(DB_PATH, demand_id)
    if not rows:
        raise HTTPException(status_code=404, detail="No matches found for this demand.")

    return [
        MatchResult(
            match_id=r["id"],
            supply_id=r["supply_id"],
            demand_id=r["demand_id"],
            supplier_name=r["supplier_name"],
            food_type=r["food_type"],
            org_name=r["org_name"],
            distance_km=r["distance_km"],
            score=r["score"],
            status=r["status"],
        )
        for r in rows
    ]


@app.post("/matches/{match_id}/confirm", response_model=ConfirmResponse)
def confirm_a_match(match_id: int):
    """Confirm a pending match, marking it as confirmed in the database."""
    success = confirm_match(DB_PATH, match_id)
    return ConfirmResponse(
        match_id=match_id,
        confirmed=success,
        message="Match confirmed." if success else "Match not found or already confirmed.",
    )


@app.get("/supply/available")
def list_available_supply():
    """List all supply listings currently marked as available."""
    rows = get_available_supply(DB_PATH)
    return {"count": len(rows), "listings": rows}


@app.get("/demand/open")
def list_open_demand():
    """List all demand listings currently marked as open."""
    rows = get_open_demand(DB_PATH)
    return {"count": len(rows), "listings": rows}


@app.get("/stats", response_model=StatsResponse)
def live_stats():
    """Return live aggregate statistics for the dispatch system."""
    return get_stats(DB_PATH)
