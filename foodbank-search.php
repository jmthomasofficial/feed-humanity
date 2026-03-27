<?php
/**
 * Food Bank Search — Feed Humanity
 *
 * Server-side food bank + grocery store search.
 * Uses Google Maps API (if configured) or free Overpass/Nominatim fallback.
 *
 * POST body: {"zip": "38320"}
 * Returns: {"city":"Camden","state":"Tennessee","lat":36.05,"lng":-88.1,"food_banks":[...],"grocery_stores":[...]}
 */

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }
if ($_SERVER['REQUEST_METHOD'] !== 'POST') { http_response_code(405); echo json_encode(['error' => 'POST only']); exit; }

$input = json_decode(file_get_contents('php://input'), true);
$zip = trim($input['zip'] ?? '');
if (!$zip || !preg_match('/^\d{5}$/', $zip)) {
    http_response_code(400);
    echo json_encode(['error' => 'Valid 5-digit ZIP code required']);
    exit;
}

// Load config (optional — fallback works without it)
$configFile = __DIR__ . '/api-config.php';
$mapsKey = '';
if (file_exists($configFile)) {
    require_once $configFile;
    $mapsKey = (defined('MAPS_API_KEY') && MAPS_API_KEY !== '') ? MAPS_API_KEY : '';
}

$radius = 40000; // 25 miles in meters

function httpGet($url, $timeout = 10) {
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => $timeout,
        CURLOPT_USERAGENT => 'FeedHumanity/1.0',
        CURLOPT_FOLLOWLOCATION => true,
    ]);
    $r = curl_exec($ch);
    curl_close($ch);
    return $r ? json_decode($r, true) : null;
}

$lat = null; $lng = null; $city = null; $state = null;
$foodBanks = []; $groceryStores = [];

