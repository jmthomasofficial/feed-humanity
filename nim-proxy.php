<?php
/**
 * NIM BYOK Proxy — Feed Humanity
 * 
 * Relays NVIDIA NIM API requests from the browser to bypass CORS.
 * The user's API key passes through — never stored.
 * Upload this file to your web hosting alongside index.html.
 */

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, OPTIONS');
header('Access-Control-Allow-Headers: Authorization, Content-Type');

// Handle preflight
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }
if ($_SERVER['REQUEST_METHOD'] !== 'POST') { http_response_code(405); echo json_encode(['error' => 'POST only']); exit; }

$auth = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
if (!$auth) { http_response_code(400); echo json_encode(['error' => 'Missing Authorization header']); exit; }

$body = file_get_contents('php://input');

$ch = curl_init('https://integrate.api.nvidia.com/v1/chat/completions');
curl_setopt_array($ch, [
    CURLOPT_POST => true,
    CURLOPT_POSTFIELDS => $body,
    CURLOPT_HTTPHEADER => ["Authorization: $auth", 'Content-Type: application/json'],
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT => 60,
]);
$response = curl_exec($ch);
$httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$error = curl_error($ch);
curl_close($ch);

if ($error) { http_response_code(502); echo json_encode(['error' => "Upstream error: $error"]); exit; }

http_response_code($httpCode);
echo $response;
