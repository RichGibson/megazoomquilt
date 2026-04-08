#!/usr/bin/env python3
"""
reconcile.py — Merge gigapan_list.json metadata into static/panos/{id}/{id}.json.

For each gigapan.com pano (ID < 1,000,000) that has been imported locally,
copies any non-null fields from gigapan_list.json into the pano's JSON file.
Existing values in the pano JSON are only overwritten if the list has a
non-null, non-zero value and the pano currently has null/missing/zero.

Fields that are NEVER overwritten (pano JSON is authoritative for these):
  source, source_path, img_type, levels

Usage:
  python util/reconcile.py              # dry run — show what would change
  python util/reconcile.py --apply      # apply changes
  python util/reconcile.py --apply --id 38490  # single pano

Run from the project root.
"""

import argparse
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent / "static" / "panos"
LIST_PATH = Path(__file__).resolve().parent.parent / "gigapan_list.json"

# Fields where the pano JSON is always authoritative — never overwrite
PANO_AUTHORITATIVE = {"source", "source_path", "img_type", "levels"}

# A value counts as "empty" if it's None, 0, 0.0, or ""
def is_empty(v):
    return v is None or v == 0 or v == 0.0 or v == ""


def reconcile(dry_run=True, only_id=None):
    with LIST_PATH.open() as f:
        gp_list = json.load(f)
    gp_by_id = {g["id"]: g for g in gp_list}

    total_panos = 0
    total_changes = 0

    for entry in sorted(BASE_DIR.iterdir()):
        if not entry.is_dir():
            continue
        try:
            pano_id = int(entry.name)
        except ValueError:
            continue
        if pano_id >= 1_000_000:
            continue  # local-only pano, gigapan_list.json has no record
        if only_id and pano_id != only_id:
            continue

        json_path = entry / f"{entry.name}.json"
        if not json_path.is_file():
            continue

        with json_path.open() as f:
            raw = json.load(f)

        # Local imports nest data under "gigapan"; gigapan.com files are flat
        nested = "gigapan" in raw and isinstance(raw["gigapan"], dict)
        pano = raw["gigapan"] if nested else raw

        source = gp_by_id.get(pano_id)
        if not source:
            continue

        changes = {}
        for key, val in source.items():
            if key in PANO_AUTHORITATIVE:
                continue
            if is_empty(val):
                continue
            if is_empty(pano.get(key)):
                changes[key] = val

        if not changes:
            continue

        total_panos += 1
        total_changes += len(changes)

        print(f"\n{'[DRY RUN] ' if dry_run else ''}Pano {pano_id} — {pano.get('name', '?')}")
        for k, v in sorted(changes.items()):
            print(f"  {k}: {pano.get(k)!r} → {v!r}")

        if not dry_run:
            pano.update(changes)
            if nested:
                raw["gigapan"] = pano
            with json_path.open("w") as f:
                json.dump(raw, f, indent=2)

    print(f"\n{'Would update' if dry_run else 'Updated'} {total_panos} panos, {total_changes} fields.")
    if dry_run:
        print("Run with --apply to apply changes.")


def main():
    parser = argparse.ArgumentParser(
        description="Reconcile gigapan_list.json metadata into imported pano JSON files."
    )
    parser.add_argument("--apply", action="store_true",
                        help="Apply changes (default is dry run)")
    parser.add_argument("--id", type=int, default=None,
                        help="Only reconcile a single pano ID")
    args = parser.parse_args()
    reconcile(dry_run=not args.apply, only_id=args.id)


if __name__ == "__main__":
    main()
