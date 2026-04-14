"""
Standalone thumbnail generator for iterating on thumbnail quality.
Generates a thumbnail for a single pano and saves it.

Usage:
    python3 util/gen_thumb.py <pano_id>
    python3 util/gen_thumb.py <pano_id> --zoom 2
    python3 util/gen_thumb.py <pano_id> --out /tmp/test.jpg
    python3 util/gen_thumb.py <pano_id> --no-crop-black
    python3 util/gen_thumb.py <pano_id> --no-crop-sides
    python3 util/gen_thumb.py <pano_id> --aspect 16:9
    python3 util/gen_thumb.py <pano_id> --black-threshold 20

Algorithm:
    1. Detect content bounding box at zoom 0 (fast, single tile)
       and convert to fractions of full image size.
    2. Pick the lowest zoom level where the content region is at least
       THUMB_MIN_DIM on its shorter side (default 128px).
    3. Composite only the tiles that cover the content region at that zoom.
    4. Crop composited image to the content region.
    5. Apply aspect ratio rule: show full height, center-crop width if wider
       than target ratio.
    6. Save result.
"""

import argparse
import json
import math
from pathlib import Path
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent / "static/panos"

THUMB_MIN_DIM   = 400   # minimum px on shorter side of content region
THUMB_MAX_TILES = 64
BLACK_THRESHOLD = 15


def find_content_fractions(pano_dir, img_ext, threshold=BLACK_THRESHOLD):
    """
    Use the zoom-0 tile to detect content bounding box as fractions of the tile.
    Returns (left, top, right, bottom) as 0.0–1.0 fractions.
    Falls back to (0, 0, 1, 1) if no content detected or zoom-0 missing.
    """
    tile_path = pano_dir / '0' / '0' / f'0{img_ext}'
    if not tile_path.exists():
        print(f"  No zoom-0 tile found, skipping black border detection")
        return (0.0, 0.0, 1.0, 1.0)

    img = Image.open(tile_path).convert('RGB')
    w, h = img.size
    pixels = img.load()

    def row_has_content(y):
        return any(max(pixels[x, y]) > threshold for x in range(w))

    def col_has_content(x):
        return any(max(pixels[x, y]) > threshold for y in range(h))

    top    = next((y for y in range(h)          if row_has_content(y)), 0)
    bottom = next((y for y in range(h-1, -1, -1) if row_has_content(y)), h-1)
    left   = next((x for x in range(w)          if col_has_content(x)), 0)
    right  = next((x for x in range(w-1, -1, -1) if col_has_content(x)), w-1)

    lf = left   / w
    tf = top    / h
    rf = (right  + 1) / w
    bf = (bottom + 1) / h

    print(f"  Content fractions: left={lf:.2f} top={tf:.2f} right={rf:.2f} bottom={bf:.2f}")
    return (lf, tf, rf, bf)


def pick_zoom(W, H, levels, content_fractions, min_dim=THUMB_MIN_DIM):
    """
    Pick the lowest zoom level where the content region is at least min_dim
    on its shorter side, without exceeding THUMB_MAX_TILES tiles.
    """
    lf, tf, rf, bf = content_fractions
    max_zoom = levels - 1

    zoom = 0
    for z in range(0, levels):
        scale = 2 ** (max_zoom - z)
        full_w = max(1, int(W / scale))
        full_h = max(1, int(H / scale))
        content_pw = int((rf - lf) * full_w)
        content_ph = int((bf - tf) * full_h)
        cols = math.ceil(full_w / 256)
        rows = math.ceil(full_h / 256)
        total_tiles = cols * rows
        zoom = z
        if total_tiles > THUMB_MAX_TILES:
            break
        if min(content_pw, content_ph) >= min_dim:
            break

    return zoom