if ($mapsKey) {
    // ── Google Geocoding ──────────────────────────────────────────────────
    $geoUrl = "https://maps.googleapis.com/maps/api/geocode/json?address=" . urlencode($zip) . "&key={$mapsKey}";
    $geo = httpGet($geoUrl, 10);

    if ($geo && $geo['status'] === 'OK' && !empty($geo['results'])) {
        $loc = $geo['results'][0];
        $lat = $loc['geometry']['location']['lat'];
        $lng = $loc['geometry']['location']['lng'];
        // Extract city and state
        foreach ($loc['address_components'] as $comp) {
            if (in_array('locality', $comp['types'])) $city = $comp['long_name'];
            if (in_array('sublocality', $comp['types']) && !$city) $city = $comp['long_name'];
            if (in_array('administrative_area_level_1', $comp['types'])) $state = $comp['long_name'];
        }
        if (!$city) $city = $zip;
    }

    if ($lat !== null) {
        // ── Google Places: Food Banks ────────────────────────────────────
        $keywords = ['food bank', 'food pantry', 'soup kitchen', 'food assistance', 'community kitchen', 'food distribution'];
        $allPlaces = [];
        $seenIds = [];

        foreach ($keywords as $kw) {
            $url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={$lat},{$lng}&radius={$radius}&keyword=" . urlencode($kw) . "&key={$mapsKey}";
            $data = httpGet($url, 10);
            if ($data && !empty($data['results'])) {
                foreach ($data['results'] as $p) {
                    if (!in_array($p['place_id'], $seenIds)) {
                        $seenIds[] = $p['place_id'];
                        $allPlaces[] = $p;
                    }
                }
            }
        }

        $foodBanks = array_slice(array_map(function($p) {
            return [
                'name' => $p['name'],
                'lat' => $p['geometry']['location']['lat'],
                'lng' => $p['geometry']['location']['lng'],
                'address' => $p['vicinity'] ?? '',
                'rating' => $p['rating'] ?? null,
                'open_now' => $p['opening_hours']['open_now'] ?? null,
                'source' => 'google_places',
            ];
        }, $allPlaces), 0, 20);

        // ── Google Places: Grocery Stores ────────────────────────────────
        $grocUrl = "https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={$lat},{$lng}&radius={$radius}&type=grocery_or_supermarket&key={$mapsKey}";
        $grocData = httpGet($grocUrl, 10);
        $discUrl = "https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={$lat},{$lng}&radius={$radius}&keyword=" . urlencode('dollar general walmart dollar tree food lion aldi kroger') . "&key={$mapsKey}";
        $discData = httpGet($discUrl, 10);

        $grocRaw = array_merge($grocData['results'] ?? [], $discData['results'] ?? []);
        $seenGrocIds = [];
        foreach ($grocRaw as $p) {
            if (!in_array($p['place_id'], $seenGrocIds) && count($groceryStores) < 6) {
                $seenGrocIds[] = $p['place_id'];
                $groceryStores[] = ['name' => $p['name'], 'address' => $p['vicinity'] ?? ''];
            }
        }
    }

} else {
    // ── Nominatim fallback: geocoding ─────────────────────────────────────
    $nomUrl = "https://nominatim.openstreetmap.org/search?postalcode=" . urlencode($zip) . "&country=us&format=json&limit=1";
    $nomData = httpGet($nomUrl, 10);

    if ($nomData && !empty($nomData)) {
        $lat = (float)$nomData[0]['lat'];
        $lng = (float)$nomData[0]['lon'];
        $displayName = $nomData[0]['display_name'] ?? '';
        $parts = array_map('trim', explode(',', $displayName));
        $city = $parts[0] ?? $zip;
        $state = $parts[2] ?? '';
    }

    if ($lat !== null) {
        // ── Overpass fallback: food banks ────────────────────────────────
        $overpassQ = '[out:json][timeout:25];(node["amenity"="food_bank"](around:' . $radius . ',' . $lat . ',' . $lng . ');node["amenity"="social_facility"]["social_facility"~"food_bank|food_pantry|soup_kitchen"](around:' . $radius . ',' . $lat . ',' . $lng . ');node["social_facility:for"~"hungry|underprivileged"](around:' . $radius . ',' . $lat . ',' . $lng . ');way["amenity"="food_bank"](around:' . $radius . ',' . $lat . ',' . $lng . '););out center 30;';

        $ch = curl_init('https://overpass-api.de/api/interpreter');
        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => 'data=' . urlencode($overpassQ),
            CURLOPT_HTTPHEADER => ['Content-Type: application/x-www-form-urlencoded'],
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => 25,
            CURLOPT_USERAGENT => 'FeedHumanity/1.0',
        ]);
        $ovResponse = curl_exec($ch);
        curl_close($ch);
        $ovData = $ovResponse ? json_decode($ovResponse, true) : null;

        foreach (($ovData['elements'] ?? []) as $el) {
            $elLat = $el['lat'] ?? $el['center']['lat'] ?? null;
            $elLng = $el['lon'] ?? $el['center']['lon'] ?? null;
            if ($elLat && $elLng) {
                $foodBanks[] = [
                    'name' => $el['tags']['name'] ?? 'Food Bank',
                    'lat' => $elLat, 'lng' => $elLng,
                    'address' => trim(($el['tags']['addr:street'] ?? '') . ' ' . ($el['tags']['addr:city'] ?? '')),
                    'source' => 'overpass',
                ];
            }
        }

        // ── Nominatim text search backup ─────────────────────────────────
        if (count($foodBanks) < 5 && $city) {
            foreach (['food pantry', 'food bank', 'soup kitchen', 'community food'] as $term) {
                $nimUrl = "https://nominatim.openstreetmap.org/search?q=" . urlencode($term . ' ' . $city . ' ' . $state) . "&format=json&limit=5&countrycodes=us";
                $nimData = httpGet($nimUrl, 8);
                foreach (($nimData ?? []) as $item) {
                    $iLat = (float)$item['lat']; $iLng = (float)$item['lon'];
                    $isDupe = false;
                    foreach ($foodBanks as $fb) {
                        if (abs($fb['lat'] - $iLat) < 0.002 && abs($fb['lng'] - $iLng) < 0.002) { $isDupe = true; break; }
                    }
                    if (!$isDupe) {
                        $nameParts = explode(',', $item['display_name'] ?? '');
                        $foodBanks[] = [
                            'name' => trim($nameParts[0]),
                            'lat' => $iLat, 'lng' => $iLng,
                            'address' => trim(implode(',', array_slice($nameParts, 1, 2))),
                            'source' => 'nominatim',
                        ];
                    }
                }
            }
        }
    }
}

if ($lat === null) {
    http_response_code(422);
    echo json_encode(['error' => 'Could not locate ZIP code ' . $zip]);
    exit;
}

echo json_encode([
    'city' => $city ?? $zip,
    'state' => $state ?? '',
    'lat' => $lat,
    'lng' => $lng,
    'food_banks' => $foodBanks,
    'grocery_stores' => $groceryStores,
    'zip_code' => $zip,
]);
