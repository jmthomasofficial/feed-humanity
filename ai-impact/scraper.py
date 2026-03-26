"""
scraper.py — Automated #FeedHumanity post ingestion pipeline.

Three intake modes:
  1. Manual CSV/JSON import (batch file of posts)
  2. RSS feed polling (Reddit, YouTube, Tumblr — platforms with public feeds)
  3. Webhook receiver (for future Zapier/IFTTT/n8n integrations)

All ingested posts are sent to POST /impact for NLP extraction + geocoding.

Usage:
  python scraper.py --mode csv --file posts.csv
  python scraper.py --mode rss --interval 300
  python scraper.py --mode webhook --port 8003
"""

import argparse
import csv
import json
import os
import sys
import time
import logging
from datetime import datetime, timezone
from typing import Optional

import requests

# --- Configuration ---
IMPACT_API = os.environ.get("IMPACT_API", "http://localhost:8002")
IMPACT_ENDPOINT = f"{IMPACT_API}/impact"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
log = logging.getLogger("scraper")

# Reddit RSS feeds for #FeedHumanity
RSS_FEEDS = [
    "https://www.reddit.com/search.json?q=%23FeedHumanity&sort=new&limit=25",
]

# --- Core: Submit post to Impact API ---
def submit_post(post_url: str, raw_text: str) -> Optional[dict]:
    """Submit a single post to the Impact API for extraction + geocoding."""
    payload = {"post_url": post_url, "raw_text": raw_text}
    try:
        r = requests.post(IMPACT_ENDPOINT, json=payload, timeout=30)
        if r.status_code == 201:
            data = r.json()
            log.info(f"✓ Ingested: {data.get('meals_extracted', 0)} meals from {post_url}")
            return data
        elif r.status_code == 409:
            log.debug(f"⊘ Duplicate: {post_url}")
            return None
        else:
            log.warning(f"✗ HTTP {r.status_code} for {post_url}: {r.text[:200]}")
            return None
    except requests.RequestException as e:
        log.error(f"✗ Network error submitting {post_url}: {e}")
        return None


# --- Mode 1: CSV/JSON Import ---
def import_csv(filepath: str) -> dict:
    """
    Import posts from CSV file.
    Expected columns: post_url, raw_text
    """
    if not os.path.exists(filepath):
        log.error(f"File not found: {filepath}")
        return {"imported": 0, "errors": 0}

    imported, errors = 0, 0
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = row.get("post_url", "").strip()
            text = row.get("raw_text", "").strip()
            if not url or not text:
                errors += 1
                continue
            result = submit_post(url, text)
            if result:
                imported += 1
            # Rate limit: 1 post per second (Nominatim courtesy)
            time.sleep(1.1)

    log.info(f"CSV import complete: {imported} imported, {errors} errors")
    return {"imported": imported, "errors": errors}


def import_json(filepath: str) -> dict:
    """
    Import posts from JSON file.
    Expected format: [{"post_url": "...", "raw_text": "..."}]
    """
    if not os.path.exists(filepath):
        log.error(f"File not found: {filepath}")
        return {"imported": 0, "errors": 0}

    with open(filepath, "r", encoding="utf-8") as f:
        posts = json.load(f)

    imported, errors = 0, 0
    for post in posts:
        url = post.get("post_url", "").strip()
        text = post.get("raw_text", "").strip()
        if not url or not text:
            errors += 1
            continue
        result = submit_post(url, text)
        if result:
            imported += 1
        time.sleep(1.1)

    log.info(f"JSON import complete: {imported} imported, {errors} errors")
    return {"imported": imported, "errors": errors}


# --- Mode 2: Reddit RSS Polling ---
def poll_reddit_feed(feed_url: str) -> int:
    """Poll Reddit JSON search feed for #FeedHumanity posts."""
    headers = {"User-Agent": "FeedHumanity-Scraper/1.0"}
    try:
        r = requests.get(feed_url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.error(f"Reddit feed error: {e}")
        return 0

    children = data.get("data", {}).get("children", [])
    ingested = 0
    for child in children:
        post = child.get("data", {})
        title = post.get("title", "")
        selftext = post.get("selftext", "")
        permalink = post.get("permalink", "")
        url = f"https://www.reddit.com{permalink}" if permalink else ""

        # Combine title + body for NLP extraction
        raw_text = f"{title} {selftext}".strip()
        if not raw_text or not url:
            continue

        # Only process if it mentions FeedHumanity
        if "feedhumanity" not in raw_text.lower():
            continue

        result = submit_post(url, raw_text)
        if result:
            ingested += 1
        time.sleep(1.1)

    log.info(f"Reddit poll: {ingested} new posts ingested from {len(children)} results")
    return ingested


def run_rss_loop(interval: int = 300):
    """Continuously poll RSS feeds at the given interval (seconds)."""
    log.info(f"Starting RSS polling loop (interval: {interval}s)")
    while True:
        for feed_url in RSS_FEEDS:
            poll_reddit_feed(feed_url)
        log.info(f"Sleeping {interval}s until next poll...")
        time.sleep(interval)


# --- Mode 3: Webhook Receiver ---
def run_webhook_server(port: int = 8003):
    """
    Lightweight webhook server for Zapier/IFTTT/n8n integrations.
    Accepts POST /webhook with JSON body: {"post_url": "...", "raw_text": "..."}
    """
    from fastapi import FastAPI
    import uvicorn
    from pydantic import BaseModel

    webhook_app = FastAPI(title="Feed Humanity Webhook Receiver")

    class WebhookPost(BaseModel):
        post_url: str
        raw_text: str

    @webhook_app.post("/webhook")
    async def receive_webhook(post: WebhookPost):
        result = submit_post(post.post_url, post.raw_text)
        if result:
            return {"status": "ingested", "data": result}
        return {"status": "skipped"}

    @webhook_app.get("/webhook/health")
    async def webhook_health():
        return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

    log.info(f"Starting webhook server on port {port}")
    uvicorn.run(webhook_app, host="0.0.0.0", port=port, reload=False)


# --- CLI Entry Point ---
def main():
    parser = argparse.ArgumentParser(description="Feed Humanity #FeedHumanity Post Scraper")
    parser.add_argument("--mode", choices=["csv", "json", "rss", "webhook"], required=True,
                        help="Intake mode: csv, json, rss (polling), or webhook (server)")
    parser.add_argument("--file", type=str, help="Path to CSV/JSON file (for csv/json modes)")
    parser.add_argument("--interval", type=int, default=300,
                        help="Polling interval in seconds (for rss mode, default: 300)")
    parser.add_argument("--port", type=int, default=8003,
                        help="Webhook server port (for webhook mode, default: 8003)")
    args = parser.parse_args()

    if args.mode == "csv":
        if not args.file:
            log.error("--file is required for csv mode")
            sys.exit(1)
        import_csv(args.file)

    elif args.mode == "json":
        if not args.file:
            log.error("--file is required for json mode")
            sys.exit(1)
        import_json(args.file)

    elif args.mode == "rss":
        run_rss_loop(args.interval)

    elif args.mode == "webhook":
        run_webhook_server(args.port)


if __name__ == "__main__":
    main()
