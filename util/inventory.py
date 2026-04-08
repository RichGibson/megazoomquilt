#!/usr/bin/env python3
"""
inventory.py — Inventory all panorama project files on a drive.

Scans for:
  - .gigapan files (Gigapan Stitcher projects)
  - .pano files (Autopano Giga projects)
  - Large images (TIF/TIFF/PSD/PSB) that may be pre-stitched panoramas

For each project file, reports:
  - Whether tiles already exist (rendered and importable)
  - Whether the source images referenced inside exist on disk
  - Whether it has already been imported into MegaZoomQuilt

For large images, reports whether they've been tiled into MegaZoomQuilt.

Usage:
  python util/inventory.py /Volumes/bigeneration
  python util/inventory.py --output inventory.json /Volumes/bigeneration
  python util/inventory.py --summary /Volumes/bigeneration
  python util/inventory.py --importable /Volumes/bigeneration   # only ready-to-import
  python util/inventory.py --needs-stitching /Volumes/bigeneration

Run from the project root.
"""

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent / "static" / "panos"
LARGE_IMAGE_EXTS = {".tif", ".tiff", ".psd", ".psb"}
LARGE_IMAGE_MIN = 50 * 1024 * 1024  # 50MB


# ---------------------------------------------------------------------------
# Already-imported detection
# ---------------------------------------------------------------------------

def load_imported() -> dict:
    """Return {source_path: pano_id} for all locally-imported panos."""
    result = {}
    if not BASE_DIR.is_dir():
        return result
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
                result[data["source_path"]] = data["id"]
        except Exception:
            pass
    return result


# ---------------------------------------------------------------------------
# .gigapan parser
# ---------------------------------------------------------------------------

def parse_gigapan(path: Path) -> dict:
    """Extract source image list and metadata from a .gigapan XML file."""
    result = {"images": [], "parse_error": None}
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        for fn_el in root.iter("filename"):
            if fn_el.text:
                result["images"].append(fn_el.text.strip())
        version = root.findtext("stitcher_version")
        if version:
            result["stitcher_version"] = version
        platform = root.findtext("stitcher_platform")
        if platform:
            result["platform"] = platform
    except ET.ParseError as e:
        result["parse_error"] = str(e)
    except Exception as e:
        result["parse_error"] = str(e)
    return result


# ---------------------------------------------------------------------------
# .pano parser (Autopano Giga XML format)
# ---------------------------------------------------------------------------

def parse_pano(path: Path) -> dict:
    """Extract source image list from an Autopano Giga .pano XML file.

    .pano files have multiple top-level elements (not valid XML), so we wrap
    them in a synthetic root before parsing. Images are listed as:
      <Image><FullFilename>/path/to/file.jpg</FullFilename>...</Image>
    """
    result = {"images": [], "parse_error": None}
    try:
        raw = path.read_text(errors="replace")
        wrapped = f"<_root_>{raw}</_root_>"
        root = ET.fromstring(wrapped)
        for el in root.iter("FullFilename"):
            if el.text and el.text.strip():
                result["images"].append(el.text.strip())
        # Dedupe while preserving order
        seen = set()
        result["images"] = [x for x in result["images"] if not (x in seen or seen.add(x))]
    except ET.ParseError as e:
        result["parse_error"] = str(e)
    except Exception as e:
        result["parse_error"] = str(e)
    return result


# ---------------------------------------------------------------------------
# Source image resolution
# ---------------------------------------------------------------------------

def find_source_images(image_paths: list[str], project_file: Path,
                       filename_index: dict = None) -> dict:
    """
    For each source image path from a project file, determine if it exists.
    Tries (in order):
      1. Absolute path as-is
      2. Relative to project directory
      3. Basename search in project dir tree
      4. Lookup in filename_index (maps basename→[absolute paths])
    Returns {"found": [...], "missing": [...]}
    """
    project_dir = project_file.parent
    found = []
    missing = []

    for raw_path in image_paths:
        # Normalize cross-platform paths (Windows backslashes, old volume names)
        normalized = raw_path.replace("\\", "/")
        p = Path(normalized)
        basename = p.name

        # 1. Absolute path as-is
        if p.is_file():
            found.append(str(p))
            continue
        # 2. Relative to project directory
        rel = project_dir / basename
        if rel.is_file():
            found.append(str(rel))
            continue
        # 3. Basename search in project dir tree
        matches = list(project_dir.rglob(basename))
        if matches:
            found.append(str(matches[0]))
            continue
        # 4. Filename index (drive-wide search)
        if filename_index and basename.lower() in filename_index:
            found.append(filename_index[basename.lower()][0])
            continue

        missing.append(raw_path)

    return {"found": found, "missing": missing}


