#!/usr/bin/env python3
"""
tile_image.py — Tile a large image into MegaZoomQuilt XYZ format.

Accepts any image readable by GDAL: TIFF, PSB, PSD, JPG, PNG, etc.
Uses gdal2tiles.py to generate tiles (TMS convention, y=0 at bottom),
then flips the Y axis to XYZ convention (y=0 at top) as expected by
the Leaflet viewer.

Also accepts .pano files (Autopano Giga) and .gigapan files as
stitch project manifests — these are recorded in metadata but not
rendered here; you must stitch them first, then pass the output image.

Usage:
  # Tile a single large image
  python util/tile_image.py path/to/panorama.tif

  # Tile with a custom name
  python util/tile_image.py --name "WhereCamp 2009" path/to/wherecamp_09.tif

  # Tile and associate with a stitch project file for provenance
  python util/tile_image.py --project path/to/foo.gigapan path/to/foo_stitched.tif

  # Override the assigned ID
  python util/tile_image.py --id 1000300 path/to/image.tif

  # Dry run
  python util/tile_image.py --dry-run path/to/image.tif

  # Batch: tile all large images listed in a file (size TAB path)
  python util/tile_image.py --from-file path/to/list.txt

Run from the project root. Requires gdal2tiles.py in PATH.
gdal2tiles.py is part of GDAL: brew install gdal
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

BASE_DIR = Path(__file__).resolve().parent.parent / "static" / "panos"
SYNTHETIC_ID_START = 1_000_001
TILE_SIZE = 256


def next_synthetic_id() -> int:
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
    return max(existing) + 1 if existing else SYNTHETIC_ID_START


def already_imported_paths() -> set:
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
            if "source_path" in data:
                imported.add(data["source_path"])
        except Exception:
            pass
    return imported


def get_psd_dimensions(image_path: Path) -> tuple[int, int] | None:
    """
    Read PSD/PSB dimensions directly from the file header — no PIL needed.
    PSD header layout:
      0-3:   "8BPS" signature
      4-5:   version (1=PSD, 2=PSB)
      6-11:  reserved
      12-13: channels
      14-17: height (big-endian uint32)
      18-21: width  (big-endian uint32)
    """
    import struct
    try:
        with open(image_path, "rb") as f:
            header = f.read(22)
        if len(header) < 22 or header[:4] != b"8BPS":
            return None
        height = struct.unpack(">I", header[14:18])[0]
        width  = struct.unpack(">I", header[18:22])[0]
        return width, height
    except Exception:
        return None


def get_image_dimensions(image_path: Path) -> tuple[int, int]:
    """Return (width, height) of an image."""
    ext = image_path.suffix.lower()

    # PSD/PSB: read header directly — fast and works for any size
    if ext in (".psd", ".psb"):
        dims = get_psd_dimensions(image_path)
        if dims:
            return dims

    # TIF/PNG/JPG: use PIL (lazy open, no pixel data loaded)
    if HAS_PIL:
        try:
            import PIL.Image as PILImage
            PILImage.MAX_IMAGE_PIXELS = None  # disable decompression bomb check
            with PILImage.open(image_path) as img:
                return img.size  # (width, height)
        except Exception:
            pass

    # Fall back to gdalinfo
    try:
        result = subprocess.run(
            ["gdalinfo", str(image_path)],
            capture_output=True, text=True
        )
        for line in result.stdout.splitlines():
            if "Size is" in line:
                parts = line.split("Size is")[1].strip().split(",")
                return int(parts[0].strip()), int(parts[1].strip())
    except Exception:
        pass

    raise RuntimeError(f"Could not determine dimensions of {image_path}")


def compute_levels(width: int, height: int) -> int:
    """Compute the number of zoom levels needed to represent the image."""
    max_dim = max(width, height)
    return max(1, math.ceil(math.log2(max_dim / TILE_SIZE)) + 1)


def flip_y_in_place(tiles_dir: Path) -> None:
    """Flip Y axis of TMS tiles to XYZ convention, in place."""
    for z_dir in sorted(tiles_dir.iterdir()):
        if not z_dir.is_dir():
            continue
        # Collect all tiles and find max_y per zoom level
        max_y = -1
        tiles = []
        for x_dir in z_dir.iterdir():
            if not x_dir.is_dir():
                continue
            for tile_file in x_dir.iterdir():
                if tile_file.suffix.lower() in ('.jpg', '.png'):
                    try:
                        y = int(tile_file.stem)
                        tiles.append((x_dir.name, y, tile_file))
                        if y > max_y:
                            max_y = y
                    except ValueError:
                        pass

        if max_y < 0:
            continue

        # Rename: use a temp suffix to avoid collisions
        for x_name, y, tile_file in tiles:
            new_y = max_y - y
            if new_y != y:
                tmp = tile_file.with_name(f"_flip_{new_y}{tile_file.suffix}")
                tile_file.rename(tmp)

        # Remove the _flip_ prefix
        for x_dir in z_dir.iterdir():
            if not x_dir.is_dir():
                continue
            for tile_file in x_dir.iterdir():
                if tile_file.name.startswith("_flip_"):
                    final = tile_file.with_name(tile_file.name[len("_flip_"):])
                    tile_file.rename(final)


def convert_psb_to_tiff(psb_path: Path, tiff_path: Path) -> None:
    """Convert a PSB (Photoshop Large Document) to TIFF using vips."""
    cmd = ["vips", "copy", str(psb_path), str(tiff_path)]
    print(f"  Converting PSB to TIFF via vips...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"vips failed: {result.stderr.strip()}")
    print(f"  Saved TIFF: {tiff_path}")


def convert_psd_to_tiff(psd_path: Path, tiff_path: Path) -> None:
    """Convert a PSD file to TIFF using Pillow."""
    if not HAS_PIL:
        raise RuntimeError("Pillow is required to convert PSD files: pip install pillow")
    print(f"  Converting PSD to TIFF (loading into memory)...")
    Image.MAX_IMAGE_PIXELS = None  # disable decompression bomb check for large panos
    with Image.open(psd_path) as img:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(tiff_path, format="TIFF", compression="lzw")
    print(f"  Saved TIFF: {tiff_path}")


def run_gdal2tiles(image_path: Path, out_dir: Path, tile_size: int = 256) -> None:
    """Run gdal2tiles.py to generate TMS tiles into out_dir.
    If the image is a PSD/PSB, converts to TIFF first via Pillow.
    """
    work_path = image_path
    tmp_tiff = None

    if image_path.suffix.lower() == ".psb":
        tmp_tiff = image_path.with_suffix(".gdal_tmp.tif")
        convert_psb_to_tiff(image_path, tmp_tiff)
        work_path = tmp_tiff
    elif image_path.suffix.lower() == ".psd":
        tmp_tiff = image_path.with_suffix(".gdal_tmp.tif")
        convert_psd_to_tiff(image_path, tmp_tiff)
        work_path = tmp_tiff

    try:
        cmd = [
            "gdal2tiles.py",
            "--profile", "raster",
            "--tilesize", str(tile_size),
            "--tiledriver", "JPEG",
            "--resampling", "average",
            "--webviewer", "none",
            str(work_path),
            str(out_dir),
        ]
        print(f"  Running gdal2tiles...")
        result = subprocess.run(cmd, capture_output=False, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"gdal2tiles.py failed with exit code {result.returncode}")
    finally:
        if tmp_tiff and tmp_tiff.exists():
            tmp_tiff.unlink()


def tile_image(
    image_path: Path,
    pano_id: int,
    pano_name: str,
    *,
    project_file: Path = None,
    dry_run: bool = False,
) -> dict:
    """
    Tile a large image and install it into static/panos/{pano_id}/.
    Returns the metadata dict.
    """
    image_path = image_path.resolve()

    print(f"  Reading dimensions: {image_path.name}")
    width, height = get_image_dimensions(image_path)
    levels = compute_levels(width, height)
    print(f"  Dimensions: {width} x {height} px → {levels} zoom levels")

    out_dir = BASE_DIR / str(pano_id)

    meta = {
        "gigapan": {
            "id": pano_id,
            "name": pano_name,
            "width": width,
            "height": height,
            "levels": levels,
            "img_type": "jpg",
            "views": 0,
            "description": f"Tiled from: {image_path.name}" + (
                f" | Project: {project_file.name}" if project_file else ""
            ),
            "source": "local",
            "source_path": str(image_path),
        }
    }

    if project_file:
        meta["gigapan"]["project_file"] = str(project_file)

    if dry_run:
        print(f"  [dry-run] Would tile → {out_dir}")
        print(f"  [dry-run] Dimensions: {width}x{height}, levels: {levels}")
        return meta

    out_dir.mkdir(parents=True, exist_ok=True)

    # gdal2tiles outputs into a subdirectory; use a temp dir then move
    with tempfile.TemporaryDirectory(prefix="mzq_tile_") as tmp:
        tmp_tiles = Path(tmp) / "tiles"
        run_gdal2tiles(image_path, tmp_tiles)

        # gdal2tiles creates zoom-level dirs directly inside tmp_tiles
        # Move them into out_dir, flipping Y axis in place first
        print(f"  Flipping Y axis (TMS→XYZ)...")
        flip_y_in_place(tmp_tiles)

        print(f"  Installing tiles into {out_dir}...")
        tile_count = 0
        for z_dir in tmp_tiles.iterdir():
            if not z_dir.is_dir() or not z_dir.name.isdigit():
                continue
            dst_z = out_dir / z_dir.name
            if dst_z.exists():
                shutil.rmtree(dst_z)
            shutil.copytree(z_dir, dst_z)
            tile_count += sum(1 for _ in dst_z.rglob("*.jpg")) + sum(1 for _ in dst_z.rglob("*.png"))

        print(f"  {tile_count} tiles installed.")

    # Copy project file if provided
    if project_file and project_file.is_file():
        shutil.copy2(project_file, out_dir / project_file.name)
        print(f"  Copied {project_file.name}")

    # Write metadata JSON
    json_path = out_dir / f"{pano_id}.json"
    with json_path.open("w") as f:
        json.dump(meta, f, indent=2)
    print(f"  Wrote {json_path}")

    (out_dir / ".complete").write_text("")
    return meta


def parse_size_file(list_file: Path) -> list[tuple[str, Path]]:
    """Parse a size-list file (size TAB path). Returns [(size_str, path)]."""
    entries = []
    with list_file.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                entries.append((parts[0].strip(), Path(parts[1].strip())))
            else:
                # Plain path, no size prefix
                entries.append(("?", Path(line)))
    return entries


def from_file_import(list_file: Path, args) -> None:
    entries = parse_size_file(list_file)
    # Filter to image types only
    IMAGE_EXTS = {'.tif', '.tiff', '.psd', '.psb', '.jpg', '.jpeg', '.png'}
    entries = [(s, p) for s, p in entries if p.suffix.lower() in IMAGE_EXTS]

    done = already_imported_paths()
    todo = [(s, p) for s, p in entries if str(p.resolve()) not in done]
    skipped = len(entries) - len(todo)
    print(f"{len(entries)} images in list, {skipped} already imported, {len(todo)} to do.")

    current_id = args.id if args.id else next_synthetic_id()
    for i, (size_str, image_path) in enumerate(todo, 1):
        print(f"\n[{i}/{len(todo)}] {size_str}  {image_path.name}  ({image_path.parent})")
        if not image_path.is_file():
            print(f"  SKIP: file not found")
            continue
        name = args.name or image_path.stem.replace("_", " ").replace("-", " ").title()
        try:
            tile_image(image_path, current_id, name, dry_run=args.dry_run)
            current_id += 1
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Tile a large image into MegaZoomQuilt XYZ format."
    )
    parser.add_argument(
        "image",
        type=Path,
        nargs="?",
        help="Image file to tile (TIFF, PSB, PSD, JPG, PNG)",
    )
    parser.add_argument(
        "--from-file",
        type=Path,
        metavar="LIST",
        help="Tile all images listed in a size-list file (size TAB path)",
    )
    parser.add_argument(
        "--project",
        type=Path,
        metavar="FILE",
        help="Associated stitch project file (.gigapan or .pano) to copy alongside tiles",
    )
    parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="Display name for the panorama (default: derived from filename)",
    )
    parser.add_argument(
        "--id",
        type=int,
        default=None,
        help=f"Override the panorama ID (default: auto-assign from {SYNTHETIC_ID_START})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without writing anything",
    )
    args = parser.parse_args()

    if args.from_file:
        if not args.from_file.is_file():
            print(f"ERROR: list file not found: {args.from_file}", file=sys.stderr)
            sys.exit(1)
        from_file_import(args.from_file, args)
        return

    if not args.image:
        parser.print_help()
        sys.exit(1)

    image_path = args.image.resolve()
    if not image_path.is_file():
        print(f"ERROR: file not found: {image_path}", file=sys.stderr)
        sys.exit(1)

    name = args.name or image_path.stem.replace("_", " ").replace("-", " ").title()
    pano_id = args.id or next_synthetic_id()

    print(f"Tiling '{name}' as ID {pano_id}")
    print(f"Source: {image_path}")
    print(f"Destination: {BASE_DIR / str(pano_id)}")

    try:
        meta = tile_image(
            image_path,
            pano_id,
            name,
            project_file=args.project,
            dry_run=args.dry_run,
        )
        print(f"\nDone. Panorama ID: {pano_id}")
        print(json.dumps(meta["gigapan"], indent=2))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
