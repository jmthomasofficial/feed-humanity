"""
matching_engine.py — Core AI matching logic for the HELIOS AI Dispatch System.

Scores each available supply listing against each open demand listing using
a weighted composite of four signals:
  - Distance score      (40%): closer supplier = higher score
  - Perishability score (30%): expires sooner = higher priority
  - Volume match score  (20%): quantity closer to need = higher score
  - Dietary fit score   (10%): dietary flags satisfy requirements = higher score

All lat/lng distance calculations use the real geodesic formula via geopy.
"""

import json
from datetime import datetime, timezone
from typing import List, Dict, Any

from geopy.distance import geodesic

from database import (
    get_available_supply,
    get_open_demand,
    insert_match,
)

# Composite score weights — must sum to 1.0
WEIGHT_DISTANCE    = 0.40
WEIGHT_PERISHABLE  = 0.30
WEIGHT_VOLUME      = 0.20
WEIGHT_DIETARY     = 0.10

# Distance beyond which score decays to near-zero (km)
MAX_USEFUL_DISTANCE_KM = 200.0


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate the geodesic distance in kilometres between two coordinate pairs.
    Uses geopy's geodesic (WGS-84 ellipsoid) for accurate real-world distances.
    """
    return geodesic((lat1, lng1), (lat2, lng2)).kilometers


def distance_score(distance_km: float) -> float:
    """
    Convert a raw distance into a 0–1 score.
    Uses exponential decay: score = exp(-distance / half_range).
    Score ≈ 1.0 at 0 km, ≈ 0.5 at MAX_USEFUL_DISTANCE_KM/2, decays to ~0 beyond.
    """
    import math
    half_range = MAX_USEFUL_DISTANCE_KM / 2.0
    return math.exp(-distance_km / half_range)


def perishability_score(expires_at_str: str) -> float:
    """
    Convert a supply's expiry datetime into a 0–1 urgency score.
    Items expiring within 2 hours score near 1.0.
    Items expiring in 48+ hours score near 0.0.
    Score = 1 - clamp(hours_until_expiry / 48, 0, 1)
    """
    try:
        expires_at = datetime.fromisoformat(expires_at_str)
        # Make both timezone-naive for comparison
        if expires_at.tzinfo is not None:
            expires_at = expires_at.replace(tzinfo=None)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        hours_remaining = max((expires_at - now).total_seconds() / 3600.0, 0)
        max_hours = 48.0
        return 1.0 - min(hours_remaining / max_hours, 1.0)
    except (ValueError, TypeError):
        return 0.5  # fallback if datetime is malformed


def volume_match_score(supply_qty: int, demand_qty: int) -> float:
    """
    Score how well supply quantity matches demand quantity.
    Perfect match = 1.0. Ratio-based: score = min(supply, demand) / max(supply, demand).
    This rewards matches where supply closely covers demand without massive over/under-supply.
    """
    if supply_qty <= 0 or demand_qty <= 0:
        return 0.0
    return min(supply_qty, demand_qty) / max(supply_qty, demand_qty)


def dietary_fit_score(supply_flags_json: str, demand_requirements_json: str) -> float:
    """
    Score dietary compatibility between a supply and a demand.
    Returns 1.0 if all demand requirements are satisfied by supply flags.
    Returns partial credit proportional to fraction of requirements met.
    Returns 1.0 if demand has no dietary requirements.

    Flags/requirements are JSON objects with boolean values, e.g.:
      {"vegan": true, "halal": false, "kosher": false, "gluten_free": true}
    """
    try:
        supply_flags = json.loads(supply_flags_json) if supply_flags_json else {}
        demand_reqs  = json.loads(demand_requirements_json) if demand_requirements_json else {}
    except (json.JSONDecodeError, TypeError):
        return 0.5  # fallback

    # Only score against requirements that are True on demand side
    required = [k for k, v in demand_reqs.items() if v]
    if not required:
        return 1.0  # no requirements = any supply fits

    met = sum(1 for req in required if supply_flags.get(req, False))
    return met / len(required)


def score_match(supply: Dict[str, Any], demand: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute the composite match score between one supply and one demand.

    Returns a dict with:
      supply_id, demand_id, distance_km, score,
      sub_scores: {distance, perishability, volume, dietary}
    """
    dist_km = haversine_km(
        supply["lat"], supply["lng"],
        demand["lat"], demand["lng"]
    )

    d_score = distance_score(dist_km)
    p_score = perishability_score(supply["expires_at"])
    v_score = volume_match_score(supply["quantity_meals"], demand["meals_needed"])
    diet_score = dietary_fit_score(
        supply.get("dietary_flags", "{}"),
        demand.get("dietary_requirements", "{}")
    )

    composite = (
        WEIGHT_DISTANCE   * d_score +
        WEIGHT_PERISHABLE * p_score +
        WEIGHT_VOLUME     * v_score +
        WEIGHT_DIETARY    * diet_score
    )

    return {
        "supply_id":   supply["id"],
        "demand_id":   demand["id"],
        "distance_km": round(dist_km, 3),
        "score":       round(composite, 4),
        "sub_scores": {
            "distance":      round(d_score, 4),
            "perishability": round(p_score, 4),
            "volume":        round(v_score, 4),
            "dietary":       round(diet_score, 4),
        }
    }


def run_matching(
    db_path: str,
    top_n: int = 3,
    write_to_db: bool = True
) -> List[Dict[str, Any]]:
    """
    Main entry point. Load all available supply + open demand from the database,
    score every supply-demand pair, select the top-N matches per demand,
    optionally write them to the matches table.

    Args:
        db_path:     Path to the SQLite dispatch database.
        top_n:       Number of top supply matches to record per demand listing.
        write_to_db: If True, persist matches to the matches table.

    Returns:
        List of match result dicts, each containing supply_id, demand_id,
        distance_km, score, sub_scores, supplier_name, org_name.
    """
    supply_listings = get_available_supply(db_path)
    demand_listings = get_open_demand(db_path)

    if not supply_listings:
        print("[matching_engine] No available supply listings found.")
        return []
    if not demand_listings:
        print("[matching_engine] No open demand listings found.")
        return []

    all_matches = []

    for demand in demand_listings:
        scored = []
        for supply in supply_listings:
            result = score_match(supply, demand)
            result["supplier_name"] = supply["supplier_name"]
            result["food_type"]     = supply["food_type"]
            result["org_name"]      = demand["org_name"]
            scored.append(result)

        # Sort by composite score descending
        scored.sort(key=lambda x: x["score"], reverse=True)
        top_matches = scored[:top_n]

        if write_to_db:
            for match in top_matches:
                match["db_id"] = insert_match(db_path, {
                    "supply_id":   match["supply_id"],
                    "demand_id":   match["demand_id"],
                    "distance_km": match["distance_km"],
                    "score":       match["score"],
                })

        all_matches.extend(top_matches)

    return all_matches
