<?php
/**
 * Feed Humanity — API Configuration
 *
 * Copy this file to api-config.php and fill in your keys.
 * api-config.php is gitignored and never committed to the repo.
 *
 * Getting your keys:
 *   Gemini: https://aistudio.google.com/app/apikey  (free, 30 seconds)
 *   Maps:   https://console.cloud.google.com/apis/credentials  (optional)
 */

// Required: Gemini API key for AI plan generation
// Get it free at: https://aistudio.google.com/app/apikey
define('GEMINI_API_KEY', 'your_gemini_key_here');

// Optional: Google Maps API key for real-time food bank search
// Without this, the free Overpass/OpenStreetMap fallback is used instead.
// If you add one, enable: Geocoding API + Places API (Legacy) + Maps JavaScript API
define('MAPS_API_KEY', '');

// Free AI plans per IP address per day (applies to server-hosted key only)
// Users who add their own key in Settings get unlimited plans.
define('RATE_LIMIT_PER_DAY', 5);
