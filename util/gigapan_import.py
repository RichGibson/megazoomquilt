#!/usr/bin/env python3
"""
gigapan_import.py — Import local Gigapan Stitcher files into MegaZoomQuilt.

The Gigapan Stitcher saves two artifacts:
  - <name>.gigapan   : XML stitcher project (not needed for viewing)
  - <name>.data/     : tile pyramid + r.info metadata

Tiles are stored in a quadtree naming scheme:
  r.jpg           → zoom 0 (root)
  r0.jpg          → zoom 1, top-left quadrant
  r1.jpg          → zoom 1, top-right
  r2.jpg          → zoom 1, bottom-left
  r3.jpg          → zoom 1, bottom-right
  r00.jpg ...     → zoom 2, etc.

Each quadkey digit encodes a quadrant:
  0 = top-left  (neither x nor y bit)
  1 = top-right (x bit)
  2 = bottom-left (y bit)
  3 = bottom-right (x and y bit)

This script converts tiles to the XYZ z/x/y.jpg layout expected by MegaZoomQuilt
and writes a metadata JSON file.

Usage:
  # Import a single panorama
  python util/gigapan_import.py path/to/name.gigapan

  # Import a single panorama by its .data directory
  python util/gigapan_import.py path/to/name.data

  # Import all .gigapan files in a directory
  python util/gigapan_import.py --batch path/to/directory/

  # Use symlinks instead of copying (faster, but requires source to stay mounted)
  python util/gigapan_import.py --symlink path/to/name.gigapan

  # Override the output pano ID
  python util/gigapan_import.py --id 1000001 path/to/name.gigapan

  # Dry run: show what would be done without writing anything
  python util/gigapan_import.py --dry-run path/to/name.gigapan

Run from the project root. Output goes to static/panos/<id>/.
"""

import argparse
import json
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent / "static" / "panos"
SYNTHETIC_ID_START = 1_000_001


def quadkey_to_zxy(key: str) -> tuple[int, int, int]:
    """Convert a Gigapan quadtree key string to (zoom, x, y)."""
    z = len(key)
    x, y = 0, 0
    for i, c in enumerate(key):
        bit = z - 1 - i
        if c in ("1", "3"):
            x += 1 << bit
        if c in ("2", "3"):
            y += 1 << bit
    return z, x, y


def parse_r_info(r_info_path: Path) -> dict:
    """Parse r.info XML and return a dict with nlevels, tile_size, etc."""
    tree = ET.parse(r_info_path)
    root = tree.getroot()
    nlevels = int(root.findtext("nlevels") or 0)
    tile_size = int(root.findtext("tile_size") or 256)
    suffix = root.findtext("suffix") or "jpg"

    # projection_size (full spherical projection dimensions)
    proj_size = root.find("projection_size/vector")
    proj_w = proj_h = None
    if proj_size is not None:
        elts = [int(e.text) for e in proj_size.findall("elt")]
        if len(elts) >= 2:
            proj_w, proj_h = elts[0], elts[1]

    # bounding_box (where this pano sits in the projection)
    bbox_min = root.find(".//bounding_box//min/vector")
    bbox_max = root.find(".//bounding_box//max/vector")
    bbox = None
    if bbox_min is not None and bbox_max is not None:
        min_elts = [int(e.text) for e in bbox_min.findall("elt")]
        max_elts = [int(e.text) for e in bbox_max.findall("elt")]
        if len(min_elts) >= 2 and len(max_elts) >= 2:
            bbox = {
                "min_x": min_elts[0], "min_y": min_elts[1],
                "max_x": max_elts[0], "max_y": max_elts[1],
            }

    return {
        "nlevels": nlevels,
        "tile_size": tile_size,
        "suffix": suffix,
        "projection_size": (proj_w, proj_h),
        "bounding_box": bbox,
    }


def next_synthetic_id() -> int:
    """Find the next available synthetic ID (>= SYNTHETIC_ID_START)."""
    existing = set()
    if BASE_DIR.is_dir():
        for entry in BASE_DIR.iterdir():
            if entry.is_dir():
                try:
                    n = int(entry.name)
                    if n >= SYNTHETIC_ID_START:
                        existing.add(n)
                except ValueError:
                    pass
    if not existing:
        return SYNTHETIC_ID_START
    return max(existing) + 1


def find_tiles(tiles_dir: Path) -> list[tuple[str, Path]]:
    """
    Walk tiles_dir and return a list of (quadkey, filepath) for every tile.
    Tiles are named like r.jpg, r0.jpg, r000000.jpg regardless of subdir structure.
    """
    results = []
    for path in tiles_dir.rglob("*.jpg"):
        stem = path.stem  # e.g. "r000000" or "r"
        if not stem.startswith("r"):
            continue
        key = stem[1:]  # strip leading 'r'; empty string = zoom 0
        # Validate: only digits 0-3
        if key and not re.fullmatch(r"[0-3]+", key):
            continue
        results.append((key, path))
    return results


