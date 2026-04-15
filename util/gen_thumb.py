"""
Standalone thumbnail generator for iterating on thumbnail quality.
Generates a thumbnail for a single pano and saves it.

Usage:
    python3 util/gen_thumb.py <pano_id>
    python3 util/gen_thumb.py <pano_id> --zoom 2
    python3 util/gen_thumb.py <pano_id> --out /tmp/test.jpg
    python3 util/gen_thumb.py <pano_id> --no-fill
    python3 util/gen_thumb.py <pano_id> --no-crop-bg
    python3 util/gen_thumb.py <pano_id> --no-crop-sides
    python3 util/gen_thumb.py <pano_id> --aspect 16:9
    python3 util/gen_thumb.py <pano_id> --bg-tolerance 20
    python3 util/gen_thumb.py <pano_id> --black-crop edge
    python3 util/gen_thumb.py <pano_id> --black-crop tight
    python3 util/gen_thumb.py <pano_id> --black-crop tight --black-threshold 10

Algorithm:
    1. Pick the lowest zoom level where the image is at least THUMB_MIN_DIM px
       on its shorter side, without exceeding THUMB_MAX_TILES total tiles.
    2. Composite the full tile grid at that zoom level.
    3. Trim tile-grid padding (crop to actual content dimensions).
    4. Fill black regions by extending edge content inward (default on, --no-fill to skip).
    5. Detect solid-color borders and crop to content region (or --black-crop edge/tight).
    6. Apply aspect ratio rule: show full height, center-crop width if wider
       than target ratio.
    7. Save result.
"""

import argparse
import io
import json
import math
import sys
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from fill_black import fill_black_regions

BASE_DIR = Path(__file__).resolve().parent.parent / "static/panos"

THUMB_MIN_DIM    = 400   # minimum px on shorter side of full image at chosen zoom
THUMB_MAX_TILES  = 64    # max tiles to composite
BG_TOLERANCE     = 20    # max channel deviation from bg color to be considered bg
BG_ROW_THRESHOLD = 0.95  # fraction of sampled pixels in a row/col that must be bg
BG_PADDING_MAX   = 30    # brightness below this → likely generated black padding
BG_PADDING_MIN   = 225   # brightness above this → likely generated white padding
BORDER_MARGIN_PX = 20    # safety margin added outward after border detection
BLACK_THRESHOLD  = 15    # per-channel max value to be considered "black" for --black-crop


def pick_zoom(W, H, levels, min_dim=THUMB_MIN_DIM):
    """
    Pick the lowest zoom level where the full image is at least min_dim on its
    shorter side, without exceeding THUMB_MAX_TILES tiles.
    """
    max_zoom = levels - 1
    zoom = 0
    for z in range(0, levels):
        scale = 2 ** (max_zoom - z)
        full_w = max(1, int(W / scale))
        full_h = max(1, int(H / scale))
        cols = math.ceil(full_w / 256)
        rows = math.ceil(full_h / 256)
        zoom = z
        if cols * rows > THUMB_MAX_TILES:
            break
        if min(full_w, full_h) >= min_dim:
            break
    return zoom


def _open_tile(local_path, remote_url):
    """
    Open a tile as a PIL Image.  Try local file first; fall back to remote URL.
    Returns None if neither source has the tile.
    """
    if local_path is not None and local_path.exists():
        return Image.open(local_path)
    if remote_url is not None:
        try:
            req = Request(remote_url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=15) as resp:
                return Image.open(io.BytesIO(resp.read()))
        except URLError as e:
            print(f"  WARNING: could not fetch {remote_url}: {e}")
    return None


