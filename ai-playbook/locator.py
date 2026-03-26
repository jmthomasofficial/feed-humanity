"""
locator.py — Find real food banks near a zip code.

Uses:
  - Nominatim (OpenStreetMap, no API key) to resolve zip → lat/lng/city/state
  - Overpass API (OpenStreetMap, no API key) to find food banks within radius
  - SQLite cache (7-day TTL) at playbook_cache.db
"""

import sqlite3
import json
import time
import math
import os
import requests
from geopy.geocoders import Nominatim  # type: ignore[import-untyped]
from geopy.exc import GeocoderTimedOut, GeocoderServiceError  # type: ignore[import-untyped]
from datetime import datetime

# Cache DB path
DB_PATH = os.path.join(os.path.dirname(__file__), "playbook_cache.db")
CACHE_TTL_DAYS = 7

# Overpass API endpoint
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Nominatim user-agent (required by OSM usage policy)
NOMINATIM_USER_AGENT = "FeedHumanity-PlaybookGenerator/1.0 (contact@feedhumanity.org)"


def _init_db():
    """Initialize SQLite cache tables."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS geocode_cache (
            zip_code TEXT PRIMARY KEY,
            lat REAL,
            lng REAL,
            city TEXT,
            state TEXT,
            country TEXT,
            cached_at REAL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS foodbank_cache (
            zip_code TEXT PRIMARY KEY,
            radius_km REAL,
            results_json TEXT,
            cached_at REAL
        )
    """)
    conn.commit()
    conn.close()


def _haversine_km(lat1, lng1, lat2, lng2):
    """Calculate distance in km between two lat/lng points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def geocode_zip(zip_code: str) -> dict:
    """
    Resolve a US zip code to lat/lng/city/state using Nominatim.
    Returns dict: {lat, lng, city, state, country}
    Raises ValueError if zip cannot be resolved.
    """
    _init_db()
    zip_code = zip_code.strip()

    # Check cache
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT lat, lng, city, state, country, cached_at FROM geocode_cache WHERE zip_code=?", (zip_code,))
    row = c.fetchone()
    conn.close()

    if row:
        lat, lng, city, state, country, cached_at = row
        age = time.time() - cached_at
        if age < CACHE_TTL_DAYS * 86400:
            return {"lat": lat, "lng": lng, "city": city, "state": state, "country": country}

    # Geocode via Nominatim
    geolocator = Nominatim(user_agent=NOMINATIM_USER_AGENT, timeout=10)
    try:
        # Try "{zip}, USA" for US zip codes
        location = geolocator.geocode(f"{zip_code}, USA", addressdetails=True)
        if not location:
            # Fallback: try plain zip
            location = geolocator.geocode(zip_code, addressdetails=True)
        if not location:
            raise ValueError(f"Could not geocode zip code: {zip_code}")
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        raise ValueError(f"Geocoding service error for zip {zip_code}: {e}")

    addr = location.raw.get("address", {})
    city = (addr.get("city") or addr.get("town") or addr.get("village") or
            addr.get("county") or addr.get("hamlet") or "Unknown City")
    state = addr.get("state", "Unknown State")
    country = addr.get("country_code", "us").upper()
    lat = location.latitude
    lng = location.longitude

    # Cache result
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO geocode_cache (zip_code, lat, lng, city, state, country, cached_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (zip_code, lat, lng, city, state, country, time.time()))
    conn.commit()
    conn.close()

    return {"lat": lat, "lng": lng, "city": city, "state": state, "country": country}


def _build_overpass_query(lat: float, lng: float, radius_m: int) -> str:
    """Build Overpass QL query for food banks within radius."""
    return f"""
