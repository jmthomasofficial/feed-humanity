"""
database.py — SQLite schema, connection management, and aggregate queries
for the Feed Humanity AI Impact Tracker.

Tables:
  - impact_events:    Individual social media post records with parsed data.
  - city_leaderboard: Aggregated per-city stats (meals, posts, last active).
  - geocode_cache:    Cached city → lat/lng lookups (avoids repeat Nominatim calls).
"""

import sqlite3
import os
from datetime import datetime, timezone
from typing import Optional

# Default production DB path (same directory as this file)
DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "impact.db")


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """
    Return a SQLite connection with row_factory set to sqlite3.Row
    so columns are accessible by name.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """
    Create all tables if they don't already exist.
    Safe to call on an existing database — idempotent.
    """
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS impact_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            post_url        TEXT    NOT NULL,
            platform        TEXT    NOT NULL DEFAULT 'unknown',
            raw_text        TEXT    NOT NULL,
            meals_count     INTEGER NOT NULL CHECK(meals_count >= 0),
            city            TEXT    NOT NULL DEFAULT '',
            state           TEXT    NOT NULL DEFAULT '',
            country         TEXT    NOT NULL DEFAULT 'US',
            lat             REAL,
            lng             REAL,
            poster_handle   TEXT    NOT NULL DEFAULT '',
            verified        INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS city_leaderboard (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            city            TEXT    NOT NULL,
            state           TEXT    NOT NULL DEFAULT '',
            country         TEXT    NOT NULL DEFAULT 'US',
            lat             REAL,
            lng             REAL,
            meals_total     INTEGER NOT NULL DEFAULT 0,
            post_count      INTEGER NOT NULL DEFAULT 0,
            last_active     TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE(city, state, country)
        );

        CREATE TABLE IF NOT EXISTS geocode_cache (
            query           TEXT PRIMARY KEY,
            lat             REAL NOT NULL,
            lng             REAL NOT NULL,
            display_name    TEXT NOT NULL DEFAULT '',
            cached_at       TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_impact_city ON impact_events(city);
        CREATE INDEX IF NOT EXISTS idx_impact_created ON impact_events(created_at);
        CREATE INDEX IF NOT EXISTS idx_leaderboard_meals ON city_leaderboard(meals_total DESC);
    """)

    conn.commit()
    conn.close()


def insert_impact(db_path: str, event: dict) -> int:
    """
    Insert an impact event and update the city leaderboard atomically.

    Required keys: post_url, raw_text, meals_count
    Optional keys: platform, city, state, country, lat, lng, poster_handle, verified
    """
    conn = get_connection(db_path)
    cur = conn.cursor()

    # Insert the event
    cur.execute("""
        INSERT INTO impact_events
            (post_url, platform, raw_text, meals_count, city, state, country,
             lat, lng, poster_handle, verified)
        VALUES
            (:post_url, :platform, :raw_text, :meals_count, :city, :state, :country,
             :lat, :lng, :poster_handle, :verified)
    """, {
        "post_url":       event["post_url"],
        "platform":       event.get("platform", "unknown"),
        "raw_text":       event["raw_text"],
        "meals_count":    event["meals_count"],
        "city":           event.get("city", ""),
        "state":          event.get("state", ""),
        "country":        event.get("country", "US"),
        "lat":            event.get("lat"),
        "lng":            event.get("lng"),
        "poster_handle":  event.get("poster_handle", ""),
        "verified":       1 if event.get("verified") else 0,
    })
    row_id = cur.lastrowid
    assert row_id is not None

    # Update city leaderboard if city is present
    city = event.get("city", "").strip()
    if city:
        cur.execute("""
            INSERT INTO city_leaderboard (city, state, country, lat, lng, meals_total, post_count, last_active)
            VALUES (:city, :state, :country, :lat, :lng, :meals, 1, datetime('now'))
            ON CONFLICT(city, state, country) DO UPDATE SET
                meals_total = meals_total + :meals,
                post_count  = post_count + 1,
                last_active = datetime('now'),
                lat = COALESCE(:lat, lat),
                lng = COALESCE(:lng, lng)
        """, {
            "city":    city,
            "state":   event.get("state", ""),
            "country": event.get("country", "US"),
            "lat":     event.get("lat"),
            "lng":     event.get("lng"),
            "meals":   event["meals_count"],
        })

    conn.commit()
    conn.close()
    return row_id


def get_stats(db_path: str = DEFAULT_DB_PATH) -> dict:
    """
    Return aggregate impact stats:
      - total_meals: sum of all meals across all events
      - total_posts: count of all impact events
      - cities_active: count of distinct cities with at least 1 post
      - top_cities: list of top 5 cities by meal count
    """
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute("SELECT COALESCE(SUM(meals_count), 0) FROM impact_events")
    total_meals = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM impact_events")
    total_posts = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM city_leaderboard WHERE post_count > 0")
    cities_active = cur.fetchone()[0]

    cur.execute("""
        SELECT city, state, meals_total, post_count
        FROM city_leaderboard
        ORDER BY meals_total DESC
        LIMIT 5
    """)
    top_cities = [dict(r) for r in cur.fetchall()]

    conn.close()
    return {
        "total_meals":    total_meals,
        "total_posts":    total_posts,
        "cities_active":  cities_active,
        "top_cities":     top_cities,
    }


def get_map_data(db_path: str = DEFAULT_DB_PATH) -> dict:
    """
    Return GeoJSON FeatureCollection of all cities with impact data.
    Each feature is a point with properties: city, state, meals_total, post_count.
    """
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute("""
        SELECT city, state, country, lat, lng, meals_total, post_count
        FROM city_leaderboard
        WHERE lat IS NOT NULL AND lng IS NOT NULL AND post_count > 0
        ORDER BY meals_total DESC
    """)
    rows = cur.fetchall()
    conn.close()

    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [r["lng"], r["lat"]],  # GeoJSON is [lng, lat]
            },
            "properties": {
                "city":        r["city"],
                "state":       r["state"],
                "country":     r["country"],
                "meals_total": r["meals_total"],
                "post_count":  r["post_count"],
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def get_leaderboard(db_path: str = DEFAULT_DB_PATH, limit: int = 20) -> list:
    """Return top cities by meal count, descending."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT city, state, country, meals_total, post_count, last_active
        FROM city_leaderboard
        ORDER BY meals_total DESC
        LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ─── Geocode Cache ─────────────────────────────────────────────

def get_cached_geocode(db_path: str, query: str) -> Optional[dict]:
    """Look up a cached geocode result. Returns None if not cached."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT lat, lng, display_name FROM geocode_cache WHERE query = ?", (query,))
    row = cur.fetchone()
    conn.close()
    if row:
        return {"lat": row["lat"], "lng": row["lng"], "display_name": row["display_name"]}
    return None


def cache_geocode(db_path: str, query: str, lat: float, lng: float, display_name: str = "") -> None:
    """Store a geocode result in the cache."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO geocode_cache (query, lat, lng, display_name)
        VALUES (?, ?, ?, ?)
    """, (query, lat, lng, display_name))
    conn.commit()
    conn.close()