def composite_full(pano_dir, zoom, W, H, levels, img_ext, tile_base_url=None):
    """
    Composite the full tile grid at the given zoom level.
    Local tiles are used when present; tiles missing locally are fetched from
    tile_base_url (if provided) using the path pattern {tile_base_url}/{z}/{x}/{y}{ext}.
    Returns the composited PIL image.
    """
    max_zoom = levels - 1
    scale = 2 ** (max_zoom - zoom)
    full_w = max(1, int(W / scale))
    full_h = max(1, int(H / scale))
    cols = math.ceil(full_w / 256)
    rows = math.ceil(full_h / 256)

    zoom_dir = pano_dir / str(zoom)
    local_available = zoom_dir.is_dir()

    if not local_available and tile_base_url is None:
        raise FileNotFoundError(
            f"Zoom level {zoom} not found at {zoom_dir} and no tile_base_url in JSON"
        )

    if not local_available:
        print(f"  Local tiles not found — fetching from {tile_base_url}")

    def tile_local(x, y):
        return zoom_dir / str(x) / f"{y}{img_ext}" if local_available else None

    def tile_url(x, y):
        return f"{tile_base_url}/{zoom}/{x}/{y}{img_ext}" if tile_base_url else None

    # Determine tile dimensions from the 0/0 tile
    sample = _open_tile(tile_local(0, 0), tile_url(0, 0))
    if sample is None:
        raise FileNotFoundError(
            f"Could not load sample tile for zoom {zoom} from local or remote source"
        )
    tile_w, tile_h = sample.size

    composed = Image.new("RGB", (cols * tile_w, rows * tile_h))
    composed.paste(sample.convert("RGB"), (0, 0))
    loaded = 1
    for x in range(cols):
        for y in range(rows):
            if x == 0 and y == 0:
                continue  # already pasted
            tile = _open_tile(tile_local(x, y), tile_url(x, y))
            if tile is not None:
                composed.paste(tile.convert("RGB"), (x * tile_w, y * tile_h))
                loaded += 1

    print(f"  Zoom {zoom}: {cols}×{rows} tile grid ({loaded} tiles loaded) → {composed.width}×{composed.height}")
    return composed, full_w, full_h


def _pixel_is_bg(px, bg, tol):
    return all(abs(px[i] - bg[i]) <= tol for i in range(3))


def _is_padding_color(c):
    """True if color is likely digitally-generated padding (very dark or very light)."""
    brightness = (c[0] + c[1] + c[2]) // 3
    return brightness <= BG_PADDING_MAX or brightness >= BG_PADDING_MIN


