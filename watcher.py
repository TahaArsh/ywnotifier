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

Discord webhook is set directly below as a default. If you ever add a
GitHub secret named DISCORD_WEBHOOK_URL, it takes priority over this.
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


PRUNE_AFTER_SECONDS = 48 * 60 * 60  # remove entries 48h after their auction ended


def load_seen() -> dict:
    """Returns a dict of {bid_id: end_date}. Handles migrating the old
    flat-list format transparently if it's still around from before."""
    if not SEEN_FILE.exists():
        return {}
    try:
        data = json.loads(SEEN_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}

    if isinstance(data, list):
        # old format: just bid_ids, no end_date known — stamp with "now"
        # so they still get cleaned up ~48h from today rather than kept forever
        now = int(time.time())
        return {str(bid_id): now for bid_id in data}

    return {str(k): v for k, v in data.items()}


def save_seen(seen: dict) -> None:
    # prune anything whose auction ended more than PRUNE_AFTER_SECONDS ago
    cutoff = int(time.time()) - PRUNE_AFTER_SECONDS
    pruned = {bid_id: end_date for bid_id, end_date in seen.items() if end_date >= cutoff}
    removed = len(seen) - len(pruned)
    if removed:
        print(f"Pruned {removed} expired entr{'y' if removed == 1 else 'ies'} from seen_bids.json.")
    SEEN_FILE.write_text(json.dumps(pruned, sort_keys=True))


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


# Discord embed side-bar colors (decimal, not hex string)
COLOR_URGENT = 0xE74C3C   # red   — ends within 2 hours
COLOR_SOON = 0xF39C12     # orange — ends within 12 hours
COLOR_NORMAL = 0x2ECC71   # green — ends later than that
COLOR_UNKNOWN = 0x7289DA  # discord blurple — no end date info


def _item_to_embed(item: dict) -> dict:
    currency = "Cash" if item.get("currency") == 2 else "Coins"
    end_date = item.get("end_date")
    now = int(time.time())

    if end_date is None:
        color = COLOR_UNKNOWN
    else:
        seconds_left = end_date - now
        if seconds_left <= 2 * 3600:
            color = COLOR_URGENT
        elif seconds_left <= 12 * 3600:
            color = COLOR_SOON
        else:
            color = COLOR_NORMAL

    cur_bid = item.get("cur_bid_amount")
    max_price = item.get("max_price")
    cur_bid_str = f"{cur_bid:,} {currency}" if isinstance(cur_bid, (int, float)) else "?"
    max_price_str = f"{max_price:,} {currency}" if isinstance(max_price, (int, float)) else "?"
    ends_str = f"<t:{end_date}:R>" if end_date else "Unknown"

    return {
        "title": item.get("item_name", "Unknown item"),
        "color": color,
        "fields": [
            {"name": "Current Bid", "value": cur_bid_str, "inline": True},
            {"name": "Buy Now", "value": max_price_str, "inline": True},
            {"name": "Ends", "value": ends_str, "inline": True},
        ],
    }


def send_discord_alert(new_items: list) -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", DISCORD_WEBHOOK_URL_DEFAULT)

    if not webhook_url:
        raise RuntimeError("No Discord webhook URL configured — cannot send alert.")

    embeds = [_item_to_embed(item) for item in new_items]

    # Discord allows max 10 embeds per message — batch if we ever exceed that
    BATCH_SIZE = 10
    for i in range(0, len(embeds), BATCH_SIZE):
        batch = embeds[i:i + BATCH_SIZE]
        count_in_batch = len(batch)
        total_batches = (len(embeds) + BATCH_SIZE - 1) // BATCH_SIZE
        batch_num = i // BATCH_SIZE + 1

        header = f"**YoWorld Auction Alert — {len(new_items)} new item(s)!**"
        if total_batches > 1:
            header += f" (batch {batch_num}/{total_batches})"

        payload = {"content": header, "embeds": batch}
        resp = requests.post(webhook_url, json=payload, timeout=15)
        resp.raise_for_status()

    print(f"Discord alert sent for {len(new_items)} item(s).")


def main():
    wishlist = load_wishlist()
    if not wishlist:
        print("Wishlist is empty — nothing to check.")
        return

    seen = load_seen()
    new_items = []          # live matches to alert on
    new_bid_dates = {}      # bid_id -> end_date, only marked "seen" after a successful send

    for name in wishlist:
        try:
            results = search_item(name)
        except requests.RequestException as e:
            print(f"Error checking '{name}': {e}", file=sys.stderr)
            continue

        already_seen_count = 0
        already_ended_count = 0
        matched_new_count = 0

        now = int(time.time())
        for item in results:
            bid_id = item.get("bid_id")
            if bid_id is None:
                continue
            bid_id = str(bid_id)

            end_date = item.get("end_date")
            already_ended = end_date is not None and end_date < now

            if bid_id in seen:
                already_seen_count += 1
                continue

            if already_ended:
                # No alert was ever owed for this one — safe to mark seen now.
                seen[bid_id] = end_date if end_date is not None else now
                already_ended_count += 1
                continue

            # Still live and not yet seen — hold off marking it "seen"
            # until we've actually confirmed the alert was sent.
            new_bid_dates[bid_id] = end_date if end_date is not None else now
            matched_new_count += 1
            new_items.append(item)

        print(
            f"'{name}': API returned {len(results)} raw result(s) "
            f"({already_seen_count} already seen, {already_ended_count} already ended, "
            f"{matched_new_count} new & live)"
        )

    if new_items:
        print(f"Found {len(new_items)} new item(s). Sending Discord alert...")
        try:
            send_discord_alert(new_items)
        except (requests.RequestException, RuntimeError) as e:
            print(f"Discord send failed: {e} — NOT marking these as seen, will retry next run.", file=sys.stderr)
        else:
            # Only commit these to "seen" now that the alert actually went out.
            seen.update(new_bid_dates)
    else:
        print("No new items this run.")

    save_seen(seen)


if __name__ == "__main__":
    main()
