#!/usr/bin/env python3
"""
Synthesize a <id>.json file from an existing <id>.kml when the JSON is missing.

Reads the KML to extract dimensions, name, description, camera position, and
field-of-view.  Counts zoom levels from the numbered tile subdirectories.

Usage:
    # One pano
    python3 util/json_from_kml.py 39302

    # All panos that have a KML but no JSON
    python3 util/json_from_kml.py --all

    # Dry run (print JSON, don't write)
    python3 util/json_from_kml.py 39302 --dry-run
    python3 util/json_from_kml.py --all --dry-run
"""

import json
import math
import re
import sys
from pathlib import Path
from xml.dom import minidom

import click

BASE_DIR  = Path(__file__).resolve().parent.parent / "static" / "panos"
TILE_BASE = "https://tiles.megazoomquilt.com/panos"


def _text(dom, tag):
    els = dom.getElementsByTagName(tag)
    if not els:
        return None
    child = els[0].firstChild
    return child.data.strip() if child else None


def _float(dom, tag):
    v = _text(dom, tag)
    return float(v) if v is not None else None


def _int(dom, tag):
    v = _text(dom, tag)
    return int(v) if v is not None else None


def _extract_description(dom):
    """Pull the user-written description paragraph from the KML CDATA balloon."""
    els = dom.getElementsByTagName("description")
    if not els:
        return None
    for child in els[0].childNodes:
        if child.nodeType != child.CDATA_SECTION_NODE:
            continue
        raw = child.data
        # The user description sits in a <p> before "Explore Score"
        # Find all <p> blocks and take the first one that isn't template noise
        paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', raw, re.DOTALL | re.IGNORECASE)
        for p in paragraphs:
            # Skip template paragraphs
            stripped = re.sub(r'<[^>]+>', ' ', p)
            stripped = re.sub(r'\s+', ' ', stripped).strip()
            skip = ('Explore Score' in stripped or '$[' in stripped
                    or re.match(r'^Author\s*:', stripped))
            if stripped and not skip:
                return stripped
    return None


def count_levels(pano_dir: Path) -> int:
    """Count zoom levels by finding the highest-numbered subdirectory."""
    levels = [
        int(d.name) for d in pano_dir.iterdir()
        if d.is_dir() and d.name.isdigit()
    ]
    return max(levels) + 1 if levels else 1


def compute_tiles_total(width, height, levels):
    """Sum tile counts across all zoom levels."""
    max_zoom = levels - 1
    total = 0
    for lvl in range(levels):
        scale  = 2 ** (max_zoom - lvl)
        cols   = math.ceil(width  / scale / 256)
        rows   = math.ceil(height / scale / 256)
        total += cols * rows
    return total


