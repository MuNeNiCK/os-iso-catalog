#!/usr/bin/env python3
"""Check if image download URLs are reachable."""

import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "images.yaml"

TIMEOUT = 30
MAX_WORKERS = 5
DOMAIN_DELAY = 1.0  # seconds between requests to same domain

# Track last request time per domain
domain_last_request = defaultdict(float)


def check_url(img_id, url):
    """Check a single URL. Returns (img_id, url, status, detail)."""
    domain = urlparse(url).netloc

    # Rate limit per domain
    now = time.time()
    elapsed = now - domain_last_request[domain]
    if elapsed < DOMAIN_DELAY:
        time.sleep(DOMAIN_DELAY - elapsed)
    domain_last_request[domain] = time.time()

    try:
        # Try HEAD first
        r = requests.head(url, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code in (200, 301, 302, 307, 308):
            return (img_id, url, "OK", r.status_code)
        if r.status_code in (403, 405):
            # Some servers reject HEAD, try GET
            r = requests.get(url, timeout=TIMEOUT, stream=True, allow_redirects=True)
            r.close()
            if r.status_code == 200:
                return (img_id, url, "OK", 200)
            return (img_id, url, "WARNING", r.status_code)
        if r.status_code in (404, 410, 500, 502, 503):
            return (img_id, url, "BROKEN", r.status_code)
        return (img_id, url, "WARNING", r.status_code)
    except requests.exceptions.Timeout:
        return (img_id, url, "BROKEN", "timeout")
    except requests.exceptions.ConnectionError as e:
        return (img_id, url, "BROKEN", str(e)[:80])
    except Exception as e:
        return (img_id, url, "BROKEN", str(e)[:80])


def main():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    images = data.get("images", [])

    # Collect URLs to check
    tasks = []
    for img in images:
        img_id = img["id"]
        if "url" in img and img["url"]:
            tasks.append((img_id, img["url"]))
        if "download_page" in img and img["download_page"]:
            tasks.append((img_id, img["download_page"]))

    print(f"Checking {len(tasks)} URLs...\n")

    results = {"OK": [], "WARNING": [], "BROKEN": []}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(check_url, t[0], t[1]): t for t in tasks}
        for future in as_completed(futures):
            img_id, url, status, detail = future.result()
            results[status].append((img_id, url, detail))
            symbol = {"OK": ".", "WARNING": "?", "BROKEN": "X"}[status]
            print(symbol, end="", flush=True)

    print(f"\n\n--- Link Check Report ---")
    print(f"OK:      {len(results['OK'])}")
    print(f"WARNING: {len(results['WARNING'])}")
    print(f"BROKEN:  {len(results['BROKEN'])}")

    if results["WARNING"]:
        print(f"\nWarnings:")
        for img_id, url, detail in results["WARNING"]:
            print(f"  [{img_id}] {url} -> {detail}")

    if results["BROKEN"]:
        print(f"\nBroken links:")
        for img_id, url, detail in results["BROKEN"]:
            print(f"  [{img_id}] {url} -> {detail}")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
