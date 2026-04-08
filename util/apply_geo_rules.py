#!/usr/bin/env python3
"""
apply_geo_rules.py — Apply name/description-based geo rules to pano JSON files.

Reads util/geo_rules.json and sets lat/lng on any pano that:
  - matches one of the rule's patterns in any of the specified fields
  - does not already have coordinates

Usage:
    python apply_geo_rules.py [--dry-run]
"""

import json
import sys
from pathlib import Path

PANOS_DIR  = Path(__file__).resolve().parent.parent / "static" / "panos"
RULES_FILE = Path(__file__).resolve().parent / "geo_rules.json"

dry_run = "--dry-run" in sys.argv


def matches(pano: dict, patterns: list[str], fields: list[str]) -> bool:
    for field in fields:
        value = (pano.get(field) or "").lower()
        if any(p.lower() in value for p in patterns):
            return True
    return False


def apply_rules():
    rules = json.loads(RULES_FILE.read_text())
    print(f"Loaded {len(rules)} rule(s) from {RULES_FILE.name}\n")

    updated_total = 0

    for rule in rules:
        note     = rule.get("note", "")
        patterns = rule["patterns"]
        fields   = rule["fields"]
        lat      = rule["latitude"]
        lng      = rule["longitude"]

        print(f"Rule: {note}")
        print(f"  patterns={patterns}  fields={fields}  → ({lat}, {lng})")

        rule_count = 0
        for pano_dir in sorted(PANOS_DIR.iterdir()):
            json_file = pano_dir / f"{pano_dir.name}.json"
            if not json_file.exists():
                continue

            data = json.loads(json_file.read_text())
            pano = data.get("gigapan", data)

            # Skip if already geolocated
            if pano.get("latitude") and pano.get("longitude"):
                continue

            if not matches(pano, patterns, fields):
                continue

            name = pano.get('name', '')
            prefix = '[DRY RUN] ' if dry_run else ''
            print(f"  {prefix}Setting {pano_dir.name} \"{name}\"")
            if not dry_run:
                pano["latitude"]  = lat
                pano["longitude"] = lng
                json_file.write_text(json.dumps(data, indent=2))

            rule_count   += 1
            updated_total += 1

        print(f"  → {rule_count} pano(s) updated\n")

    print(f"Done. {updated_total} total pano(s) {'would be ' if dry_run else ''}updated.")


if __name__ == "__main__":
    apply_rules()
