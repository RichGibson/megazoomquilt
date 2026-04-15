#!/usr/bin/env python3
"""
Detect actual content bounds in a panorama by finding the tight bounding box
of non-black pixels at a reference zoom level, then:

  1. Update the JSON metadata (width / height) to the detected content size.
     The Leaflet viewer uses these values to set its display bounds, so this
     effectively hides all-black areas without touching a single tile.

  2. Optionally delete local tiles that are provably useless:
       - out-of-bounds: tile starts at a coordinate >= the new content size,
         so the viewer will never request it.
       - all-black:    every pixel is below --black-threshold.

NOTE: Only right-edge and bottom-edge black areas are handled by the JSON
update.  If significant black is detected on the left or top, the script
reports it but does NOT shift tile coordinates (that would require
re-indexing the entire tile set).

Usage:
    python3 util/crop_bounds.py <pano_id>
    python3 util/crop_bounds.py <pano_id> --dry-run
    python3 util/crop_bounds.py <pano_id> --delete-black
    python3 util/crop_bounds.py <pano_id> --delete-black --dry-run
    python3 util/crop_bounds.py <pano_id> --ref-zoom 3
    python3 util/crop_bounds.py <pano_id> --threshold 20
"""

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

BASE_DIR  = Path(__file__).resolve().parent.parent / "static" / "panos"
TILE_SIZE = 256


# ── Reference zoom selection ──────────────────────────────────────────────────

