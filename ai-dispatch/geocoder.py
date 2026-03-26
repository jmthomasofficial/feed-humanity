"""
geocoder.py — Address to lat/lng resolution using Nominatim (OpenStreetMap).
Results are cached in SQLite to avoid repeated lookups.
No API key required.
"""

import time
from typing import Optional, Tuple

from geopy.geocoders import Nominatim  # type: ignore[import-untyped]
from geopy.exc import GeocoderTimedOut, GeocoderServiceError  # type: ignore[import-untyped]

from database import get_connection, DEFAULT_DB_PATH

# Nominatim requires a unique user-agent string
_GEOLOCATOR = Nominatim(user_agent="helios-ai-dispatch/1.0")


def geocode_address(
    address: str,
    db_path: str = DEFAULT_DB_PATH,
    force_refresh: bool = False
) -> Optional[Tuple[float, float]]:
    """
    Convert a street address to (lat, lng) using Nominatim with SQLite caching.

    Args:
        address:       Human-readable address string.
        db_path:       Path to the SQLite database (for cache reads/writes).
        force_refresh: If True, bypass cache and re-query Nominatim.

    Returns:
        (lat, lng) tuple, or None if geocoding fails.
    """
    if not force_refresh:
        cached = _get_cached(address, db_path)
        if cached is not None:
            return cached

    try:
        # Nominatim free tier requires 1 req/sec
        time.sleep(1.1)
        location = _GEOLOCATOR.geocode(address, timeout=10)
        if location is None:
            return None
        lat, lng = location.latitude, location.longitude
        _save_cache(address, lat, lng, db_path)
        return (lat, lng)
    except (GeocoderTimedOut, GeocoderServiceError) as exc:
        # Non-fatal: caller can supply coordinates directly
        print(f"[geocoder] Warning: geocoding failed for '{address}': {exc}")
        return None


def _get_cached(address: str, db_path: str) -> Optional[Tuple[float, float]]:
    """
    Look up an address in the geocode_cache table.
    Returns (lat, lng) if found, else None.
    """
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT lat, lng FROM geocode_cache WHERE address = ?",
        (address,)
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return (row["lat"], row["lng"])
    return None


def _save_cache(address: str, lat: float, lng: float, db_path: str) -> None:
    """
    Insert or replace an address→(lat,lng) entry in the geocode_cache table.
    """
    conn = get_connection(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO geocode_cache (address, lat, lng) VALUES (?, ?, ?)",
        (address, lat, lng)
    )
    conn.commit()
    conn.close()