def build_filename_index(search_dirs: list[Path]) -> dict:
    """
    Build a dict mapping lowercase filename → [absolute paths] by walking dirs.
    Used so source image lookup doesn't require exact original paths.
    """
    index = {}
    IMAGE_EXTS = {".jpg", ".jpeg", ".tif", ".tiff", ".png", ".cr2", ".nef", ".raw", ".dng"}
    skip = {"tiles", "thumbnails", ".DS_Store"}
    for base in search_dirs:
        if not base.is_dir():
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in skip]
            for f in files:
                if Path(f).suffix.lower() in IMAGE_EXTS:
                    key = f.lower()
                    full = str(Path(root) / f)
                    index.setdefault(key, []).append(full)
    return index


# ---------------------------------------------------------------------------
# Main scanner
# ---------------------------------------------------------------------------

def scan_directory(base: Path, search_images: bool = True,
                   filename_index: dict = None) -> list[dict]:
    """Scan base recursively and return a list of inventory records."""
    imported = load_imported()
    records = []

    skip_dirs = {"tiles", "thumbnails", ".DS_Store"}

    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        root_path = Path(root)

        for fname in files:
            fpath = root_path / fname
            ext = fpath.suffix.lower()

            if ext == ".gigapan":
                rec = _make_gigapan_record(fpath, imported, search_images, filename_index)
                records.append(rec)

            elif ext == ".pano":
                rec = _make_pano_record(fpath, imported, search_images, filename_index)
                records.append(rec)

            elif ext in LARGE_IMAGE_EXTS:
                try:
                    size = fpath.stat().st_size
                except Exception:
                    continue
                if size >= LARGE_IMAGE_MIN:
                    rec = _make_image_record(fpath, size, imported)
                    records.append(rec)

    return records


def _make_gigapan_record(fpath: Path, imported: dict, search_images: bool,
                         filename_index: dict = None) -> dict:
    data_dir = fpath.with_suffix(".data")
    tiles_dir = data_dir / "tiles"
    has_tiles = tiles_dir.is_dir()
    source_path = str(fpath.resolve())

    rec = {
        "type": "gigapan",
        "path": source_path,
        "name": fpath.stem,
        "has_tiles": has_tiles,
        "imported_id": imported.get(source_path),
        "data_dir_exists": data_dir.is_dir(),
    }

    if has_tiles:
        r_info = tiles_dir / "r.info"
        if r_info.is_file():
            try:
                tree = ET.parse(r_info)
                root = tree.getroot()
                rec["nlevels"] = int(root.findtext("nlevels") or 0)
                rec["tile_size"] = int(root.findtext("tile_size") or 256)
            except Exception:
                pass
        tile_count = sum(1 for _ in tiles_dir.rglob("*.jpg"))
        rec["tile_count"] = tile_count

    parsed = parse_gigapan(fpath)
    rec["parse_error"] = parsed.get("parse_error")
    rec["source_image_count"] = len(parsed["images"])

    if search_images and parsed["images"]:
        resolution = find_source_images(parsed["images"], fpath, filename_index)
        rec["sources_found"] = len(resolution["found"])
        rec["sources_missing"] = len(resolution["missing"])
        rec["sources_complete"] = len(resolution["missing"]) == 0
    else:
        rec["sources_found"] = None
        rec["sources_missing"] = None
        rec["sources_complete"] = None

    return rec


def _make_pano_record(fpath: Path, imported: dict, search_images: bool,
                      filename_index: dict = None) -> dict:
    source_path = str(fpath.resolve())
    rec = {
        "type": "pano",
        "path": source_path,
        "name": fpath.stem,
        "has_tiles": False,
        "imported_id": imported.get(source_path),
    }

    parsed = parse_pano(fpath)
    rec["parse_error"] = parsed.get("parse_error")
    rec["source_image_count"] = len(parsed["images"])

    if search_images and parsed["images"]:
        resolution = find_source_images(parsed["images"], fpath, filename_index)
        rec["sources_found"] = len(resolution["found"])
        rec["sources_missing"] = len(resolution["missing"])
        rec["sources_complete"] = len(resolution["missing"]) == 0
    else:
        rec["sources_found"] = None
        rec["sources_missing"] = None
        rec["sources_complete"] = None

    return rec


