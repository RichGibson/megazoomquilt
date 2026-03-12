"""
Bulk download all gigapans not yet fully present in static/panos/.

Reads gigapan_list.json (produced by fetch_gigapan_list.py), checks each
existing directory for completeness, and (re-)downloads anything missing.

Usage:
    python3 util/bulk_download.py
    python3 util/bulk_download.py --list gigapan_list.json --panos-dir static/panos
    python3 util/bulk_download.py --workers 24 --delay 0.5
    python3 util/bulk_download.py --skip-verify   # faster: skip tile count check
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Import completeness checker from sibling module
sys.path.insert(0, str(Path(__file__).parent))
from gigapan_downloader import check_completeness


def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg, log_path):
    line = f"[{ts()}] {msg}"
    print(line)
    with open(log_path, 'a') as f:
        f.write(line + "\n")


def scan_panos(panos, panos_dir, skip_verify, log_path):
    """
    Categorise every pano in the list into one of three buckets:
      - complete:    directory exists and all tiles present
      - incomplete:  directory exists but tiles are missing
      - not_started: no directory yet
    """
    complete    = []
    incomplete  = []
    not_started = []

    total = len(panos)
    log(f"Scanning {total} panos in {panos_dir} …", log_path)

    for i, pano in enumerate(panos, 1):
        pano_id  = str(pano['id'])
        pano_dir = panos_dir / pano_id

        if not pano_dir.is_dir():
            not_started.append(pano)
            continue

        if skip_verify:
            # Fast path: trust that the directory means it's done
            complete.append(pano)
            continue

        missing, total_tiles, json_data = check_completeness(pano_dir)

        if missing == -1:
            log(f"  {pano_id}: directory exists but JSON missing/unreadable — will re-download", log_path)
            incomplete.append(pano)
        elif missing == 0:
            complete.append(pano)
        else:
            log(f"  {pano_id}: {missing}/{total_tiles} tiles missing — will re-download", log_path)
            incomplete.append(pano)

        # Progress heartbeat during scan
        if i % 25 == 0 or i == total:
            log(f"  Scan progress: {i}/{total}  "
                f"({len(complete)} complete, {len(incomplete)} incomplete, {len(not_started)} not started)",
                log_path)

    return complete, incomplete, not_started


def main():
    parser = argparse.ArgumentParser(description="Bulk download gigapans with completeness checking")
    parser.add_argument("--list",        default="gigapan_list.json", help="JSON list from fetch_gigapan_list.py")
    parser.add_argument("--panos-dir",   default="static/panos",      help="Download destination")
    parser.add_argument("--log-file",    default="download.log",       help="Progress log file")
    parser.add_argument("--delay",       type=float, default=1.0,      help="Seconds between panos (default: 1.0)")
    parser.add_argument("--workers",     type=int,   default=16,       help="Concurrent tile workers (default: 16)")
    parser.add_argument("--skip-verify", action="store_true",          help="Skip tile count — trust directory existence")
    args = parser.parse_args()

    list_path = Path(args.list)
    if not list_path.exists():
        print(f"ERROR: {list_path} not found. Run fetch_gigapan_list.py first.")
        sys.exit(1)

    panos     = json.load(open(list_path))
    panos_dir = Path(args.panos_dir)
    panos_dir.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # Scan existing directories for completeness
    # -----------------------------------------------------------------------
    complete, incomplete, not_started = scan_panos(
        panos, panos_dir, args.skip_verify, args.log_file
    )

    to_download = incomplete + not_started
    total       = len(to_download)

    log(f"Scan complete: {len(complete)} complete, "
        f"{len(incomplete)} incomplete, {len(not_started)} not started", args.log_file)
    log(f"Will download {total} panos ({len(incomplete)} re-downloads, "
        f"{len(not_started)} new)  workers={args.workers}", args.log_file)

    if total == 0:
        log("Nothing to do — all panos are complete.", args.log_file)
        return

    # -----------------------------------------------------------------------
    # Download
    # -----------------------------------------------------------------------
    python     = sys.executable
    downloader = Path(__file__).parent / "gigapan_downloader.py"

    succeeded = 0
    failed    = 0
    start     = time.time()

    for i, pano in enumerate(to_download, 1):
        pano_id = str(pano['id'])
        name    = pano.get('name', 'untitled')
        out_dir = str(panos_dir / pano_id)
        w       = pano.get('width', '?')
        h       = pano.get('height', '?')

        log(f"[{i}/{total}] {pano_id} — {name}  ({w}×{h})", args.log_file)

        # Stream output directly to terminal so tile-level progress is visible
        result = subprocess.run(
            [python, str(downloader), pano_id, "-o", out_dir, "-w", str(args.workers)]
        )

        if result.returncode != 0:
            log(f"  ✗ Downloader exited {result.returncode} for {pano_id}", args.log_file)
            failed += 1
        else:
            # Verify completeness after download
            missing, total_tiles, _ = check_completeness(Path(out_dir))
            if missing == -1:
                log(f"  ⚠ {pano_id}: could not verify (JSON missing?)", args.log_file)
                failed += 1
            elif missing > 0:
                log(f"  ⚠ {pano_id}: finished but {missing}/{total_tiles} tiles still missing", args.log_file)
                failed += 1
            else:
                log(f"  ✓ {pano_id}: {total_tiles} tiles verified", args.log_file)
                succeeded += 1

        # ETA
        elapsed  = time.time() - start
        per_pano = elapsed / i
        eta_mins = per_pano * (total - i) / 60
        log(f"  Progress: {i}/{total} done  ({succeeded} ok, {failed} issues)  "
            f"avg {per_pano:.0f}s/pano  ETA ~{eta_mins:.0f}m", args.log_file)

        if args.delay > 0 and i < total:
            time.sleep(args.delay)

    elapsed = time.time() - start
    log(f"Bulk download complete: {succeeded} succeeded, {failed} with issues, "
        f"{total} total in {elapsed/3600:.1f}h", args.log_file)


if __name__ == "__main__":
    main()
