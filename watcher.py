#!/usr/bin/env python3
"""
YoWorld Auction Wishlist Watcher — Cloud Edition
--------------------------------------------------
Checks yoworld.net's public auction search API for each item on your
wishlist and posts a Discord message when a NEW auction listing appears
for one of them. Designed to run as a one-shot script triggered on a
schedule by GitHub Actions (see .github/workflows/check.yml) — no
server, no always-on computer, no email account/password needed.

State (which auctions you've already been notified about) is kept in
seen_bids.json, which the GitHub Actions workflow commits back to the
repo after each run so it persists between scheduled checks.

Required: none — the Discord webhook URL is set directly below. If you
ever want to override it without editing this file (e.g. a GitHub
secret), you still can — DISCORD_WEBHOOK_URL env var takes priority if set.
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

# Your Discord webhook — messages get posted straight to that channel.
DISCORD_WEBHOOK_URL_DEFAULT = "https://discord.com/api/webhooks/1541960697565413458/H11fyv-KlKnVp6qKhCEWqQiamMSknHP7mfGeYfrJcemWgviiAkY65uANxzhy6G0rEsAO"

# ----------------------------------------------------------------------
# CONFIG — your wishlist now lives in wishlist.txt (one item per line)
# instead of here, so you can edit it without touching this file.
# ----------------------------------------------------------------------

WISHLIST_FILE = Path(__file__).parent / "wishlist.txt"


def load_wishlist() -> list:
    if not WISHLIST_FILE.exists():
        print(f"WARNING: {WISHLIST_FILE.name} not found — wishlist is empty.", file=sys.stderr)
        return []
    lines = WISHLIST_FILE.read_text(encoding="utf-8").splitlines()
    # ignore blank lines and lines starting with # (comments)
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]

SEEN_FILE = Path(__file__).parent / "seen_bids.json"

API_URL = "https://yoworld.net/api/v1/yoworld/auction/search"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://yoworld.net",
    "Referer": "https://yoworld.net/auction-house",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
}
MAX_RETRIES = 3

# ----------------------------------------------------------------------


def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_seen(seen: set) -> None:
    SEEN_FILE.write_text(json.dumps(sorted(seen)))


def search_item(item_name: str) -> list:
    payload = {
        "active_in_store": False,
        "bid_count": False,
        "sort": 0,
        "start": 0,
        "item_name": item_name,
    }

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.put(API_URL, headers=HEADERS, json=payload, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                return []
            return data.get("results", [])
        except requests.RequestException as e:
            last_error = e
            if attempt < MAX_RETRIES:
                time.sleep(3 * attempt)  # simple backoff: 3s, 6s
    raise last_error


def send_discord_alert(new_items: list) -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", DISCORD_WEBHOOK_URL_DEFAULT)

    if not webhook_url:
        print("No Discord webhook URL configured — skipping alert.", file=sys.stderr)
        return

    lines = [f"**YoWorld Auction Alert — {len(new_items)} new item(s)!**\n"]
    for item in new_items:
        currency = "Cash" if item.get("currency") == 2 else "Coins"
        lines.append(
            f"• **{item['item_name']}**\n"
            f"  Current bid: {item.get('cur_bid_amount', '?')} {currency} "
            f"| Buy now: {item.get('max_price', '?')} {currency}"
        )

    content = "\n".join(lines)
    # Discord webhook messages cap at 2000 chars; trim if needed
    if len(content) > 1900:
        content = content[:1900] + "\n…(truncated)"

    resp = requests.post(webhook_url, json={"content": content}, timeout=15)
    resp.raise_for_status()
    print(f"Discord alert sent for {len(new_items)} item(s).")


def main():
    wishlist = load_wishlist()
    if not wishlist:
        print("Wishlist is empty — nothing to check.")
        return

    seen = load_seen()
    new_items = []

    for name in wishlist:
        try:
            results = search_item(name)
        except requests.RequestException as e:
            print(f"Error checking '{name}': {e}", file=sys.stderr)
            continue

        for item in results:
            bid_id = item.get("bid_id")
            if bid_id is None or bid_id in seen:
                continue
            seen.add(bid_id)
            new_items.append(item)

    if new_items:
        print(f"Found {len(new_items)} new item(s). Sending Discord alert...")
        send_discord_alert(new_items)
    else:
        print("No new items this run.")

    save_seen(seen)


if __name__ == "__main__":
    main()