def _edge_bg(c1, c2, tol):
    """
    If both corner pixels at an edge agree on a padding color, return that bg color.
    Otherwise return None (don't crop this edge).
    """
    if all(abs(c1[i] - c2[i]) <= tol for i in range(3)):
        avg = tuple((c1[i] + c2[i]) // 2 for i in range(3))
        if _is_padding_color(avg):
            return avg
    return None


def detect_content_box(img, bg_tolerance=BG_TOLERANCE, row_threshold=BG_ROW_THRESHOLD):
    """
    Detect content bounding box on the composited image.

    Each edge is checked independently: an edge is only cropped if both corner
    pixels at that edge agree on a plausible padding color (very dark or very
    light). Rows/columns are sampled for speed.

    Returns (left, top, right, bottom) as pixel coordinates (right/bottom exclusive).
    Returns (0, 0, img.width, img.height) if no borders detected.
    """
    w, h = img.size
    pixels = img.load()

    tl = pixels[0, 0]
    tr = pixels[w-1, 0]
    bl = pixels[0, h-1]
    br = pixels[w-1, h-1]

    top_bg   = _edge_bg(tl, tr, bg_tolerance)
    bot_bg   = _edge_bg(bl, br, bg_tolerance)
    left_bg  = _edge_bg(tl, bl, bg_tolerance)
    right_bg = _edge_bg(tr, br, bg_tolerance)

    # Sample stride: use at most ~400 samples per row/col for speed
    xs = list(range(0, w, max(1, w // 400)))
    ys = list(range(0, h, max(1, h // 400)))

    def row_is_bg(y, bg):
        hits = sum(1 for x in xs if _pixel_is_bg(pixels[x, y], bg, bg_tolerance))
        return hits / len(xs) >= row_threshold

    def col_is_bg(x, bg):
        hits = sum(1 for y in ys if _pixel_is_bg(pixels[x, y], bg, bg_tolerance))
        return hits / len(ys) >= row_threshold

    top   = next((y for y in range(h)           if not row_is_bg(y, top_bg)),   0)   if top_bg   else 0
    bot   = next((y for y in range(h-1, -1, -1) if not row_is_bg(y, bot_bg)),   h-1) if bot_bg   else h-1
    left  = next((x for x in range(w)           if not col_is_bg(x, left_bg)),  0)   if left_bg  else 0
    right = next((x for x in range(w-1, -1, -1) if not col_is_bg(x, right_bg)), w-1) if right_bg else w-1

    # Safety margin: expand outward to recover any content near the border
    top   = max(0,   top   - BORDER_MARGIN_PX)
    bot   = min(h-1, bot   + BORDER_MARGIN_PX)
    left  = max(0,   left  - BORDER_MARGIN_PX)
    right = min(w-1, right + BORDER_MARGIN_PX)

    detected = []
    if top_bg:   detected.append(f"top={top}(bg=rgb{top_bg})")
    if bot_bg:   detected.append(f"bot={bot}(bg=rgb{bot_bg})")
    if left_bg:  detected.append(f"left={left}(bg=rgb{left_bg})")
    if right_bg: detected.append(f"right={right}(bg=rgb{right_bg})")
    if detected:
        print(f"  Border detection: {', '.join(detected)}")
    else:
        print(f"  No padding borders detected")

    return (left, top, right + 1, bot + 1)


def crop_black_edge(img, threshold=BLACK_THRESHOLD):
    """
    Strip rows/cols from each edge that are predominantly black (≥95% of sampled
    pixels below threshold per channel).  Stops at the first row/col that has
    meaningful non-black content.  Conservative: interior black regions are kept.
    """
    w, h = img.size
    pixels = img.load()

    xs = list(range(0, w, max(1, w // 400)))
    ys = list(range(0, h, max(1, h // 400)))

    def px_black(x, y):
        p = pixels[x, y]
        return all(c <= threshold for c in p[:3])

    def row_is_black(y):
        hits = sum(1 for x in xs if px_black(x, y))
        return hits / len(xs) >= 0.95

    def col_is_black(x):
        hits = sum(1 for y in ys if px_black(x, y))
        return hits / len(ys) >= 0.95

    top   = next((y for y in range(h)           if not row_is_black(y)), 0)
    bot   = next((y for y in range(h-1, -1, -1) if not row_is_black(y)), h-1)
    left  = next((x for x in range(w)           if not col_is_black(x)), 0)
    right = next((x for x in range(w-1, -1, -1) if not col_is_black(x)), w-1)

    print(f"  Black edge crop (threshold={threshold}): left={left}, top={top}, right={right}, bot={bot}")
    return img.crop((left, top, right + 1, bot + 1))


def crop_black_tight(img, threshold=BLACK_THRESHOLD):
    """
    Find the minimum bounding box of all non-black pixels — the exact first/last
    row and column that contains any pixel above threshold.  More precise than edge
    mode; will clip to exactly where content begins on every edge.
    """
    w, h = img.size
    pixels = img.load()

    # Sample every Nth pixel per row/col for speed, but use a finer stride than edge mode
    stride_x = max(1, w // 800)
    stride_y = max(1, h // 800)

    def row_has_content(y):
        return any(
            not all(pixels[x, y][c] <= threshold for c in range(3))
            for x in range(0, w, stride_x)
        )

    def col_has_content(x):
        return any(
            not all(pixels[x, y][c] <= threshold for c in range(3))
            for y in range(0, h, stride_y)
        )

    top   = next((y for y in range(h)           if row_has_content(y)), 0)
    bot   = next((y for y in range(h-1, -1, -1) if row_has_content(y)), h-1)
    left  = next((x for x in range(w)           if col_has_content(x)), 0)
    right = next((x for x in range(w-1, -1, -1) if col_has_content(x)), w-1)

    print(f"  Black tight crop (threshold={threshold}): left={left}, top={top}, right={right}, bot={bot}")
    return img.crop((left, top, right + 1, bot + 1))


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
    # Fill options
    parser.add_argument('--no-fill', action='store_true',
                        help='Disable black-region fill pass (fill is on by default)')
    parser.add_argument('--fill-threshold', type=int, default=15,
                        help='Per-channel max considered black for fill (default: 15)')
    parser.add_argument('--fill-window', type=int, default=60,
                        help='Fill sliding-window half-width in px (default: 60)')
    parser.add_argument('--fill-blur', type=int, default=15,
                        help='Gaussian blur radius on filled regions (default: 15)')
    parser.add_argument('--fill-depth', type=int, default=4,
                        help='Rows/cols to skip inward before sampling (default: 4)')
    parser.add_argument('--fill-depth-range', type=int, default=8,
                        help='Rows/cols to average for fill color (default: 8)')
    # Crop options
    parser.add_argument('--no-crop-bg', action='store_true', help='Disable solid-color border detection')
    parser.add_argument('--no-crop-sides', action='store_true', help='Disable side cropping for aspect ratio')
    parser.add_argument('--aspect', default='4:3', help='Target aspect ratio for side crop (default: 4:3)')
    parser.add_argument('--bg-tolerance', type=int, default=BG_TOLERANCE,
                        help=f'Max channel deviation from bg color (default: {BG_TOLERANCE})')
    parser.add_argument('--black-crop', choices=['off', 'edge', 'tight'], default='off',
                        help='Black background removal: edge=strip black border rows/cols, '
                             'tight=crop to exact bounding box of non-black pixels (default: off)')
    parser.add_argument('--black-threshold', type=int, default=BLACK_THRESHOLD,
                        help=f'Per-channel max value considered black for --black-crop (default: {BLACK_THRESHOLD})')
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

    W             = int(meta['width'])
    H             = int(meta['height'])
    levels        = int(meta.get('levels', 1))
    img_ext       = '.' + meta.get('img_type', 'jpg')
    tile_base_url = meta.get('tile_base_url')
    if isinstance(tile_base_url, list):
        tile_base_url = tile_base_url[0] if tile_base_url else None

    print(f"Pano {args.pano_id}: {W}×{H}, {levels} levels")
    if tile_base_url:
        print(f"  tile_base_url: {tile_base_url}")

    zoom = args.zoom if args.zoom is not None else pick_zoom(W, H, levels)
    print(f"Using zoom level: {zoom}")

    img, full_w, full_h = composite_full(pano_dir, zoom, W, H, levels, img_ext, tile_base_url)

    # Step 1: always trim tile-grid padding (crop to actual content dimensions)
    img = img.crop((0, 0, min(full_w, img.width), min(full_h, img.height)))
    print(f"  Trimmed to content: {img.width}×{img.height}")

    # Step 2: fill black regions (default on)
    if not args.no_fill:
        print("  Filling black regions...")
        img = fill_black_regions(
            img,
            threshold=args.fill_threshold,
            window=args.fill_window,
            blur=args.fill_blur,
            depth=args.fill_depth,
            depth_range=args.fill_depth_range,
        )
        print(f"  After fill: {img.width}×{img.height}")

    # Step 3: additional crop
    if args.no_crop_bg:
        pass  # already trimmed in step 1
    elif args.black_crop == 'edge':
        img = crop_black_edge(img, args.black_threshold)
        print(f"  After black edge crop: {img.width}×{img.height}")
    elif args.black_crop == 'tight':
        img = crop_black_tight(img, args.black_threshold)
        print(f"  After black tight crop: {img.width}×{img.height}")
    else:
        box = detect_content_box(img, args.bg_tolerance)
        img = img.crop(box)
        print(f"  Content crop: {img.width}×{img.height}")

    # Step 4: aspect crop
    if not args.no_crop_sides:
        aw, ah = args.aspect.split(':')
        img = apply_aspect_crop(img, int(aw), int(ah))

    out_path = Path(args.out) if args.out else pano_dir / f"{args.pano_id}_thumb.jpg"
    img.save(out_path, format="JPEG", quality=args.quality)
    print(f"Saved: {out_path}  ({out_path.stat().st_size // 1024}KB)")
    return 0


if __name__ == "__main__":
    exit(main())
