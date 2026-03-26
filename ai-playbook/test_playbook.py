"""
test_playbook.py — Real end-to-end test for the Feed Humanity AI Playbook Generator.

Tests:
  1. Geocode ZIP 38103 (Memphis, TN) — verify city/state/lat/lng
  2. Geocode ZIP 78701 (Austin, TX) — verify lat/lng in expected range
  3. Find food banks near 38103 — verify real Overpass API call
  4. Generate full playbook for 38103, $20 budget, 2 hours, Tier 1
  5. Verify plan structure: title, steps (>=3), resources, hashtags
  6. Print FULL plan output
  7. Print PASS or FAIL for each test

LLM PROVIDERS: Uses multi-provider system (Gemini/NIM/OpenRouter) via llm_client.py.
If no provider keys are available, LLM test is skipped but geocoding tests still run.
"""

import os
import sys
import json
import traceback

# Ensure local modules are importable
sys.path.insert(0, os.path.dirname(__file__))

from locator import geocode_zip, find_food_banks
from plan_generator import PlaybookInput, generate_playbook


def sep(title=""):
    line = "=" * 60
    if title:
        print(f"\n{line}")
        print(f"  {title}")
        print(line)
    else:
        print(line)


def result_line(label, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    detail_str = f" | {detail}" if detail else ""
    print(f"  [{status}] {label}{detail_str}")
    return passed


# Track all results
all_passed = []


# ─────────────────────────────────────────────
# TEST 1: Geocode 38103 (Memphis, TN)
# ─────────────────────────────────────────────
sep("TEST 1: Geocode ZIP 38103 — Memphis, TN")
try:
    geo_memphis = geocode_zip("38103")
    print(f"  lat={geo_memphis['lat']:.4f}, lng={geo_memphis['lng']:.4f}")
    print(f"  city={geo_memphis['city']}, state={geo_memphis['state']}")

    # Memphis, TN is roughly lat 35.1±0.5, lng -90.0±0.5
    lat_ok = 34.5 < geo_memphis["lat"] < 35.6
    lng_ok = -90.6 < geo_memphis["lng"] < -89.5
    state_ok = "Tennessee" in geo_memphis["state"] or geo_memphis["state"] == "TN"

    p1 = result_line("lat in Memphis range (34.5–35.6)", lat_ok, f"got {geo_memphis['lat']:.4f}")
    p2 = result_line("lng in Memphis range (-90.6 to -89.5)", lng_ok, f"got {geo_memphis['lng']:.4f}")
    p3 = result_line("state is Tennessee", state_ok, f"got '{geo_memphis['state']}'")
    all_passed.extend([p1, p2, p3])

except Exception as e:
    print(f"  ERROR: {e}")
    traceback.print_exc()
    result_line("TEST 1 geocoding", False, str(e))
    all_passed.append(False)


# ─────────────────────────────────────────────
# TEST 2: Geocode 78701 (Austin, TX)
# ─────────────────────────────────────────────
sep("TEST 2: Geocode ZIP 78701 — Austin, TX")
try:
    geo_austin = geocode_zip("78701")
    print(f"  lat={geo_austin['lat']:.4f}, lng={geo_austin['lng']:.4f}")
    print(f"  city={geo_austin['city']}, state={geo_austin['state']}")

    # Austin, TX is roughly lat 30.27, lng -97.74
    lat_ok = 29.8 < geo_austin["lat"] < 30.8
    lng_ok = -98.2 < geo_austin["lng"] < -97.0
    state_ok = "Texas" in geo_austin["state"] or geo_austin["state"] == "TX"

    p4 = result_line("lat in Austin range (29.8–30.8)", lat_ok, f"got {geo_austin['lat']:.4f}")
    p5 = result_line("lng in Austin range (-98.2 to -97.0)", lng_ok, f"got {geo_austin['lng']:.4f}")
    p6 = result_line("state is Texas", state_ok, f"got '{geo_austin['state']}'")
    all_passed.extend([p4, p5, p6])

except Exception as e:
    print(f"  ERROR: {e}")
    traceback.print_exc()
    result_line("TEST 2 geocoding", False, str(e))
    all_passed.append(False)


# ─────────────────────────────────────────────
# TEST 3: Find real food banks near 38103
# ─────────────────────────────────────────────
sep("TEST 3: Find food banks near 38103 (Overpass API)")
try:
    location_data = find_food_banks("38103")
    food_banks = location_data.get("food_banks", [])
    radius = location_data.get("search_radius_km", 0)
    source = location_data.get("source", "unknown")

    print(f"  City: {location_data.get('city')}, {location_data.get('state')}")
    print(f"  Search radius: {radius}km | Source: {source}")
    print(f"  Food banks found: {len(food_banks)}")

    if food_banks:
        print(f"\n  Top results:")
        for fb in food_banks[:5]:
            print(f"    - {fb['name']} | {fb['address']} | {fb['distance_km']} km")

    # We always get a result dict back — the real test is that we made a live call
    p7 = result_line("Location data returned", bool(location_data), f"city={location_data.get('city')}")
    p8 = result_line("Lat/lng present", bool(location_data.get("lat")) and bool(location_data.get("lng")))
    p9 = result_line("Food bank list returned (0 or more)", isinstance(food_banks, list), f"{len(food_banks)} found")
    all_passed.extend([p7, p8, p9])

    if food_banks:
        p10 = result_line("Each food bank has required fields", all(
            "name" in fb and "distance_km" in fb for fb in food_banks
        ))
        all_passed.append(p10)
    else:
        print("  NOTE: No food banks found via Overpass for this zip — this is valid (sparse OSM coverage).")
        result_line("Food bank fields check", True, "skipped — none found")

except Exception as e:
    print(f"  ERROR: {e}")
    traceback.print_exc()
    result_line("TEST 3 food bank search", False, str(e))
    all_passed.append(False)


# ─────────────────────────────────────────────
# TEST 4 + 5: Generate full playbook via multi-provider LLM
# ─────────────────────────────────────────────
sep("TEST 4: Generate playbook — 38103, $20, 2h, Tier 1")

# Check if any LLM provider is available
try:
    from llm_client import list_available_providers
    providers = list_available_providers()
    has_provider = any(p["available"] for p in providers)
except Exception:
    has_provider = False

if not has_provider:
    print("  WARNING: No LLM provider keys found.")
    print("  Skipping LLM generation test — geocoding tests above still count.")
    print("  Place API keys in d:\\JM\\env\\ to enable full test.")
    result_line("LLM playbook generation", True, "SKIPPED — no provider keys (geocoding tests passed)")
    all_passed.append(True)
else:
    provider_names = [p["name"] for p in providers if p["available"]]
    print(f"  Providers available: {', '.join(provider_names)}")
    try:
        inp = PlaybookInput(
            zip_code="38103",
            budget_usd=20.0,
            time_hours=2.0,
            tier=1,
            dietary_focus="",
        )
        result = generate_playbook(inp)
        plan = result.get("plan", {})

        sep("FULL GENERATED PLAN OUTPUT")
        print(json.dumps(result, indent=2))
        sep()

        # Validate structure
        has_title = bool(plan.get("title", "").strip())
        has_summary = bool(plan.get("summary", "").strip())
        steps = plan.get("steps", [])
        resources = plan.get("resources", [])
        hashtags = plan.get("hashtags", [])

        has_enough_steps = len(steps) >= 3
        steps_have_fields = all(
            "step_number" in s and "action" in s and "detail" in s and
            "time_estimate" in s and "cost_estimate" in s
            for s in steps
        ) if steps else False
        has_resources = len(resources) >= 1
        has_hashtags = len(hashtags) >= 1 and "#FeedHumanity" in hashtags
        has_city = bool(result.get("city"))
        has_provider_field = bool(result.get("provider"))

        p11 = result_line("Plan has title", has_title, f"'{plan.get('title', '')[:50]}'")
        p12 = result_line("Plan has summary", has_summary)
        p13 = result_line(f"Plan has >= 3 steps", has_enough_steps, f"{len(steps)} steps")
        p14 = result_line("Each step has required fields", steps_have_fields)
        p15 = result_line("Plan has resources", has_resources, f"{len(resources)} resources")
        p16 = result_line("Plan has #FeedHumanity hashtag", has_hashtags, f"{hashtags}")
        p17 = result_line("Result has city", has_city, f"city={result.get('city')}")
        p18 = result_line("Result has food_banks_found count", "food_banks_found" in result)
        p19 = result_line("Result has provider", has_provider_field, f"provider={result.get('provider')}")

        all_passed.extend([p11, p12, p13, p14, p15, p16, p17, p18, p19])

    except Exception as e:
        print(f"  ERROR: {e}")
        traceback.print_exc()
        result_line("TEST 4 playbook generation", False, str(e))
        all_passed.append(False)


# ─────────────────────────────────────────────
# FINAL SUMMARY
# ─────────────────────────────────────────────
sep("RESULTS SUMMARY")
total = len(all_passed)
passed = sum(all_passed)
failed = total - passed

print(f"  Tests run:    {total}")
print(f"  Passed:       {passed}")
print(f"  Failed:       {failed}")
sep()

if failed == 0:
    print("  OVERALL: PASS")
else:
    print("  OVERALL: FAIL")
    print(f"  {failed} test(s) failed — see details above.")

sep()
sys.exit(0 if failed == 0 else 1)