def import_pano(
    data_dir: Path,
    pano_name: str,
    pano_id: int,
    *,
    gigapan_file: Path = None,
    source_label: str = None,
    symlink: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    Import one panorama from data_dir into BASE_DIR / str(pano_id).
    If gigapan_file is provided, it is copied into the output directory.
    Returns the metadata dict that was (or would be) written.
    """
    tiles_dir = data_dir / "tiles"
    r_info_path = tiles_dir / "r.info"

    if not tiles_dir.is_dir():
        raise FileNotFoundError(f"tiles/ directory not found in {data_dir}")
    if not r_info_path.is_file():
        raise FileNotFoundError(f"r.info not found in {tiles_dir}")

    info = parse_r_info(r_info_path)
    nlevels = info["nlevels"]
    tile_size = info["tile_size"]
    max_zoom = nlevels - 1

    print(f"  nlevels={nlevels}, tile_size={tile_size}")

    tiles = find_tiles(tiles_dir)
    print(f"  Found {len(tiles)} tiles")

    out_dir = BASE_DIR / str(pano_id)

    # Track extents at the deepest zoom level to compute actual image dimensions
    max_x_at_max = -1
    max_y_at_max = -1

    ops = []  # list of (src_path, dst_path)
    for key, src_path in tiles:
        z, x, y = quadkey_to_zxy(key)
        dst_path = out_dir / str(z) / str(x) / f"{y}.jpg"
        ops.append((src_path, dst_path))
        if z == max_zoom:
            if x > max_x_at_max:
                max_x_at_max = x
            if y > max_y_at_max:
                max_y_at_max = y

    # Derive image dimensions from tile extents at max zoom
    width = (max_x_at_max + 1) * tile_size if max_x_at_max >= 0 else tile_size
    height = (max_y_at_max + 1) * tile_size if max_y_at_max >= 0 else tile_size
    print(f"  Computed dimensions: {width} x {height} px ({max_x_at_max + 1} x {max_y_at_max + 1} tiles at zoom {max_zoom})")

    meta = {
        "gigapan": {
            "id": pano_id,
            "name": pano_name,
            "width": width,
            "height": height,
            "levels": nlevels,
            "img_type": "jpg",
            "views": 0,
            "description": f"Imported from local Gigapan Stitcher file: {pano_name}" + (f" | Source: {source_label}" if source_label else ""),
            "source": "local",
            "source_path": str(gigapan_file) if gigapan_file else str(data_dir),
        }
    }

    if dry_run:
        print(f"  [dry-run] Would create {out_dir}")
        print(f"  [dry-run] Would write {out_dir / f'{pano_id}.json'}")
        print(f"  [dry-run] Would {'symlink' if symlink else 'copy'} {len(ops)} tiles")
        if gigapan_file:
            print(f"  [dry-run] Would copy {gigapan_file.name} → {out_dir / gigapan_file.name}")
        return meta

    # Create output directory structure and copy/symlink tiles
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, (src_path, dst_path) in enumerate(ops):
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if dst_path.exists() or dst_path.is_symlink():
            dst_path.unlink()
        if symlink:
            dst_path.symlink_to(src_path.resolve())
        else:
            shutil.copy2(src_path, dst_path)
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(ops)} tiles...")

    print(f"  {len(ops)}/{len(ops)} tiles done.")

    # Copy the .gigapan project file if provided
    if gigapan_file and gigapan_file.is_file():
        dst = out_dir / gigapan_file.name
        shutil.copy2(gigapan_file, dst)
        print(f"  Copied {gigapan_file.name}")

    # Write metadata JSON
    json_path = out_dir / f"{pano_id}.json"
    with json_path.open("w") as f:
        json.dump(meta, f, indent=2)
    print(f"  Wrote {json_path}")

    # Write .complete marker
    (out_dir / ".complete").write_text("")
    print(f"  Wrote .complete")

    return meta


def resolve_data_dir(path: Path) -> tuple[Path, str]:
    """
    Given a .gigapan file, .data directory, or other path,
    return (data_dir, pano_name).
    """
    path = path.resolve()
    if path.suffix == ".gigapan":
        pano_name = path.stem
        data_dir = path.with_suffix(".data")
    elif path.suffix == ".data" or path.name.endswith(".data"):
        pano_name = path.stem if path.suffix == ".data" else path.name[:-5]
        data_dir = path
    elif path.is_dir() and (path / "tiles").is_dir():
        # Bare .data directory passed without extension
        pano_name = path.name
        data_dir = path
    else:
        raise ValueError(f"Cannot determine data directory from: {path}")

    if not data_dir.is_dir():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    return data_dir, pano_name


def already_imported_paths() -> set:
    """Return set of source_path values from all existing local pano JSON files."""
    imported = set()
    if not BASE_DIR.is_dir():
        return imported
    for entry in BASE_DIR.iterdir():
        if not entry.is_dir():
            continue
        json_path = entry / f"{entry.name}.json"
        if not json_path.is_file():
            continue
        try:
            with json_path.open() as f:
                data = json.load(f).get("gigapan", {})
            if data.get("source") == "local" and "source_path" in data:
                imported.add(data["source_path"])
        except Exception:
            pass
    return imported


def from_file_import(list_file: Path, args) -> None:
    """Import .gigapan files listed in a size-file (format: size TAB path)."""
    entries = []
    with list_file.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            size_str, gp_path = parts[0].strip(), parts[1].strip()
            if size_str == "0B":
                continue
            entries.append((size_str, Path(gp_path)))

    # Sort ascending by human-readable size using sort -h logic
    def size_key(s):
        units = {"B": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
        s = s.strip()
        for suffix, mult in sorted(units.items(), key=lambda x: -x[1]):
            if s.endswith(suffix):
                try:
                    return float(s[:-len(suffix)]) * mult
                except ValueError:
                    pass
        try:
            return float(s)
        except ValueError:
            return 0

    entries.sort(key=lambda e: size_key(e[0]))

    done = already_imported_paths()
    skipped = sum(1 for _, p in entries if str(p.resolve()) in done)
    todo = [(sz, p) for sz, p in entries if str(p.resolve()) not in done]

    print(f"{len(entries)} entries in list, {skipped} already imported, {len(todo)} to do.")

    current_id = args.id if args.id else next_synthetic_id()

    for i, (size_str, gp_file) in enumerate(todo, 1):
        print(f"\n[{i}/{len(todo)}] {size_str}  {gp_file.name}  ({gp_file.parent})")
        try:
            data_dir, pano_name = resolve_data_dir(gp_file)
            print(f"  Importing '{pano_name}' as ID {current_id}")
            import_pano(
                data_dir,
                pano_name,
                current_id,
                gigapan_file=gp_file,
                source_label=str(gp_file.parent),
                symlink=args.symlink,
                dry_run=args.dry_run,
            )
            current_id += 1
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)


def batch_import(directory: Path, args) -> None:
    """Import all .gigapan files found in directory."""
    gigapan_files = sorted(directory.glob("*.gigapan"))
    if not gigapan_files:
        print(f"No .gigapan files found in {directory}")
        return

    print(f"Found {len(gigapan_files)} .gigapan files in {directory}")
    current_id = args.id if args.id else next_synthetic_id()

    for gp_file in gigapan_files:
        print(f"\n--- {gp_file.name} ---")
        try:
            data_dir, pano_name = resolve_data_dir(gp_file)
            print(f"  Importing '{pano_name}' as ID {current_id}")
            import_pano(
                data_dir,
                pano_name,
                current_id,
                gigapan_file=gp_file,
                source_label=str(gp_file.parent),
                symlink=args.symlink,
                dry_run=args.dry_run,
            )
            current_id += 1
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Import local Gigapan Stitcher files into MegaZoomQuilt."
    )
    parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        help=".gigapan file, .data directory, or (with --batch) a directory of .gigapan files",
    )
    parser.add_argument(
        "--from-file",
        type=Path,
        metavar="LIST",
        help="Import from a size-list file (format: size TAB path, one per line)",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Import all .gigapan files found in the given directory",
    )
    parser.add_argument(
        "--id",
        type=int,
        default=None,
        help=f"Override the panorama ID (default: auto-assign from {SYNTHETIC_ID_START})",
    )
    parser.add_argument(
        "--symlink",
        action="store_true",
        help="Symlink tiles instead of copying (source must stay mounted)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without writing anything",
    )
    parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="Override the panorama display name",
    )

    args = parser.parse_args()

    if args.from_file:
        if not args.from_file.is_file():
            print(f"ERROR: list file not found: {args.from_file}", file=sys.stderr)
            sys.exit(1)
        from_file_import(args.from_file, args)
        return

    if not args.path:
        parser.print_help()
        sys.exit(1)

    if args.batch:
        if not args.path.is_dir():
            print(f"ERROR: --batch requires a directory, got: {args.path}", file=sys.stderr)
            sys.exit(1)
        batch_import(args.path, args)
        return

    # Single import
    try:
        data_dir, pano_name = resolve_data_dir(args.path)
    except (ValueError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if args.name:
        pano_name = args.name

    # Locate the .gigapan file if the input was a .gigapan path
    gigapan_file = args.path.resolve() if args.path.suffix == ".gigapan" else None

    pano_id = args.id if args.id else next_synthetic_id()
    print(f"Importing '{pano_name}' as ID {pano_id}")
    print(f"Source: {data_dir}")
    print(f"Destination: {BASE_DIR / str(pano_id)}")

    try:
        meta = import_pano(
            data_dir,
            pano_name,
            pano_id,
            gigapan_file=gigapan_file,
            source_label=str(args.path.resolve().parent),
            symlink=args.symlink,
            dry_run=args.dry_run,
        )
        print(f"\nDone. Panorama ID: {pano_id}")
        print(f"Metadata: {json.dumps(meta['gigapan'], indent=2)}")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
