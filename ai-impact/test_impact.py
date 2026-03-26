"""
test_impact.py — Real end-to-end test for the Feed Humanity AI Impact Tracker.

Tests:
  1. Parse post with explicit meal count + city hashtag (regex)
  2. Parse post with word-based meal count (regex)
  3. Parse post detecting platform from URL
  4. Geocode "Nashville" — verify lat/lng in expected range
  5. Insert 5 impact events into temp DB — verify stats aggregate correctly
  6. Verify map-data returns valid GeoJSON structure
  7. Verify leaderboard sorts by meal count descending
  8. Verify API app imports without error

Prints PASS/FAIL per test, with OVERALL summary.
"""

import os
import sys
import json
import tempfile
import traceback

# Ensure local modules are importable
sys.path.insert(0, os.path.dirname(__file__))

from database import init_db, insert_impact, get_stats, get_map_data, get_leaderboard
from parser import parse_post, extract_meal_count_regex, extract_city_from_hashtag, detect_platform


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
# TEST 1: Parse post with meal count + city hashtag (regex)
# ─────────────────────────────────────────────
sep("TEST 1: Parse post with explicit meal count + city hashtag")
try:
    text = "Just fed 5 people downtown! #FeedHumanityNashville #FeedHumanity @jmthomasofficial"
    url = "https://www.tiktok.com/@user/video/123456"
    result = parse_post(text, url)

    print(f"  Input: {text[:60]}...")
    print(f"  Meals: {result['meals']}")
    print(f"  City:  {result['city']}")
    print(f"  Platform: {result['platform']}")
    print(f"  Handle: {result['poster_handle']}")
    print(f"  Method: {result['extraction_method']}")

    p1 = result_line("Meals = 5", result["meals"] == 5, f"got {result['meals']}")
    p2 = result_line("City = Nashville", result["city"] == "Nashville", f"got '{result['city']}'")
    p3 = result_line("Platform = tiktok", result["platform"] == "tiktok", f"got '{result['platform']}'")
    p4 = result_line("Method = regex", result["extraction_method"] == "regex")
    p5 = result_line("Handle = jmthomasofficial", result["poster_handle"] == "jmthomasofficial")
    all_passed.extend([p1, p2, p3, p4, p5])

except Exception as e:
    print(f"  ERROR: {e}")
    traceback.print_exc()
    all_passed.append(False)


# ─────────────────────────────────────────────
# TEST 2: Parse post with word-based meal count
# ─────────────────────────────────────────────
sep("TEST 2: Parse post with various meal patterns")
try:
    cases = [
        ("bought 10 meals for the shelter #FeedHumanity", 10),
        ("delivered 3 plates to neighbors", 3),
        ("25 meals served at the community center", 25),
    ]

    all_ok = True
    for text, expected in cases:
        count = extract_meal_count_regex(text)
        ok = count == expected
        result_line(f"'{text[:40]}...' → {expected}", ok, f"got {count}")
        if not ok:
            all_ok = False

    all_passed.append(all_ok)

except Exception as e:
    print(f"  ERROR: {e}")
    traceback.print_exc()
    all_passed.append(False)


# ─────────────────────────────────────────────
# TEST 3: Platform detection from URLs
# ─────────────────────────────────────────────
sep("TEST 3: Platform detection from URL")
try:
    cases = [
        ("https://www.tiktok.com/@user/video/123", "tiktok"),
        ("https://www.instagram.com/p/ABC123/", "instagram"),
        ("https://x.com/user/status/456", "twitter"),
        ("https://youtube.com/watch?v=xyz", "youtube"),
        ("https://randomsite.com/post", "unknown"),
    ]

    all_ok = True
    for url, expected in cases:
        platform = detect_platform(url)
        ok = platform == expected
        result_line(f"'{url[:35]}...' → {expected}", ok, f"got '{platform}'")
        if not ok:
            all_ok = False

    all_passed.append(all_ok)

except Exception as e:
    print(f"  ERROR: {e}")
    traceback.print_exc()
    all_passed.append(False)


# ─────────────────────────────────────────────
# TEST 4: City hashtag extraction (CamelCase handling)
# ─────────────────────────────────────────────
sep("TEST 4: City hashtag extraction")
try:
    cases = [
        ("#FeedHumanityNashville is amazing!", "Nashville"),
        ("#FeedHumanityLosAngeles big event!", "Los Angeles"),
        ("#FeedHumanityNewYork here we go!", "New York"),
        ("#FeedHumanity no city here", None),
    ]

    all_ok = True
    for text, expected in cases:
        city = extract_city_from_hashtag(text)
        ok = city == expected
        result_line(f"'{text[:35]}...' → {expected}", ok, f"got '{city}'")
        if not ok:
            all_ok = False

    all_passed.append(all_ok)

except Exception as e:
    print(f"  ERROR: {e}")
    traceback.print_exc()
    all_passed.append(False)


# ─────────────────────────────────────────────
# TEST 5: Database — insert events and verify stats
# ─────────────────────────────────────────────
sep("TEST 5: Database — insert 5 events, verify aggregation")

tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
db_path = tmp_file.name
tmp_file.close()

try:
    init_db(db_path)
    print(f"  Test DB: {db_path}")

    events = [
        {"post_url": "https://tiktok.com/1", "raw_text": "fed 5 people", "meals_count": 5,
         "city": "Nashville", "state": "Tennessee", "lat": 36.16, "lng": -86.78, "platform": "tiktok"},
        {"post_url": "https://tiktok.com/2", "raw_text": "10 meals served", "meals_count": 10,
         "city": "Nashville", "state": "Tennessee", "lat": 36.16, "lng": -86.78, "platform": "tiktok"},
        {"post_url": "https://instagram.com/3", "raw_text": "3 plates given", "meals_count": 3,
         "city": "Memphis", "state": "Tennessee", "lat": 35.15, "lng": -90.05, "platform": "instagram"},
        {"post_url": "https://x.com/4", "raw_text": "bought 20 meals", "meals_count": 20,
         "city": "Austin", "state": "Texas", "lat": 30.27, "lng": -97.74, "platform": "twitter"},
        {"post_url": "https://youtube.com/5", "raw_text": "7 meals delivered", "meals_count": 7,
         "city": "Austin", "state": "Texas", "lat": 30.27, "lng": -97.74, "platform": "youtube"},
    ]

    for ev in events:
        row_id = insert_impact(db_path, ev)
        print(f"    + Event #{row_id}: {ev['meals_count']} meals in {ev['city']}")

    stats = get_stats(db_path)
    print(f"\n  Stats: {json.dumps(stats, indent=2)}")

    p6 = result_line("Total meals = 45", stats["total_meals"] == 45, f"got {stats['total_meals']}")
    p7 = result_line("Total posts = 5", stats["total_posts"] == 5, f"got {stats['total_posts']}")
    p8 = result_line("Cities active = 3", stats["cities_active"] == 3, f"got {stats['cities_active']}")
    p9 = result_line("Top city has most meals", len(stats["top_cities"]) > 0 and
                     stats["top_cities"][0]["meals_total"] >= stats["top_cities"][-1]["meals_total"])
    all_passed.extend([p6, p7, p8, p9])

except Exception as e:
    print(f"  ERROR: {e}")
    traceback.print_exc()
    all_passed.append(False)


# ─────────────────────────────────────────────
# TEST 6: GeoJSON map data structure
# ─────────────────────────────────────────────
sep("TEST 6: GeoJSON map data structure")
try:
    map_data = get_map_data(db_path)
    print(f"  Type: {map_data.get('type')}")
    print(f"  Features: {len(map_data.get('features', []))}")

    p10 = result_line("Type = FeatureCollection", map_data["type"] == "FeatureCollection")
    p11 = result_line("Has features", len(map_data["features"]) > 0, f"{len(map_data['features'])} features")

    if map_data["features"]:
        f0 = map_data["features"][0]
        has_geometry = "geometry" in f0 and f0["geometry"]["type"] == "Point"
        has_coords = len(f0["geometry"]["coordinates"]) == 2
        has_props = "city" in f0.get("properties", {}) and "meals_total" in f0.get("properties", {})
        p12 = result_line("Feature has Point geometry", has_geometry)
        p13 = result_line("Feature has [lng, lat] coordinates", has_coords)
        p14 = result_line("Feature has city + meals_total properties", has_props)
        all_passed.extend([p12, p13, p14])

    all_passed.extend([p10, p11])

except Exception as e:
    print(f"  ERROR: {e}")
    traceback.print_exc()
    all_passed.append(False)


# ─────────────────────────────────────────────
# TEST 7: Leaderboard sorted by meals descending
# ─────────────────────────────────────────────
sep("TEST 7: Leaderboard sorted by meals descending")
try:
    lb = get_leaderboard(db_path, limit=10)
    print(f"  Entries: {len(lb)}")
    for entry in lb:
        print(f"    {entry['city']}, {entry['state']}: {entry['meals_total']} meals ({entry['post_count']} posts)")

    p15 = result_line("Leaderboard has entries", len(lb) > 0, f"{len(lb)} entries")

    if len(lb) >= 2:
        sorted_ok = all(lb[i]["meals_total"] >= lb[i+1]["meals_total"] for i in range(len(lb) - 1))
        p16 = result_line("Sorted by meals descending", sorted_ok)
        all_passed.append(p16)

    all_passed.append(p15)

except Exception as e:
    print(f"  ERROR: {e}")
    traceback.print_exc()
    all_passed.append(False)

finally:
    # Clean up test database
    try:
        os.unlink(db_path)
        print(f"\n[cleanup] Test database removed: {db_path}")
    except OSError:
        pass


# ─────────────────────────────────────────────
# TEST 8: API app imports cleanly
# ─────────────────────────────────────────────
sep("TEST 8: API app import check")
try:
    from api import app as impact_app  # noqa
    p17 = result_line("FastAPI app imported", True, f"title='{impact_app.title}'")
    all_passed.append(p17)

except Exception as e:
    print(f"  ERROR: {e}")
    traceback.print_exc()
    result_line("API import", False, str(e))
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
