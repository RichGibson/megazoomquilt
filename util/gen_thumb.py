"""
Standalone thumbnail generator for iterating on thumbnail quality.
Generates a thumbnail for a single pano and saves it.

Usage:
    python3 util/gen_thumb.py <pano_id>
    python3 util/gen_thumb.py <pano_id> --zoom 0
    python3 util/gen_thumb.py <pano_id> --out /tmp/test.jpg
    python3 util/gen_thumb.py <pano_id> --no-crop-sides
    python3 util/gen_thumb.py <pano_id> --aspect 16:9

Algorithm:
    1. Pick zoom level (auto or --zoom)
    2. Composite all tiles at that zoom level
    3. Crop to content bounds (remove quadtree black padding beyond image edge)
    4. Apply aspect ratio rule: show full height, center-crop width if image
       is wider than the target aspect ratio.
    5. Save result.
"""

import argparse
import json
import math
from pathlib import Path
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent / "static/panos"

THUMB_MIN_DIM  = 128
THUMB_MAX_TILES = 16


def pick_zoom(W, H, levels):
    """Pick the coarsest zoom level with adequate resolution and tile count."""
    max_zoom = levels - 1
    zoom = 1
    for z in range(1, levels):
        scale = 2 ** (max_zoom - z)
        cw = max(1, int(W / scale))
        ch = max(1, int(H / scale))
        cols = math.ceil(cw / 256)
        rows = math.ceil(ch / 256)
        if cols * rows > THUMB_MAX_TILES:
            break
        zoom = z
        if min(cw, ch) >= THUMB_MIN_DIM:
            break
    return zoom


def composite_tiles(pano_dir, zoom, W, H, levels, img_ext):
    """Load and composite all tiles at the given zoom level."""
    max_zoom = levels - 1
    scale = 2 ** (max_zoom - zoom)
    content_w = max(1, int(W / scale))
    content_h = max(1, int(H / scale))
    cols = math.ceil(content_w / 256)
    rows = math.ceil(content_h / 256)

    zoom_dir = pano_dir / str(zoom)
    if not zoom_dir.is_dir():
        raise FileNotFoundError(f"Zoom level {zoom} not found at {zoom_dir}")

    # Get tile size from sample tile
    sample = zoom_dir / '0' / f'0{img_ext}'
    if not sample.exists():
        raise FileNotFoundError(f"Sample tile not found: {sample}")
    tile_w, tile_h = Image.open(sample).size

    composed = Image.new("RGB", (cols * tile_w, rows * tile_h))
    for x in range(cols):
        for y in range(rows):
            tile_path = zoom_dir / str(x) / f"{y}{img_ext}"
            if tile_path.exists():
                composed.paste(Image.open(tile_path).convert("RGB"), (x * tile_w, y * tile_h))

    # Crop to content bounds (removes quadtree padding beyond image edge)
    crop_w = min(content_w, composed.width)
    crop_h = min(content_h, composed.height)
    composed = composed.crop((0, 0, crop_w, crop_h))

    print(f"  Zoom {zoom}: {cols}×{rows} tiles → composited {composed.width}×{composed.height}")
    return composed


def apply_aspect_crop(img, target_aspect_w, target_aspect_h):
    """
    Show full height. If image is wider than target aspect ratio, center-crop
    the width. If image is taller, keep as-is (no top/bottom crop).
    """
    iw, ih = img.size
    target_ratio = target_aspect_w / target_aspect_h
    actual_ratio = iw / ih

    if actual_ratio > target_ratio:
        # Image is wider than target: crop sides, keep full height
        new_w = int(ih * target_ratio)
        x_offset = (iw - new_w) // 2
        img = img.crop((x_offset, 0, x_offset + new_w, ih))
        print(f"  Cropped sides: {iw}×{ih} → {img.width}×{img.height} (aspect {target_aspect_w}:{target_aspect_h})")
    else:
        print(f"  No side crop needed (image aspect {actual_ratio:.2f} ≤ target {target_ratio:.2f})")

    return img


def main():
    parser = argparse.ArgumentParser(description="Generate a thumbnail for a single pano")
    parser.add_argument('pano_id', help='Pano ID')
    parser.add_argument('--zoom', type=int, default=None, help='Force specific zoom level (default: auto)')
    parser.add_argument('--out', default=None, help='Output path (default: static/panos/{id}/{id}_thumb.jpg)')
    parser.add_argument('--no-crop-sides', action='store_true', help='Disable side cropping')
    parser.add_argument('--aspect', default='4:3', help='Target aspect ratio for side crop (default: 4:3)')
    parser.add_argument('--quality', type=int, default=85, help='JPEG quality (default: 85)')
    args = parser.parse_args()

    pano_dir = BASE_DIR / args.pano_id
    json_path = pano_dir / f"{args.pano_id}.json"
    if not json_path.exists():
        print(f"ERROR: JSON not found at {json_path}")
        return 1

    with open(json_path) as f:
        raw = json.load(f)
    meta = raw.get('gigapan', raw)

    W      = int(meta['width'])
    H      = int(meta['height'])
    levels = int(meta.get('levels', 1))
    img_ext = '.' + meta.get('img_type', 'jpg')

    print(f"Pano {args.pano_id}: {W}×{H}, {levels} levels")

    zoom = args.zoom if args.zoom is not None else pick_zoom(W, H, levels)
    print(f"Using zoom level: {zoom}")

    img = composite_tiles(pano_dir, zoom, W, H, levels, img_ext)

    if not args.no_crop_sides:
        aw, ah = args.aspect.split(':')
        img = apply_aspect_crop(img, int(aw), int(ah))

    out_path = Path(args.out) if args.out else pano_dir / f"{args.pano_id}_thumb.jpg"
    img.save(out_path, format="JPEG", quality=args.quality)
    print(f"Saved: {out_path}  ({out_path.stat().st_size // 1024}KB)")
    return 0


if __name__ == "__main__":
    exit(main())
