"""
Upload all locally-tiled panos to R2 that don't yet have tile_base_url set.
Skips the currently-downloading pano by reading the log file.
Safe to stop and resume — completed panos have tile_base_url set and are skipped.

Usage:
    python3 util/upload_all_r2.py
    python3 util/upload_all_r2.py --log dow --dry-run
    python3 util/upload_all_r2.py --upload-log upload_r2.log
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR    = Path(__file__).resolve().parent.parent / "static/panos"
R2_BASE     = "r2:megazoomquilt-panos/panos"
TILE_URL    = "https://tiles.megazoomquilt.com/panos"
DEFAULT_LOG = Path(__file__).resolve().parent.parent / "dow"
DEFAULT_UPLOAD_LOG = Path(__file__).resolve().parent.parent / "upload_r2.log"


def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg, upload_log, print_msg=True):
    line = f"[{ts()}] {msg}"
    if print_msg:
        print(line)
    with open(upload_log, 'a') as f:
        f.write(line + "\n")


def get_in_progress_id(log_path):
    """Read the last [N/M] PANOID line from the download log."""
    if not log_path.exists():
        return None
    pattern = re.compile(r'\[(\d+)/\d+\]\s+(\d+)\s+—')
    last_id = None
    with open(log_path) as f:
        for line in f:
            m = pattern.search(line)
            if m:
                last_id = int(m.group(2))
    return last_id


def has_local_tiles(pano_dir):
    """Return True if the pano directory contains at least one tile subdirectory."""
    for entry in pano_dir.iterdir():
        if entry.is_dir() and entry.name.isdigit():
            return True
    return False


def set_tile_base_url(pano_id):
    json_path = BASE_DIR / str(pano_id) / f"{pano_id}.json"
    if not json_path.exists():
        return False
    data = json.load(open(json_path))
    data['gigapan']['tile_base_url'] = f"{TILE_URL}/{pano_id}"
    json.dump(data, open(json_path, 'w'), indent=2)
    return True


def upload_pano(pano_id, upload_log, dry_run=False):
    cmd = [
        "rclone", "copy",
        str(BASE_DIR / str(pano_id)) + "/",
        f"{R2_BASE}/{pano_id}/",
        "--transfers", "64",
        "--checkers", "32",
        "--s3-upload-concurrency", "16",
        "--ignore-existing",
        "--stats", "10s",
        "--stats-log-level", "NOTICE",
    ]
    if dry_run:
        cmd.append("--dry-run")

    # Run rclone, tee output to both stdout and log file
    with open(upload_log, 'a') as lf:
        lf.write(f"  rclone: {' '.join(cmd)}\n")
        result = subprocess.run(cmd)
        lf.write(f"  rclone exit code: {result.returncode}\n")
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--log', default=str(DEFAULT_LOG), help='Download log file (to detect in-progress pano)')
    parser.add_argument('--upload-log', default=str(DEFAULT_UPLOAD_LOG), help='Upload log file')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be uploaded without doing it')
    args = parser.parse_args()

    upload_log = Path(args.upload_log)

    log(f"=== upload_all_r2.py started ===", upload_log)

    in_progress = get_in_progress_id(Path(args.log))
    if in_progress:
        log(f"In-progress pano (will skip): {in_progress}", upload_log)
    else:
        log("No in-progress pano detected.", upload_log)

    # Find panos with local tiles but no tile_base_url
    to_upload = []
    for entry in sorted(BASE_DIR.iterdir(), key=lambda e: int(e.name) if e.name.isdigit() else 0):
        if not entry.is_dir() or not entry.name.isdigit():
            continue
        pano_id = int(entry.name)
        if pano_id == in_progress:
            continue
        json_path = entry / f"{pano_id}.json"
        if not json_path.exists():
            continue
        data = json.load(open(json_path))
        if data.get('gigapan', data).get('tile_base_url'):
            continue  # already on R2
        if not has_local_tiles(entry):
            continue  # no tiles to upload
        to_upload.append(pano_id)

    log(f"{len(to_upload)} panos to upload.", upload_log)

    if args.dry_run:
        for pid in to_upload:
            log(f"  would upload: {pid}", upload_log)
        return

    ok_count = fail_count = 0
    for i, pano_id in enumerate(to_upload, 1):
        log(f"[{i}/{len(to_upload)}] Uploading {pano_id}...", upload_log)
        ok = upload_pano(pano_id, upload_log, dry_run=args.dry_run)
        if ok:
            set_tile_base_url(pano_id)
            log(f"  OK {pano_id} — tile_base_url set", upload_log)
            ok_count += 1
        else:
            log(f"  FAILED {pano_id}", upload_log)
            fail_count += 1

    log(f"=== Done: {ok_count} uploaded, {fail_count} failed ===", upload_log)
    log("Commit updated JSONs:", upload_log)
    log("  git add static/panos/ && git commit -m 'chore: set tile_base_url for bulk R2 upload' && git push", upload_log)


if __name__ == "__main__":
    main()