def _make_image_record(fpath: Path, size: int, imported: dict) -> dict:
    source_path = str(fpath.resolve())
    return {
        "type": "image",
        "path": source_path,
        "name": fpath.stem,
        "ext": fpath.suffix.lower(),
        "size_bytes": size,
        "size_mb": round(size / 1024 / 1024),
        "has_tiles": False,  # images don't have .data dirs
        "imported_id": imported.get(source_path),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_summary(records: list[dict]) -> None:
    gigapans = [r for r in records if r["type"] == "gigapan"]
    panos = [r for r in records if r["type"] == "pano"]
    images = [r for r in records if r["type"] == "image"]

    def counts(items, key):
        return sum(1 for r in items if r.get(key))

    print(f"\n{'='*60}")
    print(f"INVENTORY SUMMARY")
    print(f"{'='*60}")

    print(f"\n.gigapan projects: {len(gigapans)}")
    print(f"  with tiles (importable):       {counts(gigapans, 'has_tiles')}")
    print(f"  already imported:              {counts(gigapans, 'imported_id')}")
    print(f"  without tiles (need stitch):   {sum(1 for r in gigapans if not r['has_tiles'])}")
    ready = [r for r in gigapans if not r['has_tiles'] and r.get('sources_complete')]
    print(f"  sources all found (stitchable):{len(ready)}")
    partial = [r for r in gigapans if not r['has_tiles'] and r.get('sources_found') and not r.get('sources_complete')]
    print(f"  sources partial:               {len(partial)}")

    print(f"\n.pano projects (Autopano Giga): {len(panos)}")
    print(f"  already imported:              {counts(panos, 'imported_id')}")
    ready_p = [r for r in panos if r.get('sources_complete')]
    print(f"  sources all found (stitchable):{len(ready_p)}")

    print(f"\nLarge images (≥50MB): {len(images)}")
    print(f"  already tiled/imported:        {counts(images, 'imported_id')}")
    print(f"  TIF/TIFF (gdal2tiles ready):   {sum(1 for r in images if r['ext'] in ('.tif','.tiff'))}")
    print(f"  PSD (PIL convertible):         {sum(1 for r in images if r['ext'] == '.psd')}")
    print(f"  PSB (needs vips/Photoshop):    {sum(1 for r in images if r['ext'] == '.psb')}")

    total_size = sum(r.get('size_bytes', 0) for r in images)
    print(f"  Total size:                    {total_size/1024/1024/1024:.1f} GB")
    print()


def print_importable(records: list[dict]) -> None:
    print("# .gigapan files with tiles, not yet imported:")
    for r in records:
        if r["type"] == "gigapan" and r["has_tiles"] and not r["imported_id"]:
            print(f"  {r['path']}")

    print("\n# Large images not yet tiled:")
    for r in records:
        if r["type"] == "image" and not r["imported_id"]:
            print(f"  {r['size_mb']:>6}MB  {r['path']}")


def print_needs_stitching(records: list[dict]) -> None:
    print("# Projects needing stitching (sources found):")
    for r in records:
        if r["type"] in ("gigapan", "pano") and not r["has_tiles"] and r.get("sources_complete"):
            found = r.get("sources_found", "?")
            print(f"  [{r['type']:7}] {r['name']} ({found} images)  {r['path']}")

    print("\n# Projects with partial sources:")
    for r in records:
        if r["type"] in ("gigapan", "pano") and not r["has_tiles"] \
                and r.get("sources_found") and not r.get("sources_complete"):
            f, m = r.get("sources_found", 0), r.get("sources_missing", 0)
            print(f"  [{r['type']:7}] {r['name']} ({f} found, {m} missing)  {r['path']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Inventory panorama project files on a drive."
    )
    parser.add_argument(
        "directories",
        type=Path,
        nargs="+",
        help="Directory (or directories) to scan",
    )
    parser.add_argument(
        "--output",
        type=Path,
        metavar="FILE",
        help="Write full JSON results to FILE",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print summary counts (default if no other filter given)",
    )
    parser.add_argument(
        "--importable",
        action="store_true",
        help="List projects/images ready to import right now",
    )
    parser.add_argument(
        "--needs-stitching",
        action="store_true",
        help="List projects that need stitching but have source images",
    )
    parser.add_argument(
        "--no-source-search",
        action="store_true",
        help="Skip searching for source images (faster)",
    )
    parser.add_argument(
        "--search-dirs",
        type=Path,
        nargs="+",
        metavar="DIR",
        help="Extra directories to search for source images by filename "
             "(handles old volume paths like /Volumes/BISCUIT/...)",
    )
    args = parser.parse_args()

    # Build filename index from extra search dirs
    filename_index = None
    if not args.no_source_search and args.search_dirs:
        print(f"Building filename index from {len(args.search_dirs)} search dir(s)...", file=sys.stderr)
        filename_index = build_filename_index(args.search_dirs)
        print(f"  Indexed {len(filename_index)} unique filenames.", file=sys.stderr)

    all_records = []
    for d in args.directories:
        if not d.is_dir():
            print(f"WARNING: not a directory: {d}", file=sys.stderr)
            continue
        print(f"Scanning {d}...", file=sys.stderr)
        records = scan_directory(d, search_images=not args.no_source_search,
                                 filename_index=filename_index)
        all_records.extend(records)
        print(f"  {len(records)} records found.", file=sys.stderr)

    if args.output:
        with args.output.open("w") as f:
            json.dump(all_records, f, indent=2)
        print(f"Wrote {len(all_records)} records to {args.output}", file=sys.stderr)

    show_summary = args.summary or not (args.importable or args.needs_stitching)

    if show_summary:
        print_summary(all_records)
    if args.importable:
        print_importable(all_records)
    if args.needs_stitching:
        print_needs_stitching(all_records)


if __name__ == "__main__":
    main()
