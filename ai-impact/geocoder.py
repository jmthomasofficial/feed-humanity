"""
geocoder.py — City name to lat/lng via Nominatim (OpenStreetMap) with SQLite cache.

Uses the same geocoding pattern as ai-playbook/locator.py but specialized for
city-level lookups rather than zip codes. Results are cached in the impact
database's geocode_cache table to avoid repeat API calls.
"""

import time
import requests
from typing import Optional

from database import (
    DEFAULT_DB_PATH,
    get_cached_geocode,
    cache_geocode,
    init_db,
)

# Nominatim requires a descriptive User-Agent (no generic strings)
NOMINATIM_USER_AGENT = "FeedHumanity-ImpactTracker/1.0 (https://feedhumanity.org)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Rate limit: Nominatim requires max 1 request per second
_last_request_time = 0.0


def _rate_limit():
    """Enforce 1-second minimum between Nominatim requests."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)
    _last_request_time = time.time()


def geocode_city(
    city: str,
    state: str = "",
    country: str = "US",
    db_path: str = DEFAULT_DB_PATH,
) -> Optional[dict]:
    """
    Geocode a city name to lat/lng coordinates.

    1. Check SQLite cache first.
    2. If not cached, call Nominatim API.
    3. Cache the result for future lookups.

    Args:
        city:    City name (e.g., "Nashville")
        state:   State name or abbreviation (e.g., "Tennessee" or "TN")
        country: Country code (default: "US")
        db_path: Path to the SQLite database

    Returns:
        {"lat": float, "lng": float, "display_name": str} or None if not found.
    """
    if not city.strip():
        return None

    # Build cache key
    query = f"{city}, {state}, {country}".strip(", ")

    # Check cache
    cached = get_cached_geocode(db_path, query)
    if cached:
        return cached

    # Call Nominatim
    _rate_limit()

    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "addressdetails": 1,
    }

    try:
        resp = requests.get(
            NOMINATIM_URL,
            params=params,
            headers={"User-Agent": NOMINATIM_USER_AGENT},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()

        if not results:
            return None

        hit = results[0]
        lat = float(hit["lat"])
        lng = float(hit["lon"])
        display_name = hit.get("display_name", "")

        # Cache the result
        cache_geocode(db_path, query, lat, lng, display_name)

        return {
            "lat": lat,
            "lng": lng,
            "display_name": display_name,
        }

    except Exception as e:
        print(f"[geocoder] Nominatim error for '{query}': {e}")
        return None


# ─── Quick Self-Test ───────────────────────────────────────────

if __name__ == "__main__":
    import tempfile
    import os

    print("=" * 50)
    print("  GEOCODER — Self-Test")
    print("=" * 50)

    # Use temp DB for test
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    test_db = tmp.name
    tmp.close()

    try:
        init_db(test_db)

        result = geocode_city("Nashville", "Tennessee", db_path=test_db)
        if result:
            print(f"  Nashville: lat={result['lat']:.4f}, lng={result['lng']:.4f}")
            print(f"  Display: {result['display_name'][:80]}")

            # Test cache hit
            cached = geocode_city("Nashville", "Tennessee", db_path=test_db)
            if cached:
                print(f"  Cache hit: lat={cached['lat']:.4f} (same={cached['lat'] == result['lat']})")
                print("  RESULT: PASS")
            else:
                print("  RESULT: FAIL (cache miss)")
        else:
            print("  RESULT: FAIL (no geocode result)")

    finally:
        os.unlink(test_db)

    print("=" * 50)
