<?php
/**
 * Impact Tracker API — Feed Humanity
 * 
 * Lightweight REST API backed by a flat JSON file.
 * No database needed — works on any PHP shared hosting.
 * 
 * Endpoints:
 *   GET  ?action=stats    — total meals, cities, posts
 *   GET  ?action=map      — lat/lng data for map markers
 *   POST ?action=track    — add a new impact entry
 */

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }

$DATA_FILE = __DIR__ . '/impact-data.json';

function loadData($file) {
    if (!file_exists($file)) return ['entries' => []];
    $data = json_decode(file_get_contents($file), true);
    return $data ?: ['entries' => []];
}

function saveData($file, $data) {
    file_put_contents($file, json_encode($data, JSON_PRETTY_PRINT), LOCK_EX);
}

$action = $_GET['action'] ?? '';

if ($_SERVER['REQUEST_METHOD'] === 'GET' && $action === 'stats') {
    $data = loadData($DATA_FILE);
    $entries = $data['entries'];
    $totalMeals = array_sum(array_column($entries, 'meals_count'));
    $cities = array_unique(array_column($entries, 'city'));
    echo json_encode([
        'total_meals' => $totalMeals,
        'total_cities' => count($cities),
        'total_posts' => count($entries),
    ]);
    exit;
}

if ($_SERVER['REQUEST_METHOD'] === 'GET' && $action === 'map') {
    $data = loadData($DATA_FILE);
    $markers = array_map(function($e) {
        return [
            'lat' => $e['lat'] ?? 0,
            'lng' => $e['lng'] ?? 0,
            'city' => $e['city'] ?? '',
            'meals' => $e['meals_count'] ?? 0,
        ];
    }, $data['entries']);
    echo json_encode($markers);
    exit;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && $action === 'track') {
    $input = json_decode(file_get_contents('php://input'), true);
    if (!$input || !isset($input['city']) || !isset($input['meals_count'])) {
        http_response_code(400);
        echo json_encode(['error' => 'Required: city, meals_count']);
        exit;
    }

    $data = loadData($DATA_FILE);
    $entry = [
        'id' => count($data['entries']) + 1,
        'meals_count' => (int)$input['meals_count'],
        'city' => $input['city'],
        'state' => $input['state'] ?? '',
        'lat' => (float)($input['lat'] ?? 0),
        'lng' => (float)($input['lng'] ?? 0),
        'platform' => $input['platform'] ?? '',
        'tracked_at' => date('c'),
    ];
    $data['entries'][] = $entry;
    saveData($DATA_FILE, $data);

    echo json_encode($entry);
    exit;
}

http_response_code(400);
echo json_encode(['error' => 'Invalid action. Use ?action=stats|map|track']);