def pick_ref_zoom(pano_dir, W, H, levels, img_ext):
    """
    Pick the lowest zoom level that is fully downloaded locally AND gives a
    reference image of at least 400px on the shorter side.
    Falls back to the lowest fully-downloaded zoom if none meets the size bar.
    """
    max_zoom = levels - 1
    best = None
    for z in range(levels):
        scale  = 2 ** (max_zoom - z)
        fw     = max(1, W // scale)
        fh     = max(1, H // scale)
        cols   = math.ceil(fw / TILE_SIZE)
        rows   = math.ceil(fh / TILE_SIZE)
        zoom_dir = pano_dir / str(z)
        if not zoom_dir.is_dir():
            continue
        local = sum(1 for _ in zoom_dir.rglob(f"*{img_ext}"))
        if local < cols * rows:
            continue  # incomplete — skip
        if best is None:
            best = z
        if min(fw, fh) >= 400:
            return z
    return best


# ── Tile compositing ──────────────────────────────────────────────────────────

def composite_zoom(pano_dir, zoom, W, H, levels, img_ext):
    max_zoom = levels - 1
    scale    = 2 ** (max_zoom - zoom)
    full_w   = max(1, W // scale)
    full_h   = max(1, H // scale)
    cols     = math.ceil(full_w / TILE_SIZE)
    rows     = math.ceil(full_h / TILE_SIZE)

    zoom_dir = pano_dir / str(zoom)
    sample   = next(zoom_dir.rglob(f"*{img_ext}"), None)
    if sample is None:
        raise FileNotFoundError(f"No tiles at zoom {zoom}")
    tw, th = Image.open(sample).size

    canvas = np.zeros((rows * th, cols * tw, 3), dtype=np.uint8)
    for x in range(cols):
        for y in range(rows):
            tp = zoom_dir / str(x) / f"{y}{img_ext}"
            if tp.exists():
                canvas[y*th:(y+1)*th, x*tw:(x+1)*tw] = \
                    np.array(Image.open(tp).convert("RGB"))

    # Crop to actual content dimensions
    return canvas[:full_h, :full_w], full_w, full_h


# ── Content bbox detection ────────────────────────────────────────────────────

def detect_content_bbox(arr, threshold):
    """
    Find the tight bounding box of all pixels above `threshold` on any channel.
    Returns (left, top, right, bottom) in pixel coords (right/bottom exclusive).
    If no content found, returns (0, 0, W, H).
    """
    H, W = arr.shape[:2]
    above = (arr[:,:,0] > threshold) | \
            (arr[:,:,1] > threshold) | \
            (arr[:,:,2] > threshold)

    rows_with_content = np.any(above, axis=1)
    cols_with_content = np.any(above, axis=0)

    if not rows_with_content.any():
        return 0, 0, W, H

    top    = int(np.argmax(rows_with_content))
    bottom = H - int(np.argmax(rows_with_content[::-1]))
    left   = int(np.argmax(cols_with_content))
    right  = W - int(np.argmax(cols_with_content[::-1]))

    return left, top, right, bottom


# ── Tile walk ─────────────────────────────────────────────────────────────────

def is_all_black(tile_path, threshold):
    """Return True if every pixel in the tile is at or below threshold."""
    arr = np.array(Image.open(tile_path).convert("RGB"))
    return bool((arr <= threshold).all())


def process_tiles(pano_dir, levels, new_W, new_H, img_ext,
                  delete_black, threshold, dry_run):
    """
    Walk all local tiles.  For each tile decide whether to delete it:
      - out-of-bounds: tile's top-left pixel >= new content size at that zoom
      - all-black:     only checked (and deleted) when delete_black=True

    Returns (oob_count, black_count, total_deleted).
    """
    max_zoom  = levels - 1
    oob_total = 0
    blk_total = 0

    for z in range(levels):
        scale      = 2 ** (max_zoom - z)
        content_w  = max(1, new_W // scale)
        content_h  = max(1, new_H // scale)
        zoom_dir   = pano_dir / str(z)
        if not zoom_dir.is_dir():
            continue

        oob_z = blk_z = 0
        for x_dir in sorted(zoom_dir.iterdir()):
            if not x_dir.is_dir():
                continue
            try:
                x = int(x_dir.name)
            except ValueError:
                continue
            tile_px_x = x * TILE_SIZE
            for tile_file in sorted(x_dir.iterdir()):
                if tile_file.suffix.lower() not in ('.jpg', '.png'):
                    continue
                try:
                    y = int(tile_file.stem)
                except ValueError:
                    continue
                tile_px_y = y * TILE_SIZE

                deleted = False

                # Out-of-bounds check (coordinate only — no image load needed)
                if tile_px_x >= content_w or tile_px_y >= content_h:
                    if not dry_run:
                        tile_file.unlink()
                    oob_z += 1
                    deleted = True

                # All-black check (image load — only when requested)
                if not deleted and delete_black:
                    if is_all_black(tile_file, threshold):
                        if not dry_run:
                            tile_file.unlink()
                        blk_z += 1
                        deleted = True

        if oob_z or blk_z:
            label = "(dry-run)" if dry_run else ""
            print(f"  zoom {z:2d}: {oob_z} out-of-bounds, {blk_z} all-black deleted {label}")
        oob_total += oob_z
        blk_total += blk_z

    return oob_total, blk_total


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Detect content bounds, update JSON, and prune black tiles."
    )
    parser.add_argument("pano_id")
    parser.add_argument("--ref-zoom", type=int, default=None,
                        help="Force reference zoom level (default: auto)")
    parser.add_argument("--threshold", type=int, default=15,
                        help="Per-channel brightness below which a pixel counts as black (default: 15)")
    parser.add_argument("--delete-black", action="store_true",
                        help="Also delete local tiles that are entirely black (within new bounds)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing anything")
    args = parser.parse_args()

    pano_dir  = BASE_DIR / args.pano_id
    json_path = pano_dir / f"{args.pano_id}.json"
    if not json_path.exists():
        print(f"ERROR: {json_path} not found", file=sys.stderr)
        return 1

    raw  = json.loads(json_path.read_text())
    meta = raw.get("gigapan", raw)
    W       = int(meta["width"])
    H       = int(meta["height"])
    levels  = int(meta.get("levels", 1))
    img_ext = "." + meta.get("img_type", "jpg")

    print(f"Pano {args.pano_id}: {W}×{H}, {levels} levels")

    # ── Step 1: pick reference zoom ──
    ref_zoom = args.ref_zoom
    if ref_zoom is None:
        ref_zoom = pick_ref_zoom(pano_dir, W, H, levels, img_ext)
    if ref_zoom is None:
        print("ERROR: no complete local zoom level found — download tiles first", file=sys.stderr)
        return 1

    max_zoom  = levels - 1
    ref_scale = 2 ** (max_zoom - ref_zoom)
    ref_w     = max(1, W // ref_scale)
    ref_h     = max(1, H // ref_scale)
    print(f"Reference zoom: {ref_zoom} ({ref_w}×{ref_h} px)")

    # ── Step 2: composite reference zoom ──
    print("Compositing reference zoom...")
    arr, ref_w, ref_h = composite_zoom(pano_dir, ref_zoom, W, H, levels, img_ext)

    # ── Step 3: detect content bbox ──
    print(f"Detecting content bbox (threshold={args.threshold})...")
    left, top, right, bottom = detect_content_bbox(arr, args.threshold)
    print(f"  Content bbox in ref coords: left={left}, top={top}, right={right}, bottom={bottom}")
    print(f"  Content size in ref coords: {right-left}×{bottom-top}")

    # Warn if significant black on left or top (can't fix with metadata alone)
    if left > TILE_SIZE // 4:
        print(f"  WARNING: {left}px of black on left edge at ref zoom "
              f"(≈{left * ref_scale}px original) — not correctable via metadata update alone")
    if top > TILE_SIZE // 4:
        print(f"  WARNING: {top}px of black on top edge at ref zoom "
              f"(≈{top * ref_scale}px original) — not correctable via metadata update alone")

    # Scale detected bounds back to original-resolution coordinates
    # Align new_W/new_H to the reference scale so tile boundaries stay consistent
    new_W = right  * ref_scale
    new_H = bottom * ref_scale
    # Clamp to declared dimensions
    new_W = min(new_W, W)
    new_H = min(new_H, H)

    print(f"\nDetected content size (original resolution): {new_W}×{new_H}")
    print(f"  Width  change: {W} → {new_W}  (saving {W - new_W}px / {100*(W-new_W)/W:.1f}%)")
    print(f"  Height change: {H} → {new_H}  (saving {H - new_H}px / {100*(H-new_H)/H:.1f}%)")

    if new_W == W and new_H == H:
        print("\nNo change to content bounds needed.")
    elif not dry_run_mode(args):
        # Backup then update JSON
        bak = json_path.with_suffix(".bak")
        if not bak.exists():
            shutil.copy2(json_path, bak)
            print(f"  JSON backed up to {bak.name}")
        meta["width"]  = new_W
        meta["height"] = new_H
        json_path.write_text(json.dumps(raw, indent=2))
        print(f"  JSON updated: width={new_W}, height={new_H}")
    else:
        print("  [dry-run] would update JSON")

    # ── Step 4: prune tiles ──
    print(f"\nScanning local tiles for deletion"
          f"{' (out-of-bounds only)' if not args.delete_black else ' (out-of-bounds + all-black)'}...")
    oob, blk = process_tiles(
        pano_dir, levels, new_W, new_H, img_ext,
        args.delete_black, args.threshold, args.dry_run
    )

    action = "would be " if args.dry_run else ""
    print(f"\nDone: {oob} out-of-bounds tiles {action}deleted, "
          f"{blk} all-black tiles {action}deleted.")
    return 0


def dry_run_mode(args):
    return args.dry_run


if __name__ == "__main__":
    sys.exit(main())
