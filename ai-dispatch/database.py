"""
database.py — SQLite schema, connection management, and geocode caching
for the HELIOS AI Dispatch System (Feed Humanity campaign).
"""

import sqlite3
import os

# Default production DB path
DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "dispatch.db")


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
        CREATE TABLE IF NOT EXISTS supply_listings (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_name    TEXT    NOT NULL,
            supplier_type    TEXT    NOT NULL CHECK(supplier_type IN ('restaurant','farm','grocer','caterer')),
            address          TEXT    NOT NULL,
            lat              REAL    NOT NULL,
            lng              REAL    NOT NULL,
            food_type        TEXT    NOT NULL,
            quantity_meals   INTEGER NOT NULL CHECK(quantity_meals > 0),
            dietary_flags    TEXT    NOT NULL DEFAULT '{}',  -- JSON: {vegan, halal, kosher, gluten_free}
            available_from   TEXT    NOT NULL,               -- ISO datetime
            expires_at       TEXT    NOT NULL,               -- ISO datetime
            status           TEXT    NOT NULL DEFAULT 'available'
                             CHECK(status IN ('available','matched','expired','collected')),
            contact_phone    TEXT,
            contact_email    TEXT,
            created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS demand_listings (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            org_name             TEXT    NOT NULL,
            org_type             TEXT    NOT NULL CHECK(org_type IN ('food_bank','shelter','soup_kitchen','event')),
            address              TEXT    NOT NULL,
            lat                  REAL    NOT NULL,
            lng                  REAL    NOT NULL,
            meals_needed         INTEGER NOT NULL CHECK(meals_needed > 0),
            dietary_requirements TEXT    NOT NULL DEFAULT '{}',  -- JSON subset
            needed_by            TEXT    NOT NULL,               -- ISO datetime
            status               TEXT    NOT NULL DEFAULT 'open'
                                 CHECK(status IN ('open','matched','fulfilled')),
            contact_phone        TEXT,
            contact_email        TEXT,
            created_at           TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS matches (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            supply_id   INTEGER NOT NULL REFERENCES supply_listings(id),
            demand_id   INTEGER NOT NULL REFERENCES demand_listings(id),
            distance_km REAL    NOT NULL,
            score       REAL    NOT NULL CHECK(score >= 0.0 AND score <= 1.0),
            matched_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            status      TEXT    NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','confirmed','completed','cancelled')),
            pickup_time TEXT,
            notes       TEXT
        );

        CREATE TABLE IF NOT EXISTS geocode_cache (
            address     TEXT PRIMARY KEY,
            lat         REAL NOT NULL,
            lng         REAL NOT NULL,
            cached_at   TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)

    conn.commit()
    conn.close()


def insert_supply(db_path: str, supply: dict) -> int:
    """
    Insert a supply listing and return the new row id.

    Required keys: supplier_name, supplier_type, address, lat, lng,
                   food_type, quantity_meals, available_from, expires_at
    Optional keys: dietary_flags, status, contact_phone, contact_email
    """
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO supply_listings
            (supplier_name, supplier_type, address, lat, lng,
             food_type, quantity_meals, dietary_flags,
             available_from, expires_at, status, contact_phone, contact_email)
        VALUES
            (:supplier_name, :supplier_type, :address, :lat, :lng,
             :food_type, :quantity_meals, :dietary_flags,
             :available_from, :expires_at, :status, :contact_phone, :contact_email)
    """, {
        "supplier_name":  supply["supplier_name"],
        "supplier_type":  supply["supplier_type"],
        "address":        supply["address"],
        "lat":            supply["lat"],
        "lng":            supply["lng"],
        "food_type":      supply["food_type"],
        "quantity_meals": supply["quantity_meals"],
        "dietary_flags":  supply.get("dietary_flags", "{}"),
        "available_from": supply["available_from"],
        "expires_at":     supply["expires_at"],
        "status":         supply.get("status", "available"),
        "contact_phone":  supply.get("contact_phone"),
        "contact_email":  supply.get("contact_email"),
    })
    row_id = cur.lastrowid
    assert row_id is not None
    conn.commit()
    conn.close()
    return row_id


def insert_demand(db_path: str, demand: dict) -> int:
    """
    Insert a demand listing and return the new row id.

    Required keys: org_name, org_type, address, lat, lng,
                   meals_needed, needed_by
    Optional keys: dietary_requirements, status, contact_phone, contact_email
    """
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO demand_listings
            (org_name, org_type, address, lat, lng,
             meals_needed, dietary_requirements, needed_by,
             status, contact_phone, contact_email)
        VALUES
            (:org_name, :org_type, :address, :lat, :lng,
             :meals_needed, :dietary_requirements, :needed_by,
             :status, :contact_phone, :contact_email)
    """, {
        "org_name":              demand["org_name"],
        "org_type":              demand["org_type"],
        "address":               demand["address"],
        "lat":                   demand["lat"],
        "lng":                   demand["lng"],
        "meals_needed":          demand["meals_needed"],
        "dietary_requirements":  demand.get("dietary_requirements", "{}"),
        "needed_by":             demand["needed_by"],
        "status":                demand.get("status", "open"),
        "contact_phone":         demand.get("contact_phone"),
        "contact_email":         demand.get("contact_email"),
    })
    row_id = cur.lastrowid
    assert row_id is not None
    conn.commit()
    conn.close()
    return row_id


def insert_match(db_path: str, match: dict) -> int:
    """
    Insert a match record and return the new row id.

    Required keys: supply_id, demand_id, distance_km, score
    Optional keys: status, pickup_time, notes
    """
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO matches
            (supply_id, demand_id, distance_km, score, status, pickup_time, notes)
        VALUES
            (:supply_id, :demand_id, :distance_km, :score, :status, :pickup_time, :notes)
    """, {
        "supply_id":   match["supply_id"],
        "demand_id":   match["demand_id"],
        "distance_km": match["distance_km"],
        "score":       match["score"],
        "status":      match.get("status", "pending"),
        "pickup_time": match.get("pickup_time"),
        "notes":       match.get("notes"),
    })
    row_id = cur.lastrowid
    assert row_id is not None
    conn.commit()
    conn.close()
    return row_id


def get_available_supply(db_path: str) -> list:
    """Return all supply listings with status='available' as list of dicts."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM supply_listings WHERE status = 'available'")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_open_demand(db_path: str) -> list:
    """Return all demand listings with status='open' as list of dicts."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM demand_listings WHERE status = 'open'")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_matches_for_demand(db_path: str, demand_id: int) -> list:
    """Return all matches for a given demand_id, sorted by score descending."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT m.*, s.supplier_name, s.food_type, s.quantity_meals,
               d.org_name, d.meals_needed
        FROM matches m
        JOIN supply_listings s ON m.supply_id = s.id
        JOIN demand_listings d ON m.demand_id = d.id
        WHERE m.demand_id = ?
        ORDER BY m.score DESC
    """, (demand_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def confirm_match(db_path: str, match_id: int) -> bool:
    """Set a match status to 'confirmed'. Returns True if a row was updated."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute(
        "UPDATE matches SET status = 'confirmed' WHERE id = ? AND status = 'pending'",
        (match_id,)
    )
    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def get_stats(db_path: str) -> dict:
    """
    Return live stats:
      - total_meals_available: sum of quantity_meals for available supply
      - total_meals_needed: sum of meals_needed for open demand
      - total_matches_made: count of all matches
      - confirmed_matches: count of confirmed/completed matches
    """
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute("SELECT COALESCE(SUM(quantity_meals),0) FROM supply_listings WHERE status='available'")
    total_available = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(meals_needed),0) FROM demand_listings WHERE status='open'")
    total_needed = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM matches")
    total_matches = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM matches WHERE status IN ('confirmed','completed')")
    confirmed = cur.fetchone()[0]

    conn.close()
    return {
        "total_meals_available": total_available,
        "total_meals_needed":    total_needed,
        "total_matches_made":    total_matches,
        "confirmed_matches":     confirmed,
    }
