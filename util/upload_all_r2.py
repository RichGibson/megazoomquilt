"""
Upload all locally-tiled panos to R2 that don't yet have tile_base_url set.
Skips the currently-downloading pano by reading the log file.

Usage:
    python3 util/upload_all_r2.py
    python3 util/upload_all_r2.py --log dow --dry-run
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

BASE_DIR    = Path(__file__).resolve().parent.parent / "static/panos"
R2_BASE     = "r2:megazoomquilt-panos/panos"
TILE_URL    = "https://tiles.megazoomquilt.com/panos"
DEFAULT_LOG = Path(__file__).resolve().parent.parent / "dow"


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


def upload_pano(pano_id, dry_run=False):
    cmd = [
        "rclone", "copy",
        str(BASE_DIR / str(pano_id)) + "/",
        f"{R2_BASE}/{pano_id}/",
        "--transfers", "64",
        "--checkers", "32",
        "--s3-upload-concurrency", "16",
        "--ignore-existing",
        "--progress",
    ]
    if dry_run:
        cmd.append("--dry-run")
    result = subprocess.run(cmd)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--log', default=str(DEFAULT_LOG), help='Download log file')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be uploaded without doing it')
    args = parser.parse_args()

    in_progress = get_in_progress_id(Path(args.log))
    if in_progress:
        print(f"In-progress pano (will skip): {in_progress}")
    else:
        print("No in-progress pano detected.")

    # Find panos with local tiles but no tile_base_url
    to_upload = []
    for entry in sorted(BASE_DIR.iterdir(), key=lambda e: int(e.name) if e.name.isdigit() else 0):
        if not entry.is_dir() or not entry.name.isdigit():
            continue
        pano_id = int(entry.name)
        if pano_id == in_progress:
            print(f"  SKIP {pano_id} (in progress)")
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

    print(f"\n{len(to_upload)} panos to upload.")
    if args.dry_run:
        for pid in to_upload:
            print(f"  would upload: {pid}")
        return

    for i, pano_id in enumerate(to_upload, 1):
        print(f"\n[{i}/{len(to_upload)}] Uploading {pano_id}...")
        ok = upload_pano(pano_id, dry_run=args.dry_run)
        if ok:
            set_tile_base_url(pano_id)
            print(f"  tile_base_url set for {pano_id}")
        else:
            print(f"  FAILED {pano_id}")

    print("\nAll done. Commit the updated JSON files and deploy to server:")
    print("  git add static/panos/*/  && git commit -m 'chore: set tile_base_url for bulk R2 upload' && git push")


if __name__ == "__main__":
    main()
