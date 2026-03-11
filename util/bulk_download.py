"""
Bulk download all gigapans not yet present in static/panos/.

Reads gigapan_list.json (produced by fetch_gigapan_list.py), skips already-
downloaded IDs, and calls gigapan_downloader.py for each remaining one.
Progress and errors are written to a log file so you can resume safely.

Usage:
    python3 util/bulk_download.py
    python3 util/bulk_download.py --log-file download.log
    python3 util/bulk_download.py --list gigapan_list.json --panos-dir static/panos
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def log(msg, log_path):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(log_path, "a") as f:
        f.write(line + "\n")


def main():
    parser = argparse.ArgumentParser(description="Bulk download gigapans")
    parser.add_argument("--list", default="gigapan_list.json", help="JSON file from fetch_gigapan_list.py")
    parser.add_argument("--panos-dir", default="static/panos", help="Download destination")
    parser.add_argument("--log-file", default="download.log", help="Progress log file")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds to wait between panos (default: 1.0)")
    args = parser.parse_args()

    list_path = Path(args.list)
    if not list_path.exists():
        print(f"ERROR: {list_path} not found. Run fetch_gigapan_list.py first.")
        sys.exit(1)

    panos = json.load(open(list_path))
    panos_dir = Path(args.panos_dir)
    already = {p.name for p in panos_dir.iterdir() if p.is_dir()} if panos_dir.exists() else set()

    missing = [p for p in panos if str(p["id"]) not in already]
    total = len(missing)

    log(f"Starting bulk download: {total} panos to fetch, {len(panos)-total} already done", args.log_file)

    # Use the same python interpreter that's running this script
    python = sys.executable
    downloader = Path(__file__).parent / "gigapan_downloader.py"

    for i, pano in enumerate(missing, 1):
        pano_id = str(pano["id"])
        name = pano.get("name", "untitled")
        out_dir = str(panos_dir / pano_id)

        log(f"[{i}/{total}] {pano_id} — {name}", args.log_file)

        result = subprocess.run(
            [python, str(downloader), pano_id, "-o", out_dir],
            capture_output=True, text=True
        )

        if result.returncode != 0:
            log(f"  ERROR (exit {result.returncode}): {result.stderr.strip()}", args.log_file)
        else:
            log(f"  OK", args.log_file)

        if args.delay > 0:
            time.sleep(args.delay)

    log(f"Done. {total} panos processed.", args.log_file)


if __name__ == "__main__":
    main()
