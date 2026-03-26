"""
test_dispatch.py — Real end-to-end test for the HELIOS AI Dispatch System.

This test:
  1. Creates a fresh temporary SQLite database
  2. Inserts 5 real-looking supply listings with authentic US city coordinates
  3. Inserts 3 real-looking demand listings
  4. Runs the matching engine
  5. Prints actual match results with scores and sub-scores
  6. Asserts at least 3 matches were produced
  7. Destroys the test database on completion
  8. Prints PASS or FAIL with clear explanation

Real coordinates used (no fabricated lat/lng):
  Memphis TN:   35.1495, -90.0490
  Nashville TN: 36.1627, -86.7816
  Austin TX:    30.2672, -97.7431
  Houston TX:   29.7604, -95.3698
  Dallas TX:    32.7767, -96.7970
"""

import os
import sys
import json
import tempfile
from datetime import datetime, timedelta, timezone

# ── Make sure local modules are importable ─────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

from database import init_db, get_available_supply, get_open_demand, get_matches_for_demand
from database import insert_supply, insert_demand
from matching_engine import run_matching, haversine_km


# ─── Helpers ──────────────────────────────────────────────────────────────────

def iso(dt: datetime) -> str:
    """Format a datetime as an ISO 8601 string without timezone info."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def now_plus(hours: float) -> str:
    """Return ISO string for UTC now + N hours."""
    return iso(datetime.now(timezone.utc) + timedelta(hours=hours))


def now_minus(hours: float) -> str:
    """Return ISO string for UTC now - N hours (already available)."""
    return iso(datetime.now(timezone.utc) - timedelta(hours=hours))


# ─── Test Data ─────────────────────────────────────────────────────────────────
# Real US city coordinates — no invented values

SUPPLY_LISTINGS = [
    {
        "supplier_name":  "Blues City Catering Co.",
        "supplier_type":  "caterer",
        "address":        "123 Beale St, Memphis, TN 38103",
        "lat":            35.1495,
        "lng":            -90.0490,
        "food_type":      "BBQ plates, coleslaw, cornbread",
        "quantity_meals": 120,
        "dietary_flags":  json.dumps({"vegan": False, "halal": False, "kosher": False, "gluten_free": False}),
        "available_from": now_minus(0.5),
        "expires_at":     now_plus(4),
        "contact_phone":  "901-555-0101",
        "contact_email":  "events@bluescitycatering.com",
    },
    {
        "supplier_name":  "Music City Fresh Market",
        "supplier_type":  "grocer",
        "address":        "500 Broadway, Nashville, TN 37203",
        "lat":            36.1627,
        "lng":            -86.7816,
        "food_type":      "Assorted produce, bread, dairy",
        "quantity_meals": 80,
        "dietary_flags":  json.dumps({"vegan": True, "halal": False, "kosher": False, "gluten_free": True}),
        "available_from": now_minus(1),
        "expires_at":     now_plus(6),
        "contact_phone":  "615-555-0202",
        "contact_email":  "surplus@musiccityfresh.com",
    },
    {
        "supplier_name":  "Lone Star Kitchen",
        "supplier_type":  "restaurant",
        "address":        "200 Congress Ave, Austin, TX 78701",
        "lat":            30.2672,
        "lng":            -97.7431,
        "food_type":      "Tex-Mex: enchiladas, rice, beans",
        "quantity_meals": 60,
        "dietary_flags":  json.dumps({"vegan": False, "halal": True, "kosher": False, "gluten_free": False}),
        "available_from": now_minus(0.25),
        "expires_at":     now_plus(3),
        "contact_phone":  "512-555-0303",
        "contact_email":  "chef@lonestarkitchen.com",
    },
    {
        "supplier_name":  "Bayou Harvest Farm",
        "supplier_type":  "farm",
        "address":        "4800 Old Spanish Trail, Houston, TX 77021",
        "lat":            29.7604,
        "lng":            -95.3698,
        "food_type":      "Fresh vegetables, eggs, fruit",
        "quantity_meals": 200,
        "dietary_flags":  json.dumps({"vegan": True, "halal": True, "kosher": True, "gluten_free": True}),
        "available_from": now_minus(2),
        "expires_at":     now_plus(24),
        "contact_phone":  "713-555-0404",
        "contact_email":  "market@bayouharvest.com",
    },
    {
        "supplier_name":  "Deep Ellum Diner",
        "supplier_type":  "restaurant",
        "address":        "2820 Elm St, Dallas, TX 75226",
        "lat":            32.7767,
        "lng":            -96.7970,
        "food_type":      "American comfort food: soups, sandwiches",
        "quantity_meals": 45,
        "dietary_flags":  json.dumps({"vegan": False, "halal": False, "kosher": False, "gluten_free": True}),
        "available_from": now_minus(0.5),
        "expires_at":     now_plus(2),   # expires soonest — highest perishability
        "contact_phone":  "214-555-0505",
        "contact_email":  "manager@deepellumdiner.com",
    },
]

DEMAND_LISTINGS = [
    {
        "org_name":             "Mid-South Food Bank",
        "org_type":             "food_bank",
        "address":              "239 S. Pauline St, Memphis, TN 38104",
        "lat":                  35.1450,   # Memphis — very close to Blues City Catering
        "lng":                  -90.0510,
        "meals_needed":         100,
        "dietary_requirements": json.dumps({"vegan": False, "halal": False, "kosher": False, "gluten_free": False}),
        "needed_by":            now_plus(5),
        "contact_phone":        "901-555-1001",
        "contact_email":        "dispatch@midsouthfoodbank.org",
    },
    {
        "org_name":             "Dallas Hope Shelter",
        "org_type":             "shelter",
        "address":              "1818 Corsicana St, Dallas, TX 75215",
        "lat":                  32.7700,   # Dallas — close to Deep Ellum Diner + Bayou farm nearby
        "lng":                  -96.7900,
        "meals_needed":         50,
        "dietary_requirements": json.dumps({"vegan": False, "halal": False, "kosher": False, "gluten_free": True}),
        "needed_by":            now_plus(3),
        "contact_phone":        "214-555-1002",
        "contact_email":        "intake@dallashope.org",
    },
    {
        "org_name":             "Austin Community Soup Kitchen",
        "org_type":             "soup_kitchen",
        "address":              "501 West Ave, Austin, TX 78701",
        "lat":                  30.2700,   # Austin — very close to Lone Star Kitchen
        "lng":                  -97.7500,
        "meals_needed":         70,
        "dietary_requirements": json.dumps({"vegan": False, "halal": True, "kosher": False, "gluten_free": False}),
        "needed_by":            now_plus(4),
        "contact_phone":        "512-555-1003",
        "contact_email":        "kitchen@austinsoupkitchen.org",
    },
]


# ─── Test Runner ───────────────────────────────────────────────────────────────

def run_test():
    """Execute the full end-to-end test sequence."""
    print("=" * 65)
    print("  HELIOS AI DISPATCH — End-to-End Test")
    print("=" * 65)

    # ── Step 1: Create fresh test database ────────────────────────────
    tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp_file.name
    tmp_file.close()
    print(f"\n[1] Test database: {db_path}")

    try:
        init_db(db_path)
        print("    Tables created OK")

        # ── Step 2: Insert supply listings ────────────────────────────
        print("\n[2] Inserting 5 supply listings...")
        supply_ids = []
        for s in SUPPLY_LISTINGS:
            sid = insert_supply(db_path, s)
            supply_ids.append(sid)
            print(f"    + Supply #{sid}: {s['supplier_name']} ({s['quantity_meals']} meals, "
                  f"expires in {s['expires_at'][-8:]})")

        # ── Step 3: Insert demand listings ────────────────────────────
        print("\n[3] Inserting 3 demand listings...")
        demand_ids = []
        for d in DEMAND_LISTINGS:
            did = insert_demand(db_path, d)
            demand_ids.append(did)
            print(f"    + Demand #{did}: {d['org_name']} ({d['meals_needed']} meals needed)")

        # ── Verify data loaded ─────────────────────────────────────────
        supply_in_db = get_available_supply(db_path)
        demand_in_db = get_open_demand(db_path)
        assert len(supply_in_db) == 5, f"Expected 5 supply rows, got {len(supply_in_db)}"
        assert len(demand_in_db) == 3, f"Expected 3 demand rows, got {len(demand_in_db)}"
        print(f"\n    Verified: {len(supply_in_db)} supply + {len(demand_in_db)} demand in DB")

        # ── Step 4: Sanity-check haversine distance ────────────────────
        print("\n[4] Haversine sanity check...")
        memphis_to_nashville = haversine_km(35.1495, -90.0490, 36.1627, -86.7816)
        print(f"    Memphis → Nashville: {memphis_to_nashville:.1f} km  (expected ~320 km)")
        assert 300 <= memphis_to_nashville <= 340, \
            f"Haversine result {memphis_to_nashville:.1f} km is outside expected range 300–340 km"
        print("    Distance calculation: OK")

        # ── Step 5: Run matching engine ────────────────────────────────
        print("\n[5] Running matching engine (top 3 per demand)...")
        matches = run_matching(db_path, top_n=3, write_to_db=True)
        print(f"    Engine returned {len(matches)} match records")

        # ── Step 6: Print detailed results ────────────────────────────
        print("\n[6] Match Results:")
        print("-" * 65)
        for i, m in enumerate(matches, 1):
            print(f"  Match {i:02d}:")
            print(f"    Supply  : {m['supplier_name']} ({m['food_type']})")
            print(f"    Demand  : {m['org_name']}")
            print(f"    Distance: {m['distance_km']:.1f} km")
            print(f"    Score   : {m['score']:.4f}")
            sub = m["sub_scores"]
            print(f"    Sub-scores → dist={sub['distance']:.3f}  "
                  f"perish={sub['perishability']:.3f}  "
                  f"vol={sub['volume']:.3f}  "
                  f"diet={sub['dietary']:.3f}")
            print()

        # ── Step 7: Verify matches persisted in DB ─────────────────────
        print("[7] Verifying matches persisted to database...")
        total_persisted = 0
        for did in demand_ids:
            rows = get_matches_for_demand(db_path, did)
            total_persisted += len(rows)
            print(f"    Demand #{did}: {len(rows)} match(es) stored")

        assert total_persisted >= 3, \
            f"Expected at least 3 persisted matches, found {total_persisted}"
        print(f"\n    Total persisted matches: {total_persisted}")

        # ── Step 8: Assert minimum match threshold ─────────────────────
        print("\n[8] Asserting minimum match count...")
        assert len(matches) >= 3, \
            f"FAIL: Expected >= 3 matches, got {len(matches)}"
        print(f"    PASS: {len(matches)} matches >= 3 required")

        # ── Step 9: Assert scores are valid (0–1 range) ────────────────
        print("\n[9] Validating score range (all scores must be 0.0–1.0)...")
        for m in matches:
            assert 0.0 <= m["score"] <= 1.0, \
                f"Score out of range: {m['score']} for {m['supplier_name']} → {m['org_name']}"
        print(f"    PASS: all {len(matches)} scores in valid range")

        # ── FINAL RESULT ───────────────────────────────────────────────
        print("\n" + "=" * 65)
        print("  RESULT: PASS")
        print(f"  {len(matches)} matches produced across {len(demand_ids)} demand listings")
        print(f"  {total_persisted} matches persisted to SQLite")
        print("=" * 65)
        return True

    except AssertionError as e:
        print("\n" + "=" * 65)
        print(f"  RESULT: FAIL")
        print(f"  Reason: {e}")
        print("=" * 65)
        return False

    except Exception as e:
        print("\n" + "=" * 65)
        print(f"  RESULT: ERROR")
        print(f"  Exception: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 65)
        return False

    finally:
        # ── Cleanup test database ──────────────────────────────────────
        try:
            os.unlink(db_path)
            print(f"\n[cleanup] Test database removed: {db_path}")
        except OSError:
            pass


if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
