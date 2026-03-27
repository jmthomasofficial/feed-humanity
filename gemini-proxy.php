<?php
/**
 * Gemini Proxy — Feed Humanity
 *
 * Server-side Gemini API relay with per-IP rate limiting.
 * Eliminates the need for visitors to create their own API keys.
 *
 * Rate limit: RATE_LIMIT_PER_DAY requests per IP per day (set in api-config.php)
 * Rate limit data stored in rate-limit.json (auto-created, gitignored)
 */

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }
if ($_SERVER['REQUEST_METHOD'] !== 'POST') { http_response_code(405); echo json_encode(['error' => 'POST only']); exit; }

// Load config
$configFile = __DIR__ . '/api-config.php';
if (!file_exists($configFile)) {
    http_response_code(503);
    echo json_encode(['error' => 'server_config', 'message' => 'Server not configured. Add your own API key in ⚙️ Settings to use this feature.']);
    exit;
}
require_once $configFile;

if (!defined('GEMINI_API_KEY') || GEMINI_API_KEY === 'your_gemini_key_here' || empty(GEMINI_API_KEY)) {
    http_response_code(503);
    echo json_encode(['error' => 'server_config', 'message' => 'Server AI key not configured. Add your own free Gemini key in ⚙️ Settings.']);
    exit;
}

// ── Rate limiting ──────────────────────────────────────────────────────────
$rateLimitFile = __DIR__ . '/rate-limit.json';
$today = date('Y-m-d');
$ipHash = md5($_SERVER['REMOTE_ADDR'] ?? 'unknown'); // Hash for privacy
$limit = defined('RATE_LIMIT_PER_DAY') ? (int)RATE_LIMIT_PER_DAY : 5;

$rateLimitData = [];
if (file_exists($rateLimitFile)) {
    $raw = file_get_contents($rateLimitFile);
    $rateLimitData = json_decode($raw, true) ?: [];
}

// Clean old dates
foreach (array_keys($rateLimitData) as $date) {
    if ($date !== $today) unset($rateLimitData[$date]);
}

$todayData = $rateLimitData[$today] ?? [];
$currentCount = $todayData[$ipHash] ?? 0;

if ($currentCount >= $limit) {
    http_response_code(429);
    echo json_encode([
        'error' => 'rate_limit',
        'message' => "You've used your {$limit} free daily plans. Add your own free Gemini key in ⚙️ Settings for unlimited access — it takes 30 seconds."
    ]);
    exit;
}

// Increment count
$todayData[$ipHash] = $currentCount + 1;
$rateLimitData[$today] = $todayData;
file_put_contents($rateLimitFile, json_encode($rateLimitData));

// ── Parse request ──────────────────────────────────────────────────────────
$input = json_decode(file_get_contents('php://input'), true);
if (!$input || empty($input['system']) || empty($input['user'])) {
    http_response_code(400);
    echo json_encode(['error' => 'Missing system or user fields']);
    exit;
}

// ── Call Gemini API ────────────────────────────────────────────────────────
$model = 'gemini-2.0-flash';
$url = "https://generativelanguage.googleapis.com/v1beta/models/{$model}:generateContent?key=" . GEMINI_API_KEY;

$payload = json_encode([
    'systemInstruction' => ['parts' => [['text' => $input['system']]]],
    'contents' => [['role' => 'user', 'parts' => [['text' => $input['user']]]]],
    'generationConfig' => ['temperature' => 0.7]
]);

$ch = curl_init($url);
curl_setopt_array($ch, [
    CURLOPT_POST => true,
    CURLOPT_POSTFIELDS => $payload,
    CURLOPT_HTTPHEADER => ['Content-Type: application/json'],
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT => 90,
]);
$response = curl_exec($ch);
$httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$curlError = curl_error($ch);
curl_close($ch);

if ($curlError) {
    http_response_code(502);
    echo json_encode(['error' => "Network error: {$curlError}"]);
    exit;
}

http_response_code($httpCode);
echo $response;
