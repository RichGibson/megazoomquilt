#!/usr/bin/env python3
"""
Apply black-fill directly to panorama tiles without loading the full image.

Algorithm:
  1. Composite tiles at a low reference zoom (auto-selected to fit in ~300 MB).
  2. Compute fill colors for all black pixels at that zoom using the same
     sliding-window boundary extension as fill_black.py.
  3. Walk every tile at every zoom level (or a specified zoom).
     For each tile that contains black pixels: map its pixel coordinates back
     to the reference zoom, sample the fill color map, apply fill to black
     pixels only, and save the tile in-place.

Fill colors are smooth gradients so upsampling from a coarse reference map
to max-zoom tile resolution looks natural.

Usage:
    python3 util/fill_black_tiles.py <pano_id>
    python3 util/fill_black_tiles.py <pano_id> --zoom 7        # one zoom level only
    python3 util/fill_black_tiles.py <pano_id> --ref-zoom 3    # force reference zoom
    python3 util/fill_black_tiles.py <pano_id> --dry-run
    python3 util/fill_black_tiles.py <pano_id> --backup        # copy originals to .bak
    python3 util/fill_black_tiles.py <pano_id> --quality 95
"""

import argparse
import math
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

# Reuse fill logic from fill_black.py
sys.path.insert(0, str(Path(__file__).parent))
from fill_black import black_mask, fill_top, fill_bottom, fill_left, fill_right

BASE_DIR  = Path(__file__).resolve().parent.parent / "static" / "panos"
TILE_SIZE = 256
REF_MAX_TILES = 64    # max tiles to composite for the reference image
REF_MIN_DIM   = 600   # min pixels on shorter side for reference image


# ── Reference zoom selection ──────────────────────────────────────────────────

