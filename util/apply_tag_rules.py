#!/usr/bin/env python3
"""
apply_tag_rules.py — Apply name/description/location-based tag rules to pano JSON files.

Reads util/tag_rules.json. For each rule a pano matches if:
  - any pattern appears in any of the specified fields, OR
  - the pano's coordinates fall within geo_bounds (if specified)

Tags are additive — existing tags are never removed.

Optional rule fields:
  geo_bounds       dict with min_lat, max_lat, min_lng, max_lng
  year_tag_prefix  string — also add prefix+year tag (e.g. "bm_" → "bm_2008")
  year_from        list — where to look for the year: "taken_at", "created_at", "name"

Usage:
    python apply_tag_rules.py [--dry-run]
"""

import json
import re
import sys
from pathlib import Path

PANOS_DIR  = Path(__file__).resolve().parent.parent / "static" / "panos"
RULES_FILE = Path(__file__).resolve().parent / "tag_rules.json"

dry_run = "--dry-run" in sys.argv

YEAR_RE = re.compile(r'\b(19[89]\d|20[012]\d)\b')


def text_matches(pano: dict, patterns: list, fields: list) -> bool:
    for field in fields:
        value = (pano.get(field) or "").lower()
        for p in patterns:
            if re.search(p.lower(), value):
                return True
    return False


def geo_matches(pano: dict, bounds: dict) -> bool:
    lat = pano.get("latitude")
    lng = pano.get("longitude")
    if not lat or not lng:
        return False
    return (bounds["min_lat"] <= lat <= bounds["max_lat"] and
            bounds["min_lng"] <= lng <= bounds["max_lng"])


def extract_year(pano: dict, year_from: list) -> str | None:
    for source in year_from:
        if source == "name":
            m = YEAR_RE.search(pano.get("name") or "")
            if m:
                return m.group(1)
        elif source in ("taken_at", "created_at"):
            val = pano.get(source) or ""
            m = re.match(r'(\d{4})', val)
            if m:
                return m.group(1)
    return None


def apply_rules():
    rules = json.loads(RULES_FILE.read_text())
    print(f"Loaded {len(rules)} rule(s) from {RULES_FILE.name}\n")

    updated_total = 0

    for rule in rules:
        note       = rule.get("note", "")
        patterns   = rule.get("patterns", [])
        excludes   = rule.get("exclude_patterns", [])
        fields     = rule.get("fields", ["name", "description"])
        bounds     = rule.get("geo_bounds")
        tags       = rule["tags"]
        yr_prefix  = rule.get("year_tag_prefix")
        yr_from    = rule.get("year_from", ["taken_at", "created_at", "name"])

        print(f"Rule: {note}")
        print(f"  patterns={patterns}  → tags={tags}"
              + (f" + {yr_prefix}YYYY" if yr_prefix else "")
              + (f"  geo_bounds={bounds}" if bounds else "")
              + (f"  exclude={excludes}" if excludes else ""))

        rule_count = 0
        for pano_dir in sorted(PANOS_DIR.iterdir()):
            json_file = pano_dir / f"{pano_dir.name}.json"
            if not json_file.exists():
                continue

            data = json.loads(json_file.read_text())
            pano = data.get("gigapan", data)

            if not (text_matches(pano, patterns, fields) or
                    (bounds and geo_matches(pano, bounds))):
                continue

            if excludes and text_matches(pano, excludes, fields):
                continue

            existing = list(pano.get("tags") or [])
            to_add   = [t for t in tags if t not in existing]

            if yr_prefix:
                year = extract_year(pano, yr_from)
                if year:
                    yr_tag = f"{yr_prefix}{year}"
                    if yr_tag not in existing:
                        to_add.append(yr_tag)

            if not to_add:
                continue

            name   = pano.get('name', '')
            prefix = '[DRY RUN] ' if dry_run else ''
            print(f"  {prefix}Adding {to_add} to {pano_dir.name} \"{name}\"")

            if not dry_run:
                pano["tags"] = sorted(set(existing) | set(to_add))
                json_file.write_text(json.dumps(data, indent=2))

            rule_count   += 1
            updated_total += 1

        print(f"  → {rule_count} pano(s) updated\n")

    print(f"Done. {updated_total} total pano(s) {'would be ' if dry_run else ''}updated.")


if __name__ == "__main__":
    apply_rules()
