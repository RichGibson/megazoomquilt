"""
Fetch the full list of gigapans for a user from gigapan.com and save to JSON.

Usage:
    python3 util/fetch_gigapan_list.py
    python3 util/fetch_gigapan_list.py --user rich --output gigapan_list.json
    python3 util/fetch_gigapan_list.py --print-ids
    python3 util/fetch_gigapan_list.py --missing-only     # IDs not yet in static/panos/
"""

import argparse
import json
import requests
import time
from pathlib import Path

API_URL = "https://gigapan.com/gigapans.json"
PER_PAGE = 50


def fetch_all(user, delay=0.5):
    all_panos = []
    page = 1
    while True:
        params = {"user_id": user, "order": "most_recent", "per_page": PER_PAGE, "page": page}
        print(f"Fetching page {page}...", end=" ", flush=True)
        try:
            resp = requests.get(API_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"ERROR: {e}")
            break

        if not data:
            print("done.")
            break

        entries = [item["gigapan"] for item in data if "gigapan" in item]
        all_panos.extend(entries)
        print(f"{len(entries)} panos (total so far: {len(all_panos)})")

        if len(data) < PER_PAGE:
            break
        page += 1
        time.sleep(delay)

    return all_panos


def main():
    parser = argparse.ArgumentParser(description="Fetch gigapan list for a user")
    parser.add_argument("--user", default="rich", help="Gigapan username (default: rich)")
    parser.add_argument("--output", default="gigapan_list.json", help="Output JSON file (default: gigapan_list.json)")
    parser.add_argument("--panos-dir", default="static/panos", help="Directory with downloaded panos (default: static/panos)")
    parser.add_argument("--print-ids", action="store_true", help="Print all gigapan IDs to stdout")
    parser.add_argument("--missing-only", action="store_true", help="Only print IDs not yet downloaded")
    args = parser.parse_args()

    panos = fetch_all(args.user)
    print(f"\nTotal gigapans found: {len(panos)}")

    output_path = Path(args.output)
    with output_path.open("w") as f:
        json.dump(panos, f, indent=2)
    print(f"Saved metadata to {output_path}")

    panos_dir = Path(args.panos_dir)
    already_downloaded = {p.name for p in panos_dir.iterdir() if p.is_dir()} if panos_dir.exists() else set()
    missing = [p for p in panos if str(p["id"]) not in already_downloaded]
    print(f"Already downloaded: {len(panos) - len(missing)}")
    print(f"Not yet downloaded: {len(missing)}")

    if args.print_ids:
        for p in panos:
            print(p["id"])
    elif args.missing_only:
        for p in missing:
            print(p["id"])


if __name__ == "__main__":
    main()