def pick_ref_zoom(W, H, levels):
    """Pick lowest zoom level meeting REF_MIN_DIM with ≤ REF_MAX_TILES tiles."""
    max_zoom = levels - 1
    zoom = 0
    for z in range(levels):
        scale  = 2 ** (max_zoom - z)
        fw     = max(1, W // scale)
        fh     = max(1, H // scale)
        cols   = math.ceil(fw / TILE_SIZE)
        rows   = math.ceil(fh / TILE_SIZE)
        zoom   = z
        if cols * rows > REF_MAX_TILES:
            break
        if min(fw, fh) >= REF_MIN_DIM:
            break
    return zoom


# ── Tile compositing ──────────────────────────────────────────────────────────

def composite_zoom(pano_dir, zoom, W, H, levels, img_ext):
    """Composite all tiles at `zoom` into a single numpy array (H_z, W_z, 3)."""
    max_zoom = levels - 1
    scale    = 2 ** (max_zoom - zoom)
    full_w   = max(1, W // scale)
    full_h   = max(1, H // scale)
    cols     = math.ceil(full_w / TILE_SIZE)
    rows     = math.ceil(full_h / TILE_SIZE)

    zoom_dir = pano_dir / str(zoom)
    if not zoom_dir.is_dir():
        raise FileNotFoundError(f"Zoom level {zoom} not found at {zoom_dir}")

    # Detect tile size from first available tile
    sample = next(zoom_dir.rglob(f"*{img_ext}"), None)
    if sample is None:
        raise FileNotFoundError(f"No tiles found at zoom {zoom}")
    tw, th = Image.open(sample).size

    canvas = np.zeros((rows * th, cols * tw, 3), dtype=np.uint8)
    loaded = 0
    for x in range(cols):
        for y in range(rows):
            tp = zoom_dir / str(x) / f"{y}{img_ext}"
            if tp.exists():
                canvas[y*th:(y+1)*th, x*tw:(x+1)*tw] = \
                    np.array(Image.open(tp).convert("RGB"))
                loaded += 1

    print(f"  Composited zoom {zoom}: {cols}×{rows} grid ({loaded} tiles) → {cols*tw}×{rows*th}")
    # Crop to actual content dimensions
    canvas = canvas[:full_h, :full_w]
    return canvas, full_w, full_h


# ── Fill computation ──────────────────────────────────────────────────────────

def compute_fill_map(arr, threshold, window, depth, depth_range, blur):
    """
    Run the fill algorithm on `arr`.  Returns:
        fill_arr     (H, W, 3) uint8  — fill color for every pixel
        covered_mask (H, W)    bool   — True where fill was applied
    """
    H, W = arr.shape[:2]
    mask = black_mask(arr, threshold)

    total_black = int(mask.sum())
    if total_black == 0:
        print("  No black pixels found at reference zoom.")
        return arr.copy(), np.zeros((H, W), dtype=bool)

    print(f"  Black pixels at reference: {total_black:,} of {H*W:,} ({100*total_black/(H*W):.1f}%)")

    fills, weights = [], []
    for name, fn in [('top', fill_top), ('bottom', fill_bottom),
                     ('left', fill_left), ('right', fill_right)]:
        f, d = fn(arr, mask, window, depth, depth_range)
        w = np.where(np.isfinite(d), 1.0 / np.maximum(d, 0.5), 0.0)
        fills.append(f)
        weights.append(w)
        covered = int((np.isfinite(d) & mask).sum())
        print(f"  {name:6s}: {covered:,} black pixels covered")

    total_w  = sum(weights)
    covered_mask = mask & (total_w > 0)

    blended = np.zeros((H, W, 3), dtype=float)
    for f, w in zip(fills, weights):
        blended += f * w[:, :, np.newaxis]
    total_w3 = np.maximum(total_w[:, :, np.newaxis], 1e-9)
    blended  = np.clip(blended / total_w3, 0, 255).astype(np.uint8)

    fill_arr = arr.copy()
    fill_arr[covered_mask] = blended[covered_mask]

    # Apply blur to filled region
    if blur > 0:
        blurred    = np.array(Image.fromarray(fill_arr).filter(ImageFilter.GaussianBlur(radius=blur)))
        mask_img   = Image.fromarray((covered_mask * 255).astype(np.uint8))
        soft       = np.array(mask_img.filter(ImageFilter.GaussianBlur(radius=blur // 2))) / 255.0
        soft3      = soft[:, :, np.newaxis]
        fill_arr   = np.clip(blurred * soft3 + fill_arr * (1 - soft3), 0, 255).astype(np.uint8)

    return fill_arr, covered_mask


# ── Per-tile application ──────────────────────────────────────────────────────

def apply_fill_to_tile(tile_path, fill_arr, covered_mask,
                       tile_x, tile_y, zoom, ref_zoom,
                       full_w_z, full_h_z, ref_w, ref_h,
                       threshold, quality, dry_run, backup):
    """Load one tile, apply fill to its black pixels, save in-place."""
    Image.MAX_IMAGE_PIXELS = None
    tile_img = Image.open(tile_path).convert("RGB")
    tile_arr = np.array(tile_img, dtype=np.uint8)
    th, tw   = tile_arr.shape[:2]

    tile_mask = black_mask(tile_arr, threshold)
    if not tile_mask.any():
        return False  # nothing to do

    # Map this tile's pixel bounds to reference zoom coordinates
    px0 = tile_x * TILE_SIZE
    py0 = tile_y * TILE_SIZE
    # Scale factor: ref pixels per zoom-z pixel
    ratio_x = ref_w / full_w_z
    ratio_y = ref_h / full_h_z

    rx0 = max(0, int(px0 * ratio_x))
    ry0 = max(0, int(py0 * ratio_y))
    rx1 = min(ref_w, int((px0 + tw) * ratio_x) + 1)
    ry1 = min(ref_h, int((py0 + th) * ratio_y) + 1)

    if rx1 <= rx0 or ry1 <= ry0:
        return False

    # Extract and resize the fill patch to tile dimensions
    fill_patch    = fill_arr[ry0:ry1, rx0:rx1]
    covered_patch = covered_mask[ry0:ry1, rx0:rx1]

    if not covered_patch.any():
        return False  # fill doesn't cover this tile's region

    fill_resized    = np.array(Image.fromarray(fill_patch).resize((tw, th), Image.BILINEAR))
    covered_resized = np.array(
        Image.fromarray((covered_patch * 255).astype(np.uint8)).resize((tw, th), Image.NEAREST)
    ) > 128

    apply_mask = tile_mask & covered_resized
    if not apply_mask.any():
        return False

    if dry_run:
        n = int(apply_mask.sum())
        print(f"    [dry-run] would fill {n} px in {tile_path.relative_to(BASE_DIR)}")
        return True

    if backup:
        bak = tile_path.with_suffix(tile_path.suffix + ".bak")
        if not bak.exists():
            shutil.copy2(tile_path, bak)

    result = tile_arr.copy()
    result[apply_mask] = fill_resized[apply_mask]
    Image.fromarray(result).save(tile_path, format="JPEG", quality=quality)
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fill black tile padding in-place across all zoom levels."
    )
    parser.add_argument("pano_id", help="Pano ID")
    parser.add_argument("--zoom", type=int, default=None,
                        help="Only process this zoom level (default: all)")
    parser.add_argument("--ref-zoom", type=int, default=None,
                        help="Reference zoom for fill computation (default: auto)")
    parser.add_argument("--threshold", type=int, default=15,
                        help="Per-channel max considered black (default: 15)")
    parser.add_argument("--window", type=int, default=120,
                        help="Sliding window half-width in px (default: 120)")
    parser.add_argument("--blur", type=int, default=25,
                        help="Gaussian blur on filled region (default: 25)")
    parser.add_argument("--depth", type=int, default=8,
                        help="Rows to skip inward before sampling (default: 8)")
    parser.add_argument("--depth-range", type=int, default=15,
                        help="Rows to average for fill color (default: 15)")
    parser.add_argument("--quality", type=int, default=92,
                        help="JPEG save quality for modified tiles (default: 92)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing anything")
    parser.add_argument("--backup", action="store_true",
                        help="Copy each tile to .bak before modifying")
    args = parser.parse_args()

    import json
    pano_dir  = BASE_DIR / args.pano_id
    json_path = pano_dir / f"{args.pano_id}.json"
    if not json_path.exists():
        print(f"ERROR: {json_path} not found", file=sys.stderr)
        return 1

    meta    = json.loads(json_path.read_text()).get("gigapan", {})
    W       = int(meta["width"])
    H       = int(meta["height"])
    levels  = int(meta.get("levels", 1))
    img_ext = "." + meta.get("img_type", "jpg")
    max_zoom = levels - 1

    print(f"Pano {args.pano_id}: {W}×{H}, {levels} levels")

    # Choose reference zoom
    ref_zoom = args.ref_zoom if args.ref_zoom is not None else pick_ref_zoom(W, H, levels)
    ref_scale = 2 ** (max_zoom - ref_zoom)
    ref_w = max(1, W // ref_scale)
    ref_h = max(1, H // ref_scale)
    print(f"Reference zoom: {ref_zoom} ({ref_w}×{ref_h} px, "
          f"~{ref_w*ref_h*3/1e6:.0f} MB)")

    # Step 1: composite reference zoom
    print("\nStep 1: Compositing reference zoom...")
    arr_ref, ref_w, ref_h = composite_zoom(pano_dir, ref_zoom, W, H, levels, img_ext)

    # Step 2: compute fill map
    print("\nStep 2: Computing fill color map...")
    fill_arr, covered_mask = compute_fill_map(
        arr_ref, args.threshold, args.window,
        args.depth, args.depth_range, args.blur
    )

    if not covered_mask.any():
        print("Nothing to fill.")
        return 0

    # Step 3: apply to tiles
    zoom_range = [args.zoom] if args.zoom is not None else range(levels)
    print(f"\nStep 3: Applying fill to tiles {'(dry run)' if args.dry_run else ''}...")

    total_modified = 0
    for z in zoom_range:
        scale  = 2 ** (max_zoom - z)
        full_w_z = max(1, W // scale)
        full_h_z = max(1, H // scale)
        cols   = math.ceil(full_w_z / TILE_SIZE)
        rows   = math.ceil(full_h_z / TILE_SIZE)
        zoom_dir = pano_dir / str(z)
        if not zoom_dir.is_dir():
            print(f"  Zoom {z}: directory not found, skipping")
            continue

        modified = 0
        for x in range(cols):
            for y in range(rows):
                tp = zoom_dir / str(x) / f"{y}{img_ext}"
                if not tp.exists():
                    continue
                changed = apply_fill_to_tile(
                    tp, fill_arr, covered_mask,
                    x, y, z, ref_zoom,
                    full_w_z, full_h_z, ref_w, ref_h,
                    args.threshold, args.quality, args.dry_run, args.backup
                )
                if changed:
                    modified += 1

        total_modified += modified
        print(f"  Zoom {z:2d}: {modified} tiles modified  ({cols}×{rows} grid)")

    print(f"\nDone: {total_modified} tiles {'would be ' if args.dry_run else ''}modified.")
    if args.backup and not args.dry_run:
        print("  Originals backed up as *.bak  (delete with: find . -name '*.bak' -delete)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