def composite_content(pano_dir, zoom, W, H, levels, img_ext, content_fractions):
    """
    Composite tiles covering the content region at the given zoom level.
    Returns the cropped content image.
    """
    lf, tf, rf, bf = content_fractions
    max_zoom = levels - 1
    scale = 2 ** (max_zoom - zoom)
    full_w = max(1, int(W / scale))
    full_h = max(1, int(H / scale))

    # Content region in pixels at this zoom level
    cx0 = int(lf * full_w)
    cy0 = int(tf * full_h)
    cx1 = int(rf * full_w)
    cy1 = int(bf * full_h)

    # Tile range that covers the content region
    tx0 = cx0 // 256
    ty0 = cy0 // 256
    tx1 = math.ceil(cx1 / 256)
    ty1 = math.ceil(cy1 / 256)

    zoom_dir = pano_dir / str(zoom)
    if not zoom_dir.is_dir():
        raise FileNotFoundError(f"Zoom level {zoom} not found at {zoom_dir}")

    sample = zoom_dir / str(tx0) / f'{ty0}{img_ext}'
    if not sample.exists():
        # fall back to 0/0
        sample = zoom_dir / '0' / f'0{img_ext}'
    tile_w, tile_h = Image.open(sample).size

    cols = tx1 - tx0
    rows = ty1 - ty0
    composed = Image.new("RGB", (cols * tile_w, rows * tile_h))

    for xi, x in enumerate(range(tx0, tx1)):
        for yi, y in enumerate(range(ty0, ty1)):
            tile_path = zoom_dir / str(x) / f"{y}{img_ext}"
            if tile_path.exists():
                composed.paste(Image.open(tile_path).convert("RGB"),
                               (xi * tile_w, yi * tile_h))

    # Crop to exact content pixel bounds within the composited sub-image
    local_cx0 = cx0 - tx0 * tile_w
    local_cy0 = cy0 - ty0 * tile_h
    local_cx1 = min(cx1 - tx0 * tile_w, composed.width)
    local_cy1 = min(cy1 - ty0 * tile_h, composed.height)
    content_img = composed.crop((local_cx0, local_cy0, local_cx1, local_cy1))

    print(f"  Zoom {zoom}: tiles ({tx0},{ty0})–({tx1},{ty1}) → content {content_img.width}×{content_img.height}")
    return content_img


def apply_aspect_crop(img, target_aspect_w, target_aspect_h):
    """Show full height, center-crop width if wider than target aspect ratio."""
    iw, ih = img.size
    target_ratio = target_aspect_w / target_aspect_h
    actual_ratio = iw / ih

    if actual_ratio > target_ratio:
        new_w = int(ih * target_ratio)
        x_offset = (iw - new_w) // 2
        img = img.crop((x_offset, 0, x_offset + new_w, ih))
        print(f"  Side crop: {iw}×{ih} → {img.width}×{img.height} (aspect {target_aspect_w}:{target_aspect_h})")
    else:
        print(f"  No side crop needed (aspect {actual_ratio:.2f} ≤ target {target_ratio:.2f})")

    return img


def main():
    parser = argparse.ArgumentParser(description="Generate a thumbnail for a single pano")
    parser.add_argument('pano_id', help='Pano ID')
    parser.add_argument('--zoom', type=int, default=None, help='Force specific zoom level (default: auto)')
    parser.add_argument('--out', default=None, help='Output path (default: static/panos/{id}/{id}_thumb.jpg)')
    parser.add_argument('--no-crop-black', action='store_true', help='Disable black border detection')
    parser.add_argument('--no-crop-sides', action='store_true', help='Disable side cropping for aspect ratio')
    parser.add_argument('--aspect', default='4:3', help='Target aspect ratio for side crop (default: 4:3)')
    parser.add_argument('--black-threshold', type=int, default=BLACK_THRESHOLD,
                        help=f'Brightness threshold for black border detection (default: {BLACK_THRESHOLD})')
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

    W       = int(meta['width'])
    H       = int(meta['height'])
    levels  = int(meta.get('levels', 1))
    img_ext = '.' + meta.get('img_type', 'jpg')

    print(f"Pano {args.pano_id}: {W}×{H}, {levels} levels")

    if args.no_crop_black:
        content_fractions = (0.0, 0.0, 1.0, 1.0)
    else:
        content_fractions = find_content_fractions(pano_dir, img_ext, args.black_threshold)

    zoom = args.zoom if args.zoom is not None else pick_zoom(W, H, levels, content_fractions)
    print(f"Using zoom level: {zoom}")

    img = composite_content(pano_dir, zoom, W, H, levels, img_ext, content_fractions)

    if not args.no_crop_sides:
        aw, ah = args.aspect.split(':')
        img = apply_aspect_crop(img, int(aw), int(ah))

    out_path = Path(args.out) if args.out else pano_dir / f"{args.pano_id}_thumb.jpg"
    img.save(out_path, format="JPEG", quality=args.quality)
    print(f"Saved: {out_path}  ({out_path.stat().st_size // 1024}KB)")
    return 0


if __name__ == "__main__":
    exit(main())