def build_json(pano_id: str, kml_path: Path) -> dict:
    raw = kml_path.read_bytes()
    dom = minidom.parseString(raw)

    width  = _int(dom, "maxWidth")
    height = _int(dom, "maxHeight")

    # Name: use the plain <name> element inside PhotoOverlay (not the Document name)
    name_els = dom.getElementsByTagName("name")
    name = None
    for el in name_els:
        val = el.firstChild.data.strip() if el.firstChild else ""
        if val and val != "Panoramas":
            name = val
            break

    description = _extract_description(dom)

    lon    = _float(dom, "longitude")
    lat    = _float(dom, "latitude")
    alt    = _float(dom, "altitude")
    hdg    = _float(dom, "heading")
    tilt   = _float(dom, "tilt")
    roll   = _float(dom, "roll")
    score  = _float(dom, "value")  # <Data name="score"><value>

    # Field of view from ViewVolume
    left_fov   = _float(dom, "leftFov")
    right_fov  = _float(dom, "rightFov")
    bottom_fov = _float(dom, "bottomFov")
    top_fov    = _float(dom, "topFov")

    fov_w = (right_fov - left_fov)  if (left_fov is not None and right_fov is not None)  else None
    fov_h = (top_fov - bottom_fov)  if (top_fov  is not None and bottom_fov is not None) else None
    fov_b = bottom_fov

    pano_dir = kml_path.parent
    levels   = count_levels(pano_dir)
    tiles_total = compute_tiles_total(width, height, levels) if (width and height) else None

    # gigapan.org placeholder coordinates (Rich's Bay Area home) — treat as no location
    if lat == 37.4413 and lon == -122.1419:
        lat, lon, alt = None, None, None

    is_geolocated = (lat is not None and lon is not None)

    return {
        "gigapan": {
            "id":                           int(pano_id) if pano_id.isdigit() else pano_id,
            "name":                         name,
            "description":                  description,
            "width":                        width,
            "height":                       height,
            "levels":                       levels,
            "img_type":                     "jpg",
            "latitude":                     lat,
            "longitude":                    lon,
            "altitude":                     alt,
            "heading":                      hdg,
            "tilt":                         tilt,
            "roll":                         roll,
            "is_geolocated":                is_geolocated,
            "field_of_view_w":              fov_w,
            "field_of_view_h":              fov_h,
            "field_of_view_b":              fov_b,
            "explore_score":                score,
            "tiles_total":                  tiles_total,
            "resolution":                   None,
            "is_game":                      False,
            "snapshottable":                True,
            "created_at":                   None,
            "auth_key":                     None,
            "tiles_requested":              None,
            "taken_at":                     None,
            "last_tile_received":           None,
            "external_app_id":              None,
            "updated_at":                   None,
            "is_private":                   False,
            "stitcher_notes":               None,
            "default_snapshot_id":          None,
            "allow_others_to_print":        False,
            "views":                        0,
            "owner_id":                     None,
            "owner_type":                   None,
            "user_id":                      None,
            "allow_anonymous_snapshotting": False,
            "allow_revenue_sharing":        False,
            "visible":                      True,
            "embeddable":                   False,
            "commentable":                  True,
            "distance":                     None,
            "allow_others_to_add_to_gallery": True,
            "options": {
                "snapshot_count": 0,
                "comment_count":  0,
                "bookmark_count": 0,
            },
            "tags":                         [],
            "tile_base_url":                f"{TILE_BASE}/{pano_id}",
            "_synthetic":                   True,
        }
    }


def process_one(pano_id: str, dry_run: bool) -> bool:
    pano_dir  = BASE_DIR / pano_id
    kml_path  = pano_dir / f"{pano_id}.kml"
    json_path = pano_dir / f"{pano_id}.json"

    if not kml_path.exists():
        print(f"[{pano_id}] SKIP — no KML found")
        return False

    if json_path.exists() and not dry_run:
        print(f"[{pano_id}] SKIP — JSON already exists")
        return False

    try:
        data = build_json(pano_id, kml_path)
    except Exception as e:
        print(f"[{pano_id}] ERROR parsing KML: {e}")
        return False

    pretty = json.dumps(data, indent=2)

    if dry_run:
        print(f"\n=== {pano_id} ===")
        print(pretty)
        return True

    json_path.write_text(pretty + "\n")
    g = data["gigapan"]
    print(f"[{pano_id}] wrote {json_path.name}  "
          f"{g['width']}x{g['height']} levels={g['levels']}  \"{g['name']}\"")
    return True


@click.command()
@click.argument("pano_id", required=False)
@click.option("--all", "do_all", is_flag=True, help="Process all panos missing a JSON")
@click.option("--dry-run", is_flag=True, help="Print JSON without writing")
def main(pano_id, do_all, dry_run):
    if do_all:
        candidates = sorted(
            d.name for d in BASE_DIR.iterdir()
            if d.is_dir()
            and (d / f"{d.name}.kml").exists()
            and not (d / f"{d.name}.json").exists()
        )
        if not candidates:
            print("No panos found with KML but no JSON.")
            return
        print(f"Found {len(candidates)} panos to synthesize: {candidates}")
        ok = sum(process_one(pid, dry_run) for pid in candidates)
        print(f"\nDone: {ok}/{len(candidates)} processed.")
    elif pano_id:
        process_one(pano_id, dry_run)
    else:
        print("Provide a pano_id or --all", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