[out:json][timeout:25];
(
  node["amenity"="food_bank"](around:{radius_m},{lat},{lng});
  way["amenity"="food_bank"](around:{radius_m},{lat},{lng});
  node["social_facility"="food_bank"](around:{radius_m},{lat},{lng});
  way["social_facility"="food_bank"](around:{radius_m},{lat},{lng});
  node["social_facility"="soup_kitchen"](around:{radius_m},{lat},{lng});
  node["amenity"="social_facility"]["social_facility"="food_pantry"](around:{radius_m},{lat},{lng});
  node["amenity"="community_centre"]["community_centre"="food_pantry"](around:{radius_m},{lat},{lng});
);
out body;
>;
out skel qt;
"""


def _query_overpass(lat: float, lng: float, radius_m: int) -> list:
    """
    Query Overpass API and return list of food bank dicts.
    Each dict: {name, address, lat, lng, distance_km}
    """
    query = _build_overpass_query(lat, lng, radius_m)
    try:
        resp = requests.post(
            OVERPASS_URL,
            data={"data": query},
            timeout=30,
            headers={"User-Agent": NOMINATIM_USER_AGENT}
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise RuntimeError(f"Overpass API request failed: {e}")
    except ValueError as e:
        raise RuntimeError(f"Overpass API returned invalid JSON: {e}")

    results = []
    for el in data.get("elements", []):
        # Skip ways (we only want nodes for point locations)
        if el.get("type") not in ("node", "way"):
            continue

        el_lat = el.get("lat")
        el_lng = el.get("lon")

        # Ways have center instead of direct lat/lon
        if el_lat is None and el.get("type") == "way":
            center = el.get("center", {})
            el_lat = center.get("lat")
            el_lng = center.get("lon")

        if el_lat is None or el_lng is None:
            continue

        tags = el.get("tags", {})
        name = (tags.get("name") or tags.get("operator") or
                tags.get("brand") or "Unnamed Food Bank")

        # Build address from tags
        addr_parts = []
        if tags.get("addr:housenumber") and tags.get("addr:street"):
            addr_parts.append(f"{tags['addr:housenumber']} {tags['addr:street']}")
        elif tags.get("addr:street"):
            addr_parts.append(tags["addr:street"])
        if tags.get("addr:city"):
            addr_parts.append(tags["addr:city"])
        if tags.get("addr:state"):
            addr_parts.append(tags["addr:state"])
        address = ", ".join(addr_parts) if addr_parts else "Address not listed"

        distance_km = _haversine_km(lat, lng, el_lat, el_lng)
        results.append({
            "name": name,
            "address": address,
            "lat": el_lat,
            "lng": el_lng,
            "distance_km": round(distance_km, 2)
        })

    # Sort by distance
    results.sort(key=lambda x: x["distance_km"])
    return results


def find_food_banks(zip_code: str) -> dict:
    """
    Find real food banks near a zip code.

    Returns:
        {
            "zip_code": str,
            "city": str,
            "state": str,
            "lat": float,
            "lng": float,
            "food_banks": [...],
            "search_radius_km": int,
            "source": "cache"|"live"
        }

    Always returns a result. If no food banks found within 25km, expands to 50km.
    If still none found, returns empty list with note.
    """
    _init_db()
    zip_code = zip_code.strip()

    # Get geo coordinates
    geo = geocode_zip(zip_code)
    lat, lng = geo["lat"], geo["lng"]
    city, state = geo["city"], geo["state"]

    # Check food bank cache
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT radius_km, results_json, cached_at FROM foodbank_cache WHERE zip_code=?", (zip_code,))
    row = c.fetchone()
    conn.close()

    if row:
        radius_km, results_json, cached_at = row
        age = time.time() - cached_at
        if age < CACHE_TTL_DAYS * 86400:
            return {
                "zip_code": zip_code,
                "city": city,
                "state": state,
                "lat": lat,
                "lng": lng,
                "food_banks": json.loads(results_json),
                "search_radius_km": int(radius_km),
                "source": "cache"
            }

    # Query Overpass — 25km first
    radius_km = 25
    food_banks = _query_overpass(lat, lng, radius_m=25000)

    # Fallback to 50km if nothing found
    if not food_banks:
        radius_km = 50
        food_banks = _query_overpass(lat, lng, radius_m=50000)

    # Cache the results
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO foodbank_cache (zip_code, radius_km, results_json, cached_at)
        VALUES (?, ?, ?, ?)
    """, (zip_code, radius_km, json.dumps(food_banks), time.time()))
    conn.commit()
    conn.close()

    return {
        "zip_code": zip_code,
        "city": city,
        "state": state,
        "lat": lat,
        "lng": lng,
        "food_banks": food_banks,
        "search_radius_km": radius_km,
        "source": "live"
    }
