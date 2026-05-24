"""
Delete all tiles for a pano from R2 and optionally clear tile_base_url from the JSON.

Usage:
    python3 util/delete_r2_pano.py 39302
    python3 util/delete_r2_pano.py 39302 --dry-run
    python3 util/delete_r2_pano.py 39302 --keep-url   # delete tiles but leave JSON unchanged
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent / "static/panos"
R2_BASE  = "r2:megazoomquilt-panos/panos"


def r2_path(pano_id):
    return f"{R2_BASE}/{pano_id}/"


def delete_from_r2(pano_id, dry_run=False):
    cmd = [
        "rclone", "delete",
        r2_path(pano_id),
        "--transfers", "32",
        "--checkers", "16",
    ]
    if dry_run:
        cmd.append("--dry-run")

    print(f"{'[dry-run] ' if dry_run else ''}rclone delete {r2_path(pano_id)}")
    result = subprocess.run(cmd)
    return result.returncode == 0


def clear_tile_base_url(pano_id):
    json_path = BASE_DIR / str(pano_id) / f"{pano_id}.json"
    if not json_path.exists():
        print(f"  WARN: {json_path} not found — skipping JSON update")
        return False
    data = json.load(open(json_path))
    meta = data.get('gigapan', data)
    if 'tile_base_url' not in meta:
        print(f"  INFO: tile_base_url not set in JSON — nothing to clear")
        return True
    del meta['tile_base_url']
    json.dump(data, open(json_path, 'w'), indent=2)
    print(f"  Cleared tile_base_url from {json_path.name}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Delete a pano's tiles from R2.")
    parser.add_argument('pano_id', help='Panorama ID to delete from R2')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted without doing it')
    parser.add_argument('--keep-url', action='store_true', help='Do not clear tile_base_url from JSON after deleting')
    args = parser.parse_args()

    pano_id = args.pano_id

    ok = delete_from_r2(pano_id, dry_run=args.dry_run)
    if not ok:
        print(f"ERROR: rclone delete failed for {pano_id}")
        sys.exit(1)

    if args.dry_run:
        print("Dry run — JSON not modified.")
        return

    if not args.keep_url:
        clear_tile_base_url(pano_id)
        print(f"Done. Remember to commit the JSON change.")
    else:
        print(f"Done. tile_base_url left unchanged (--keep-url).")


if __name__ == "__main__":
    main()
